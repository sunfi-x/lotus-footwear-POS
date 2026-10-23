from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
from core.models import BusinessDay
from inventory.models import ProductVariant

class Sale(models.Model):
    STATUS_CHOICES = [
        ('COMPLETED', 'Completed'),
        ('CANCELLED', 'Cancelled'),
    ]

    PAYMENT_METHODS = [
        ('CASH', 'Cash (নগদ)'),
        ('BKASH', 'bKash (বিকাশ)'),
        ('NAGAD', 'Nagad (নগদ ডিজিটাল)'),
        ('CARD', 'Card (কার্ড)'),
        ('OTHER', 'Other (অন্যান্য)'),
        ('SPLIT', 'Split / Multiple (মিশ্র)'),
    ]

    invoice_no = models.CharField(max_length=50, unique=True, db_index=True)
    business_day = models.ForeignKey(BusinessDay, on_delete=models.PROTECT, related_name='sales')
    customer_name = models.CharField(max_length=150, blank=True, default='')
    customer_phone = models.CharField(max_length=50, blank=True, default='')

    # Monetary fields with 12 digits, 2 decimals
    subtotal = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    calculated_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    manual_adjustment = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'),
                                            help_text="Difference between staff customized total and calculated total")
    final_total = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'),
                                      help_text="Authoritative final billed amount")

    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='CASH')
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    change_given = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    balance_due = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED', db_index=True)
    cancellation_reason = models.TextField(blank=True, default='')

    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='sales')

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return f"Invoice {self.invoice_no} - Tk {self.final_total} ({self.status})"

    @property
    def total_pairs(self):
        """Sum of all line quantities for this invoice."""
        return sum(line.quantity for line in self.lines.all())


class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='lines')
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='sale_lines')
    quantity = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    line_subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    discount_percent = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    final_line_total = models.DecimalField(max_digits=12, decimal_places=2)

    # Cost and profit snapshot for historical integrity
    cost_snapshot = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'),
                                        help_text="Unit Weighted Average Cost at time of sale")
    gross_profit = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))

    def __str__(self):
        return f"{self.sale.invoice_no} | {self.variant.sku} x {self.quantity} = Tk {self.final_line_total}"


class Payment(models.Model):
    PAYMENT_TYPES = [
        ('INITIAL', 'Initial Invoice Payment'),
        ('DUE_COLLECTION', 'Subsequent Due Collection'),
    ]

    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name='payments')
    business_day = models.ForeignKey(BusinessDay, on_delete=models.PROTECT, null=True, blank=True, related_name='payments')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=Sale.PAYMENT_METHODS, default='CASH')
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPES, default='INITIAL')
    received_at = models.DateTimeField(default=timezone.now, db_index=True)
    received_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-received_at']

    def __str__(self):
        return f"Payment Tk {self.amount} ({self.payment_method}) for {self.sale.invoice_no}"


class SaleReturn(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name='returns')
    return_no = models.CharField(max_length=50, unique=True, db_index=True)
    business_day = models.ForeignKey(BusinessDay, on_delete=models.PROTECT, related_name='returns')
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    reason = models.TextField()
    returned_at = models.DateTimeField(default=timezone.now, db_index=True)
    processed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-returned_at']

    def __str__(self):
        return f"Return {self.return_no} for {self.sale.invoice_no} (Refund: Tk {self.refund_amount})"


class SaleReturnLine(models.Model):
    DISPOSITION_CHOICES = [
        ('RESTOCK', 'Restocked into Sellable Inventory'),
        ('DAMAGED', 'Damaged / Unsellable Scrap'),
    ]

    return_record = models.ForeignKey(SaleReturn, on_delete=models.CASCADE, related_name='lines')
    sale_line = models.ForeignKey(SaleLine, on_delete=models.PROTECT, related_name='return_lines')
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT)
    quantity = models.PositiveIntegerField()
    refund_amount = models.DecimalField(max_digits=12, decimal_places=2)
    disposition = models.CharField(max_length=20, choices=DISPOSITION_CHOICES, default='RESTOCK')

    def __str__(self):
        return f"Returned {self.variant.sku} x {self.quantity} ({self.disposition})"
