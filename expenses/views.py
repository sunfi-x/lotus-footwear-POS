import csv
from datetime import datetime, date
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.db import transaction
from django.db.models import Sum, Q, Count
from django.core.paginator import Paginator

from .models import Expense, ExpenseCategory, Salesman, SalesmanPayment
from core.models import BusinessDay, AuditLog


# -------------------------------------------------------------
# Standard Expenses Views (Preserved)
# -------------------------------------------------------------
@login_required
def expenses_list_view(request):
    expenses = Expense.objects.select_related('category').all().order_by('-expense_date', '-id')
    categories = ExpenseCategory.objects.all()

    # Aggregate total across the full queryset (not just the first 100)
    total_expenses = expenses.aggregate(total=Sum('amount'))['total'] or Decimal('0')

    return render(request, 'expenses/expenses_list.html', {
        'expenses': expenses[:100],
        'categories': categories,
        'total_expenses': total_expenses,
    })


@login_required
def add_expense_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন দোকান খরচ এন্ট্রি করতে পারেন।")
        return redirect('expenses_list')

    if request.method == 'POST':
        category_id = request.POST.get('category_id')
        amount = request.POST.get('amount')
        payment_method = request.POST.get('payment_method', 'CASH')
        expense_date = request.POST.get('expense_date')
        recipient = request.POST.get('recipient', '').strip()
        description = request.POST.get('description', '').strip()

        category = get_object_or_404(ExpenseCategory, id=category_id)
        current_day = BusinessDay.get_current()

        try:
            Expense.objects.create(
                category=category,
                business_day=current_day,
                amount=Decimal(amount),
                payment_method=payment_method,
                expense_date=expense_date or timezone.localdate(),
                recipient=recipient,
                description=description,
                recorded_by=request.user
            )
            messages.success(request, f"খরচ ৳ {amount} ({category.name}) সফলভাবে হিসাবভুক্ত হয়েছে।")
        except Exception as e:
            messages.error(request, f"খরচ সংরক্ষণে ত্রুটি: {str(e)}")

    return redirect('expenses_list')


# -------------------------------------------------------------
# Helper: Get or Create Staff Salary Expense Category
# -------------------------------------------------------------
def get_salesman_expense_category(payment_type='SALARY'):
    """
    Returns appropriate ExpenseCategory for salesman payment.
    Ensures linking with operating expenses without duplicate accounting.
    """
    category_names = {
        'SALARY': 'Staff Salary (কর্মচারী বেতন)',
        'ADVANCE': 'Staff Advance (কর্মচারী অগ্রিম)',
        'BONUS': 'Staff Bonus (কর্মচারী বোনাস ও ইনসেন্টিভ)',
        'OTHER': 'Staff Allowances (অন্যান্য ভাতা)',
    }
    target_name = category_names.get(payment_type, 'Staff Salary (কর্মচারী বেতন)')
    category, _ = ExpenseCategory.objects.get_or_create(
        name=target_name,
        defaults={'description': f'Auto-tracked category for salesman {payment_type.lower()}'}
    )
    return category


