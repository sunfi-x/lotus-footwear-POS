from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import BusinessDay, ApplicationSetting, AuditLog
from .services import BusinessDayService
from reports.services import ReportingService
from pos.models import Sale

@login_required
def home_view(request):
    current_day = BusinessDay.get_current()
    overview = ReportingService.get_daily_overview(current_day)
    
    # Recent sales for today
    if current_day:
        recent_sales = Sale.objects.filter(business_day=current_day).order_by('-created_at')[:15]
    else:
        recent_sales = []

    return render(request, 'core/home.html', {
        'overview': overview,
        'recent_sales': recent_sales,
    })

def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    if request.method == 'POST':
        u = request.POST.get('username', '').strip()
        p = request.POST.get('password', '').strip()
        user = authenticate(request, username=u, password=p)
        if user is not None:
            login(request, user)
            AuditLog.log('LOGIN', user=user, role='admin' if user.is_superuser else 'staff', details=f"User {u} logged in.")
            messages.success(request, f"স্বাগতম, {user.first_name or user.username}!")
            return redirect('home')
        else:
            messages.error(request, "ইউজারনেম অথবা পাসওয়ার্ড সঠিক নয়। আবার চেষ্টা করুন।")

    return render(request, 'core/login.html')

def logout_view(request):
    if request.user.is_authenticated:
        AuditLog.log('LOGOUT', user=request.user, details=f"User {request.user.username} logged out.")
        logout(request)
    messages.info(request, "সফলভাবে লগআউট সম্পন্ন হয়েছে।")
    return redirect('login')

@login_required
def open_business_day_view(request):
    if request.method == 'POST':
        day_date_str = request.POST.get('day_date')
        opening_cash = request.POST.get('opening_cash', '0.00')
        notes = request.POST.get('notes', '')

        try:
            day_date = timezone.datetime.strptime(day_date_str, '%Y-%m-%d').date() if day_date_str else timezone.localdate()
            b_day = BusinessDayService.open_day(
                day_date=day_date,
                opening_cash=opening_cash,
                notes=notes,
                user=request.user
            )
            messages.success(request, f"ব্যবসা দিন {b_day.date} সফলভাবে শুরু হয়েছে। প্রারম্ভিক ক্যাশ: ৳ {b_day.opening_cash}")
        except Exception as e:
            messages.error(request, f"দিন শুরু করতে সমস্যা হয়েছে: {str(e)}")

    return redirect('home')

@login_required
def close_business_day_view(request):
    if request.method == 'POST':
        actual_cash = request.POST.get('actual_cash', '0.00')
        discrepancy_reason = request.POST.get('discrepancy_reason', '')
        notes = request.POST.get('notes', '')

        current_day = BusinessDay.get_current()
        if not current_day:
            messages.error(request, "কোনো সক্রিয় ব্যবসা দিন খোলা নেই যা বন্ধ করা যাবে।")
            return redirect('home')

        try:
            b_day, sys_cash, diff, backup = BusinessDayService.close_day(
                business_day=current_day,
                actual_cash_counted=actual_cash,
                discrepancy_reason=discrepancy_reason,
                notes=notes,
                user=request.user
            )
            diff_msg = f" (ক্যাশ গরমিল: ৳ {diff})" if diff != 0 else " (ক্যাশ সমতা সঠিক)"
            messages.success(request, f"দিন {b_day.date} সফলভাবে সমাপ্ত হয়েছে!{diff_msg} দিন-সমাপ্তি ব্যাকআপ: {backup.filename}")
        except Exception as e:
            messages.error(request, f"দিন সমাপ্ত করতে সমস্যা হয়েছে: {str(e)}")

    return redirect('home')

@login_required
def shop_settings_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন বা মালিক সেটিংস পরিবর্তন করতে পারেন।")
        return redirect('home')

    settings_obj = ApplicationSetting.get_settings()
    if request.method == 'POST':
        settings_obj.shop_name = request.POST.get('shop_name', '').strip()
        settings_obj.shop_phone = request.POST.get('shop_phone', '').strip()
        settings_obj.shop_address = request.POST.get('shop_address', '').strip()
        settings_obj.receipt_header = request.POST.get('receipt_header', '').strip()
        settings_obj.receipt_footer = request.POST.get('receipt_footer', '').strip()
        settings_obj.external_backup_directory = request.POST.get('external_backup_directory', '').strip()
        try:
            settings_obj.low_stock_threshold = int(request.POST.get('low_stock_threshold', 5))
        except ValueError:
            pass
        settings_obj.save()

        AuditLog.log('SETTINGS_CHANGE', user=request.user, role='admin', details="Shop settings updated.")
        messages.success(request, "দোকান ও রসিদ সেটিংস সফলভাবে হালনাগাদ হয়েছে।")
        return redirect('shop_settings')

    return render(request, 'core/settings.html', {'settings': settings_obj})

@login_required
def audit_logs_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন অডিট লগ দেখতে পারেন।")
        return redirect('home')

    action = request.GET.get('action', '').strip()
    logs = AuditLog.objects.all()
    if action:
        logs = logs.filter(action_type=action)

    logs = logs[:100]
    return render(request, 'core/audit_logs.html', {
        'logs': logs,
        'selected_action': action
    })
