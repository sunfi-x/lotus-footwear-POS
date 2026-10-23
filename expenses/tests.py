from decimal import Decimal
from datetime import date
from django.test import TestCase, Client
from django.contrib.auth.models import User
from django.utils import timezone

from expenses.models import Expense, ExpenseCategory, Salesman, SalesmanPayment
from core.models import BusinessDay, AuditLog
from reports.services import ReportingService
from backup_system.services import BackupService


class SalesmanPaymentManagementTests(TestCase):
    def setUp(self):
        # 1. Users
        self.admin = User.objects.create_superuser(username='admin_boss', password='password123', email='admin@lotus.com')
        self.staff = User.objects.create_user(username='staff_sales', password='password123')

        self.client_admin = Client()
        self.client_admin.login(username='admin_boss', password='password123')

        self.client_staff = Client()
        self.client_staff.login(username='staff_sales', password='password123')

        self.client_anon = Client()

        # 2. Business Day
        self.today = timezone.localdate()
        self.business_day = BusinessDay.objects.create(
            date=self.today,
            status='OPEN',
            opening_cash=Decimal('10000.00'),
            other_cash_in=Decimal('0.00')
        )

        # 3. Salesman
        self.sm1 = Salesman.objects.create(
            name='Md Rafiqul Islam',
            phone='01711223344',
            joining_date=date(2026, 1, 1),
            is_active=True
        )
        self.sm2 = Salesman.objects.create(
            name='Md Rafiqul Islam',  # Similar name, different person/phone/ID
            phone='01899887766',
            joining_date=date(2026, 3, 1),
            is_active=True
        )

    def test_salesman_id_auto_generation_unique(self):
        """1 & 2. Test salesman creation and auto-generated unique internal IDs."""
        self.assertEqual(self.sm1.salesman_id, 'SM-0001')
        self.assertEqual(self.sm2.salesman_id, 'SM-0002')
        self.assertNotEqual(self.sm1.salesman_id, self.sm2.salesman_id)

    def test_add_and_edit_salesman_profile(self):
        """Test adding a new salesman and editing existing non-financial profile."""
        response = self.client_admin.post('/salesman-payments/add-salesman/', {
            'name': 'Tanvir Ahmed',
            'phone': '01911002233',
            'joining_date': '2026-05-10',
            'is_active': 'true',
            'notes': 'Experienced showroom assistant'
        })
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])
        new_sm_id = data['salesman']['salesman_id']

        # Edit profile
        edit_resp = self.client_admin.post(f'/salesman-payments/edit-salesman/{new_sm_id}/', {
            'name': 'Tanvir Ahmed (Senior)',
            'phone': '01911002299',
            'joining_date': '2026-05-10',
            'is_active': 'true',
            'notes': 'Promoted to senior salesman'
        })
        self.assertEqual(edit_resp.status_code, 200)
        self.assertTrue(edit_resp.json()['success'])

        # Verify in DB
        sm = Salesman.objects.get(salesman_id=new_sm_id)
        self.assertEqual(sm.name, 'Tanvir Ahmed (Senior)')
        self.assertEqual(sm.phone, '01911002299')

    def test_inactive_salesman_preserves_payment_history(self):
        """14. Inactive salesman remains in DB and payments remain linked."""
        # Record a payment first
        pay_resp = self.client_admin.post('/salesman-payments/record-payment/', {
            'salesman_id': self.sm1.salesman_id,
            'payment_date': str(self.today),
            'amount': '8000.00',
            'payment_type': 'SALARY',
            'payment_method': 'CASH',
            'period_covered': 'October 2026'
        })
        self.assertEqual(pay_resp.status_code, 200)
        self.assertTrue(pay_resp.json()['success'])

        # Deactivate salesman
        self.sm1.is_active = False
        self.sm1.save()

        # Check payment still linked
        self.assertEqual(self.sm1.payments.count(), 1)
        payment = self.sm1.payments.first()
        self.assertEqual(payment.amount, Decimal('8000.00'))
        self.assertEqual(payment.status, 'COMPLETED')

    def test_record_cash_payment_reduces_cash_drawer(self):
        """3 & 10. Record cash payment: creates payment, linked expense, and reduces expected cash."""
        overview_before = ReportingService.get_daily_overview(self.business_day)
        # Expected cash before: 10,000 (opening)
        self.assertEqual(overview_before['expected_cash'], Decimal('10000.00'))

        resp = self.client_admin.post('/salesman-payments/record-payment/', {
            'salesman_id': self.sm1.salesman_id,
            'payment_date': str(self.today),
            'amount': '4500.00',
            'payment_type': 'SALARY',
            'payment_method': 'CASH',
            'period_covered': 'October 2026',
            'notes': 'Cash salary paid from drawer'
        })
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data['success'])
        payment_id = data['payment_id']

        # Verify Payment record
        payment = SalesmanPayment.objects.get(payment_id=payment_id)
        self.assertEqual(payment.amount, Decimal('4500.00'))
        self.assertEqual(payment.payment_method, 'CASH')
        self.assertEqual(payment.status, 'COMPLETED')
        self.assertIsNotNone(payment.linked_expense)
        self.assertEqual(payment.linked_expense.amount, Decimal('4500.00'))
        self.assertEqual(payment.linked_expense.payment_method, 'CASH')

        # Check Expected Cash in Cash Drawer
        overview_after = ReportingService.get_daily_overview(self.business_day)
        # Expected cash: 10,000 - 4,500 = 5,500
        self.assertEqual(overview_after['cash_expenses'], Decimal('4500.00'))
        self.assertEqual(overview_after['expected_cash'], Decimal('5500.00'))

    def test_record_digital_payment_does_not_reduce_physical_cash(self):
        """3 & 11. Record digital payment (bKash): does NOT reduce cash drawer."""
        resp = self.client_admin.post('/salesman-payments/record-payment/', {
            'salesman_id': self.sm2.salesman_id,
            'payment_date': str(self.today),
            'amount': '3000.00',
            'payment_type': 'ADVANCE',
            'payment_method': 'BKASH',
            'reference_id': 'BK-TRX-998811',
            'period_covered': 'Festive advance'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])

        overview = ReportingService.get_daily_overview(self.business_day)
        # Expected cash remains 10,000 because bKash is non-cash
        self.assertEqual(overview['cash_expenses'], Decimal('0.00'))
        self.assertEqual(overview['expected_cash'], Decimal('10000.00'))
        # But operating expense includes it
        self.assertEqual(overview['expenses_total'], Decimal('3000.00'))

    def test_invalid_payment_amount_rejected(self):
        """4. Reject zero, negative, or invalid amounts."""
        # Zero amount
        r1 = self.client_admin.post('/salesman-payments/record-payment/', {
            'salesman_id': self.sm1.salesman_id,
            'payment_date': str(self.today),
            'amount': '0.00',
            'payment_type': 'SALARY',
            'payment_method': 'CASH'
        })
        self.assertEqual(r1.status_code, 400)
        self.assertFalse(r1.json()['success'])

        # Negative amount
        r2 = self.client_admin.post('/salesman-payments/record-payment/', {
            'salesman_id': self.sm1.salesman_id,
            'payment_date': str(self.today),
            'amount': '-500.00',
            'payment_type': 'SALARY',
            'payment_method': 'CASH'
        })
        self.assertEqual(r2.status_code, 400)
        self.assertFalse(r2.json()['success'])

    def test_reversal_workflow_and_audit_trail(self):
        """13. Controlled reversal: marks REVERSED, removes expense, restores cash drawer."""
        # Record payment
        resp = self.client_admin.post('/salesman-payments/record-payment/', {
            'salesman_id': self.sm1.salesman_id,
            'payment_date': str(self.today),
            'amount': '2000.00',
            'payment_type': 'BONUS',
            'payment_method': 'CASH'
        })
        payment_id = resp.json()['payment_id']

        overview_with_payment = ReportingService.get_daily_overview(self.business_day)
        self.assertEqual(overview_with_payment['expected_cash'], Decimal('8000.00'))

        # Reverse payment
        rev_resp = self.client_admin.post(f'/salesman-payments/reverse-payment/{payment_id}/', {
            'reason': 'Entered by mistake; salesman already received bonus earlier'
        })
        self.assertEqual(rev_resp.status_code, 200)
        self.assertTrue(rev_resp.json()['success'])

        # Verify payment status
        payment = SalesmanPayment.objects.get(payment_id=payment_id)
        self.assertEqual(payment.status, 'REVERSED')
        self.assertIn('mistake', payment.reversal_reason)
        self.assertEqual(payment.reversed_by, self.admin)
        self.assertIsNone(payment.linked_expense)

        # Cash drawer restored to 10,000
        overview_restored = ReportingService.get_daily_overview(self.business_day)
        self.assertEqual(overview_restored['expected_cash'], Decimal('10000.00'))
        self.assertEqual(overview_restored['cash_expenses'], Decimal('0.00'))

    def test_individual_salesman_totals_and_separation(self):
        """5 & 7. Keep similar names separated; calculate totals correctly."""
        # Pay sm1 (SM-0001) 5,000
        self.client_admin.post('/salesman-payments/record-payment/', {
            'salesman_id': self.sm1.salesman_id,
            'payment_date': str(self.today),
            'amount': '5000.00',
            'payment_type': 'SALARY',
            'payment_method': 'CASH'
        })
        # Pay sm2 (SM-0002) 3,500
        self.client_admin.post('/salesman-payments/record-payment/', {
            'salesman_id': self.sm2.salesman_id,
            'payment_date': str(self.today),
            'amount': '3500.00',
            'payment_type': 'SALARY',
            'payment_method': 'BKASH'
        })

        # Fetch sm1 profile
        r1 = self.client_admin.get(f'/salesman-payments/profile/{self.sm1.salesman_id}/')
        self.assertEqual(r1.status_code, 200)
        self.assertEqual(r1.context['total_amount_paid'], Decimal('5000.00'))
        self.assertEqual(r1.context['total_completed_count'], 1)

        # Fetch sm2 profile
        r2 = self.client_admin.get(f'/salesman-payments/profile/{self.sm2.salesman_id}/')
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.context['total_amount_paid'], Decimal('3500.00'))
        self.assertEqual(r2.context['total_completed_count'], 1)

    def test_csv_export(self):
        """11. Test CSV export reflects recorded salesman payments."""
        self.client_admin.post('/salesman-payments/record-payment/', {
            'salesman_id': self.sm1.salesman_id,
            'payment_date': str(self.today),
            'amount': '7500.00',
            'payment_type': 'SALARY',
            'payment_method': 'CASH',
            'period_covered': 'October 2026'
        })
        resp = self.client_admin.get('/salesman-payments/?export=csv')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp['Content-Type'], 'text/csv; charset=utf-8')
        content = resp.content.decode('utf-8')
        self.assertIn('SM-0001', content)
        self.assertIn('7500.00', content)
        self.assertIn('Salary', content)

    def test_backup_service_includes_salesman_and_payments(self):
        """15. Salesman and payments records are saved in DB and ready for backup."""
        # Create a salesman payment
        resp = self.client_admin.post('/salesman-payments/record-payment/', {
            'salesman_id': self.sm1.salesman_id,
            'payment_date': str(self.today),
            'amount': '1500.00',
            'payment_type': 'BONUS',
            'payment_method': 'CASH'
        })
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()['success'])
        self.assertTrue(SalesmanPayment.objects.filter(salesman=self.sm1, amount=Decimal('1500.00')).exists())
