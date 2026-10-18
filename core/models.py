from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from decimal import Decimal

class BusinessDay(models.Model):
    STATUS_CHOICES = [
        ('OPEN', 'Open'),
        ('CLOSED', 'Closed'),
    ]

    date = models.DateField(unique=True, db_index=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='OPEN', db_index=True)
    opened_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(null=True, blank=True)
    opened_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='opened_days')
    closed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='closed_days')

    opening_cash = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    closing_cash_system = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    closing_cash_actual = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    cash_discrepancy = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    discrepancy_reason = models.TextField(blank=True, default='')

    notes = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-date']

    def __str__(self):
        return f"Business Day {self.date} ({self.status})"

    @classmethod
    def get_current(cls):
        """Returns the currently open business day if any, or None."""
        return cls.objects.filter(status='OPEN').order_by('-date').first()


class ApplicationSetting(models.Model):
    """Singleton application and shop configuration model."""
    shop_name = models.CharField(max_length=200, default='LOTUS FOOTWEAR')
    shop_phone = models.CharField(max_length=50, default='+880 1XXXXXXXXX')
    shop_address = models.TextField(default='Shop # 12, Ground Floor, Dhaka, Bangladesh')
    receipt_header = models.CharField(max_length=255, default='LOTUS FOOTWEAR')
    receipt_footer = models.TextField(default='THANK YOU FOR SHOPPING!\nExchange within 7 days with receipt.')
    
    backup_directory = models.CharField(max_length=255, default='backups')
    external_backup_directory = models.CharField(max_length=255, blank=True, default='D:\\LotusPOS_Backups')
    low_stock_threshold = models.IntegerField(default=5)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.shop_name} Configuration"

    @classmethod
    def get_settings(cls):
        obj, created = cls.objects.get_or_create(id=1)
        return obj


class AuditLog(models.Model):
    ACTION_CHOICES = [
        ('LOGIN', 'User Login'),
        ('LOGOUT', 'User Logout'),
        ('SALE_CREATE', 'Sale Created'),
        ('PRICE_OVERRIDE', 'Price Override'),
        ('DISCOUNT_APPLIED', 'Discount Applied'),
        ('SALE_CANCEL', 'Sale Cancelled'),
        ('RETURN_PROCESSED', 'Return Processed'),
        ('PURCHASE_ADD', 'Purchase Added'),
        ('STOCK_ADJUST', 'Stock Adjusted'),
        ('CSV_IMPORT', 'CSV Imported'),
        ('DAY_OPEN', 'Day Opened'),
        ('DAY_CLOSE', 'Day Closed'),
        ('DAY_REOPEN', 'Day Reopened'),
        ('BACKUP_CREATE', 'Backup Created'),
        ('BACKUP_RESTORE', 'Backup Restored'),
        ('SETTINGS_CHANGE', 'Settings Changed'),
    ]

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    username = models.CharField(max_length=150, default='system')
    role = models.CharField(max_length=50, default='staff')
    action_type = models.CharField(max_length=50, choices=ACTION_CHOICES, db_index=True)
    entity_type = models.CharField(max_length=100, blank=True, default='')
    entity_id = models.CharField(max_length=100, blank=True, default='')
    details = models.TextField(blank=True, default='')
    ip_address = models.CharField(max_length=50, default='127.0.0.1')

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        return f"[{self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}] {self.role} - {self.action_type}"

    @classmethod
    def log(cls, action_type, user=None, role='staff', entity_type='', entity_id='', details='', ip='127.0.0.1'):
        username = user.username if user else 'anonymous'
        actual_role = role
        if user and user.is_superuser:
            actual_role = 'admin'
        return cls.objects.create(
            user=user,
            username=username,
            role=actual_role,
            action_type=action_type,
            entity_type=entity_type,
            entity_id=str(entity_id),
            details=details,
            ip_address=ip
        )
