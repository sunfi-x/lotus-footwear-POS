from datetime import date
from decimal import Decimal
from django.test import TestCase
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
