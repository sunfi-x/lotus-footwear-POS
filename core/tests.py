from decimal import Decimal
from django.test import TransactionTestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User
from core.models import BusinessDay, ApplicationSetting
from inventory.models import ProductModel, ProductVariant
from pos.models import Sale

class SystemIntegrationTests(TransactionTestCase):
    def setUp(self):
        self.client = Client()
        self.admin = User.objects.create_superuser(username='admin_ui', password='adminpassword')
        self.staff = User.objects.create_user(username='staff_ui', password='staffpassword')

        self.product = ProductModel.objects.create(code='T100', name='Test Sneaker')
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size='41',
            colour='Black',
            current_stock=25,
            weighted_avg_cost=Decimal('600.00'),
            standard_selling_price=Decimal('1000.00')
        )

    def test_login_and_home_access(self):
        # Unauthenticated access redirects to login
        res = self.client.get(reverse('home'))
        self.assertEqual(res.status_code, 302)
        self.assertIn('/login/', res.url)

        # Login as staff
        login_res = self.client.post(reverse('login'), {
            'username': 'staff_ui',
            'password': 'staffpassword'
        })
        self.assertEqual(login_res.status_code, 302)
        self.assertEqual(login_res.url, reverse('home'))

        # Home page renders 200
        home_res = self.client.get(reverse('home'))
        self.assertEqual(home_res.status_code, 200)
        self.assertContains(home_res, 'দৈনিক বিক্রয় সারসংক্ষেপ')

    def test_open_and_close_business_day_workflow(self):
        self.client.login(username='admin_ui', password='adminpassword')

        # Open Day
        open_res = self.client.post(reverse('open_business_day'), {
            'day_date': '2026-10-18',
            'opening_cash': '2500.00',
            'notes': 'Test morning start'
        })
        self.assertEqual(open_res.status_code, 302)
        current_day = BusinessDay.get_current()
        self.assertIsNotNone(current_day)
        self.assertEqual(current_day.status, 'OPEN')
        self.assertEqual(current_day.opening_cash, Decimal('2500.00'))

        # Close Day
        close_res = self.client.post(reverse('close_business_day'), {
            'actual_cash': '2500.00',
            'discrepancy_reason': '',
            'notes': 'Test evening closing'
        })
        self.assertEqual(close_res.status_code, 302)
        current_day.refresh_from_db()
        self.assertEqual(current_day.status, 'CLOSED')

    def test_pos_billing_api_and_receipt(self):
        self.client.login(username='staff_ui', password='staffpassword')

        # Open day first
        b_day = BusinessDay.objects.create(
            date='2026-10-18',
            status='OPEN',
            opening_cash=Decimal('1000.00'),
            opened_by=self.staff
        )

        # Product Search API
        search_res = self.client.get(reverse('search_product_api') + '?query=T100')
        self.assertEqual(search_res.status_code, 200)
        data = search_res.json()
        self.assertTrue(data['success'])
        self.assertEqual(data['product']['code'], 'T100')
        self.assertEqual(len(data['variants']), 1)

        # Submit Bill via API
        sale_payload = {
            'items': [{
                'variant_id': self.variant.id,
                'quantity': 2,
                'unit_price': '950.00',
                'discount_percent': '0'
            }],
            'manual_final_total': '1900.00',
            'payment_method': 'CASH',
            'amount_paid': '2000.00',
            'customer_name': 'Kamal Hossain',
            'customer_phone': '01900000000'
        }
        create_res = self.client.post(
            reverse('create_sale_api'),
            data=sale_payload,
            content_type='application/json'
        )
        self.assertEqual(create_res.status_code, 200)
        c_data = create_res.json()
        self.assertTrue(c_data['success'])

        sale_id = c_data['sale_id']
        sale = Sale.objects.get(id=sale_id)
        self.assertEqual(sale.total_pairs, 2)
        self.assertEqual(sale.final_total, Decimal('1900.00'))

        # Verify English 58mm Thermal Receipt view
        receipt_res = self.client.get(reverse('receipt_view', kwargs={'sale_id': sale_id}))
        self.assertEqual(receipt_res.status_code, 200)
        self.assertContains(receipt_res, 'SALES RECEIPT')
        self.assertContains(receipt_res, sale.invoice_no)
        self.assertContains(receipt_res, 'Kamal Hossain')
        self.assertContains(receipt_res, 'TOTAL:')
