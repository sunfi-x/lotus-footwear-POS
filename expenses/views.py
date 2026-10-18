from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils import timezone
from .models import Expense, ExpenseCategory
from core.models import BusinessDay

@login_required
def expenses_list_view(request):
    expenses = Expense.objects.select_related('category').all().order_by('-expense_date', '-id')
    categories = ExpenseCategory.objects.all()

    total_expenses = sum(e.amount for e in expenses[:100])

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
