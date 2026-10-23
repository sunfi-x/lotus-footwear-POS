from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction
from django.utils import timezone
from .models import Sale, SaleLine, Payment, SaleReturn, SaleReturnLine
from inventory.models import ProductVariant
from inventory.services import InventoryService
from core.models import BusinessDay, AuditLog

class BillingService:

    @classmethod
    def generate_invoice_number(cls, business_day):
        """
        Generates a clean sequential invoice number: INV-YYYYMMDD-0001
        """
        date_str = business_day.date.strftime('%Y%m%d')
        prefix = f"INV-{date_str}-"
        last_sale = Sale.objects.filter(invoice_no__startswith=prefix).order_by('-invoice_no').first()
        if last_sale:
            try:
                seq = int(last_sale.invoice_no.split('-')[-1]) + 1
            except (ValueError, IndexError):
                seq = 1
        else:
            seq = 1
        return f"{prefix}{seq:04d}"

    @classmethod
    @transaction.atomic
    def create_invoice(cls, business_day, items, customer_name='', customer_phone='',
                       overall_discount_percent=Decimal('0.00'), manual_final_total=None,
                       payment_method='CASH', amount_paid=Decimal('0.00'), user=None,
                       split_payments=None):
        """
        Creates an invoice atomically with all line items, inventory deductions,
        cost snapshots, and payment records.

        items format:
        [
            {
                'variant_id': 1,
                'quantity': 1,
                'unit_price': Decimal('1200.00'),
                'discount_percent': Decimal('0.00')
            }, ...
        ]
        """
        if not business_day or business_day.status != 'OPEN':
            raise ValueError("Invoices can only be created during an active, OPEN business day.")

        if not items:
            raise ValueError("Cannot create an invoice with no product items.")

        # 1. Calculate line subtotals and initial discounts
        calculated_subtotal = Decimal('0.00')
        line_specs = []

        for item in items:
            var_id = item['variant_id']
            qty = int(item['quantity'])
            if qty <= 0:
                raise ValueError("Quantity must be at least 1.")

            unit_price = Decimal(str(item['unit_price'])).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            line_disc_pct = Decimal(str(item.get('discount_percent', 0))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

            sub = (unit_price * qty).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            disc_amt = (sub * (line_disc_pct / Decimal('100.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            net_line = sub - disc_amt

            calculated_subtotal += sub
            line_specs.append({
                'variant_id': var_id,
                'quantity': qty,
                'unit_price': unit_price,
                'line_subtotal': sub,
                'discount_percent': line_disc_pct,
                'discount_amount': disc_amt,
                'net_line': net_line
            })

        # Calculate invoice-wide discount
        total_initial_discount = sum(l['discount_amount'] for l in line_specs)
        calculated_total = calculated_subtotal - total_initial_discount

        # Handle overall invoice discount if provided
        overall_disc_pct = Decimal(str(overall_discount_percent)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
        if overall_disc_pct > 0 and total_initial_discount == 0:
            extra_disc = (calculated_subtotal * (overall_disc_pct / Decimal('100.00'))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            total_initial_discount = extra_disc
            calculated_total = calculated_subtotal - extra_disc

        # Handle manual final total override (Staff freedom)
        if manual_final_total is not None and str(manual_final_total).strip() != '':
            final_total = Decimal(str(manual_final_total)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            manual_adjustment = final_total - calculated_total
        else:
            final_total = calculated_total
            manual_adjustment = Decimal('0.00')

        if final_total < 0:
            raise ValueError("Final invoice total cannot be negative.")

        # Determine payments and dues (support split payments if provided)
        parsed_split_payments = []
        if split_payments:
            for sp in split_payments:
                sp_method = sp.get('payment_method') or sp.get('method') or 'CASH'
                sp_amount = Decimal(str(sp.get('amount', 0))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                if sp_amount > Decimal('0.00'):
                    parsed_split_payments.append({
                        'method': sp_method,
                        'amount': sp_amount
                    })

        if parsed_split_payments:
            total_paid = sum(sp['amount'] for sp in parsed_split_payments)
            distinct_methods = set(sp['method'] for sp in parsed_split_payments)
            if len(distinct_methods) > 1:
                sale_payment_method = 'SPLIT'
            elif len(distinct_methods) == 1:
                sale_payment_method = parsed_split_payments[0]['method']
            else:
                sale_payment_method = payment_method
        else:
            total_paid = Decimal(str(amount_paid)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            sale_payment_method = payment_method

        if total_paid >= final_total:
            change_given = total_paid - final_total
            balance_due = Decimal('0.00')
            recorded_initial_paid = final_total
        else:
            change_given = Decimal('0.00')
            balance_due = final_total - total_paid
            recorded_initial_paid = total_paid

        # Generate unique invoice number
        invoice_no = cls.generate_invoice_number(business_day)

        # Create Sale header
        sale = Sale.objects.create(
            invoice_no=invoice_no,
            business_day=business_day,
            customer_name=customer_name.strip(),
            customer_phone=customer_phone.strip(),
            subtotal=calculated_subtotal,
            discount_percent=overall_disc_pct,
            discount_amount=total_initial_discount,
            calculated_total=calculated_total,
            manual_adjustment=manual_adjustment,
            final_total=final_total,
            payment_method=sale_payment_method,
            amount_paid=recorded_initial_paid,
            change_given=change_given,
            balance_due=balance_due,
            status='COMPLETED',
            created_by=user
        )

        # Allocate manual adjustment proportionally across lines for accurate line profit reporting
        allocated_line_totals = []
        if calculated_total > 0 and manual_adjustment != 0:
            accumulated_allocated = Decimal('0.00')
            for i, line in enumerate(line_specs):
                if i == len(line_specs) - 1:
                    # Last item absorbs any rounding cent
                    allocated_final = final_total - accumulated_allocated
                else:
                    ratio = line['net_line'] / calculated_total
                    allocated_final = (ratio * final_total).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                    accumulated_allocated += allocated_final
                allocated_line_totals.append(allocated_final)
        else:
            allocated_line_totals = [l['net_line'] for l in line_specs]

        # 2. Process each sale line, deduct stock, and store cost snapshot
        for idx, line in enumerate(line_specs):
            var = ProductVariant.objects.select_for_update().get(id=line['variant_id'])
            qty = line['quantity']
            unit_price = line['unit_price']
            final_line_total = allocated_line_totals[idx]

            # Current unit WAC snapshot
            cost_snapshot = var.weighted_avg_cost
            gross_profit = final_line_total - (cost_snapshot * qty)

            # Create line item
            SaleLine.objects.create(
                sale=sale,
                variant=var,
                quantity=qty,
                unit_price=unit_price,
                line_subtotal=line['line_subtotal'],
                discount_percent=line['discount_percent'],
                discount_amount=line['discount_amount'],
                final_line_total=final_line_total,
                cost_snapshot=cost_snapshot,
                gross_profit=gross_profit
            )

            # Atomically deduct stock
            InventoryService.record_stock_movement(
                variant=var,
                movement_type='SALE',
                quantity_delta=-qty,
                unit_cost=cost_snapshot,
                reference_type='Sale',
                reference_id=sale.invoice_no,
                notes=f"Sold on invoice {sale.invoice_no}",
                user=user
            )

        # 3. Create initial Payment record(s) if any amount paid
        if recorded_initial_paid > 0:
            if parsed_split_payments:
                rem_change = change_given
                for sp in parsed_split_payments:
                    sp_amt = sp['amount']
                    if rem_change > 0 and sp['method'] == 'CASH':
                        deduct = min(sp_amt, rem_change)
                        sp_amt -= deduct
                        rem_change -= deduct
                    if sp_amt > Decimal('0.00'):
                        Payment.objects.create(
                            sale=sale,
                            business_day=business_day,
                            amount=sp_amt,
                            payment_method=sp['method'],
                            payment_type='INITIAL',
                            received_by=user,
                            notes=f"Initial payment ({sp['method']}) for invoice {sale.invoice_no}"
                        )
            else:
                Payment.objects.create(
                    sale=sale,
                    business_day=business_day,
                    amount=recorded_initial_paid,
                    payment_method=payment_method,
                    payment_type='INITIAL',
                    received_by=user,
                    notes=f"Initial payment for invoice {sale.invoice_no}"
                )

        # 4. Audit Log
        AuditLog.log(
            action_type='SALE_CREATE',
            user=user,
            role='staff',
            entity_type='Sale',
            entity_id=sale.invoice_no,
            details=f"Created Invoice {sale.invoice_no}: {sale.total_pairs} pairs, Final Total Tk {final_total}, Paid Tk {recorded_initial_paid}, Due Tk {balance_due}."
        )

        return sale

    @classmethod
    @transaction.atomic
    def cancel_invoice(cls, sale_id, reason, user=None):
        """
        Cancels an invoice, reverses the inventory deductions, and marks invoice as CANCELLED.
        """
        sale = Sale.objects.select_for_update().get(id=sale_id)
        if sale.status == 'CANCELLED':
            raise ValueError("Invoice is already cancelled.")

        # Restore inventory for each line
        for line in sale.lines.all():
            InventoryService.record_stock_movement(
                variant=line.variant,
                movement_type='SALE_RETURN',
                quantity_delta=line.quantity,
                unit_cost=line.cost_snapshot,
                reference_type='SaleCancellation',
                reference_id=sale.invoice_no,
                notes=f"Restored from cancelled invoice {sale.invoice_no}. Reason: {reason}",
                user=user
            )

        sale.status = 'CANCELLED'
        sale.cancellation_reason = reason
        sale.save(update_fields=['status', 'cancellation_reason'])

        AuditLog.log(
            action_type='SALE_CANCEL',
            user=user,
            role='admin' if user and user.is_superuser else 'staff',
            entity_type='Sale',
            entity_id=sale.invoice_no,
            details=f"Cancelled invoice {sale.invoice_no}. Reason: {reason}"
        )
        return sale

    @classmethod
    @transaction.atomic
    def process_return(cls, sale_id, return_items, reason, business_day, user=None):
        """
        Processes a customer return.
        return_items format:
        [
            {
                'sale_line_id': 1,
                'quantity': 1,
                'refund_amount': Decimal('900.00'),
                'disposition': 'RESTOCK' # or 'DAMAGED'
            }, ...
        ]
        """
        sale = Sale.objects.select_for_update().get(id=sale_id)
        if sale.status == 'CANCELLED':
            raise ValueError("Cannot return items from a cancelled invoice.")

        total_refund = sum(Decimal(str(item['refund_amount'])) for item in return_items)
        date_str = timezone.now().strftime('%Y%m%d')
        return_no = f"RET-{date_str}-{sale.id:04d}-{SaleReturn.objects.count() + 1}"

        ret = SaleReturn.objects.create(
            sale=sale,
            return_no=return_no,
            business_day=business_day,
            refund_amount=total_refund,
            reason=reason,
            processed_by=user
        )

        for item in return_items:
            line = SaleLine.objects.get(id=item['sale_line_id'], sale=sale)
            qty = int(item['quantity'])
            refund_amt = Decimal(str(item['refund_amount']))
            disposition = item.get('disposition', 'RESTOCK')

            SaleReturnLine.objects.create(
                return_record=ret,
                sale_line=line,
                variant=line.variant,
                quantity=qty,
                refund_amount=refund_amt,
                disposition=disposition
            )

            # If disposition is RESTOCK, put back into active sellable inventory
            if disposition == 'RESTOCK':
                InventoryService.record_stock_movement(
                    variant=line.variant,
                    movement_type='SALE_RETURN',
                    quantity_delta=qty,
                    unit_cost=line.cost_snapshot,
                    reference_type='CustomerReturn',
                    reference_id=ret.return_no,
                    notes=f"Customer return from invoice {sale.invoice_no}",
                    user=user
                )

        AuditLog.log(
            action_type='RETURN_PROCESSED',
            user=user,
            role='admin' if user and user.is_superuser else 'staff',
            entity_type='SaleReturn',
            entity_id=ret.return_no,
            details=f"Processed return {ret.return_no} for {sale.invoice_no}. Refund Tk {total_refund}. Reason: {reason}"
        )
        return ret

    @classmethod
    @transaction.atomic
    def record_due_collection(cls, sale_id, amount, payment_method='CASH', notes='', user=None, business_day=None):
        """
        Records subsequent customer payment towards an outstanding balance.
        """
        sale = Sale.objects.select_for_update().get(id=sale_id)
        amount = Decimal(str(amount)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        if amount <= 0:
            raise ValueError("Payment amount must be greater than zero.")
        if amount > sale.balance_due:
            raise ValueError(f"Payment amount Tk {amount} exceeds outstanding due Tk {sale.balance_due}.")

        if business_day is None:
            business_day = BusinessDay.get_current() or sale.business_day

        sale.amount_paid += amount
        sale.balance_due -= amount
        sale.save(update_fields=['amount_paid', 'balance_due'])

        payment = Payment.objects.create(
            sale=sale,
            business_day=business_day,
            amount=amount,
            payment_method=payment_method,
            payment_type='DUE_COLLECTION',
            received_by=user,
            notes=notes or f"Due collection for {sale.invoice_no}"
        )

        AuditLog.log(
            action_type='SALE_CREATE',
            user=user,
            role='staff',
            entity_type='Payment',
            entity_id=payment.id,
            details=f"Collected due Tk {amount} for {sale.invoice_no}. Remaining due: Tk {sale.balance_due}"
        )
        return payment
