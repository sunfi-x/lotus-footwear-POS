import os
import sqlite3
import shutil
from datetime import datetime
from pathlib import Path
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from .models import BackupRecord
from core.models import ApplicationSetting, AuditLog

class BackupService:

    @classmethod
    def get_backup_dir(cls):
        backup_dir = Path(settings.BACKUP_DIR)
        backup_dir.mkdir(parents=True, exist_ok=True)
        return backup_dir

    @classmethod
    def verify_sqlite_file(cls, db_file_path):
        """
        Connects to a candidate SQLite backup file and runs PRAGMA integrity_check.
        Returns: (passed: bool, details: str)
        """
        if not os.path.exists(db_file_path) or os.path.getsize(db_file_path) == 0:
            return False, "File does not exist or is 0 bytes."

        conn = None
        try:
            conn = sqlite3.connect(str(db_file_path))
            cursor = conn.cursor()
            cursor.execute("PRAGMA integrity_check;")
            row = cursor.fetchone()
            passed = (row is not None and row[0] == "ok")

            # Check critical tables exist
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = [r[0] for r in cursor.fetchall()]

            required = ['core_businessday', 'inventory_productvariant', 'pos_sale']
            missing = [t for t in required if t not in tables]
            if missing:
                return False, f"Integrity check passed but missing tables: {missing}"

            if passed:
                return True, f"Integrity check OK. Tables count: {len(tables)}"
            else:
                return False, f"Integrity check returned: {row}"
        except Exception as e:
            return False, f"Verification failed with exception: {str(e)}"
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass

    @classmethod
    def create_backup(cls, backup_type='MANUAL', user=None):
        """
        Creates a hot, atomic online backup using SQLite's backup API.
        Saves locally and mirrors to external drive if configured.
        """
        timestamp_str = datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"lotus_pos_backup_{timestamp_str}_{backup_type.lower()}.sqlite3"
        backup_dir = cls.get_backup_dir()
        target_path = backup_dir / filename

        try:
            db_name = connection.settings_dict.get('NAME')
            dst_conn = sqlite3.connect(str(target_path))

            is_memory = not db_name or str(db_name) == ':memory:' or str(db_name).startswith('file:')
            if not is_memory and os.path.exists(str(db_name)):
                # Open read-only URI connection for zero lock contention
                db_abs = os.path.abspath(str(db_name))
                src_conn = sqlite3.connect(f"file:{db_abs}?mode=ro", uri=True)
                with dst_conn:
                    src_conn.backup(dst_conn)
                src_conn.close()
            else:
                # Active connection fallback (e.g. in-memory test databases)
                connection.ensure_connection()
                with dst_conn:
                    connection.connection.backup(dst_conn)

            dst_conn.close()
            file_size = os.path.getsize(target_path)

            # Immediately verify the backup file
            passed, details = cls.verify_sqlite_file(target_path)

            record = BackupRecord.objects.create(
                timestamp=timezone.now(),
                backup_type=backup_type,
                filename=filename,
                filepath=str(target_path),
                file_size_bytes=file_size,
                integrity_check_passed=passed,
                verification_details=details,
                status='SUCCESS' if passed else 'FAILED',
                error_message='' if passed else details,
                created_by=user
            )

            # Mirror to external USB / path if configured and reachable
            try:
                app_settings = ApplicationSetting.get_settings()
                if app_settings.external_backup_directory and os.path.exists(app_settings.external_backup_directory):
                    ext_target = Path(app_settings.external_backup_directory) / filename
                    shutil.copy2(target_path, ext_target)
            except Exception as ext_err:
                record.verification_details += f" [Note: Mirror to external drive failed: {ext_err}]"
                record.save(update_fields=['verification_details'])

            AuditLog.log(
                action_type='BACKUP_CREATE',
                user=user,
                role='admin' if user and user.is_superuser else 'staff',
                entity_type='BackupRecord',
                entity_id=record.id,
                details=f"Backup {filename} created ({file_size} bytes). Integrity: {passed}."
            )

            return record, passed, details

        except Exception as e:
            err_msg = str(e)
            record = BackupRecord.objects.create(
                timestamp=timezone.now(),
                backup_type=backup_type,
                filename=filename,
                filepath=str(target_path),
                file_size_bytes=0,
                integrity_check_passed=False,
                verification_details='Failed during execution',
                status='FAILED',
                error_message=err_msg,
                created_by=user
            )
            return record, False, err_msg

    @classmethod
    def restore_backup(cls, backup_file_path, user=None):
        """
        Safely restores the database from a verified backup file.
        1. Validates candidate backup integrity first.
        2. Creates an emergency pre-restore snapshot of the current database.
        3. Restores candidate database.
        4. Verifies database post-restore.
        """
        if not user or not user.is_superuser:
            raise PermissionError("Only Admin/Owner can restore database backups.")

        candidate_path = Path(backup_file_path)
        if not candidate_path.exists():
            raise FileNotFoundError(f"Backup file not found at: {backup_file_path}")

        # 1. Verify candidate file
        passed, details = cls.verify_sqlite_file(candidate_path)
        if not passed:
            raise ValueError(f"Candidate backup file failed integrity check: {details}")

        source_db_path = Path(connection.settings_dict['NAME'])

        # 2. Safety copy of current running database
        safety_record, s_passed, s_details = cls.create_backup(backup_type='PRE_RESTORE', user=user)

        try:
            # Close existing Django connections to release locks
            connection.close()

            # Copy candidate over active database file
            shutil.copy2(candidate_path, source_db_path)

            # Re-verify restored active database
            post_passed, post_details = cls.verify_sqlite_file(source_db_path)
            if not post_passed:
                # Rollback from safety backup
                shutil.copy2(safety_record.filepath, source_db_path)
                raise RuntimeError(f"Post-restore verification failed! Rolled back to safety copy. Error: {post_details}")

            AuditLog.log(
                action_type='BACKUP_RESTORE',
                user=user,
                role='admin',
                details=f"Restored database from {candidate_path.name}. Pre-restore safety copy: {safety_record.filename}."
            )

            return True, f"Successfully restored from {candidate_path.name}. Active database verified healthy."

        except Exception as e:
            # Ensure safety rollback if possible
            if os.path.exists(safety_record.filepath):
                try:
                    shutil.copy2(safety_record.filepath, source_db_path)
                except Exception:
                    pass
            raise RuntimeError(f"Restore failed: {str(e)}")
