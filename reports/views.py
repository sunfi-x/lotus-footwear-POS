from datetime import date, datetime
from decimal import Decimal
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from django.db.models import Sum
from .services import ReportingService
from inventory.models import ProductModel, ProductVariant
from core.models import ApplicationSetting

@login_required
def admin_dashboard_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন বা মালিক ড্যাশবোর্ড দেখতে পারেন।")
        return redirect('home')

    period = request.GET.get('period', 'daily')
    today = timezone.localdate()

    if period == 'weekly':
        start_date, end_date = ReportingService.get_business_week_range(today)
    elif period == 'monthly':
        start_date, end_date = ReportingService.get_calendar_month_range(today.year, today.month)
    else: # daily
        period = 'daily'
        start_date = today
        end_date = today

    # Calculate financial report for the period
    financial = ReportingService.get_financial_report(start_date, end_date)

    # Stock metrics
    all_variants = ProductVariant.objects.filter(is_active=True).select_related('product')
    total_models_count = ProductModel.objects.filter(is_active=True).count()
    total_variants_count = all_variants.count()

    total_stock_pairs = sum(v.current_stock for v in all_variants)
    total_stock_valuation = sum(v.current_stock * v.weighted_avg_cost for v in all_variants)

    app_settings = ApplicationSetting.get_settings()
    low_threshold = app_settings.low_stock_threshold

    low_stock_variants = all_variants.filter(current_stock__lt=low_threshold, current_stock__gt=0).order_by('current_stock')
    out_of_stock_count = all_variants.filter(current_stock__lte=0).count()

    return render(request, 'reports/admin_dashboard.html', {
        'period': period,
        'financial': financial,
        'total_models_count': total_models_count,
        'total_variants_count': total_variants_count,
        'total_stock_pairs': total_stock_pairs,
        'total_stock_valuation': total_stock_valuation,
        'low_threshold': low_threshold,
        'low_stock_variants': low_stock_variants,
        'out_of_stock_count': out_of_stock_count,
    })

@login_required
def historical_search_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন ঐতিহাসিক বিক্রয় অনুসন্ধান দেখতে পারেন।")
        return redirect('home')

    code = request.GET.get('code', '').strip()
    results = None
    if code:
        results = ReportingService.search_historical_sales_by_code(code)

    return render(request, 'reports/historical_search.html', {
        'searched_code': code,
        'results': results,
    })


@login_required
def profit_report_view(request):
    """Standalone profit & loss report with custom date range selection."""
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন লাভ-ক্ষতির রিপোর্ট দেখতে পারেন।")
        return redirect('home')

    today = timezone.localdate()

    # Parse user-supplied date range or preset period
    period = request.GET.get('period', '').strip()
    start_str = request.GET.get('start_date', '').strip()
    end_str   = request.GET.get('end_date', '').strip()

    start_date = None
    end_date = None

    if start_str and end_str:
        try:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
            end_date   = datetime.strptime(end_str,   '%Y-%m-%d').date()
            period = 'custom'
        except ValueError:
            messages.warning(request, "তারিখের বিন্যাস সঠিক নয় (YYYY-MM-DD)। ডিফল্ট ব্যবহার করা হয়েছে।")
            start_date = end_date = None

    if not start_date or not end_date:
        if period == 'daily':
            start_date = end_date = today
        elif period == 'weekly':
            start_date, end_date = ReportingService.get_business_week_range(today)
        elif period == 'monthly':
            start_date, end_date = ReportingService.get_calendar_month_range(today.year, today.month)
        else:
            period = 'monthly'
            start_date, end_date = ReportingService.get_calendar_month_range(today.year, today.month)

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    financial = ReportingService.get_financial_report(start_date, end_date)

    return render(request, 'reports/profit_report.html', {
        'financial': financial,
        'start_date': start_date,
        'end_date': end_date,
        'period': period,
        'today': today,
    })
