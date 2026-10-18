import csv
from decimal import Decimal
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Sum
from .models import ProductModel, ProductVariant, Supplier, Purchase, StockMovement
from .services import InventoryService

@login_required
def products_list_view(request):
    query = request.GET.get('q', '').strip()
    variants = ProductVariant.objects.select_related('product').filter(is_active=True)
    if query:
        variants = variants.filter(product__code__icontains=query) | variants.filter(product__name__icontains=query) | variants.filter(sku__icontains=query)

    products = ProductModel.objects.filter(is_active=True).order_by('code')

    return render(request, 'inventory/products_list.html', {
        'variants': variants[:150],
        'products': products,
        'query': query,
    })

@login_required
def add_product_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন নতুন জুতার মডেল যোগ করতে পারেন।")
        return redirect('products_list')

    if request.method == 'POST':
        code = request.POST.get('code', '').strip()
        name = request.POST.get('name', '').strip()
        category = request.POST.get('category', 'General').strip()
        brand = request.POST.get('brand', 'Lotus').strip()

        if ProductModel.objects.filter(code__iexact=code).exists():
            messages.error(request, f"জুতার কোড '{code}' ইতোমধ্যে বিদ্যমান!")
        else:
            prod = ProductModel.objects.create(code=code, name=name, category=category, brand=brand)
            messages.success(request, f"নতুন জুতার মডেল '{prod.code} - {prod.name}' সফলভাবে যোগ হয়েছে।")

    return redirect('products_list')

@login_required
def add_variant_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন নতুন ভ্যারিয়েন্ট যোগ করতে পারেন।")
        return redirect('products_list')

    if request.method == 'POST':
        product_id = request.POST.get('product_id')
        size = request.POST.get('size', '').strip()
        colour = request.POST.get('colour', '').strip()
        selling_price = request.POST.get('selling_price', '0.00')

        product = get_object_or_404(ProductModel, id=product_id)
        if ProductVariant.objects.filter(product=product, size__iexact=size, colour__iexact=colour).exists():
            messages.error(request, f"এই মডেলের সাইজ {size} এবং কালার {colour} ইতোমধ্যে রয়েছে!")
        else:
            var = ProductVariant.objects.create(
                product=product,
                size=size,
                colour=colour,
                standard_selling_price=Decimal(selling_price)
            )
            messages.success(request, f"নতুন ভ্যারিয়েন্ট {var.sku} সফলভাবে তৈরি হয়েছে।")

    return redirect('products_list')

@login_required
def adjust_stock_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন স্টক সমন্বয় করতে পারেন।")
        return redirect('products_list')

    if request.method == 'POST':
        variant_id = request.POST.get('variant_id')
        new_stock = request.POST.get('new_stock')
        reason = request.POST.get('reason', '').strip()

        variant = get_object_or_404(ProductVariant, id=variant_id)
        try:
            adj = InventoryService.record_stock_adjustment(
                variant=variant,
                new_stock=int(new_stock),
                reason=reason,
                user=request.user
            )
            if adj:
                messages.success(request, f"{variant.sku} এর স্টক সফলভাবে সমন্বয় করা হয়েছে ({adj.old_stock} -> {adj.new_stock})।")
            else:
                messages.info(request, "স্টকে কোনো পরিবর্তন ঘটেনি।")
        except Exception as e:
            messages.error(request, f"স্টক সমন্বয়ে সমস্যা: {str(e)}")

    return redirect('products_list')

@login_required
def purchases_list_view(request):
    purchases = Purchase.objects.select_related('supplier').all().order_by('-purchase_date', '-id')
    suppliers = Supplier.objects.all()
    variants = ProductVariant.objects.select_related('product').filter(is_active=True).order_by('product__code')

    return render(request, 'inventory/purchases_list.html', {
        'purchases': purchases[:50],
        'suppliers': suppliers,
        'variants': variants,
    })

