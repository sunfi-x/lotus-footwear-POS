from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal

class ProductModel(models.Model):
    code = models.CharField(max_length=50, unique=True, db_index=True, help_text="Product/Article Code printed on shoe")
    name = models.CharField(max_length=200, help_text="Product or model name")
    brand = models.CharField(max_length=100, default='Lotus', blank=True)
    category = models.CharField(max_length=100, default='General', blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['code']

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def total_stock(self):
        return sum(v.current_stock for v in self.variants.filter(is_active=True))


class ProductVariant(models.Model):
    product = models.ForeignKey(ProductModel, on_delete=models.CASCADE, related_name='variants')
    size = models.CharField(max_length=20, db_index=True)
    colour = models.CharField(max_length=50, db_index=True)
    sku = models.CharField(max_length=100, unique=True, db_index=True)
    current_stock = models.IntegerField(default=0)
    weighted_avg_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    standard_selling_price = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    low_stock_threshold = models.PositiveIntegerField(default=5, help_text="Alert when stock falls to or below this level")
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['product__code', 'size', 'colour']
        constraints = [
            models.UniqueConstraint(fields=['product', 'size', 'colour'], name='unique_product_size_colour')
        ]

    def __str__(self):
        return f"{self.product.code} | Size: {self.size} | Colour: {self.colour} (Stock: {self.current_stock})"

    def save(self, *args, **kwargs):
        if not self.sku:
            clean_code = str(self.product.code).strip().replace(" ", "-")
            clean_size = str(self.size).strip().replace(" ", "-")
            clean_colour = str(self.colour).strip().replace(" ", "-")
            self.sku = f"{clean_code}-{clean_size}-{clean_colour}".upper()
        super().save(*args, **kwargs)


class Supplier(models.Model):
    name = models.CharField(max_length=200, unique=True)
    phone = models.CharField(max_length=50, blank=True, default='')
    address = models.TextField(blank=True, default='')
    contact_person = models.CharField(max_length=100, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name


class Purchase(models.Model):
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name='purchases')
    invoice_no = models.CharField(max_length=100, blank=True, default='', help_text="Supplier invoice/challan number")
    purchase_date = models.DateField(default=timezone.now, db_index=True)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='recorded_purchases')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-purchase_date', '-id']

    def __str__(self):
        return f"Purchase #{self.id} from {self.supplier.name} on {self.purchase_date}"


class PurchaseLine(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name='lines')
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='purchase_lines')
    quantity = models.PositiveIntegerField()
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    line_total = models.DecimalField(max_digits=12, decimal_places=2)

    def save(self, *args, **kwargs):
        self.line_total = Decimal(str(self.quantity)) * Decimal(str(self.unit_cost))
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.variant.sku} x {self.quantity} @ Tk {self.unit_cost}"


class StockMovement(models.Model):
    MOVEMENT_CHOICES = [
        ('OPENING', 'Opening Stock'),
        ('PURCHASE', 'Purchase Consignment'),
        ('SALE', 'Customer Sale'),
        ('SALE_RETURN', 'Customer Sale Return'),
        ('ADJUSTMENT', 'Stock Reconciliation Adjustment'),
    ]

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='stock_movements')
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_CHOICES, db_index=True)
    quantity_delta = models.IntegerField(help_text="Positive for addition, negative for deduction")
    resulting_stock = models.IntegerField(help_text="Stock balance immediately after this movement")
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    reference_type = models.CharField(max_length=50, blank=True, default='')
    reference_id = models.CharField(max_length=50, blank=True, default='')
    notes = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-timestamp', '-id']

    def __str__(self):
        sign = "+" if self.quantity_delta > 0 else ""
        return f"{self.timestamp.strftime('%Y-%m-%d %H:%M')} | {self.variant.sku} | {sign}{self.quantity_delta} ({self.movement_type})"


class StockAdjustment(models.Model):
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, related_name='adjustments')
    old_stock = models.IntegerField()
    new_stock = models.IntegerField()
    difference = models.IntegerField()
    reason = models.TextField()
    authorized_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"Adjustment {self.variant.sku}: {self.old_stock} -> {self.new_stock} ({self.difference})"
