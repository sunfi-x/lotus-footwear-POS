import json
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.views.decorators.csrf import csrf_exempt
from core.models import BusinessDay
from inventory.models import ProductModel, ProductVariant
from .models import Sale, SaleLine
from .services import BillingService

@login_required
def pos_screen_view(request):
    current_day = BusinessDay.get_current()
    if not current_day:
        messages.warning(request, "দোকানের ব্যবসা দিন এখনও শুরু হয়নি। বিলিং শুরু করার আগে দিন শুরু (Open Day) করুন।")
        return redirect('home')

    return render(request, 'pos/billing.html')

@login_required
def search_product_api(request):
    """
    Fast JSON API to find product by code or model name.
    Returns product info and list of variants with current stock.
    """
    query = request.GET.get('query', '').strip()
    if not query:
        return JsonResponse({'success': False, 'error': 'Query required'})

    # Try exact code first, then icontains
    product = ProductModel.objects.filter(code__iexact=query, is_active=True).first()
    if not product:
        product = ProductModel.objects.filter(code__icontains=query, is_active=True).first()

    if not product:
        return JsonResponse({'success': False, 'error': 'Product not found'})

    variants = product.variants.filter(is_active=True).order_by('size', 'colour')
    var_list = []
    for v in variants:
        var_list.append({
            'id': v.id,
            'size': v.size,
            'colour': v.colour,
            'sku': v.sku,
            'current_stock': v.current_stock,
            'standard_selling_price': str(v.standard_selling_price),
        })

    return JsonResponse({
        'success': True,
        'product': {
            'id': product.id,
            'code': product.code,
            'name': product.name,
            'brand': product.brand,
            'category': product.category,
        },
        'variants': var_list
    })

@login_required
def create_sale_api(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST method required'})

    current_day = BusinessDay.get_current()
    if not current_day:
        return JsonResponse({'success': False, 'error': 'No active business day is currently open.'})

    try:
        data = json.loads(request.body)
        items = data.get('items', [])
        if not items:
            return JsonResponse({'success': False, 'error': 'Cart is empty.'})

        manual_final_total = data.get('manual_final_total')
        payment_method = data.get('payment_method', 'CASH')
        amount_paid = data.get('amount_paid', 0)
        customer_name = data.get('customer_name', '')
        customer_phone = data.get('customer_phone', '')

        sale = BillingService.create_invoice(
            business_day=current_day,
            items=items,
            customer_name=customer_name,
            customer_phone=customer_phone,
            manual_final_total=manual_final_total,
            payment_method=payment_method,
            amount_paid=amount_paid,
            user=request.user
        )

        return JsonResponse({
            'success': True,
            'sale_id': sale.id,
            'invoice_no': sale.invoice_no,
            'final_total': str(sale.final_total),
            'amount_paid': str(sale.amount_paid),
            'balance_due': str(sale.balance_due),
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})

@login_required
def receipt_view(request, sale_id):
    sale = get_object_or_404(Sale, id=sale_id)
    auto_print = request.GET.get('auto_print') == 'true'
    return render(request, 'pos/receipt.html', {
        'sale': sale,
        'auto_print': auto_print,
    })

@login_required
def invoices_list_view(request):
    sales = Sale.objects.all().order_by('-created_at')

    q = request.GET.get('q', '').strip()
    if q:
        sales = sales.filter(invoice_no__icontains=q) | sales.filter(customer_phone__icontains=q) | sales.filter(customer_name__icontains=q)

    start_date = request.GET.get('start_date')
    if start_date:
        sales = sales.filter(created_at__date__gte=start_date)

    end_date = request.GET.get('end_date')
    if end_date:
        sales = sales.filter(created_at__date__lte=end_date)

    sales = sales[:100]

    return render(request, 'pos/invoices_list.html', {
        'sales': sales,
        'query': q,
        'start_date': start_date,
        'end_date': end_date,
    })

@login_required
def collect_due_view(request):
    if request.method == 'POST':
        sale_id = request.POST.get('sale_id')
        amount = request.POST.get('amount')
        payment_method = request.POST.get('payment_method', 'CASH')

        try:
            payment = BillingService.record_due_collection(
                sale_id=sale_id,
                amount=amount,
                payment_method=payment_method,
                user=request.user
            )
            messages.success(request, f"ইনভয়েস {payment.sale.invoice_no} এর জন্য ৳ {payment.amount} সফলভাবে জমা নেওয়া হয়েছে। অবশিষ্ট বাকি: ৳ {payment.sale.balance_due}")
        except Exception as e:
            messages.error(request, f"বাকি টাকা জমা নিতে ত্রুটি: {str(e)}")

    return redirect('invoices_list')

@login_required
def cancel_sale_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন ইনভয়েস বাতিল করতে পারেন।")
        return redirect('invoices_list')

    if request.method == 'POST':
        sale_id = request.POST.get('sale_id')
        reason = request.POST.get('reason', '').strip()

        try:
            sale = BillingService.cancel_invoice(sale_id, reason=reason, user=request.user)
            messages.success(request, f"ইনভয়েস {sale.invoice_no} বাতিল করা হয়েছে এবং বিক্রীত জুতা পুনরায় স্টকে যোগ হয়েছে।")
        except Exception as e:
            messages.error(request, f"ইনভয়েস বাতিল করতে ব্যর্থ: {str(e)}")

    return redirect('invoices_list')
