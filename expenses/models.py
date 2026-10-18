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
        ('BANK', 'Bank Transfer (ব্যাংক)'),
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
