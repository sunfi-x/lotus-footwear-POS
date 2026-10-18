from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from .models import BackupRecord
from .services import BackupService
from core.models import ApplicationSetting

@login_required
def backup_center_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন ব্যাকআপ ও রিস্টোর সেন্টার ব্যবহার করতে পারেন।")
        return redirect('home')

    backups = BackupRecord.objects.all().order_by('-timestamp')[:50]
    app_settings = ApplicationSetting.get_settings()
    backup_dir = BackupService.get_backup_dir()

    return render(request, 'backup_system/backup_center.html', {
        'backups': backups,
        'backup_dir': str(backup_dir),
        'shop_settings': app_settings,
    })

@login_required
def trigger_manual_backup_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন ব্যাকআপ নিতে পারেন।")
        return redirect('home')

    if request.method == 'POST':
        record, passed, details = BackupService.create_backup(backup_type='MANUAL', user=request.user)
        if passed:
            messages.success(request, f"অনলাইন হট ব্যাকআপ '{record.filename}' সফলভাবে তৈরি ও ত্রুটিহীনভাবে যাচাই হয়েছে ({record.file_size_bytes} বাইট)!")
        else:
            messages.error(request, f"ব্যাকআপ তৈরিতে বা ইন্টিগ্রিটি পরীক্ষায় ত্রুটি হয়েছে: {details}")

    return redirect('backup_center')

@login_required
def restore_backup_view(request):
    if not request.user.is_superuser:
        messages.error(request, "শুধুমাত্র প্রধান এডমিন ডাটাবেজ রিস্টোর করার অনুমতিপ্রাপ্ত।")
        return redirect('backup_center')

    if request.method == 'POST':
        filepath = request.POST.get('backup_filepath', '').strip()
        confirmation = request.POST.get('confirmation_code', '').strip()

        if confirmation != 'RESTORE':
            messages.error(request, "নিশ্চিতকরণ কোড ভুল হয়েছে! হুবহু 'RESTORE' লিখতে হবে।")
            return redirect('backup_center')

        try:
            success, msg = BackupService.restore_backup(filepath, user=request.user)
            messages.success(request, f"সফলভাবে ডাটাবেজ রিস্টোর সম্পন্ন হয়েছে! {msg}")
        except Exception as e:
            messages.error(request, f"ডাটাবেজ রিস্টোর ব্যর্থ হয়েছে: {str(e)}")

    return redirect('backup_center')
