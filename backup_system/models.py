from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone

class BackupRecord(models.Model):
    BACKUP_TYPES = [
        ('MANUAL', 'Manual On-Demand Backup'),
        ('DAY_END', 'Day-End Closing Backup'),
        ('AUTO', 'Scheduled Automatic Backup'),
        ('PRE_RESTORE', 'Safety Backup Pre-Restore'),
    ]

    STATUS_CHOICES = [
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
    ]

    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    backup_type = models.CharField(max_length=20, choices=BACKUP_TYPES, default='MANUAL')
    filename = models.CharField(max_length=255)
    filepath = models.CharField(max_length=500)
    file_size_bytes = models.BigIntegerField(default=0)
    integrity_check_passed = models.BooleanField(default=False)
    verification_details = models.TextField(blank=True, default='')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='SUCCESS')
    error_message = models.TextField(blank=True, default='')
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']

    def __str__(self):
        status_sym = "✓" if self.status == 'SUCCESS' and self.integrity_check_passed else "✗"
        return f"{status_sym} [{self.backup_type}] {self.filename} ({self.timestamp.strftime('%Y-%m-%d %H:%M')})"
