from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal
from core.models import BusinessDay

class ExpenseCategory(models.Model):
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['name']
        verbose_name_plural = 'Expense Categories'

    def __str__(self):
        return self.name


class Expense(models.Model):
    PAYMENT_METHODS = [
        ('CASH', 'Cash (দোকানের ক্যাশ)'),
        ('BKASH', 'bKash (বিকাশ)'),
        ('NAGAD', 'Nagad (নগদ)'),
        ('BANK', 'Bank Transfer (ব্যাংক)'),
        ('CARD', 'Card (কার্ড)'),
        ('OTHER', 'Other (অন্যান্য)'),
    ]

    category = models.ForeignKey(ExpenseCategory, on_delete=models.PROTECT, related_name='expenses')
    business_day = models.ForeignKey(BusinessDay, on_delete=models.SET_NULL, null=True, blank=True, related_name='expenses')
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='CASH')
    expense_date = models.DateField(default=timezone.now, db_index=True)
    description = models.TextField()
    recipient = models.CharField(max_length=150, blank=True, default='', help_text="Paid to person/entity")
    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-expense_date', '-id']

    def __str__(self):
        return f"{self.category.name}: Tk {self.amount} ({self.expense_date})"


class Salesman(models.Model):
    """
    Salesman profile record with a stable unique internal Salesman ID.
    Supports active/inactive status, phone, joining date, and notes.
    """
    salesman_id = models.CharField(max_length=30, unique=True, db_index=True, help_text="Unique internal ID e.g. SM-0001")
    name = models.CharField(max_length=150, db_index=True)
    phone = models.CharField(max_length=30, blank=True, default='')
    joining_date = models.DateField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name', 'salesman_id']

    def __str__(self):
        return f"{self.name} ({self.salesman_id})"

    def save(self, *args, **kwargs):
        if not self.salesman_id:
            # Auto-generate next unique salesman ID: SM-0001, SM-0002...
            last_obj = Salesman.objects.order_by('-id').first()
            next_num = (last_obj.id + 1) if last_obj else 1
            candidate = f"SM-{next_num:04d}"
            while Salesman.objects.filter(salesman_id=candidate).exists():
                next_num += 1
                candidate = f"SM-{next_num:04d}"
            self.salesman_id = candidate
        super().save(*args, **kwargs)


class SalesmanPayment(models.Model):
    """
    Immutable payment record to a salesman with unique Payment ID, auditability,
    expense linkage, and controlled reversal/void tracking.
    """
    PAYMENT_TYPES = [
        ('SALARY', 'Salary (মাসিক বেতন)'),
        ('ADVANCE', 'Advance (অগ্রিম)'),
        ('BONUS', 'Bonus (বোনাস/ইনসেন্টিভ)'),
        ('OTHER', 'Other (অন্যান্য ভাতা)'),
    ]

    PAYMENT_METHODS = [
        ('CASH', 'Cash (নগদ টাকা)'),
        ('BKASH', 'bKash (বিকাশ)'),
        ('NAGAD', 'Nagad (নগদ)'),
        ('BANK', 'Bank Transfer (ব্যাংক)'),
        ('CARD', 'Card (কার্ড)'),
        ('OTHER', 'Other (অন্যান্য)'),
    ]

    STATUS_CHOICES = [
        ('COMPLETED', 'Completed'),
        ('REVERSED', 'Reversed / Voided'),
    ]

    payment_id = models.CharField(max_length=40, unique=True, db_index=True, help_text="Unique payment ID e.g. SMP-20261020-0001")
    salesman = models.ForeignKey(Salesman, on_delete=models.PROTECT, related_name='payments')
    business_day = models.ForeignKey(BusinessDay, on_delete=models.SET_NULL, null=True, blank=True, related_name='salesman_payments')
    linked_expense = models.OneToOneField(Expense, on_delete=models.SET_NULL, null=True, blank=True, related_name='salesman_payment')

    payment_date = models.DateField(default=timezone.now, db_index=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    payment_type = models.CharField(max_length=20, choices=PAYMENT_TYPES, default='SALARY')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='CASH')
    reference_id = models.CharField(max_length=100, blank=True, default='', help_text="Txn ID / Ref")
    period_covered = models.CharField(max_length=100, blank=True, default='', help_text="e.g. October 2026")
    notes = models.TextField(blank=True, default='')

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='COMPLETED', db_index=True)
    
    # Controlled reversal / void audit fields
    reversal_reason = models.TextField(blank=True, default='')
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reversed_salesman_payments')

    recorded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='recorded_salesman_payments')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-payment_date', '-id']

    def __str__(self):
        return f"{self.payment_id} - {self.salesman.name} - Tk {self.amount} ({self.status})"

    def save(self, *args, **kwargs):
        if not self.payment_id:
            # Auto-generate unique Payment ID e.g. SMP-YYYYMMDD-0001
            date_str = (self.payment_date or timezone.localdate()).strftime('%Y%m%d')
            prefix = f"SMP-{date_str}"
            count_today = SalesmanPayment.objects.filter(payment_id__startswith=prefix).count() + 1
            candidate = f"{prefix}-{count_today:04d}"
            while SalesmanPayment.objects.filter(payment_id=candidate).exists():
                count_today += 1
                candidate = f"{prefix}-{count_today:04d}"
            self.payment_id = candidate
        super().save(*args, **kwargs)
