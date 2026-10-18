from datetime import timedelta, date
from decimal import Decimal, ROUND_HALF_UP
from django.db.models import Sum, Count, Q
from django.utils import timezone
from pos.models import Sale, SaleLine, Payment, SaleReturn, SaleReturnLine
from expenses.models import Expense
from inventory.models import ProductVariant, ProductModel
from core.models import BusinessDay

class ReportingService:

    @classmethod
    def get_business_week_range(cls, target_date=None):
        """
        Calculates the Friday-to-Wednesday business week range.
        - Friday is day 0 of the business week.
        - Saturday through Wednesday are part of the same week.
        - Thursday is weekly closing day (belongs to week ending on preceding Wednesday).
        """
        if target_date is None:
            target_date = timezone.localdate()

        # Python weekday: Mon=0, Tue=1, Wed=2, Thu=3, Fri=4, Sat=5, Sun=6
        weekday = target_date.weekday()
        days_since_friday = (weekday - 4) % 7
        week_start_friday = target_date - timedelta(days=days_since_friday)
        week_end_wednesday = week_start_friday + timedelta(days=5)

        return week_start_friday, week_end_wednesday

    @classmethod
    def get_calendar_month_range(cls, year=None, month=None):
        """
        Returns start and end dates for a calendar month.
        """
        today = timezone.localdate()
        if year is None:
            year = today.year
        if month is None:
            month = today.month

        first_day = date(year, month, 1)
        if month == 12:
            last_day = date(year + 1, 1, 1) - timedelta(days=1)
        else:
            last_day = date(year, month + 1, 1) - timedelta(days=1)

        return first_day, last_day

    @classmethod
    def get_daily_overview(cls, business_day):
        """
        Calculates live summary for a given business day.
        """
        if not business_day:
            return {
                'business_day': None,
                'is_open': False,
                'completed_invoices': 0,
                'pairs_sold': 0,
                'subtotal': Decimal('0.00'),
                'total_discount': Decimal('0.00'),
                'net_sales': Decimal('0.00'),
                'amount_received': Decimal('0.00'),
                'customer_dues': Decimal('0.00'),
                'cash_received': Decimal('0.00'),
                'non_cash_received': Decimal('0.00'),
                'returns_count': 0,
                'returns_amount': Decimal('0.00'),
                'cancelled_count': 0,
                'expenses_total': Decimal('0.00'),
                'cash_expenses': Decimal('0.00'),
            }

        sales = Sale.objects.filter(business_day=business_day)
        completed_sales = sales.filter(status='COMPLETED')
        cancelled_sales = sales.filter(status='CANCELLED')

        completed_invoices_count = completed_sales.count()
        cancelled_count = cancelled_sales.count()

        # Sum quantities of all lines for completed sales (Pairs count)
        lines = SaleLine.objects.filter(sale__in=completed_sales)
        pairs_sold = lines.aggregate(total_pairs=Sum('quantity'))['total_pairs'] or 0

        subtotal = completed_sales.aggregate(s=Sum('subtotal'))['s'] or Decimal('0.00')
        discounts = completed_sales.aggregate(d=Sum('discount_amount'))['d'] or Decimal('0.00')
        net_sales = completed_sales.aggregate(f=Sum('final_total'))['f'] or Decimal('0.00')
        customer_dues = completed_sales.aggregate(due=Sum('balance_due'))['due'] or Decimal('0.00')

        # Payments received on this day (both initial and due collections)
        payments_today = Payment.objects.filter(
            sale__in=sales,
            received_at__date=business_day.date
        )
        amount_received = payments_today.aggregate(p=Sum('amount'))['p'] or Decimal('0.00')
        cash_received = payments_today.filter(payment_method='CASH').aggregate(c=Sum('amount'))['c'] or Decimal('0.00')
        non_cash_received = amount_received - cash_received

        # Returns on this business day
        returns = SaleReturn.objects.filter(business_day=business_day)
        returns_count = returns.count()
        returns_amount = returns.aggregate(r=Sum('refund_amount'))['r'] or Decimal('0.00')

        # Expenses on this business day
        expenses = Expense.objects.filter(
            Q(business_day=business_day) | Q(expense_date=business_day.date)
        )
        expenses_total = expenses.aggregate(e=Sum('amount'))['e'] or Decimal('0.00')
        cash_expenses = expenses.filter(payment_method='CASH').aggregate(e=Sum('amount'))['e'] or Decimal('0.00')

        return {
            'business_day': business_day,
            'is_open': business_day.status == 'OPEN',
            'completed_invoices': completed_invoices_count,
            'pairs_sold': pairs_sold,
            'subtotal': subtotal,
            'total_discount': discounts,
            'net_sales': net_sales,
            'amount_received': amount_received,
            'customer_dues': customer_dues,
            'cash_received': cash_received,
            'non_cash_received': non_cash_received,
            'returns_count': returns_count,
            'returns_amount': returns_amount,
            'cancelled_count': cancelled_count,
            'expenses_total': expenses_total,
            'cash_expenses': cash_expenses,
        }

    @classmethod
    def get_financial_report(cls, start_date, end_date):
        """
        Comprehensive financial and profitability report for any date range.
        Calculates: Net Sales, COGS, Gross Profit, Expenses, Net Profit, and Margins.
        """
        sales = Sale.objects.filter(
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            status='COMPLETED'
        )

        invoices_count = sales.count()
        lines = SaleLine.objects.filter(sale__in=sales)
        pairs_sold = lines.aggregate(q=Sum('quantity'))['q'] or 0

        gross_sales = sales.aggregate(s=Sum('final_total'))['s'] or Decimal('0.00')
        discounts = sales.aggregate(d=Sum('discount_amount'))['d'] or Decimal('0.00')

        # Returns during period
        returns = SaleReturn.objects.filter(
            returned_at__date__gte=start_date,
            returned_at__date__lte=end_date
        )
        returns_refund = returns.aggregate(r=Sum('refund_amount'))['r'] or Decimal('0.00')

        net_sales = gross_sales - returns_refund

        # COGS = Sum of (cost_snapshot * quantity) for sold lines minus cost of restocked returned lines
        line_cogs = Decimal('0.00')
        for l in lines.iterator():
            line_cogs += l.cost_snapshot * l.quantity

        restocked_return_lines = SaleReturnLine.objects.filter(
            return_record__in=returns,
            disposition='RESTOCK'
        )
        restocked_cost_credit = Decimal('0.00')
        for r_line in restocked_return_lines.iterator():
            restocked_cost_credit += r_line.sale_line.cost_snapshot * r_line.quantity

        final_cogs = line_cogs - restocked_cost_credit
        gross_profit = net_sales - final_cogs

        gross_margin_pct = Decimal('0.00')
        if net_sales > 0:
            gross_margin_pct = ((gross_profit / net_sales) * Decimal('100.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Operating Expenses
        expenses = Expense.objects.filter(
            expense_date__gte=start_date,
            expense_date__lte=end_date
        )
        total_expenses = expenses.aggregate(e=Sum('amount'))['e'] or Decimal('0.00')

        net_profit = gross_profit - total_expenses
        net_margin_pct = Decimal('0.00')
        if net_sales > 0:
            net_margin_pct = ((net_profit / net_sales) * Decimal('100.00')).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # Total Collections
        payments = Payment.objects.filter(
            received_at__date__gte=start_date,
            received_at__date__lte=end_date
        )
        total_collected = payments.aggregate(p=Sum('amount'))['p'] or Decimal('0.00')
        cash_collected = payments.filter(payment_method='CASH').aggregate(c=Sum('amount'))['c'] or Decimal('0.00')
        outstanding_dues = sales.aggregate(due=Sum('balance_due'))['due'] or Decimal('0.00')

        return {
            'start_date': start_date,
            'end_date': end_date,
            'invoices_count': invoices_count,
            'pairs_sold': pairs_sold,
            'gross_sales': gross_sales,
            'discounts': discounts,
            'returns_refund': returns_refund,
            'net_sales': net_sales,
            'cogs': final_cogs,
            'gross_profit': gross_profit,
            'gross_margin_pct': gross_margin_pct,
            'operating_expenses': total_expenses,
            'net_profit': net_profit,
            'net_margin_pct': net_margin_pct,
            'total_collected': total_collected,
            'cash_collected': cash_collected,
            'outstanding_dues': outstanding_dues,
        }

    @classmethod
    def search_historical_sales_by_code(cls, product_code):
        """
        Admin feature: Search all historical sales for any current or archived product code.
        Returns line-level breakdown with invoice, date, variant, pricing, cost, and profit.
        """
        lines = SaleLine.objects.filter(
            variant__product__code__iexact=product_code.strip()
        ).select_related('sale', 'variant', 'variant__product').order_by('-sale__created_at')

        summary = {
            'product_code': product_code.strip(),
            'total_pairs_sold': 0,
            'total_revenue': Decimal('0.00'),
            'total_gross_profit': Decimal('0.00'),
            'lines': []
        }

        for line in lines:
            if line.sale.status == 'COMPLETED':
                summary['total_pairs_sold'] += line.quantity
                summary['total_revenue'] += line.final_line_total
                summary['total_gross_profit'] += line.gross_profit

            summary['lines'].append({
                'invoice_no': line.sale.invoice_no,
                'sale_id': line.sale.id,
                'date_time': line.sale.created_at,
                'status': line.sale.status,
                'product_name': line.variant.product.name,
                'size': line.variant.size,
                'colour': line.variant.colour,
                'quantity': line.quantity,
                'unit_price': line.unit_price,
                'discount_percent': line.discount_percent,
                'discount_amount': line.discount_amount,
                'final_line_total': line.final_line_total,
                'cost_snapshot': line.cost_snapshot,
                'gross_profit': line.gross_profit,
                'customer_name': line.sale.customer_name,
                'customer_phone': line.sale.customer_phone,
            })

        return summary
