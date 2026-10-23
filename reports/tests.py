from datetime import date
from decimal import Decimal
from django.test import TestCase, TransactionTestCase
from django.contrib.auth.models import User
from core.models import BusinessDay
from inventory.models import ProductModel, ProductVariant
from pos.services import BillingService
from expenses.models import ExpenseCategory, Expense
from reports.services import ReportingService

class ReportingServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='admin_report', password='pass')
        self.category = ExpenseCategory.objects.create(name='Shop Rent')

    def test_friday_to_wednesday_business_week(self):
        # Test Friday starts the week
        friday = date(2026, 10, 16) # A Friday
        w_start, w_end = ReportingService.get_business_week_range(friday)
        self.assertEqual(w_start, date(2026, 10, 16))
        self.assertEqual(w_end, date(2026, 10, 21)) # Wednesday

        # Test Tuesday belongs to that same week
        tuesday = date(2026, 10, 20)
        w_start, w_end = ReportingService.get_business_week_range(tuesday)
        self.assertEqual(w_start, date(2026, 10, 16))
        self.assertEqual(w_end, date(2026, 10, 21))

        # Test Thursday (closing day) belongs to the week that started previous Friday
        thursday = date(2026, 10, 22)
        w_start, w_end = ReportingService.get_business_week_range(thursday)
        self.assertEqual(w_start, date(2026, 10, 16))
        self.assertEqual(w_end, date(2026, 10, 21))

    def test_daily_overview_pairs_vs_invoices_count(self):
        # 12 customers buy 20 pairs total
        b_day = BusinessDay.objects.create(
            date=date(2026, 10, 18),
            status='OPEN',
            opening_cash=Decimal('1000.00'),
            opened_by=self.user
        )
        prod = ProductModel.objects.create(code='P99', name='Sneaker')
        var = ProductVariant.objects.create(
            product=prod, size='42', colour='White',
            current_stock=100, weighted_avg_cost=Decimal('500.00')
        )

        # Create 8 invoices with 1 pair each = 8 pairs
        for i in range(8):
            BillingService.create_invoice(
                business_day=b_day,
                items=[{'variant_id': var.id, 'quantity': 1, 'unit_price': Decimal('800.00')}],
                payment_method='CASH',
                amount_paid=Decimal('800.00'),
                user=self.user
            )

        # Create 4 invoices with 3 pairs each = 12 pairs
        for i in range(4):
            BillingService.create_invoice(
                business_day=b_day,
                items=[{'variant_id': var.id, 'quantity': 3, 'unit_price': Decimal('800.00')}],
                payment_method='CASH',
                amount_paid=Decimal('2400.00'),
                user=self.user
            )

        # Total completed invoices = 8 + 4 = 12
        # Total pairs sold = (8 * 1) + (4 * 3) = 20 pairs!
        overview = ReportingService.get_daily_overview(b_day)
        self.assertEqual(overview['completed_invoices'], 12)
        self.assertEqual(overview['pairs_sold'], 20)
        self.assertEqual(overview['net_sales'], Decimal('16000.00')) # (8*800) + (4*2400) = 6400 + 9600 = 16000

    def test_profit_calculation(self):
        b_day = BusinessDay.objects.create(
            date=date(2026, 10, 18),
            status='OPEN',
            opening_cash=Decimal('0.00'),
            opened_by=self.user
        )
        prod = ProductModel.objects.create(code='PROFIT-1', name='Boots')
        var = ProductVariant.objects.create(
            product=prod, size='42', colour='Tan',
            current_stock=50, weighted_avg_cost=Decimal('600.00')
        )

        # Sell 10 pairs @ 1000 = 10,000 Net Sales
        # COGS = 10 * 600 = 6,000
        # Gross Profit = 10,000 - 6,000 = 4,000
        BillingService.create_invoice(
            business_day=b_day,
            items=[{'variant_id': var.id, 'quantity': 10, 'unit_price': Decimal('1000.00')}],
            payment_method='CASH',
            amount_paid=Decimal('10000.00'),
            user=self.user
        )

        # Add Operating Expense of 1,500
        Expense.objects.create(
            category=self.category,
            business_day=b_day,
            amount=Decimal('1500.00'),
            expense_date=date(2026, 10, 18),
            description='Shop electricity and rent',
            recorded_by=self.user
        )

        # Net Profit = 4,000 - 1,500 = 2,500
        report = ReportingService.get_financial_report(date(2026, 10, 18), date(2026, 10, 18))
        self.assertEqual(report['net_sales'], Decimal('10000.00'))
        self.assertEqual(report['cogs'], Decimal('6000.00'))
        self.assertEqual(report['gross_profit'], Decimal('4000.00'))
        self.assertEqual(report['operating_expenses'], Decimal('1500.00'))
        self.assertEqual(report['net_profit'], Decimal('2500.00'))
        self.assertEqual(report['net_margin_pct'], Decimal('25.00'))

    def test_daily_kpi_cards_and_expected_cash_formula(self):
        """
        Tests the 6 Primary KPI Cards and the exact Expected Cash formula:
        Expected Cash = Opening Cash + Cash Received + Other Cash In - Cash Expenses - Cash Refunds
        Verifies:
        - Pairs Sold: subtracts returns and excludes cancelled sales
        - Completed Invoices: excludes cancelled sales
        - Net Sales: final total minus returns
        - Discounts: total discounts on eligible invoices
        - Expected Cash: only cash transactions, excludes digital, includes due collections
        - Digital Payments: captures bKash, Nagad, Card, split payments
        """
        b_day = BusinessDay.objects.create(
            date=date(2026, 10, 19),
            status='OPEN',
            opening_cash=Decimal('5000.00'),
            other_cash_in=Decimal('500.00'),
            opened_by=self.user
        )

        prod = ProductModel.objects.create(code='SHOEKPI-1', name='Oxford')
        var = ProductVariant.objects.create(
            product=prod, size='41', colour='Black',
            current_stock=100, weighted_avg_cost=Decimal('500.00')
        )

        # 1. Sale 1: CASH - 2 pairs @ 1000 with 10% disc = 1800 final total, paid 1800 cash
        sale1 = BillingService.create_invoice(
            business_day=b_day,
            items=[{'variant_id': var.id, 'quantity': 2, 'unit_price': Decimal('1000.00'), 'discount_percent': Decimal('10.00')}],
            payment_method='CASH',
            amount_paid=Decimal('1800.00'),
            user=self.user
        )

        # 2. Sale 2: DIGITAL (BKASH) - 1 pair @ 1200, paid 1200 bKash
        sale2 = BillingService.create_invoice(
            business_day=b_day,
            items=[{'variant_id': var.id, 'quantity': 1, 'unit_price': Decimal('1200.00'), 'discount_percent': Decimal('0.00')}],
            payment_method='BKASH',
            amount_paid=Decimal('1200.00'),
            user=self.user
        )

        # 3. Sale 3: SPLIT PAYMENT - 2 pairs @ 1000 = 2000 total, paid 1000 cash + 1000 nagad
        sale3 = BillingService.create_invoice(
            business_day=b_day,
            items=[{'variant_id': var.id, 'quantity': 2, 'unit_price': Decimal('1000.00')}],
            split_payments=[
                {'payment_method': 'CASH', 'amount': Decimal('1000.00')},
                {'payment_method': 'NAGAD', 'amount': Decimal('1000.00')}
            ],
            user=self.user
        )

        # 4. Sale 4: SALE WITH DUE - 1 pair @ 1500, paid 500 cash, balance due 1000
        sale4 = BillingService.create_invoice(
            business_day=b_day,
            items=[{'variant_id': var.id, 'quantity': 1, 'unit_price': Decimal('1500.00')}],
            payment_method='CASH',
            amount_paid=Decimal('500.00'),
            user=self.user
        )

        # 5. Sale 5: CANCELLED INVOICE - 1 pair @ 800
        sale5 = BillingService.create_invoice(
            business_day=b_day,
            items=[{'variant_id': var.id, 'quantity': 1, 'unit_price': Decimal('800.00')}],
            payment_method='CASH',
            amount_paid=Decimal('800.00'),
            user=self.user
        )
        BillingService.cancel_invoice(sale5.id, reason="Customer cancelled", user=self.user)

        # 6. Customer Return: Return 1 pair from Sale 1, refund 900 cash
        line1 = sale1.lines.first()
        BillingService.process_return(
            sale_id=sale1.id,
            return_items=[{
                'sale_line_id': line1.id,
                'quantity': 1,
                'refund_amount': Decimal('900.00'),
                'disposition': 'RESTOCK'
            }],
            reason="Size mismatch",
            business_day=b_day,
            user=self.user
        )

        # 7. Operating Expenses
        # Cash expense: 400.00
        Expense.objects.create(
            category=self.category,
            business_day=b_day,
            amount=Decimal('400.00'),
            payment_method='CASH',
            expense_date=date(2026, 10, 19),
            description='Staff tea & snacks',
            recorded_by=self.user
        )
        # Bank/Digital expense: 1000.00 (must NOT reduce cash drawer!)
        Expense.objects.create(
            category=self.category,
            business_day=b_day,
            amount=Decimal('1000.00'),
            payment_method='BANK',
            expense_date=date(2026, 10, 19),
            description='Factory advance via bank',
            recorded_by=self.user
        )

        # 8. Due Collection: Customer pays 300 cash towards Sale 4
        BillingService.record_due_collection(
            sale_id=sale4.id,
            amount=Decimal('300.00'),
            payment_method='CASH',
            business_day=b_day,
            user=self.user
        )

        # Compute Overview
        overview = ReportingService.get_daily_overview(b_day)

        # Verify KPI 1: Pairs Sold
        # Total sold pairs = 2 (sale1) + 1 (sale2) + 2 (sale3) + 1 (sale4) = 6
        # Returned pairs = 1 (sale1 return)
        # Net pairs sold = 6 - 1 = 5
        self.assertEqual(overview['pairs_sold'], 5)
        self.assertEqual(overview['total_sold_pairs'], 6)
        self.assertEqual(overview['returned_pairs'], 1)

        # Verify KPI 2: Completed Invoices
        # Sales 1, 2, 3, 4 are COMPLETED; Sale 5 is CANCELLED -> count is 4
        self.assertEqual(overview['completed_invoices'], 4)
        self.assertEqual(overview['cancelled_count'], 1)

        # Verify KPI 3: Net Sales
        # Final totals: 1800 + 1200 + 2000 + 1500 = 6500.00
        # Returns refund: 900.00
        # Net Sales = 6500.00 - 900.00 = 5600.00
        self.assertEqual(overview['gross_sales'], Decimal('6500.00'))
        self.assertEqual(overview['net_sales'], Decimal('5600.00'))

        # Verify KPI 4: Total Discounts
        # Sale 1 discount: 200.00
        self.assertEqual(overview['total_discount'], Decimal('200.00'))

        # Verify Cash Received vs Digital Payments:
        # Cash Received: 1800 (Sale 1) + 1000 (Sale 3 split cash) + 500 (Sale 4 initial cash) + 300 (Sale 4 due cash) = 3600.00
        self.assertEqual(overview['cash_received'], Decimal('3600.00'))
        # Digital Received: 1200 (Sale 2 bKash) + 1000 (Sale 3 Nagad) = 2200.00
        self.assertEqual(overview['digital_received'], Decimal('2200.00'))

        # Verify KPI 5: Expected Cash Formula
        # Expected Cash = Opening Cash (5000) + Cash Received (3600) + Other Cash In (500) - Cash Expenses (400) - Cash Refunds (900)
        # 5000 + 3600 + 500 - 400 - 900 = 7800.00
        self.assertEqual(overview['opening_cash'], Decimal('5000.00'))
        self.assertEqual(overview['other_cash_in'], Decimal('500.00'))
        self.assertEqual(overview['cash_expenses'], Decimal('400.00'))
        self.assertEqual(overview['returns_amount'], Decimal('900.00'))
        self.assertEqual(overview['expected_cash'], Decimal('7800.00'))
        self.assertFalse(overview['missing_opening_cash'])

    def test_previous_day_due_collection_included_in_today_cash(self):
        """
        Verifies that collecting customer dues today for a sale from a PREVIOUS business day
        is properly included in today's Cash Received and Expected Cash.
        """
        day_yesterday = BusinessDay.objects.create(
            date=date(2026, 10, 17),
            status='OPEN',
            opening_cash=Decimal('1000.00'),
            opened_by=self.user
        )

        prod = ProductModel.objects.create(code='DUE-PREV-1', name='Loafer')
        var = ProductVariant.objects.create(
            product=prod, size='42', colour='Brown',
            current_stock=20, weighted_avg_cost=Decimal('400.00')
        )

        # Yesterday's invoice: 1 pair @ 1000, customer paid 0, due 1000
        sale_prev = BillingService.create_invoice(
            business_day=day_yesterday,
            items=[{'variant_id': var.id, 'quantity': 1, 'unit_price': Decimal('1000.00')}],
            payment_method='CASH',
            amount_paid=Decimal('0.00'),
            user=self.user
        )

        # Close yesterday's day
        day_yesterday.status = 'CLOSED'
        day_yesterday.save()

        # Open today's day
        day_today = BusinessDay.objects.create(
            date=date(2026, 10, 18),
            status='OPEN',
            opening_cash=Decimal('2000.00'),
            opened_by=self.user
        )

        # Today: customer pays 600 cash towards yesterday's invoice
        BillingService.record_due_collection(
            sale_id=sale_prev.id,
            amount=Decimal('600.00'),
            payment_method='CASH',
            business_day=day_today,
            user=self.user
        )

        overview_today = ReportingService.get_daily_overview(day_today)
        self.assertEqual(overview_today['cash_received'], Decimal('600.00'))
        # Expected cash = Opening (2000) + Cash Received (600) = 2600.00
        self.assertEqual(overview_today['expected_cash'], Decimal('2600.00'))

    def test_missing_opening_cash_sets_warning_flag(self):
        """
        Verifies that when business day has no opening cash recorded, a warning flag is set.
        """
        overview_none = ReportingService.get_daily_overview(None)
        self.assertTrue(overview_none['missing_opening_cash'])
        self.assertFalse(overview_none['has_business_day'])