# -------------------------------------------------------------
# Salesman Payments Dashboard & History View
# -------------------------------------------------------------
@login_required
def salesman_payments_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র অনুমোদিত এডমিন এই পেজে প্রবেশ করতে পারেন।")
        return redirect('home')

    today = timezone.localdate()
    first_of_month = today.replace(day=1)

    # Filter parameters
    salesman_filter = request.GET.get('salesman', '').strip()
    payment_type_filter = request.GET.get('payment_type', '').strip()
    payment_method_filter = request.GET.get('payment_method', '').strip()
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()
    q_search = request.GET.get('q', '').strip()

    payments_qs = SalesmanPayment.objects.select_related('salesman', 'recorded_by', 'reversed_by').all().order_by('-payment_date', '-id')

    # Apply filters
    if salesman_filter:
        payments_qs = payments_qs.filter(salesman__salesman_id=salesman_filter)

    if payment_type_filter:
        payments_qs = payments_qs.filter(payment_type=payment_type_filter)

    if payment_method_filter:
        payments_qs = payments_qs.filter(payment_method=payment_method_filter)

    start_date = None
    end_date = None
    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            payments_qs = payments_qs.filter(payment_date__gte=start_date)
        except ValueError:
            pass

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            payments_qs = payments_qs.filter(payment_date__lte=end_date)
        except ValueError:
            pass

    if q_search:
        payments_qs = payments_qs.filter(
            Q(payment_id__icontains=q_search) |
            Q(salesman__name__icontains=q_search) |
            Q(salesman__salesman_id__icontains=q_search) |
            Q(reference_id__icontains=q_search) |
            Q(notes__icontains=q_search)
        )

    # CSV Export support
    if request.GET.get('export') == 'csv':
        response = HttpResponse(content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="salesman_payments_{today.strftime("%Y%m%d")}.csv"'
        response.write('\ufeff')  # UTF-8 BOM for Excel Bengali compatibility
        writer = csv.writer(response)
        writer.writerow([
            'Payment ID', 'Payment Date', 'Salesman ID', 'Salesman Name',
            'Payment Type', 'Amount (BDT)', 'Payment Method', 'Reference / Txn ID',
            'Period Covered', 'Status', 'Notes', 'Recorded By', 'Recorded At'
        ])
        for p in payments_qs:
            writer.writerow([
                p.payment_id,
                p.payment_date.strftime('%Y-%m-%d'),
                p.salesman.salesman_id,
                p.salesman.name,
                p.get_payment_type_display(),
                f"{p.amount:.2f}",
                p.get_payment_method_display(),
                p.reference_id,
                p.period_covered,
                p.get_status_display(),
                p.notes,
                p.recorded_by.username if p.recorded_by else '',
                p.created_at.strftime('%Y-%m-%d %H:%M:%S')
            ])
        return response

    # Dashboard Summary Calculations (Only Completed payments)
    completed_all = SalesmanPayment.objects.filter(status='COMPLETED')

    total_active_salesmen = Salesman.objects.filter(is_active=True).count()
    payments_today_amount = completed_all.filter(payment_date=today).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    payments_this_month_amount = completed_all.filter(payment_date__gte=first_of_month, payment_date__lte=today).aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

    # Total payments in the currently filtered/selected date range
    filtered_completed = payments_qs.filter(status='COMPLETED')
    filtered_total_amount = filtered_completed.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')
    filtered_completed_count = filtered_completed.count()

    # Pagination
    paginator = Paginator(payments_qs, 30)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    all_salesmen = Salesman.objects.all().order_by('name')

    return render(request, 'expenses/salesman_payments.html', {
        'payments': page_obj,
        'page_obj': page_obj,
        'salesmen': all_salesmen,
        'total_active_salesmen': total_active_salesmen,
        'payments_today_amount': payments_today_amount,
        'payments_this_month_amount': payments_this_month_amount,
        'filtered_total_amount': filtered_total_amount,
        'filtered_completed_count': filtered_completed_count,
        'today': today,
        'selected_salesman': salesman_filter,
        'selected_type': payment_type_filter,
        'selected_method': payment_method_filter,
        'start_date': start_date_str,
        'end_date': end_date_str,
        'q_search': q_search,
    })


# -------------------------------------------------------------
# Add / Edit Salesman Profile
# -------------------------------------------------------------
@login_required
def add_salesman_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({'success': False, 'error': 'অননুমোদিত অ্যাক্সেস।'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    name = request.POST.get('name', '').strip()
    phone = request.POST.get('phone', '').strip()
    joining_date_str = request.POST.get('joining_date', '').strip()
    notes = request.POST.get('notes', '').strip()
    is_active = (request.POST.get('is_active', 'true') == 'true')

    if not name:
        return JsonResponse({'success': False, 'error': 'সেলসম্যানের নাম আবশ্যক।'}, status=400)

    joining_date = None
    if joining_date_str:
        try:
            joining_date = datetime.strptime(joining_date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'error': 'যোগদানের তারিখ সঠিক ফরম্যাটে দিন (YYYY-MM-DD)।'}, status=400)

    # Check potential duplicate warning (same name + phone)
    possible_duplicates = Salesman.objects.filter(name__iexact=name)
    if phone:
        possible_duplicates = possible_duplicates.filter(phone=phone)
    warning_duplicate = None
    if possible_duplicates.exists():
        warning_duplicate = f"সতর্কতা: '{name}' নামের এবং একই নম্বরের সেলসম্যান ({possible_duplicates.first().salesman_id}) ইতোমধ্যে ডাটাবেজে রয়েছে।"

    salesman = Salesman.objects.create(
        name=name,
        phone=phone,
        joining_date=joining_date,
        notes=notes,
        is_active=is_active
    )

    AuditLog.log(
        action_type='SALESMAN_ADD',
        user=request.user,
        role='admin',
        entity_type='Salesman',
        entity_id=salesman.salesman_id,
        details=f"Added salesman {salesman.name} (ID: {salesman.salesman_id}, Phone: {phone})"
    )

    return JsonResponse({
        'success': True,
        'message': f"সেলসম্যান '{salesman.name}' (আইডি: {salesman.salesman_id}) সফলভাবে যোগ হয়েছে।",
        'warning': warning_duplicate,
        'salesman': {
            'id': salesman.id,
            'salesman_id': salesman.salesman_id,
            'name': salesman.name,
            'phone': salesman.phone,
            'is_active': salesman.is_active,
        }
    })


@login_required
def edit_salesman_view(request, salesman_id):
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({'success': False, 'error': 'অননুমোদিত অ্যাক্সেস।'}, status=403)

    salesman = get_object_or_404(Salesman, salesman_id=salesman_id)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    name = request.POST.get('name', '').strip()
    phone = request.POST.get('phone', '').strip()
    joining_date_str = request.POST.get('joining_date', '').strip()
    notes = request.POST.get('notes', '').strip()
    is_active_val = request.POST.get('is_active')

    if not name:
        return JsonResponse({'success': False, 'error': 'সেলসম্যানের নাম আবশ্যক।'}, status=400)

    joining_date = None
    if joining_date_str:
        try:
            joining_date = datetime.strptime(joining_date_str, '%Y-%m-%d').date()
        except ValueError:
            return JsonResponse({'success': False, 'error': 'যোগদানের তারিখ সঠিক ফরম্যাটে দিন (YYYY-MM-DD)।'}, status=400)

    old_info = f"Name: {salesman.name}, Phone: {salesman.phone}, Active: {salesman.is_active}"

    salesman.name = name
    salesman.phone = phone
    salesman.joining_date = joining_date
    salesman.notes = notes
    if is_active_val is not None:
        salesman.is_active = (is_active_val == 'true' or is_active_val == '1')
    salesman.save()

    AuditLog.log(
        action_type='SALESMAN_EDIT',
        user=request.user,
        role='admin',
        entity_type='Salesman',
        entity_id=salesman.salesman_id,
        details=f"Updated salesman {salesman.salesman_id}. Prior: [{old_info}] -> New: [Name: {name}, Phone: {phone}, Active: {salesman.is_active}]"
    )

    return JsonResponse({
        'success': True,
        'message': f"সেলসম্যান '{salesman.name}' এর প্রোফাইল সফলভাবে আপডেট হয়েছে।"
    })


# -------------------------------------------------------------
# Record Salesman Payment (Atomic with Expense linkage & Cash)
# -------------------------------------------------------------
@login_required
@transaction.atomic
def record_salesman_payment_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({'success': False, 'error': 'শুধুমাত্র অনুমোদিত এডমিন পেমেন্ট এন্ট্রি করতে পারেন।'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    salesman_internal_id = request.POST.get('salesman_id', '').strip()
    payment_date_str = request.POST.get('payment_date', '').strip()
    amount_str = request.POST.get('amount', '').strip()
    payment_type = request.POST.get('payment_type', 'SALARY').strip().upper()
    payment_method = request.POST.get('payment_method', 'CASH').strip().upper()
    reference_id = request.POST.get('reference_id', '').strip()
    period_covered = request.POST.get('period_covered', '').strip()
    notes = request.POST.get('notes', '').strip()

    # Validation: Salesman
    salesman = Salesman.objects.filter(salesman_id=salesman_internal_id).first()
    if not salesman:
        return JsonResponse({'success': False, 'error': 'সঠিক সেলসম্যান নির্বাচন করুন।'}, status=400)

    # Validation: Payment Date
    try:
        payment_date = datetime.strptime(payment_date_str, '%Y-%m-%d').date() if payment_date_str else timezone.localdate()
    except ValueError:
        return JsonResponse({'success': False, 'error': 'পেমেন্টের তারিখ সঠিক নয়।'}, status=400)

    # Validation: Amount
    try:
        amount = Decimal(amount_str).quantize(Decimal('0.01'))
        if amount <= Decimal('0.00'):
            return JsonResponse({'success': False, 'error': 'পেমেন্টের পরিমাণ অবশ্যই শূন্য (০) টাকার বেশি হতে হবে।'}, status=400)
    except (InvalidOperation, ValueError):
        return JsonResponse({'success': False, 'error': 'টাকার পরিমাণ একটি সঠিক সংখ্যা হতে হবে।'}, status=400)

    # Validation: Payment Method & Type
    valid_methods = ['CASH', 'BKASH', 'NAGAD', 'BANK', 'CARD', 'OTHER']
    valid_types = ['SALARY', 'ADVANCE', 'BONUS', 'OTHER']
    if payment_method not in valid_methods:
        return JsonResponse({'success': False, 'error': 'অবৈধ পেমেন্ট মেথড নির্বাচিত হয়েছে।'}, status=400)
    if payment_type not in valid_types:
        return JsonResponse({'success': False, 'error': 'অবৈধ পেমেন্ট টাইপ নির্বাচিত হয়েছে।'}, status=400)

    # Digital Txn Reference duplicate warning/check
    duplicate_warning = None
    if reference_id and payment_method != 'CASH':
        existing_txn = SalesmanPayment.objects.filter(reference_id__iexact=reference_id, status='COMPLETED').first()
        if existing_txn:
            duplicate_warning = f"সতর্কতা: ট্রানজেকশন রেফারেন্স '{reference_id}' ইতোপূর্বে পেমেন্ট #{existing_txn.payment_id} তে ব্যবহার করা হয়েছে।"

    current_day = BusinessDay.get_current()
    if payment_date == timezone.localdate() and current_day:
        target_business_day = current_day
    else:
        target_business_day = BusinessDay.objects.filter(date=payment_date).first()

    # Determine / Create linked Expense category
    category = get_salesman_expense_category(payment_type)

    # 1. Create linked Expense record (Atomically)
    expense_desc = f"Salesman Payment: {salesman.name} ({salesman.salesman_id}) - {payment_type}"
    if period_covered:
        expense_desc += f" for {period_covered}"
    if notes:
        expense_desc += f" | {notes}"

    linked_expense = Expense.objects.create(
        category=category,
        business_day=target_business_day,
        amount=amount,
        payment_method=payment_method,
        expense_date=payment_date,
        recipient=salesman.name,
        description=expense_desc,
        recorded_by=request.user
    )

    # 2. Create SalesmanPayment record
    payment = SalesmanPayment.objects.create(
        salesman=salesman,
        business_day=target_business_day,
        linked_expense=linked_expense,
        payment_date=payment_date,
        amount=amount,
        payment_type=payment_type,
        payment_method=payment_method,
        reference_id=reference_id,
        period_covered=period_covered,
        notes=notes,
        status='COMPLETED',
        recorded_by=request.user
    )

    AuditLog.log(
        action_type='SALESMAN_PAYMENT',
        user=request.user,
        role='admin',
        entity_type='SalesmanPayment',
        entity_id=payment.payment_id,
        details=f"Recorded {payment_type} of Tk {amount:.2f} to {salesman.name} ({salesman.salesman_id}) via {payment_method} (Expense ID #{linked_expense.id})"
    )

    return JsonResponse({
        'success': True,
        'payment_id': payment.payment_id,
        'message': f"পেমেন্ট #{payment.payment_id} (৳ {amount:.2f}) সফলভাবে সংরক্ষিত হয়েছে।",
        'warning': duplicate_warning,
    })


# -------------------------------------------------------------
# Reverse / Void Salesman Payment
# -------------------------------------------------------------
@login_required
@transaction.atomic
def reverse_salesman_payment_view(request, payment_id):
    if not request.user.is_superuser:
        return JsonResponse({'success': False, 'error': 'শুধুমাত্র প্রধান এডমিন পেমেন্ট বাতিল/সংশোধন করতে পারেন।'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    payment = get_object_or_404(SalesmanPayment, payment_id=payment_id)

    if payment.status != 'COMPLETED':
        return JsonResponse({'success': False, 'error': 'এই পেমেন্টটি ইতিমধ্যে বাতিল বা রিভার্স করা হয়েছে।'}, status=400)

    reason = request.POST.get('reason', '').strip()
    if not reason:
        return JsonResponse({'success': False, 'error': 'পেমেন্ট রিভার্স/বাতিল করার বাধ্যতামূলক কারণ উল্লেখ করুন।'}, status=400)

    # Mark payment as REVERSED
    payment.status = 'REVERSED'
    payment.reversal_reason = reason
    payment.reversed_at = timezone.now()
    payment.reversed_by = request.user
    payment.save(update_fields=['status', 'reversal_reason', 'reversed_at', 'reversed_by', 'updated_at'])

    # Safely remove or neutralize linked Expense to restore cash drawer / expense figures
    if payment.linked_expense:
        linked_exp = payment.linked_expense
        payment.linked_expense = None
        payment.save(update_fields=['linked_expense'])
        linked_exp.delete()

    AuditLog.log(
        action_type='SALESMAN_PAYMENT_REVERSE',
        user=request.user,
        role='admin',
        entity_type='SalesmanPayment',
        entity_id=payment.payment_id,
        details=f"Reversed payment #{payment.payment_id} (Tk {payment.amount:.2f}) to {payment.salesman.name}. Reason: {reason}"
    )

    return JsonResponse({
        'success': True,
        'message': f"পেমেন্ট #{payment.payment_id} সফলভাবে বাতিল/রিভার্স করা হয়েছে এবং অডিট লগ আপডেট হয়েছে।"
    })


# -------------------------------------------------------------
# Individual Salesman Payment History & Profile
# -------------------------------------------------------------
@login_required
def individual_salesman_history_view(request, salesman_id):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "অননুমোদিত অ্যাক্সেস।")
        return redirect('home')

    salesman = get_object_or_404(Salesman, salesman_id=salesman_id)

    # Filter parameters
    payment_type_filter = request.GET.get('payment_type', '').strip()
    payment_method_filter = request.GET.get('payment_method', '').strip()
    start_date_str = request.GET.get('start_date', '').strip()
    end_date_str = request.GET.get('end_date', '').strip()

    payments_qs = salesman.payments.select_related('recorded_by', 'reversed_by').all().order_by('-payment_date', '-id')

    if payment_type_filter:
        payments_qs = payments_qs.filter(payment_type=payment_type_filter)
    if payment_method_filter:
        payments_qs = payments_qs.filter(payment_method=payment_method_filter)

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            payments_qs = payments_qs.filter(payment_date__gte=start_date)
        except ValueError:
            pass

    if end_date_str:
        try:
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            payments_qs = payments_qs.filter(payment_date__lte=end_date)
        except ValueError:
            pass

    # Calculations for this individual salesman
    completed_payments = payments_qs.filter(status='COMPLETED')
    total_completed_count = completed_payments.count()
    total_amount_paid = completed_payments.aggregate(s=Sum('amount'))['s'] or Decimal('0.00')

    # Breakdown by payment type
    type_breakdown = completed_payments.values('payment_type').annotate(total=Sum('amount'), count=Count('id'))
    # Breakdown by payment method
    method_breakdown = completed_payments.values('payment_method').annotate(total=Sum('amount'), count=Count('id'))

    return render(request, 'expenses/salesman_profile.html', {
        'salesman': salesman,
        'payments': payments_qs,
        'total_completed_count': total_completed_count,
        'total_amount_paid': total_amount_paid,
        'type_breakdown': type_breakdown,
        'method_breakdown': method_breakdown,
        'selected_type': payment_type_filter,
        'selected_method': payment_method_filter,
        'start_date': start_date_str,
        'end_date': end_date_str,
    })
