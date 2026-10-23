from decimal import Decimal, ROUND_HALF_UP
from django.db import transaction, models
from django.db.models import Sum
from django.utils import timezone
from .models import BusinessDay, AuditLog
from pos.models import Sale, Payment, SaleReturn
from expenses.models import Expense
from backup_system.services import BackupService
from reports.services import ReportingService

class BusinessDayService:

    @classmethod
    @transaction.atomic
    def open_day(cls, day_date=None, opening_cash=Decimal('0.00'), notes='', user=None):
        """
        Opens a new business day. Ensures no other day is currently open.
        """
        if day_date is None:
            day_date = timezone.localdate()

        current_open = BusinessDay.objects.filter(status='OPEN').first()
        if current_open:
            raise ValueError(f"Business Day {current_open.date} is currently OPEN. Close it before opening a new day.")

        existing = BusinessDay.objects.filter(date=day_date).first()
        if existing and existing.status == 'CLOSED':
            raise ValueError(f"Business Day {day_date} is already closed. To reopen, use the Admin Reopen workflow.")

        opening_cash = Decimal(str(opening_cash)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        business_day = BusinessDay.objects.create(
            date=day_date,
            status='OPEN',
            opened_at=timezone.now(),
            opened_by=user,
            opening_cash=opening_cash,
            notes=notes
        )

        AuditLog.log(
            action_type='DAY_OPEN',
            user=user,
            role='admin' if user and user.is_superuser else 'staff',
            entity_type='BusinessDay',
            entity_id=business_day.date.strftime('%Y-%m-%d'),
            details=f"Opened business day {business_day.date} with opening cash Tk {opening_cash}."
        )

        return business_day

    @classmethod
    @transaction.atomic
    def close_day(cls, business_day, actual_cash_counted, discrepancy_reason='', notes='', other_cash_in=None, user=None):
        """
        Reconciles cash, triggers a mandatory day-end backup, and marks the business day as CLOSED.
        Enforces discrepancy note when actual cash != expected cash.
        """
        if business_day.status != 'OPEN':
            raise ValueError("Only an OPEN business day can be closed.")

        actual_cash = Decimal(str(actual_cash_counted)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        if other_cash_in is not None and str(other_cash_in).strip() != '':
            business_day.other_cash_in = Decimal(str(other_cash_in)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

        # 1. Calculate Expected System Cash via single authoritative ReportingService
        overview = ReportingService.get_daily_overview(business_day)
        system_cash = overview['expected_cash']
        discrepancy = actual_cash - system_cash

        # Require a note/explanation if there is a discrepancy
        if discrepancy != Decimal('0.00') and not discrepancy_reason.strip():
            raise ValueError(f"ক্যাশ গরমিল রয়েছে (পার্থক্য: ৳ {discrepancy})। গরমিলের কারণ উল্লেখ করা বাধ্যতামূলক।")

        # 2. Mandatory Day-End Hot Backup
        backup_record, passed, details = BackupService.create_backup(backup_type='DAY_END', user=user)
        if not passed:
            raise RuntimeError(f"Day-End Backup failed integrity check: {details}. Cannot close day without a valid backup!")

        # 3. Update and close BusinessDay
        business_day.closing_cash_system = system_cash
        business_day.closing_cash_actual = actual_cash
        business_day.cash_discrepancy = discrepancy
        business_day.discrepancy_reason = discrepancy_reason.strip()
        business_day.status = 'CLOSED'
        business_day.closed_at = timezone.now()
        business_day.closed_by = user
        if notes:
            business_day.notes = (business_day.notes + "\n" if business_day.notes else "") + f"[Closing notes]: {notes}"
        business_day.save()

        AuditLog.log(
            action_type='DAY_CLOSE',
            user=user,
            role='admin' if user and user.is_superuser else 'staff',
            entity_type='BusinessDay',
            entity_id=business_day.date.strftime('%Y-%m-%d'),
            details=f"Closed business day {business_day.date}. System cash Tk {system_cash}, Actual Tk {actual_cash}, Diff Tk {discrepancy}. Backup: {backup_record.filename}."
        )

        return business_day, system_cash, discrepancy, backup_record

    @classmethod
    @transaction.atomic
    def reopen_day(cls, business_day, reason, user=None):
        """
        Protected Admin workflow to reopen a closed day for corrections.
        """
        if not user or not user.is_superuser:
            raise PermissionError("Only Admin/Owner can reopen a closed business day.")

        # Ensure no other day is currently open
        other_open = BusinessDay.objects.filter(status='OPEN').exclude(id=business_day.id).first()
        if other_open:
            raise ValueError(f"Cannot reopen day {business_day.date}. Day {other_open.date} is currently OPEN.")

        business_day.status = 'OPEN'
        business_day.notes += f"\n[Reopened on {timezone.now().strftime('%Y-%m-%d %H:%M')} by {user.username}]: {reason}"
        business_day.save(update_fields=['status', 'notes'])

        AuditLog.log(
            action_type='DAY_REOPEN',
            user=user,
            role='admin',
            entity_type='BusinessDay',
            entity_id=business_day.date.strftime('%Y-%m-%d'),
            details=f"Reopened business day {business_day.date}. Reason: {reason}"
        )
        return business_day