@login_required
def add_purchase_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন নতুন চালান এন্ট্রি করতে পারেন।")
        return redirect('purchases_list')

    if request.method == 'POST':
        supplier_id = request.POST.get('supplier_id')
        purchase_date = request.POST.get('purchase_date')
        invoice_no = request.POST.get('invoice_no', '').strip()
        variant_id = request.POST.get('variant_id')
        quantity = request.POST.get('quantity')
        unit_cost = request.POST.get('unit_cost')
        notes = request.POST.get('notes', '').strip()

        supplier = get_object_or_404(Supplier, id=supplier_id)
        items = [{
            'variant_id': variant_id,
            'quantity': int(quantity),
            'unit_cost': Decimal(unit_cost)
        }]

        try:
            purchase = InventoryService.record_purchase(
                supplier=supplier,
                invoice_no=invoice_no,
                purchase_date=purchase_date,
                items=items,
                paid_amount=Decimal('0.00'),
                notes=notes,
                user=request.user
            )
            messages.success(request, f"চালান #{purchase.id} সফলভাবে সংরক্ষিত হয়েছে এবং গড় ক্রয়মূল্য (WAC) সমন্বয় করা হয়েছে।")
        except Exception as e:
            messages.error(request, f"চালান সংরক্ষণে ব্যর্থ: {str(e)}")

    return redirect('purchases_list')

@login_required
def csv_migration_view(request):
    if not (request.user.is_superuser or request.user.is_staff):
        messages.error(request, "শুধুমাত্র এডমিন প্রারম্ভিক স্টক মাইগ্রেশন করতে পারেন।")
        return redirect('home')

    results = None
    submitted = False
    is_dry_run = True
    raw_csv_text = ''

    if request.method == 'POST':
        submitted = True
        if request.POST.get('commit_data') == 'true':
            # Real Commit
            raw_csv = request.POST.get('cached_csv', '')
            results = InventoryService.process_csv_migration(raw_csv, is_dry_run=False, user=request.user)
            messages.success(request, f"অভিনন্দন! মোট {results['imported_variants']} টি জুতার ভ্যারিয়েন্ট এবং {results['total_quantity']} জোড়া প্রারম্ভিক স্টক সফলভাবে ডাটাবেজে যুক্ত হয়েছে!")
            is_dry_run = False
        elif 'csv_file' in request.FILES:
            csv_file = request.FILES['csv_file']
            file_bytes = csv_file.read()
            is_dry_run = (request.POST.get('is_dry_run') == 'true')
            try:
                raw_csv_text = file_bytes.decode('utf-8-sig')
            except UnicodeDecodeError:
                raw_csv_text = file_bytes.decode('latin-1')

            results = InventoryService.process_csv_migration(file_bytes, is_dry_run=is_dry_run, user=request.user)
            if results['error_rows']:
                messages.error(request, f"ফাইলে {len(results['error_rows'])} টি ত্রুটি শনাক্ত হয়েছে। বিস্তারিত নিচে দেখুন।")
            elif is_dry_run:
                messages.info(request, "ড্রাই-রান প্রিভিউ সফল! কোনো ত্রুটি নেই। নিচের বাটনে ক্লিক করে ফাইনাল ইমপোর্ট সম্পন্ন করতে পারেন।")
            else:
                messages.success(request, f"মোট {results['imported_variants']} টি ভ্যারিয়েন্ট সফলভাবে ইমপোর্ট সম্পন্ন হয়েছে।")

    return render(request, 'inventory/csv_migration.html', {
        'results': results,
        'submitted': submitted,
        'is_dry_run': is_dry_run,
        'raw_csv_text': raw_csv_text,
    })

@login_required
def download_csv_template_view(request):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = 'attachment; filename="lotus_footwear_stock_template.csv"'

    writer = csv.writer(response)
    # Headers
    writer.writerow([
        'product_code', 'product_name', 'category', 'brand',
        'size', 'colour', 'quantity', 'cost_price', 'selling_price'
    ])
    # Example rows
    writer.writerow(['M0001', 'Formal Oxford Leather Shoe', 'Men', 'Lotus', '40', 'Black', '12', '750.00', '1200.00'])
    writer.writerow(['M0001', 'Formal Oxford Leather Shoe', 'Men', 'Lotus', '41', 'Black', '15', '750.00', '1200.00'])
    writer.writerow(['M0001', 'Formal Oxford Leather Shoe', 'Men', 'Lotus', '42', 'Brown', '10', '750.00', '1200.00'])
    writer.writerow(['L1002', 'Casual Loafer Slip-on', 'Men', 'Lotus', '39', 'Tan', '8', '600.00', '950.00'])
    writer.writerow(['W5001', 'Ladies High Heel Sandal', 'Women', 'Lotus', '37', 'Red', '6', '500.00', '850.00'])

    return response
