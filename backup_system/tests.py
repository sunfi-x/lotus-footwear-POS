import os
from django.test import TransactionTestCase
from django.contrib.auth.models import User
from backup_system.models import BackupRecord
from backup_system.services import BackupService

class BackupServiceTests(TransactionTestCase):
    def setUp(self):
        self.admin_user = User.objects.create_superuser(username='backup_admin', password='pass', email='admin@test.local')
        self.staff_user = User.objects.create_user(username='backup_staff', password='pass')

    def test_create_and_verify_hot_backup(self):
        record, passed, details = BackupService.create_backup(backup_type='MANUAL', user=self.admin_user)
        self.assertTrue(passed, msg=f"Backup failed with details: {details}")
        self.assertEqual(record.status, 'SUCCESS')
        self.assertTrue(record.integrity_check_passed)
        self.assertTrue(os.path.exists(record.filepath))
        self.assertGreater(record.file_size_bytes, 0)

    def test_verify_sqlite_file_detects_corrupt_file(self):
        backup_dir = BackupService.get_backup_dir()
        dummy_bad_file = backup_dir / "corrupted_test.sqlite3"
        with open(dummy_bad_file, "w") as f:
            f.write("This is not a real sqlite database!")

        passed, details = BackupService.verify_sqlite_file(dummy_bad_file)
        self.assertFalse(passed)

        # Cleanup
        if os.path.exists(dummy_bad_file):
            try:
                os.remove(dummy_bad_file)
            except Exception:
                pass

    def test_staff_cannot_restore_backup(self):
        record, _, _ = BackupService.create_backup(backup_type='MANUAL', user=self.admin_user)
        with self.assertRaises(PermissionError):
            BackupService.restore_backup(record.filepath, user=self.staff_user)
