from decimal import Decimal
from datetime import date
from django.test import TestCase
from django.contrib.auth.models import User
from core.models import BusinessDay
from inventory.models import ProductModel, ProductVariant
from pos.models import Sale, SaleLine, Payment
from pos.services import BillingService

class BillingServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='staff_test', password='password123')
        self.business_day = BusinessDay.objects.create(
            date=date(2026, 10, 18),
            status='OPEN',
            opening_cash=Decimal('5000.00'),
            opened_by=self.user
        )

        self.prod1 = ProductModel.objects.create(code='M3001', name='Derby Formal')
        self.var1 = ProductVariant.objects.create(
            product=self.prod1,
            size='42',
            colour='Black',
            current_stock=20,
            weighted_avg_cost=Decimal('700.00'),
            standard_selling_price=Decimal('1200.00')
        )

        self.prod2 = ProductModel.objects.create(code='W5001', name='Ladies Heel')
        self.var2 = ProductVariant.objects.create(
            product=self.prod2,
            size='38',
            colour='Red',
            current_stock=15,
            weighted_avg_cost=Decimal('500.00'),
            standard_selling_price=Decimal('900.00')
        )

    def test_create_invoice_success(self):
        # Sell 2 pairs of Var1 @ 1200 with 10% discount
        # Subtotal: 2400.00, Disc: 240.00, Calc: 2160.00, Paid: 2500.00 -> Change: 340.00
        items = [{
            'variant_id': self.var1.id,
            'quantity': 2,
            'unit_price': Decimal('1200.00'),
            'discount_percent': Decimal('10.00')
        }]
        sale = BillingService.create_invoice(
            business_day=self.business_day,
            items=items,
            customer_name='Rahim Uddin',
            customer_phone='01711111111',
            payment_method='CASH',
            amount_paid=Decimal('2500.00'),
            user=self.user
        )

        self.assertEqual(sale.status, 'COMPLETED')
        self.assertEqual(sale.subtotal, Decimal('2400.00'))
        self.assertEqual(sale.discount_amount, Decimal('240.00'))
        self.assertEqual(sale.final_total, Decimal('2160.00'))
        self.assertEqual(sale.change_given, Decimal('340.00'))
        self.assertEqual(sale.balance_due, Decimal('0.00'))
        self.assertEqual(sale.total_pairs, 2)

        # Verify stock was deducted exactly once
        self.var1.refresh_from_db()
        self.assertEqual(self.var1.current_stock, 18)

        # Verify cost snapshot on line item
        line = sale.lines.first()
        self.assertEqual(line.cost_snapshot, Decimal('700.00'))
        # Gross profit = 2160.00 - (700.00 * 2) = 760.00
        self.assertEqual(line.gross_profit, Decimal('760.00'))

    def test_manual_final_total_override(self):
        # 1 pair @ 1000.00 -> Calculated 1000.00. Staff manually rounds down to 950.00
        items = [{
            'variant_id': self.var1.id,
            'quantity': 1,
            'unit_price': Decimal('1000.00'),
            'discount_percent': Decimal('0.00')
        }]
        sale = BillingService.create_invoice(
            business_day=self.business_day,
            items=items,
            manual_final_total=Decimal('950.00'),
            payment_method='CASH',
            amount_paid=Decimal('950.00'),
            user=self.user
        )
        self.assertEqual(sale.calculated_total, Decimal('1000.00'))
        self.assertEqual(sale.final_total, Decimal('950.00'))
        self.assertEqual(sale.manual_adjustment, Decimal('-50.00'))
        line = sale.lines.first()
        self.assertEqual(line.final_line_total, Decimal('950.00'))

    def test_due_payment_workflow(self):
        # Total 1200.00, Customer pays 500.00, Due 700.00
        items = [{
            'variant_id': self.var1.id,
            'quantity': 1,
            'unit_price': Decimal('1200.00')
        }]
        sale = BillingService.create_invoice(
            business_day=self.business_day,
            items=items,
            payment_method='CASH',
            amount_paid=Decimal('500.00'),
            user=self.user
        )
        self.assertEqual(sale.balance_due, Decimal('700.00'))

        # Later customer pays 400.00
        payment = BillingService.record_due_collection(
            sale_id=sale.id,
            amount=Decimal('400.00'),
            payment_method='CASH',
            user=self.user
        )
        sale.refresh_from_db()
        self.assertEqual(sale.balance_due, Decimal('300.00'))
        self.assertEqual(sale.amount_paid, Decimal('900.00'))

    def test_sale_cancellation_restores_stock(self):
        items = [{
            'variant_id': self.var2.id,
            'quantity': 3,
            'unit_price': Decimal('900.00')
        }]
        sale = BillingService.create_invoice(
            business_day=self.business_day,
            items=items,
            user=self.user
        )
        self.var2.refresh_from_db()
        self.assertEqual(self.var2.current_stock, 12)

        BillingService.cancel_invoice(sale.id, reason="Customer changed mind", user=self.user)
        sale.refresh_from_db()
        self.assertEqual(sale.status, 'CANCELLED')
        self.var2.refresh_from_db()
        self.assertEqual(self.var2.current_stock, 15)
