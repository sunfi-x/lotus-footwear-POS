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
