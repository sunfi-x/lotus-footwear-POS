import csv
import io
from decimal import Decimal, InvalidOperation
from django.db import transaction
from django.utils import timezone
from .models import ProductModel, ProductVariant, Supplier, Purchase, PurchaseLine, StockMovement, StockAdjustment
from core.models import AuditLog

class InventoryService:

    @classmethod
    @transaction.atomic
    def record_stock_movement(cls, variant, movement_type, quantity_delta, unit_cost=Decimal('0.00'),
                              reference_type='', reference_id='', notes='', user=None):
        """
        Atomically records an inventory movement and updates the current_stock balance.
        Ensures stock does not become negative for customer sales.
        """
        # Lock variant row for update to prevent race conditions
        var = ProductVariant.objects.select_for_update().get(id=variant.id)
        
        new_stock = var.current_stock + quantity_delta
        if movement_type == 'SALE' and new_stock < 0:
            raise ValueError(f"Insufficient stock for SKU {var.sku}. Current: {var.current_stock}, Requested: {abs(quantity_delta)}")

        var.current_stock = new_stock
        var.save(update_fields=['current_stock', 'updated_at'])

        movement = StockMovement.objects.create(
            variant=var,
            movement_type=movement_type,
            quantity_delta=quantity_delta,
            resulting_stock=new_stock,
            unit_cost=unit_cost,
            reference_type=reference_type,
            reference_id=str(reference_id),
            notes=notes,
            created_by=user
        )
        return movement

    @classmethod
    @transaction.atomic
    def record_purchase(cls, supplier, invoice_no, purchase_date, items, paid_amount=Decimal('0.00'), notes='', user=None):
        """
        Records an incoming purchase consignment, updates Weighted Average Cost (WAC),
        creates purchase lines, and records stock movements.
        
        items format: [{'variant_id': 1, 'quantity': 10, 'unit_cost': Decimal('750.00')}, ...]
        """
        total_amount = Decimal('0.00')
        for item in items:
            qty = int(item['quantity'])
            cost = Decimal(str(item['unit_cost']))
            total_amount += cost * qty

        purchase = Purchase.objects.create(
            supplier=supplier,
            invoice_no=invoice_no,
            purchase_date=purchase_date,
            total_amount=total_amount,
            paid_amount=paid_amount,
            notes=notes,
            created_by=user
        )

        for item in items:
            var = ProductVariant.objects.select_for_update().get(id=item['variant_id'])
            qty = int(item['quantity'])
            cost = Decimal(str(item['unit_cost']))

            # Calculate Weighted Average Cost (WAC)
            curr_stock = var.current_stock
            curr_wac = var.weighted_avg_cost

            if curr_stock > 0 and (curr_stock + qty) > 0:
                new_wac = ((curr_stock * curr_wac) + (qty * cost)) / (curr_stock + qty)
            else:
                new_wac = cost

            var.weighted_avg_cost = new_wac.quantize(Decimal('0.01'))
            var.save(update_fields=['weighted_avg_cost', 'updated_at'])

            # Create Purchase Line
            line = PurchaseLine.objects.create(
                purchase=purchase,
                variant=var,
                quantity=qty,
                unit_cost=cost,
                line_total=cost * qty
            )

            # Record Stock Movement
            cls.record_stock_movement(
                variant=var,
                movement_type='PURCHASE',
                quantity_delta=qty,
                unit_cost=cost,
                reference_type='Purchase',
                reference_id=purchase.id,
                notes=f"Purchase from {supplier.name} (Inv: {invoice_no})",
                user=user
            )

        AuditLog.log(
            action_type='PURCHASE_ADD',
            user=user,
            role='admin',
            entity_type='Purchase',
            entity_id=purchase.id,
            details=f"Recorded purchase #{purchase.id} of Tk {total_amount} with {len(items)} items from {supplier.name}."
        )

        return purchase

    @classmethod
    @transaction.atomic
    def record_stock_adjustment(cls, variant, new_stock, reason, user):
        """
        Performs an audited stock discrepancy adjustment.
        """
        var = ProductVariant.objects.select_for_update().get(id=variant.id)
        old_stock = var.current_stock
        diff = new_stock - old_stock

        if diff == 0:
            return None

        adj = StockAdjustment.objects.create(
            variant=var,
            old_stock=old_stock,
            new_stock=new_stock,
            difference=diff,
            reason=reason,
            authorized_by=user
        )

        cls.record_stock_movement(
            variant=var,
            movement_type='ADJUSTMENT',
            quantity_delta=diff,
            unit_cost=var.weighted_avg_cost,
            reference_type='StockAdjustment',
            reference_id=adj.id,
            notes=f"Stock adjustment: {reason}",
            user=user
        )

        AuditLog.log(
            action_type='STOCK_ADJUST',
            user=user,
            role='admin',
            entity_type='StockAdjustment',
            entity_id=adj.id,
            details=f"Stock adjusted for {var.sku}: {old_stock} -> {new_stock} ({'+' if diff > 0 else ''}{diff}). Reason: {reason}"
        )

        return adj

    @classmethod
    def reconcile_variant_stock(cls, variant):
        """
        Audits current stock against all historical StockMovement records.
        Returns: (is_consistent, expected_stock, current_stock, difference)
        """
        movements = StockMovement.objects.filter(variant=variant)
        expected_stock = sum(m.quantity_delta for m in movements)
        current_stock = variant.current_stock
        is_consistent = (expected_stock == current_stock)
        return is_consistent, expected_stock, current_stock, (current_stock - expected_stock)

    @classmethod
    def process_csv_migration(cls, file_content, is_dry_run=True, user=None):
        """
        Processes initial inventory migration CSV.
        Expected Headers:
        product_code, product_name, category, brand, size, colour, quantity, cost_price, selling_price

        Supports preview / dry_run mode to validate without committing changes.
        """
        if isinstance(file_content, bytes):
            # Decode with utf-8 or utf-8-sig (handles Excel BOM)
            try:
                decoded_file = file_content.decode('utf-8-sig')
            except UnicodeDecodeError:
                decoded_file = file_content.decode('latin-1')
        else:
            decoded_file = file_content

        reader = csv.DictReader(io.StringIO(decoded_file))
        rows = list(reader)

        results = {
            'total_rows': len(rows),
            'valid_rows': 0,
            'error_rows': [],
            'preview_items': [],
            'imported_variants': 0,
            'total_quantity': 0,
            'total_valuation': Decimal('0.00'),
            'is_dry_run': is_dry_run,
        }

        seen_skus = set()

        for idx, row in enumerate(rows, start=1):
            row_errors = []
            code = (row.get('product_code') or '').strip()
            name = (row.get('product_name') or '').strip()
            category = (row.get('category') or 'General').strip()
            brand = (row.get('brand') or 'Lotus').strip()
            size = (row.get('size') or '').strip()
            colour = (row.get('colour') or '').strip()
            qty_str = (row.get('quantity') or '0').strip()
            cost_str = (row.get('cost_price') or '0').strip()
            price_str = (row.get('selling_price') or '0').strip()

            if not code:
                row_errors.append("Product code is required.")
            if not name:
                row_errors.append("Product name is required.")
            if not size:
                row_errors.append("Size is required.")
            if not colour:
                row_errors.append("Colour is required.")

            try:
                quantity = int(qty_str)
                if quantity < 0:
                    row_errors.append("Quantity cannot be negative.")
            except ValueError:
                row_errors.append(f"Invalid quantity: '{qty_str}'.")
                quantity = 0

            try:
                cost_price = Decimal(cost_str).quantize(Decimal('0.01'))
                if cost_price < 0:
                    row_errors.append("Cost price cannot be negative.")
            except (InvalidOperation, ValueError):
                row_errors.append(f"Invalid cost price: '{cost_str}'.")
                cost_price = Decimal('0.00')

            try:
                selling_price = Decimal(price_str).quantize(Decimal('0.01'))
                if selling_price < 0:
                    row_errors.append("Selling price cannot be negative.")
            except (InvalidOperation, ValueError):
                row_errors.append(f"Invalid selling price: '{price_str}'.")
                selling_price = Decimal('0.00')

            sku_candidate = f"{code.replace(' ', '-')}-{size.replace(' ', '-')}-{colour.replace(' ', '-')}".upper()
            if sku_candidate in seen_skus:
                row_errors.append(f"Duplicate variant in CSV: SKU {sku_candidate}")
            else:
                seen_skus.add(sku_candidate)

            if row_errors:
                results['error_rows'].append({
                    'row_number': idx,
                    'sku': sku_candidate,
                    'errors': row_errors,
                    'raw_data': row
                })
            else:
                results['valid_rows'] += 1
                results['total_quantity'] += quantity
                results['total_valuation'] += (cost_price * quantity)
                if len(results['preview_items']) < 50:
                    results['preview_items'].append({
                        'row_number': idx,
                        'code': code,
                        'name': name,
                        'size': size,
                        'colour': colour,
                        'sku': sku_candidate,
                        'quantity': quantity,
                        'cost_price': cost_price,
                        'selling_price': selling_price,
                    })

        # If not dry run and no fatal file-wide structural errors, commit all in atomic block
        if not is_dry_run and not results['error_rows']:
            with transaction.atomic():
                for item in rows:
                    code = item['product_code'].strip()
                    name = item['product_name'].strip()
                    category = (item.get('category') or 'General').strip()
                    brand = (item.get('brand') or 'Lotus').strip()
                    size = item['size'].strip()
                    colour = item['colour'].strip()
                    quantity = int(item['quantity'].strip())
                    cost_price = Decimal(item['cost_price'].strip()).quantize(Decimal('0.01'))
                    selling_price = Decimal(item['selling_price'].strip()).quantize(Decimal('0.01'))

                    product, _ = ProductModel.objects.get_or_create(
                        code=code,
                        defaults={
                            'name': name,
                            'category': category,
                            'brand': brand,
                            'is_active': True
                        }
                    )

                    variant, v_created = ProductVariant.objects.get_or_create(
                        product=product,
                        size=size,
                        colour=colour,
                        defaults={
                            'current_stock': 0,
                            'weighted_avg_cost': cost_price,
                            'standard_selling_price': selling_price,
                            'is_active': True
                        }
                    )

                    if not v_created:
                        variant.standard_selling_price = selling_price
                        variant.weighted_avg_cost = cost_price
                        variant.save()

                    # Record opening stock movement
                    if quantity > 0:
                        cls.record_stock_movement(
                            variant=variant,
                            movement_type='OPENING',
                            quantity_delta=quantity,
                            unit_cost=cost_price,
                            reference_type='CSV_Import',
                            reference_id=f"INIT-{product.code}",
                            notes='Initial stock migration from paper ledger',
                            user=user
                        )
                    results['imported_variants'] += 1

                AuditLog.log(
                    action_type='CSV_IMPORT',
                    user=user,
                    role='admin',
                    details=f"Imported opening stock from CSV: {results['imported_variants']} variants, {results['total_quantity']} total pairs, Valuation Tk {results['total_valuation']}."
                )

        return results