class DayReconciliationTests(TransactionTestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='admin_recon', password='pass')

    def test_day_end_cash_reconciliation_workflow(self):
        """
        Verifies Day-End Cash Reconciliation:
        - Reconciles expected cash against actual cash count.
        - Enforces discrepancy reason note when difference != 0.
        - Saves closing_cash_system, closing_cash_actual, cash_discrepancy, discrepancy_reason, other_cash_in.
        """
        from core.services import BusinessDayService

        b_day = BusinessDay.objects.create(
            date=date(2026, 10, 19),
            status='OPEN',
            opening_cash=Decimal('3000.00'),
            opened_by=self.user
        )

        prod = ProductModel.objects.create(code='RECON-1', name='Sandal')
        var = ProductVariant.objects.create(
            product=prod, size='40', colour='Black',
            current_stock=30, weighted_avg_cost=Decimal('300.00')
        )

        # Sale: 1000 cash
        BillingService.create_invoice(
            business_day=b_day,
            items=[{'variant_id': var.id, 'quantity': 1, 'unit_price': Decimal('1000.00')}],
            payment_method='CASH',
            amount_paid=Decimal('1000.00'),
            user=self.user
        )

        # Expected cash = 3000 (opening) + 1000 (sale) = 4000.00
        # 1. Attempt to close with discrepancy (counted 3800, short 200) without reason note -> MUST FAIL
        with self.assertRaises(ValueError) as ctx:
            BusinessDayService.close_day(
                business_day=b_day,
                actual_cash_counted=Decimal('3800.00'),
                discrepancy_reason='',
                user=self.user
            )
        self.assertIn("গরমিলের কারণ", str(ctx.exception))

        # 2. Close with discrepancy AND reason note -> MUST SUCCEED
        closed_day, sys_cash, diff, backup = BusinessDayService.close_day(
            business_day=b_day,
            actual_cash_counted=Decimal('3800.00'),
            discrepancy_reason='200 Tk short due to damaged note replacement',
            user=self.user
        )
        self.assertEqual(closed_day.status, 'CLOSED')
        self.assertEqual(closed_day.closing_cash_system, Decimal('4000.00'))
        self.assertEqual(closed_day.closing_cash_actual, Decimal('3800.00'))
        self.assertEqual(closed_day.cash_discrepancy, Decimal('-200.00'))
        self.assertEqual(closed_day.discrepancy_reason, '200 Tk short due to damaged note replacement')


class ProfitReportViewTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin_profit', password='password123', email='admin@lotus.com')
        self.staff = User.objects.create_user(username='staff_plain', password='password123')
        self.category_rent = ExpenseCategory.objects.create(name='Shop Rent (দোকান ভাড়া)')
        self.category_advance = ExpenseCategory.objects.create(name='Staff Advance (কর্মচারী অগ্রিম)')

    def test_profit_report_auth_and_url_resolution(self):
        """Admin gets 200, staff redirected, anonymous redirected to login."""
        from django.test import Client
        # Anonymous
        c_anon = Client()
        resp_anon = c_anon.get('/reports/profit/')
        self.assertEqual(resp_anon.status_code, 302)
        self.assertIn('/login/', resp_anon.url)

        # Staff (non-admin)
        c_staff = Client()
        c_staff.login(username='staff_plain', password='password123')
        resp_staff = c_staff.get('/reports/profit/')
        self.assertEqual(resp_staff.status_code, 302)
        self.assertEqual(resp_staff.url, '/')

        # Admin
        c_admin = Client()
        c_admin.login(username='admin_profit', password='password123')
        resp_admin = c_admin.get('/reports/profit/')
        self.assertEqual(resp_admin.status_code, 200)
        self.assertContains(resp_admin, 'লাভ-ক্ষতির রিপোর্ট')
        self.assertContains(resp_admin, 'বিক্রয় আয়')

    def test_zero_sales_zero_division_guard(self):
        """Zero sales and no transactions must not cause ZeroDivisionError or crash."""
        from django.test import Client
        c = Client()
        c.login(username='admin_profit', password='password123')
        resp = c.get('/reports/profit/?start_date=2026-01-01&end_date=2026-01-05')
        self.assertEqual(resp.status_code, 200)
        fin = resp.context['financial']
        self.assertEqual(fin['net_sales'], Decimal('0.00'))
        self.assertEqual(fin['gross_profit'], Decimal('0.00'))
        self.assertEqual(fin['gross_margin_pct'], Decimal('0.00'))
        self.assertEqual(fin['net_profit'], Decimal('0.00'))
        self.assertEqual(fin['net_margin_pct'], Decimal('0.00'))

    def test_advances_excluded_from_operating_expenses_in_profit_report(self):
        """
        Verify that Staff Advance is NOT automatically deducted as an operating expense in P&L,
        preserving the accounting rule that advances are balance-sheet assets/receivables.
        """
        today = date(2026, 10, 20)
        b_day = BusinessDay.objects.create(
            date=today,
            status='OPEN',
            opening_cash=Decimal('10000.00'),
            opened_by=self.admin
        )
        prod = ProductModel.objects.create(code='PROFIT-TEST-1', name='Formal Shoe')
        var = ProductVariant.objects.create(
            product=prod, size='42', colour='Black',
            current_stock=50, weighted_avg_cost=Decimal('500.00')
        )
        # Sale: 10 pairs @ 1000 = 10,000 Net Sales, COGS = 5,000, Gross Profit = 5,000
        BillingService.create_invoice(
            business_day=b_day,
            items=[{'variant_id': var.id, 'quantity': 10, 'unit_price': Decimal('1000.00')}],
            payment_method='CASH',
            amount_paid=Decimal('10000.00'),
            user=self.admin
        )

        # Operating Expense: Shop Rent 2,000
        Expense.objects.create(
            category=self.category_rent,
            business_day=b_day,
            amount=Decimal('2000.00'),
            payment_method='CASH',
            expense_date=today,
            description='Monthly shop rent',
            recorded_by=self.admin
        )

        # Advance payment: 3,000 (Must NOT be deducted as operating expense in P&L)
        Expense.objects.create(
            category=self.category_advance,
            business_day=b_day,
            amount=Decimal('3000.00'),
            payment_method='CASH',
            expense_date=today,
            description='Salesman advance against next month salary',
            recorded_by=self.admin
        )

        fin = ReportingService.get_financial_report(today, today)
        self.assertEqual(fin['net_sales'], Decimal('10000.00'))
        self.assertEqual(fin['cogs'], Decimal('5000.00'))
        self.assertEqual(fin['gross_profit'], Decimal('5000.00'))
        # Operating expenses must be ONLY 2000 (excluding 3000 advance)
        self.assertEqual(fin['operating_expenses'], Decimal('2000.00'))
        # Net Profit = 5000 - 2000 = 3000 (NOT 0!)
        self.assertEqual(fin['net_profit'], Decimal('3000.00'))
        self.assertEqual(fin['net_margin_pct'], Decimal('30.00'))
        # Staff advances reported as separate receivable
        self.assertEqual(fin['staff_advances'], Decimal('3000.00'))


