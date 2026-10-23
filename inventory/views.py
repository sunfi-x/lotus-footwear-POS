import csv
import json
from decimal import Decimal, InvalidOperation
from django.shortcuts import render, redirect, get_object_or_404
from django.http import HttpResponse, JsonResponse
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db import transaction
from django.db.models import Sum, F
from core.models import ApplicationSetting
from .models import ProductModel, ProductVariant, Supplier, Purchase, StockMovement
from .services import InventoryService

@login_required
def products_list_view(request):
    query = request.GET.get('q', '').strip()
    variants_qs = ProductVariant.objects.select_related('product').filter(is_active=True)
    if query:
        variants_qs = (
            variants_qs.filter(product__code__icontains=query)
            | variants_qs.filter(product__name__icontains=query)
            | variants_qs.filter(sku__icontains=query)
        )

    products = ProductModel.objects.filter(is_active=True).order_by('code')

    # --- 5 KPI Summary Cards ---
    all_active_variants = ProductVariant.objects.select_related('product').filter(is_active=True)

    # Separate available pairs by category (Gents, Ladies, Kids)
    # Include case-insensitive matching and fallback mappings if legacy data exists (e.g. Men -> Gents, Women -> Ladies)
    gents_pairs = 0
    ladies_pairs = 0
    kids_pairs = 0
    total_inventory_cost = Decimal('0.00')

    for v in all_active_variants:
        qty = v.current_stock if v.current_stock > 0 else 0
        cat = (v.product.category or '').strip().lower()

        if cat in ['gents', 'men']:
            gents_pairs += qty
        elif cat in ['ladies', 'women']:
            ladies_pairs += qty
        elif cat == 'kids':
            kids_pairs += qty
        else:
            # If any other category exists, count in gents as default
            gents_pairs += qty

        # Calculate INVENTORY VALUE as sum of (Current Available Quantity × Current Weighted Average Cost)
        # Exclude zero or negative quantity variants from valuation
        if v.current_stock > 0 and v.weighted_avg_cost > 0:
            total_inventory_cost += (Decimal(str(v.current_stock)) * v.weighted_avg_cost)

    total_pairs = gents_pairs + ladies_pairs + kids_pairs

    kpi = {
        'total_pairs': total_pairs,
        'gents_pairs': gents_pairs,
        'ladies_pairs': ladies_pairs,
        'kids_pairs': kids_pairs,
        'total_inventory_cost': total_inventory_cost,
    }

    return render(request, 'inventory/products_list.html', {
        'variants': variants_qs[:150],
        'products': products,
        'query': query,
        'kpi': kpi,
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


# Valid size configurations per user requirement
VALID_SIZES_MAP = {
    'Gents': {'40', '41', '42', '43', '44', '45', '46', '47', '48'},
    'Ladies': {'35', '36', '37', '38', '39', '40', '41'},
    'Kids': {
        'A': {'15', '16', '17', '18', '19', '20', '21'},
        'B': {'21', '22', '23', '24', '25', '26', '27'},
        'C': {'26', '27', '28', '29', '30', '31', '32'},
        'D': {'31', '32', '33', '34', '35', '36', '37', '38'},
        'E': {'36', '37', '38', '39', '40'},
    }
}


@login_required
def create_product_unified_view(request):
    """
    Unified view: creates a new shoe model + multiple size/colour variants
    OR adds new variants to an existing model — all in one atomic transaction.
    POST body is JSON (sent via fetch from the modal).
    """
    if not (request.user.is_superuser or request.user.is_staff):
        return JsonResponse({'success': False, 'error': 'শুধুমাত্র এডমিন এই কাজ করতে পারেন।'}, status=403)

    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        return JsonResponse({'success': False, 'error': 'Invalid JSON payload.'}, status=400)

    operation = data.get('operation', 'new_model')  # 'new_model' or 'add_to_existing'
    variants_data = data.get('variants', [])

    if not variants_data:
        return JsonResponse({'success': False, 'error': 'কমপক্ষে একটি সাইজ/কালার ভ্যারিয়েন্ট প্রয়োজন।'}, status=400)

    errors = []

    try:
        with transaction.atomic():
            # Get default low stock threshold from ApplicationSetting
            app_settings = ApplicationSetting.get_settings()
            default_low_stock = app_settings.low_stock_threshold or 5

            # --- Resolve product model ---
            code = (data.get('code') or '').strip().upper()
            if not code:
                return JsonResponse({'success': False, 'errors': ['প্রোডাক্ট কোড (Product Code) আবশ্যক।']}, status=400)

            # Auto-detect if existing product exists by code
            existing_prod = ProductModel.objects.filter(code__iexact=code).first()

            if operation == 'add_to_existing':
                product_id = data.get('existing_product_id')
                if product_id:
                    try:
                        product = ProductModel.objects.get(id=int(product_id), is_active=True)
                    except (ProductModel.DoesNotExist, ValueError):
                        return JsonResponse({'success': False, 'errors': ['নির্বাচিত মডেল পাওয়া যায়নি।']}, status=404)
                elif existing_prod:
                    product = existing_prod
                else:
                    return JsonResponse({'success': False, 'errors': [f"কোড '{code}' এর কোনো বিদ্যমান মডেল পাওয়া যায়নি।"]}, status=404)
            else:
                # new_model mode, but check if code already exists
                if existing_prod:
                    # User entered an existing code in new_model mode: reuse existing model without creating duplicate
                    product = existing_prod
                else:
                    name = (data.get('name') or '').strip()
                    category = (data.get('category') or 'Gents').strip()
                    brand = (data.get('brand') or 'Lotus').strip()

                    if not name:
                        return JsonResponse({'success': False, 'errors': ['মডেলের নাম (Model Name) আবশ্যক।']}, status=400)

                    # Validate category must be Gents, Ladies, or Kids
                    if category not in ['Gents', 'Ladies', 'Kids']:
                        return JsonResponse({'success': False, 'errors': ['ক্যাটাগরি অবশ্যই Gents, Ladies, অথবা Kids হতে হবে।']}, status=400)

                    product = ProductModel.objects.create(
                        code=code, name=name, category=category, brand=brand
                    )

            product_category = product.category or 'Gents'

            # --- Process each variant row ---
            created_variants = []
            seen_in_payload = set()

            for idx, row in enumerate(variants_data, start=1):
                raw_size = (row.get('size') or '').strip()
                kids_group = (row.get('kids_group') or '').strip().upper()
                colour = (row.get('colour') or '').strip()
                opening_qty_str = str(row.get('opening_qty', '0')).strip()
                cost_price_str = str(row.get('cost_price', '0')).strip()
                selling_price_str = str(row.get('selling_price', '0')).strip()

                row_errors = []
                if not raw_size:
                    row_errors.append(f'ভ্যারিয়েন্ট {idx}: সাইজ নির্বাচন আবশ্যক।')
                if not colour:
                    row_errors.append(f'ভ্যারিয়েন্ট {idx}: কালার আবশ্যক।')

                # Validate size against category rules
                final_size = raw_size
                if product_category == 'Gents':
                    if raw_size not in VALID_SIZES_MAP['Gents']:
                        row_errors.append(f'ভ্যারিয়েন্ট {idx}: Gents ক্যাটাগরিতে সাইজ {raw_size} বৈধ নয় (অনুমোদিত: 40-48)।')
                elif product_category == 'Ladies':
                    if raw_size not in VALID_SIZES_MAP['Ladies']:
                        row_errors.append(f'ভ্যারিয়েন্ট {idx}: Ladies ক্যাটাগরিতে সাইজ {raw_size} বৈধ নয় (অনুমোদিত: 35-41)।')
                elif product_category == 'Kids':
                    # Must have a valid kids group A-E
                    # And raw_size must be in that group
                    # If size string already looks like "Group A / Size 21" or "A-21", parse it
                    if not kids_group:
                        if '-' in raw_size:
                            parts = raw_size.split('-', 1)
                            if parts[0] in VALID_SIZES_MAP['Kids']:
                                kids_group = parts[0]
                                raw_size = parts[1]
                        elif ' ' in raw_size:
                            parts = raw_size.split()
                            if len(parts) >= 2 and parts[0] in VALID_SIZES_MAP['Kids']:
                                kids_group = parts[0]
                                raw_size = parts[-1]

                    if not kids_group or kids_group not in VALID_SIZES_MAP['Kids']:
                        row_errors.append(f'ভ্যারিয়েন্ট {idx}: Kids ক্যাটাগরির জন্য সাইজ গ্রুপ (A, B, C, D, E) আবশ্যক।')
                    elif raw_size not in VALID_SIZES_MAP['Kids'].get(kids_group, set()):
                        row_errors.append(f'ভ্যারিয়েন্ট {idx}: Kids গ্রুপ {kids_group} তে সাইজ {raw_size} অন্তর্ভুক্ত নয়।')
                    else:
                        # Distinguishable size representation for kids
                        final_size = f"{kids_group}-{raw_size}"

                try:
                    opening_qty = int(opening_qty_str)
                    if opening_qty < 0:
                        row_errors.append(f'ভ্যারিয়েন্ট {idx}: প্রারম্ভিক স্টক ঋণাত্মক হতে পারে না।')
                except ValueError:
                    row_errors.append(f'ভ্যারিয়েন্ট {idx}: প্রারম্ভিক স্টক সংখ্যা হওয়া আবশ্যক।')
                    opening_qty = 0

                try:
                    cost_price = Decimal(cost_price_str).quantize(Decimal('0.01'))
                    if cost_price < 0:
                        row_errors.append(f'ভ্যারিয়েন্ট {idx}: ক্রয়মূল্য ঋণাত্মক হতে পারে না।')
                    if opening_qty > 0 and cost_price <= 0:
                        row_errors.append(f'ভ্যারিয়েন্ট {idx}: স্টক থাকলে ক্রয়মূল্য অবশ্যই ০ এর বেশি হতে হবে।')
                except (InvalidOperation, ValueError):
                    row_errors.append(f'ভ্যারিয়েন্ট {idx}: ক্রয়মূল্য বৈধ সংখ্যা হওয়া আবশ্যক।')
                    cost_price = Decimal('0.00')

                try:
                    selling_price = Decimal(selling_price_str).quantize(Decimal('0.01'))
                    if selling_price < 0:
                        row_errors.append(f'ভ্যারিয়েন্ট {idx}: বিক্রয়মূল্য ঋণাত্মক হতে পারে না।')
                except (InvalidOperation, ValueError):
                    row_errors.append(f'ভ্যারিয়েন্ট {idx}: বিক্রয়মূল্য বৈধ সংখ্যা হওয়া আবশ্যক।')
                    selling_price = Decimal('0.00')

                # Check duplicate within this submission payload
                combo_key = (final_size.upper(), colour.upper())
                if combo_key in seen_in_payload:
                    row_errors.append(f'ভ্যারিয়েন্ট {idx}: একই সাইজ ({final_size}) ও কালার ({colour}) একাধিকবার দেওয়া হয়েছে।')
                else:
                    seen_in_payload.add(combo_key)

                if row_errors:
                    errors.extend(row_errors)
                    continue

                # Check duplicate in database for this model
                if ProductVariant.objects.filter(
                    product=product, size__iexact=final_size, colour__iexact=colour
                ).exists():
                    errors.append(
                        f'ভ্যারিয়েন্ট {idx}: {product.code} মডেলে সাইজ {final_size} ও কালার {colour} ইতোমধ্যে বিদ্যমান।'
                    )
                    continue

                # Auto-generate unique SKU
                clean_code = str(product.code).strip().replace(' ', '-')
                clean_size = str(final_size).strip().replace(' ', '-')
                clean_colour = str(colour).strip().replace(' ', '-')
                generated_sku = f'{clean_code}-{clean_size}-{clean_colour}'.upper()

                if ProductVariant.objects.filter(sku__iexact=generated_sku).exists():
                    errors.append(f'ভ্যারিয়েন্ট {idx}: SKU "{generated_sku}" ইতোমধ্যে ডাটাবেজে বিদ্যমান।')
                    continue

                # Create the variant
                variant = ProductVariant.objects.create(
                    product=product,
                    size=final_size,
                    colour=colour,
                    sku=generated_sku,
                    current_stock=0,
                    weighted_avg_cost=cost_price if opening_qty > 0 else Decimal('0.00'),
                    standard_selling_price=selling_price,
                    low_stock_threshold=default_low_stock,
                )

                # Record opening stock movement if qty > 0
                if opening_qty > 0:
                    InventoryService.record_stock_movement(
                        variant=variant,
                        movement_type='OPENING',
                        quantity_delta=opening_qty,
                        unit_cost=cost_price,
                        reference_type='UnifiedProductForm',
                        reference_id=f'INIT-{product.code}',
                        notes='Opening stock via unified product form',
                        user=request.user,
                    )

                created_variants.append({
                    'sku': variant.sku,
                    'size': final_size,
                    'colour': colour,
                    'opening_qty': opening_qty,
                })

            if errors:
                # Rollback the entire transaction
                raise ValueError('validation_errors')

    except ValueError as exc:
        if str(exc) == 'validation_errors':
            return JsonResponse({'success': False, 'errors': errors}, status=400)
        return JsonResponse({'success': False, 'errors': [str(exc)]}, status=400)
    except Exception as exc:
        return JsonResponse({'success': False, 'errors': [f'সংরক্ষণে সমস্যা হয়েছে: {str(exc)}']}, status=500)

    return JsonResponse({
        'success': True,
        'message': f"'{product.code} - {product.name}' মডেলে {len(created_variants)} টি ভ্যারিয়েন্ট সফলভাবে সংরক্ষিত হয়েছে।",
        'created_variants': created_variants,
    })


@login_required
def get_existing_product_variants_api(request):
    """Returns JSON of existing variants for a given product by id or code (used by the unified modal)."""
    product_id = request.GET.get('product_id')
    product_code = request.GET.get('code')
    product = None

    if product_id:
        try:
            product = ProductModel.objects.get(id=int(product_id), is_active=True)
        except (ProductModel.DoesNotExist, ValueError):
            product = None
    elif product_code:
        product = ProductModel.objects.filter(code__iexact=product_code.strip(), is_active=True).first()

    if not product:
        return JsonResponse({'found': False, 'variants': []})

    variants = list(
        ProductVariant.objects.filter(product=product, is_active=True)
        .values('id', 'size', 'colour', 'sku', 'current_stock', 'standard_selling_price', 'weighted_avg_cost')
    )
    return JsonResponse({
        'found': True,
        'product': {
            'id': product.id,
            'code': product.code,
            'name': product.name,
            'category': product.category,
            'brand': product.brand
        },
        'variants': variants
    })


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
