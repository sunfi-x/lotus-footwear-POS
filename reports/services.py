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
        Satisfies all primary Staff Panel KPI requirements:
        1. PAIRS SOLD: (Total pairs sold from completed invoices) - (returned pairs)
        2. COMPLETED INVOICES: count of completed sales invoices
        3. NET SALES: (completed final total) - (returns amount)
        4. DISCOUNTS: total discounts on completed invoices
        5. EXPECTED CASH: opening_cash + cash_received + other_cash_in - cash_expenses - cash_refunds
        6. DIGITAL PAYMENTS: non-cash payments (bKash/Nagad/Card/Other)
        """
        if not business_day:
            return {
                'business_day': None,
                'is_open': False,
                'has_business_day': False,
                'missing_opening_cash': True,
                'completed_invoices': 0,
                'pairs_sold': 0,
                'total_sold_pairs': 0,
                'returned_pairs': 0,
                'subtotal': Decimal('0.00'),
                'total_discount': Decimal('0.00'),
                'gross_sales': Decimal('0.00'),
                'net_sales': Decimal('0.00'),
                'amount_received': Decimal('0.00'),
                'customer_dues': Decimal('0.00'),
                'cash_received': Decimal('0.00'),
                'digital_received': Decimal('0.00'),
                'non_cash_received': Decimal('0.00'),
                'opening_cash': Decimal('0.00'),
                'other_cash_in': Decimal('0.00'),
                'cash_expenses': Decimal('0.00'),
                'expenses_total': Decimal('0.00'),
                'returns_count': 0,
                'returns_amount': Decimal('0.00'),
                'cash_refunds': Decimal('0.00'),
                'expected_cash': Decimal('0.00'),
                'cancelled_count': 0,
            }

        sales = Sale.objects.filter(business_day=business_day)
        completed_sales = sales.filter(status='COMPLETED')
        cancelled_sales = sales.filter(status='CANCELLED')

        completed_invoices_count = completed_sales.count()
        cancelled_count = cancelled_sales.count()

        # 1. Total sold pairs from completed invoices
        lines = SaleLine.objects.filter(sale__in=completed_sales)
        total_sold_pairs = lines.aggregate(total_pairs=Sum('quantity'))['total_pairs'] or 0

        # Returns on this business day
        returns = SaleReturn.objects.filter(business_day=business_day)
        returns_count = returns.count()
        returns_amount = returns.aggregate(r=Sum('refund_amount'))['r'] or Decimal('0.00')

        # Returned pairs on this business day
        return_lines = SaleReturnLine.objects.filter(return_record__in=returns)
        returned_pairs = return_lines.aggregate(q=Sum('quantity'))['q'] or 0

        # Net pairs sold
        pairs_sold = total_sold_pairs - returned_pairs

        # 3. Monetary totals
        subtotal = completed_sales.aggregate(s=Sum('subtotal'))['s'] or Decimal('0.00')
        discounts = completed_sales.aggregate(d=Sum('discount_amount'))['d'] or Decimal('0.00')
        gross_sales = completed_sales.aggregate(f=Sum('final_total'))['f'] or Decimal('0.00')
        net_sales = gross_sales - returns_amount
        customer_dues = completed_sales.aggregate(due=Sum('balance_due'))['due'] or Decimal('0.00')

        # 5 & 6. Payments received for this business day
        # Includes initial payments on today's invoices and due collections received on today's business day
        # Excludes cancelled sales and excludes unpaid amounts
        payments_today = Payment.objects.filter(
            (
                Q(business_day=business_day) |
                Q(sale__business_day=business_day, payment_type='INITIAL') |
                Q(received_at__date=business_day.date)
            ),
            sale__status='COMPLETED'
        ).distinct()

        cash_received = payments_today.filter(payment_method='CASH').aggregate(c=Sum('amount'))['c'] or Decimal('0.00')
        digital_received = payments_today.exclude(payment_method='CASH').aggregate(d=Sum('amount'))['d'] or Decimal('0.00')
        amount_received = cash_received + digital_received

        # Expenses on this business day
        expenses = Expense.objects.filter(
            Q(business_day=business_day) | Q(expense_date=business_day.date)
        ).distinct()
        expenses_total = expenses.aggregate(e=Sum('amount'))['e'] or Decimal('0.00')
        cash_expenses = expenses.filter(payment_method='CASH').aggregate(e=Sum('amount'))['e'] or Decimal('0.00')

        # Expected Cash Calculation
        # Expected Cash = Opening Cash + Cash Received + Other Cash In - Cash Expenses - Cash Refunds
        opening_cash = business_day.opening_cash if business_day.opening_cash is not None else Decimal('0.00')
        missing_opening_cash = (business_day.opening_cash is None)
        other_cash_in = getattr(business_day, 'other_cash_in', Decimal('0.00')) or Decimal('0.00')
        cash_refunds = returns_amount

        expected_cash = opening_cash + cash_received + other_cash_in - cash_expenses - cash_refunds

        return {
            'business_day': business_day,
            'is_open': business_day.status == 'OPEN',
            'has_business_day': True,
            'missing_opening_cash': missing_opening_cash,
            'completed_invoices': completed_invoices_count,
            'pairs_sold': pairs_sold,
            'total_sold_pairs': total_sold_pairs,
            'returned_pairs': returned_pairs,
            'subtotal': subtotal,
            'total_discount': discounts,
            'gross_sales': gross_sales,
            'net_sales': net_sales,
            'amount_received': amount_received,
            'customer_dues': customer_dues,
            'cash_received': cash_received,
            'digital_received': digital_received,
            'non_cash_received': digital_received, # backwards compatibility
            'opening_cash': opening_cash,
            'other_cash_in': other_cash_in,
            'cash_expenses': cash_expenses,
            'expenses_total': expenses_total,
            'returns_count': returns_count,
            'returns_amount': returns_amount,
            'cash_refunds': cash_refunds,
            'expected_cash': expected_cash,
            'cancelled_count': cancelled_count,
        }

    @classmethod
    def get_financial_report(cls, start_date, end_date):
        """
        Comprehensive financial and profitability report for any date range.
        Calculates: Net Sales, COGS, Gross Profit, Expenses, Net Profit, and Margins.
        """
        sales = Sale.objects.filter(
            business_day__date__gte=start_date,
            business_day__date__lte=end_date,
            status='COMPLETED'
        )

        invoices_count = sales.count()
        lines = SaleLine.objects.filter(sale__in=sales)
        pairs_sold = lines.aggregate(q=Sum('quantity'))['q'] or 0

        gross_sales = sales.aggregate(s=Sum('final_total'))['s'] or Decimal('0.00')
        discounts = sales.aggregate(d=Sum('discount_amount'))['d'] or Decimal('0.00')

        # Returns during period
        returns = SaleReturn.objects.filter(
            business_day__date__gte=start_date,
            business_day__date__lte=end_date
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

        # Operating Expenses:
        # Exclude staff/salesman advance payments from operating expenses in Profit & Loss
        # (Staff advances are assets/prepaid receivables until adjusted, not period expenses)
        # Also exclude any expense linked to a reversed payment.
        all_period_expenses = Expense.objects.filter(
            expense_date__gte=start_date,
            expense_date__lte=end_date
        )

        operating_expenses_qs = all_period_expenses.exclude(
            Q(category__name__icontains='Advance') |
            Q(category__name__icontains='অগ্রিম') |
            Q(salesman_payment__payment_type='ADVANCE') |
            Q(salesman_payment__status='REVERSED')
        )
        total_expenses = operating_expenses_qs.aggregate(e=Sum('amount'))['e'] or Decimal('0.00')

        advances_qs = all_period_expenses.filter(
            Q(category__name__icontains='Advance') |
            Q(category__name__icontains='অগ্রিম') |
            Q(salesman_payment__payment_type='ADVANCE')
        ).exclude(salesman_payment__status='REVERSED')
        total_advances = advances_qs.aggregate(a=Sum('amount'))['a'] or Decimal('0.00')

        # Category breakdown for operating expenses
        category_breakdown = list(
            operating_expenses_qs.values('category__name')
            .annotate(total=Sum('amount'), count=Count('id'))
            .order_by('-total')
        )

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
            # canonical keys (used by admin_dashboard and internal callers)
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
            'staff_advances': total_advances,
            'total_advances': total_advances,
            'category_breakdown': category_breakdown,
            # alias keys expected by profit_report.html template
            'total_invoices': invoices_count,
            'total_pairs_sold': pairs_sold,
            'gross_revenue': gross_sales,
            'total_discounts': discounts,
            'total_returns': returns_refund,
            'total_expenses': total_expenses,
            'gross_margin': gross_margin_pct,
            'net_margin': net_margin_pct,
            'cash_received': cash_collected,
            'total_due': outstanding_dues,
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
