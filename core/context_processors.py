from .models import ApplicationSetting, BusinessDay

def shop_context(request):
    settings = ApplicationSetting.get_settings()
    current_day = BusinessDay.get_current()
    is_admin = request.user.is_authenticated and (request.user.is_superuser or request.user.is_staff)
    day_reconciliation = None
    if current_day:
        from reports.services import ReportingService
        day_reconciliation = ReportingService.get_daily_overview(current_day)
    return {
        'shop_settings': settings,
        'current_business_day': current_day,
        'day_reconciliation': day_reconciliation,
        'is_shop_open': current_day is not None,
        'is_admin_user': is_admin,
    }
