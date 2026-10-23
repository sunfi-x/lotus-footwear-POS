from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from inventory.models import ProductModel, ProductVariant, Supplier, StockMovement
from inventory.services import InventoryService

class InventoryServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', password='pass')
        self.product = ProductModel.objects.create(code='M1001', name='Classic Oxford')
        self.variant = ProductVariant.objects.create(
            product=self.product,
            size='41',
            colour='Black',
            current_stock=10,
            weighted_avg_cost=Decimal('800.00'),
            standard_selling_price=Decimal('1200.00')
        )
        self.supplier = Supplier.objects.create(name='Wholesale Footwear')

    def test_stock_movement_deduction(self):
        # Deduct 3 pairs
        InventoryService.record_stock_movement(
            variant=self.variant,
            movement_type='SALE',
            quantity_delta=-3,
            unit_cost=self.variant.weighted_avg_cost,
            user=self.user
        )
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.current_stock, 7)

    def test_insufficient_stock_prevents_oversell(self):
        # Attempt to sell 15 pairs when only 10 available
        with self.assertRaises(ValueError):
            InventoryService.record_stock_movement(
                variant=self.variant,
                movement_type='SALE',
                quantity_delta=-15,
                unit_cost=self.variant.weighted_avg_cost,
                user=self.user
            )
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.current_stock, 10)

    def test_weighted_average_cost_calculation(self):
        # Existing: 10 pairs @ 800.00 = 8,000.00
        # Purchase: 10 pairs @ 1000.00 = 10,000.00
        # New WAC = (8000 + 10000) / 20 = 900.00
        purchase = InventoryService.record_purchase(
            supplier=self.supplier,
            invoice_no='SUP-001',
            purchase_date='2026-10-18',
            items=[{
                'variant_id': self.variant.id,
                'quantity': 10,
                'unit_cost': Decimal('1000.00')
            }],
            user=self.user
        )
        self.variant.refresh_from_db()
        self.assertEqual(self.variant.current_stock, 20)
        self.assertEqual(self.variant.weighted_avg_cost, Decimal('900.00'))

    def test_stock_reconciliation(self):
        # Record movements
        InventoryService.record_stock_movement(self.variant, 'PURCHASE', 5, Decimal('800.00'), user=self.user)
        self.variant.refresh_from_db()
        is_consistent, expected, current, diff = InventoryService.reconcile_variant_stock(self.variant)
        # Note: self.variant had initial current_stock=10 from setup without StockMovement
        # Adding movement delta=5 makes total movements=5, and current_stock=15
        self.assertEqual(current, 15)
        self.assertEqual(expected, 5)

    def test_csv_migration_preview_and_import(self):
        csv_data = """product_code,product_name,category,brand,size,colour,quantity,cost_price,selling_price
L2001,Leather Loafer,Men,Lotus,40,Brown,15,950.00,1450.00
L2001,Leather Loafer,Men,Lotus,41,Brown,20,950.00,1450.00
"""
        # Test Dry Run
        dry_run_results = InventoryService.process_csv_migration(csv_data, is_dry_run=True, user=self.user)
        self.assertEqual(dry_run_results['valid_rows'], 2)
        self.assertEqual(dry_run_results['total_quantity'], 35)
        self.assertEqual(dry_run_results['imported_variants'], 0) # Dry run should not commit

        # Test Real Import
        real_results = InventoryService.process_csv_migration(csv_data, is_dry_run=False, user=self.user)
        self.assertEqual(real_results['imported_variants'], 2)
        v1 = ProductVariant.objects.get(sku='L2001-40-BROWN')
        self.assertEqual(v1.current_stock, 15)
        self.assertEqual(v1.weighted_avg_cost, Decimal('950.00'))


class UnifiedProductCreationTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_superuser(username='admin_test', password='password123', email='admin@test.com')
        self.client.login(username='admin_test', password='password123')
        self.existing_model = ProductModel.objects.create(code='EX01', name='Existing Shoe', brand='Lotus', category='Gents')
        self.existing_var = ProductVariant.objects.create(
            product=self.existing_model,
            size='40',
            colour='Black',
            sku='EX01-40-BLACK',
            current_stock=5,
            weighted_avg_cost=Decimal('500.00'),
            standard_selling_price=Decimal('800.00')
        )

    def test_create_new_model_with_variants_and_opening_stock(self):
        payload = {
            'operation': 'new_model',
            'code': 'NMD01',
            'name': 'New Modern Derby',
            'category': 'Gents',
            'brand': 'Lotus',
            'variants': [
                {
                    'size': '41',
                    'colour': 'Black',
                    'sku': '',
                    'opening_qty': 10,
                    'cost_price': '700.00',
                    'selling_price': '1100.00',
                },
                {
                    'size': '42',
                    'colour': 'Brown',
                    'sku': '',
                    'opening_qty': 0,
                    'cost_price': '0.00',
                    'selling_price': '1150.00',
                }
            ]
        }
        response = self.client.post('/inventory/products/create-unified/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        # Verify Product Model
        prod = ProductModel.objects.get(code='NMD01')
        self.assertEqual(prod.name, 'New Modern Derby')
        self.assertEqual(prod.category, 'Gents')

        # Verify Variant 1 (with opening stock)
        v1 = ProductVariant.objects.get(product=prod, size='41', colour='Black')
        self.assertEqual(v1.sku, 'NMD01-41-BLACK')
        self.assertEqual(v1.current_stock, 10)
        self.assertEqual(v1.weighted_avg_cost, Decimal('700.00'))
        self.assertEqual(v1.standard_selling_price, Decimal('1100.00'))
        self.assertEqual(v1.low_stock_threshold, 5)

        # Check stock movement for v1
        movement = StockMovement.objects.get(variant=v1, movement_type='OPENING')
        self.assertEqual(movement.quantity_delta, 10)
        self.assertEqual(movement.unit_cost, Decimal('700.00'))

        # Verify Variant 2 (zero opening stock: no movement created)
        v2 = ProductVariant.objects.get(product=prod, size='42', colour='Brown')
        self.assertEqual(v2.current_stock, 0)
        self.assertFalse(StockMovement.objects.filter(variant=v2).exists())

    def test_add_variant_to_existing_model(self):
        payload = {
            'operation': 'add_to_existing',
            'existing_product_id': self.existing_model.id,
            'code': 'EX01',
            'variants': [
                {
                    'size': '41',
                    'colour': 'Tan',
                    'sku': '',
                    'opening_qty': 8,
                    'cost_price': '600.00',
                    'selling_price': '950.00',
                }
            ]
        }
        response = self.client.post('/inventory/products/create-unified/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])

        # Ensure no duplicate product was created
        self.assertEqual(ProductModel.objects.filter(code='EX01').count(), 1)

        # Ensure new variant was added
        new_v = ProductVariant.objects.get(product=self.existing_model, size='41', colour='Tan')
        self.assertEqual(new_v.sku, 'EX01-41-TAN')
        self.assertEqual(new_v.current_stock, 8)
        self.assertEqual(new_v.weighted_avg_cost, Decimal('600.00'))

    def test_existing_code_in_new_model_mode_reuses_existing_model(self):
        # When user types existing code EX01 even under new_model, it adds to existing model safely
        payload = {
            'operation': 'new_model',
            'code': 'EX01',
            'name': 'Different Name Ignored',
            'category': 'Gents',
            'variants': [{'size': '43', 'colour': 'Navy', 'opening_qty': 3, 'cost_price': 500, 'selling_price': 800}]
        }
        response = self.client.post('/inventory/products/create-unified/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()['success'])
        self.assertEqual(ProductModel.objects.filter(code='EX01').count(), 1)
        self.assertTrue(ProductVariant.objects.filter(product=self.existing_model, size='43', colour='Navy').exists())

    def test_gents_size_validation(self):
        # Valid: 40-48
        # Invalid: 38 (Ladies), 20 (Kids)
        payload = {
            'operation': 'new_model',
            'code': 'G01',
            'name': 'Gents Loafer',
            'category': 'Gents',
            'variants': [{'size': '38', 'colour': 'Black', 'opening_qty': 1, 'cost_price': 400, 'selling_price': 700}]
        }
        response = self.client.post('/inventory/products/create-unified/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Gents', response.json()['errors'][0])

    def test_ladies_size_validation(self):
        # Valid: 35-41
        # Invalid: 45
        payload = {
            'operation': 'new_model',
            'code': 'L01',
            'name': 'Ladies Pump',
            'category': 'Ladies',
            'variants': [{'size': '45', 'colour': 'Red', 'opening_qty': 1, 'cost_price': 400, 'selling_price': 700}]
        }
        response = self.client.post('/inventory/products/create-unified/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertIn('Ladies', response.json()['errors'][0])

        # Valid ladies size
        payload['variants'][0]['size'] = '37'
        response_ok = self.client.post('/inventory/products/create-unified/', data=payload, content_type='application/json')
        self.assertEqual(response_ok.status_code, 200)

    def test_kids_groups_and_overlapping_sizes(self):
        # Group A: 15-21
        # Group B: 21-27
        # Both can have Size 21, and they must be distinguishable (A-21 vs B-21)
        payload = {
            'operation': 'new_model',
            'code': 'KD01',
            'name': 'Kids Sneaker',
            'category': 'Kids',
            'variants': [
                {
                    'kids_group': 'A',
                    'size': '21',
                    'colour': 'Blue',
                    'opening_qty': 4,
                    'cost_price': '300.00',
                    'selling_price': '500.00'
                },
                {
                    'kids_group': 'B',
                    'size': '21',
                    'colour': 'Blue',
                    'opening_qty': 6,
                    'cost_price': '320.00',
                    'selling_price': '520.00'
                }
            ]
        }
        response = self.client.post('/inventory/products/create-unified/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertTrue(data['success'])

        kd_prod = ProductModel.objects.get(code='KD01')
        v_a = ProductVariant.objects.get(product=kd_prod, size='A-21', colour='Blue')
        v_b = ProductVariant.objects.get(product=kd_prod, size='B-21', colour='Blue')

        self.assertEqual(v_a.current_stock, 4)
        self.assertEqual(v_b.current_stock, 6)
        self.assertEqual(v_a.sku, 'KD01-A-21-BLUE')
        self.assertEqual(v_b.sku, 'KD01-B-21-BLUE')

    def test_kids_invalid_size_for_group(self):
        # Group A has 15-21. Size 30 is not in Group A
        payload = {
            'operation': 'new_model',
            'code': 'KD02',
            'name': 'Kids Boot',
            'category': 'Kids',
            'variants': [{'kids_group': 'A', 'size': '30', 'colour': 'Black', 'opening_qty': 0, 'cost_price': 0, 'selling_price': 500}]
        }
        response = self.client.post('/inventory/products/create-unified/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])

    def test_validation_duplicate_variant_in_existing_model(self):
        # self.existing_model already has 40 Black
        payload = {
            'operation': 'add_to_existing',
            'existing_product_id': self.existing_model.id,
            'code': 'EX01',
            'variants': [
                {'size': '40', 'colour': 'Black', 'opening_qty': 2, 'cost_price': 500, 'selling_price': 800}
            ]
        }
        response = self.client.post('/inventory/products/create-unified/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.json()['success'])

    def test_stock_with_zero_cost_fails_validation(self):
        payload = {
            'operation': 'new_model',
            'code': 'FAIL01',
            'name': 'Zero Cost With Stock',
            'category': 'Gents',
            'variants': [
                {'size': '41', 'colour': 'Blue', 'opening_qty': 5, 'cost_price': '0.00', 'selling_price': '800.00'}
            ]
        }
        response = self.client.post('/inventory/products/create-unified/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        self.assertFalse(ProductModel.objects.filter(code='FAIL01').exists())

    def test_transaction_rollback_on_failure(self):
        # If second variant has an error (e.g. invalid size for category), the entire transaction including product creation should rollback
        payload = {
            'operation': 'new_model',
            'code': 'ROLLBACK01',
            'name': 'Rollback Shoe',
            'category': 'Gents',
            'variants': [
                {'size': '41', 'colour': 'Black', 'opening_qty': 5, 'cost_price': '500.00', 'selling_price': '800.00'},
                {'size': '99', 'colour': 'Brown', 'opening_qty': 5, 'cost_price': '500.00', 'selling_price': '800.00'}
            ]
        }
        response = self.client.post('/inventory/products/create-unified/', data=payload, content_type='application/json')
        self.assertEqual(response.status_code, 400)
        # Verify model was NOT created
        self.assertFalse(ProductModel.objects.filter(code='ROLLBACK01').exists())
        self.assertFalse(ProductVariant.objects.filter(product__code='ROLLBACK01').exists())

    def test_products_list_view_five_kpi_cards(self):
        # Clear existing models and create fresh ones for testing the 5 KPI overview cards
        ProductVariant.objects.all().delete()
        ProductModel.objects.all().delete()

        # 1. Gents Product (2 variants)
        p_gents = ProductModel.objects.create(code='G-01', name='Gents Shoe', category='Gents')
        ProductVariant.objects.create(
            product=p_gents, size='41', colour='Black', sku='G-01-41-BLACK',
            current_stock=10, weighted_avg_cost=Decimal('500.00'), standard_selling_price=Decimal('800.00')
        )
        ProductVariant.objects.create(
            product=p_gents, size='42', colour='Brown', sku='G-01-42-BROWN',
            current_stock=5, weighted_avg_cost=Decimal('600.00'), standard_selling_price=Decimal('900.00')
        )

        # 2. Ladies Product (2 variants: one in stock, one with 0 stock)
        p_ladies = ProductModel.objects.create(code='L-01', name='Ladies Heel', category='Ladies')
        ProductVariant.objects.create(
            product=p_ladies, size='37', colour='Red', sku='L-01-37-RED',
            current_stock=8, weighted_avg_cost=Decimal('400.00'), standard_selling_price=Decimal('700.00')
        )
        ProductVariant.objects.create(
            product=p_ladies, size='38', colour='Black', sku='L-01-38-BLACK',
            current_stock=0, weighted_avg_cost=Decimal('450.00'), standard_selling_price=Decimal('750.00')
        )

        # 3. Kids Product (2 variants in different groups)
        p_kids = ProductModel.objects.create(code='K-01', name='Kids Sandal', category='Kids')
        ProductVariant.objects.create(
            product=p_kids, size='A-18', colour='Blue', sku='K-01-A-18-BLUE',
            current_stock=12, weighted_avg_cost=Decimal('300.00'), standard_selling_price=Decimal('500.00')
        )
        ProductVariant.objects.create(
            product=p_kids, size='B-22', colour='Green', sku='K-01-B-22-GREEN',
            current_stock=6, weighted_avg_cost=Decimal('350.00'), standard_selling_price=Decimal('550.00')
        )

        # Fetch products list page
        response = self.client.get('/inventory/products/')
        self.assertEqual(response.status_code, 200)
        kpi = response.context['kpi']

        # Calculations:
        # Gents: 10 + 5 = 15 pairs
        # Ladies: 8 + 0 = 8 pairs
        # Kids: 12 + 6 = 18 pairs
        # Total pairs = 15 + 8 + 18 = 41 pairs
        self.assertEqual(kpi['gents_pairs'], 15)
        self.assertEqual(kpi['ladies_pairs'], 8)
        self.assertEqual(kpi['kids_pairs'], 18)
        self.assertEqual(kpi['total_pairs'], 41)
        self.assertEqual(kpi['total_pairs'], kpi['gents_pairs'] + kpi['ladies_pairs'] + kpi['kids_pairs'])

        # Inventory Value:
        # Gents: (10 * 500) + (5 * 600) = 5000 + 3000 = 8000
        # Ladies: (8 * 400) + (0 * 450) = 3200 + 0 = 3200
        # Kids: (12 * 300) + (6 * 350) = 3600 + 2100 = 5700
        # Total Value: 8000 + 3200 + 5700 = 16900.00
        self.assertEqual(kpi['total_inventory_cost'], Decimal('16900.00'))

        # Check HTML content contains the 5 card labels
        content = response.content.decode('utf-8')
        self.assertIn('মোট স্টকে জুতা (TOTAL PAIRS)', content)
        self.assertIn('Gents Stock (GENTS PAIRS)', content)
        self.assertIn('Ladies Stock (LADIES PAIRS)', content)
        self.assertIn('Kids Stock (KIDS PAIRS)', content)
        self.assertIn('মোট স্টকের ক্রয়মূল্য (INVENTORY VALUE)', content)

        # Ensure old cards are removed
        self.assertNotIn('মোট জুতার মডেল (MODELS)', content)
        self.assertNotIn('মোট ভ্যারিয়েন্ট (VARIANTS / SKU)', content)
        self.assertNotIn('স্টক কম (LOW STOCK)', content)
        self.assertNotIn('স্টক শেষ (OUT OF STOCK)', content)


