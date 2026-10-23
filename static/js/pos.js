/**
 * Lotus Footwear POS - Staff Billing Engine
 * Handles fast product search, dynamic size/colour variant matching,
 * live calculations, manual total adjustments, and 58mm thermal printing.
 */

document.addEventListener('DOMContentLoaded', function () {
    const productSearchInput = document.getElementById('pos-product-search');
    const searchBtn = document.getElementById('pos-search-btn');
    const searchResultsBox = document.getElementById('pos-search-results');

    const sizeSelect = document.getElementById('pos-size-select');
    const colourSelect = document.getElementById('pos-colour-select');
    const stockBadge = document.getElementById('pos-stock-badge');

    const qtyInput = document.getElementById('pos-qty-input');
    const qtyMinusBtn = document.getElementById('pos-qty-minus');
    const qtyPlusBtn = document.getElementById('pos-qty-plus');

    const priceInput = document.getElementById('pos-price-input');
    const discountInput = document.getElementById('pos-discount-input');
    const lineTotalPreview = document.getElementById('pos-line-total-preview');
    const addItemBtn = document.getElementById('pos-add-item-btn');

    const cartTableBody = document.getElementById('pos-cart-tbody');
    const cartSubtotalEl = document.getElementById('pos-subtotal-val');
    const cartDiscountEl = document.getElementById('pos-discount-val');
    const cartCalculatedTotalEl = document.getElementById('pos-calc-total-val');
    const manualTotalInput = document.getElementById('pos-manual-total-input');

    const paymentMethodSelect = document.getElementById('pos-payment-method');
    const amountPaidInput = document.getElementById('pos-amount-paid-input');
    const changeGivenEl = document.getElementById('pos-change-val');
    const balanceDueEl = document.getElementById('pos-due-val');

    const customerNameInput = document.getElementById('pos-cust-name');
    const customerPhoneInput = document.getElementById('pos-cust-phone');

    const submitInvoiceBtn = document.getElementById('pos-submit-invoice-btn');

    let currentProduct = null;
    let currentVariants = [];
    let selectedVariant = null;
    let cart = [];

    // Keyboard Shortcuts
    document.addEventListener('keydown', function(e) {
        if (e.key === 'F2') {
            e.preventDefault();
            productSearchInput.focus();
            productSearchInput.select();
        } else if (e.key === 'F4') {
            e.preventDefault();
            amountPaidInput.focus();
            amountPaidInput.select();
        }
    });

    // 1. Product Search
    function performProductSearch() {
        const query = productSearchInput.value.trim();
        if (!query) return;

        fetch(`/pos/api/search-product/?query=${encodeURIComponent(query)}`)
            .then(res => res.json())
            .then(data => {
                if (data.success && data.product) {
                    currentProduct = data.product;
                    currentVariants = data.variants || [];
                    populateSizeSelector();
                    searchResultsBox.innerHTML = `<div class="alert-box alert-success" style="padding: 6px 12px; margin: 4px 0;">✓ <strong>${currentProduct.code}</strong> - ${currentProduct.name} (মোট ভ্যারিয়েন্ট: ${currentVariants.length})</div>`;
                } else {
                    currentProduct = null;
                    currentVariants = [];
                    clearVariantSelectors();
                    searchResultsBox.innerHTML = `<div class="alert-box alert-error" style="padding: 6px 12px; margin: 4px 0;">✗ এই কোডের কোনো জুতা পাওয়া যায়নি (${query})</div>`;
                }
            })
            .catch(err => {
                console.error(err);
                searchResultsBox.innerHTML = `<div class="alert-box alert-error">অনুসন্ধানে সমস্যা হয়েছে। আবার চেষ্টা করুন।</div>`;
            });
    }

    if (searchBtn) searchBtn.addEventListener('click', performProductSearch);
    if (productSearchInput) {
        productSearchInput.addEventListener('keydown', function (e) {
            if (e.key === 'Enter') {
                e.preventDefault();
                performProductSearch();
            }
        });
    }

    // 2. Dynamic Size Selection
    function populateSizeSelector() {
        sizeSelect.innerHTML = '<option value="">-- সাইজ নির্বাচন করুন --</option>';
        colourSelect.innerHTML = '<option value="">-- আগে সাইজ নির্বাচন করুন --</option>';
        colourSelect.disabled = true;
        stockBadge.innerHTML = '';
        selectedVariant = null;

        // Get unique sizes from available variants
        const sizes = [...new Set(currentVariants.map(v => v.size))];
        sizes.forEach(sz => {
            const opt = document.createElement('option');
            opt.value = sz;
            // Count total stock for this size
            const sizeStock = currentVariants.filter(v => v.size === sz).reduce((acc, v) => acc + v.current_stock, 0);
            opt.textContent = `Size ${sz} (${sizeStock > 0 ? sizeStock + ' জোড়া' : 'স্টক শেষ'})`;
            if (sizeStock <= 0) opt.style.color = '#94a3b8';
            sizeSelect.appendChild(opt);
        });

        sizeSelect.disabled = false;
        sizeSelect.focus();
    }

    if (sizeSelect) {
        sizeSelect.addEventListener('change', function () {
            const chosenSize = sizeSelect.value;
            if (!chosenSize) {
                colourSelect.innerHTML = '<option value="">-- আগে সাইজ নির্বাচন করুন --</option>';
                colourSelect.disabled = true;
                stockBadge.innerHTML = '';
                selectedVariant = null;
                return;
            }

            // Filter colours for chosen size
            const matching = currentVariants.filter(v => v.size === chosenSize);
            colourSelect.innerHTML = '<option value="">-- কালার নির্বাচন করুন --</option>';
            matching.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v.id;
                opt.textContent = `${v.colour} (স্টক: ${v.current_stock})`;
                if (v.current_stock <= 0) {
                    opt.disabled = true;
                    opt.textContent += ' [স্টক শেষ]';
                }
                colourSelect.appendChild(opt);
            });
            colourSelect.disabled = false;
            colourSelect.focus();
        });
    }

    // 3. Dynamic Colour Selection
    if (colourSelect) {
        colourSelect.addEventListener('change', function () {
            const variantId = parseInt(colourSelect.value);
            if (!variantId) {
                selectedVariant = null;
                stockBadge.innerHTML = '';
                return;
            }

            selectedVariant = currentVariants.find(v => v.id === variantId);
            if (selectedVariant) {
                stockBadge.innerHTML = `<span class="day-badge ${selectedVariant.current_stock > 0 ? 'day-open' : 'day-closed'}">মজুদ স্টক: ${selectedVariant.current_stock} জোড়া</span>`;
                priceInput.value = parseFloat(selectedVariant.standard_selling_price || 0).toFixed(2);
                discountInput.value = '0';
                qtyInput.value = '1';
                qtyInput.max = selectedVariant.current_stock;
                updateLineTotalPreview();
            }
        });
    }

    // 4. Quantity Controls: [ - ] 1 [ + ]
    if (qtyMinusBtn) {
        qtyMinusBtn.addEventListener('click', function () {
            let val = parseInt(qtyInput.value) || 1;
            if (val > 1) {
                qtyInput.value = val - 1;
                updateLineTotalPreview();
            }
        });
    }

    if (qtyPlusBtn) {
        qtyPlusBtn.addEventListener('click', function () {
            let val = parseInt(qtyInput.value) || 1;
            const max = selectedVariant ? selectedVariant.current_stock : 9999;
            if (val < max) {
                qtyInput.value = val + 1;
                updateLineTotalPreview();
            } else {
                alert(`সর্বোচ্চ বিদ্যমান স্টক ${max} জোড়া। এর বেশি বিক্রি করা সম্ভব নয়।`);
            }
        });
    }

    if (qtyInput) {
        qtyInput.addEventListener('input', function () {
            let val = parseInt(qtyInput.value) || 1;
            if (val < 1) qtyInput.value = 1;
            if (selectedVariant && val > selectedVariant.current_stock) {
                alert(`সর্বোচ্চ বিদ্যমান স্টক ${selectedVariant.current_stock} জোড়া।`);
                qtyInput.value = selectedVariant.current_stock;
            }
            updateLineTotalPreview();
        });
    }

    // 5. Price & Discount calculation
    function updateLineTotalPreview() {
        const qty = parseInt(qtyInput.value) || 1;
        const price = parseFloat(priceInput.value) || 0;
        const discPct = parseFloat(discountInput.value) || 0;

        const subtotal = qty * price;
        const discAmt = subtotal * (discPct / 100);
        const total = subtotal - discAmt;

        if (lineTotalPreview) {
            lineTotalPreview.textContent = `মোট: ৳ ${total.toFixed(2)}`;
        }
    }

    if (priceInput) priceInput.addEventListener('input', updateLineTotalPreview);
    if (discountInput) discountInput.addEventListener('input', updateLineTotalPreview);

    // 6. Add Item to Cart
    if (addItemBtn) {
        addItemBtn.addEventListener('click', function () {
            if (!selectedVariant) {
                alert('অনুগ্রহ করে জুতার সাইজ এবং কালার নির্বাচন করুন।');
                return;
            }

            const qty = parseInt(qtyInput.value) || 1;
            const price = parseFloat(priceInput.value) || 0;
            const discPct = parseFloat(discountInput.value) || 0;

            if (qty <= 0) {
                alert('পরিমাণ অবশ্যই কমপক্ষে ১ জোড়া হতে হবে।');
                return;
            }
            if (qty > selectedVariant.current_stock) {
                alert(`দুঃখিত, এই জুতার পর্যাপ্ত স্টক নেই (বিদ্যমান: ${selectedVariant.current_stock})।`);
                return;
            }

            // Check if already in cart
            const existingIndex = cart.findIndex(item => item.variant_id === selectedVariant.id);
            if (existingIndex > -1) {
                const newQty = cart[existingIndex].quantity + qty;
                if (newQty > selectedVariant.current_stock) {
                    alert(`কার্টে ইতোমধ্যে ${cart[existingIndex].quantity} জোড়া আছে। অতিরিক্ত ${qty} যোগ করলে মোট বিদ্যমান স্টক (${selectedVariant.current_stock}) অতিক্রম করবে।`);
                    return;
                }
                cart[existingIndex].quantity = newQty;
                cart[existingIndex].unit_price = price;
                cart[existingIndex].discount_percent = discPct;
            } else {
                cart.push({
                    variant_id: selectedVariant.id,
                    product_code: currentProduct.code,
                    product_name: currentProduct.name,
                    size: selectedVariant.size,
                    colour: selectedVariant.colour,
                    sku: selectedVariant.sku,
                    quantity: qty,
                    unit_price: price,
                    discount_percent: discPct,
                });
            }

            renderCart();
            clearVariantSelectors();
            productSearchInput.value = '';
            searchResultsBox.innerHTML = '';
            productSearchInput.focus();
        });
    }

    function clearVariantSelectors() {
        sizeSelect.innerHTML = '<option value="">-- সাইজ নির্বাচন করুন --</option>';
        colourSelect.innerHTML = '<option value="">-- কালার নির্বাচন করুন --</option>';
        sizeSelect.disabled = true;
        colourSelect.disabled = true;
        stockBadge.innerHTML = '';
        selectedVariant = null;
        priceInput.value = '0.00';
        discountInput.value = '0';
        qtyInput.value = '1';
        if (lineTotalPreview) lineTotalPreview.textContent = 'মোট: ৳ 0.00';
    }

    // 7. Render Cart and Update Summary
    function renderCart() {
        cartTableBody.innerHTML = '';
        let subtotal = 0;
        let totalDiscount = 0;

        cart.forEach((item, index) => {
            const lineSub = item.quantity * item.unit_price;
            const lineDisc = lineSub * (item.discount_percent / 100);
            const lineTotal = lineSub - lineDisc;

            subtotal += lineSub;
            totalDiscount += lineDisc;

            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td><strong>${item.product_code}</strong> - ${item.product_name}</td>
                <td><span class="day-badge day-open">${item.size}</span></td>
                <td>${item.colour}</td>
                <td>${item.quantity} জোড়া</td>
                <td>৳ ${item.unit_price.toFixed(2)}</td>
                <td>${item.discount_percent}%</td>
                <td><strong>৳ ${lineTotal.toFixed(2)}</strong></td>
                <td><button type="button" class="btn btn-danger btn-sm" data-idx="${index}" style="padding: 2px 8px; font-size: 0.8rem;">মুছুন</button></td>
            `;
            cartTableBody.appendChild(tr);
        });

        const calculatedTotal = subtotal - totalDiscount;
        cartSubtotalEl.textContent = `৳ ${subtotal.toFixed(2)}`;
        cartDiscountEl.textContent = `৳ ${totalDiscount.toFixed(2)}`;
        cartCalculatedTotalEl.textContent = `৳ ${calculatedTotal.toFixed(2)}`;

        // If manual total is not actively customized, default it to calculated total
        if (!manualTotalInput.dataset.userModified) {
            manualTotalInput.value = calculatedTotal.toFixed(2);
        }

        updatePaymentCalculations();

        // Wire remove buttons
        document.querySelectorAll('#pos-cart-tbody button').forEach(btn => {
            btn.addEventListener('click', function () {
                const idx = parseInt(this.dataset.idx);
                cart.splice(idx, 1);
                renderCart();
            });
        });
    }

    if (manualTotalInput) {
        manualTotalInput.addEventListener('input', function () {
            manualTotalInput.dataset.userModified = 'true';
            updatePaymentCalculations();
        });
    }

    function updatePaymentCalculations() {
        const finalTotal = parseFloat(manualTotalInput.value) || 0;
        const paid = parseFloat(amountPaidInput.value) || 0;

        if (paid >= finalTotal) {
            changeGivenEl.textContent = `৳ ${(paid - finalTotal).toFixed(2)}`;
            balanceDueEl.textContent = '৳ 0.00';
            balanceDueEl.style.color = '#15803d';
        } else {
            changeGivenEl.textContent = '৳ 0.00';
            balanceDueEl.textContent = `৳ ${(finalTotal - paid).toFixed(2)}`;
            balanceDueEl.style.color = '#b91c1c';
        }
    }

    if (amountPaidInput) {
        amountPaidInput.addEventListener('input', updatePaymentCalculations);
    }

    // Split Payment Toggle & Sync
    const splitContainer = document.getElementById('pos-split-payment-container');
    const splitCashInput = document.getElementById('pos-split-cash-input');
    const splitDigitalMethodSelect = document.getElementById('pos-split-digital-method');
    const splitDigitalInput = document.getElementById('pos-split-digital-input');

    function syncSplitPaymentTotal() {
        if (paymentMethodSelect.value === 'SPLIT') {
            const cAmt = parseFloat(splitCashInput.value) || 0;
            const dAmt = parseFloat(splitDigitalInput.value) || 0;
            amountPaidInput.value = (cAmt + dAmt).toFixed(2);
            updatePaymentCalculations();
        }
    }

    if (paymentMethodSelect) {
        paymentMethodSelect.addEventListener('change', function () {
            if (paymentMethodSelect.value === 'SPLIT') {
                if (splitContainer) splitContainer.style.display = 'block';
                syncSplitPaymentTotal();
            } else {
                if (splitContainer) splitContainer.style.display = 'none';
                updatePaymentCalculations();
            }
        });
    }

    if (splitCashInput) splitCashInput.addEventListener('input', syncSplitPaymentTotal);
    if (splitDigitalInput) splitDigitalInput.addEventListener('input', syncSplitPaymentTotal);

    // 8. Submit Invoice to Backend
    if (submitInvoiceBtn) {
        submitInvoiceBtn.addEventListener('click', function () {
            if (cart.length === 0) {
                alert('কার্ট ফাঁকা! অনুগ্রহ করে কমপক্ষে একটি পণ্য যোগ করুন।');
                return;
            }

            const finalTotal = parseFloat(manualTotalInput.value);
            if (isNaN(finalTotal) || finalTotal < 0) {
                alert('সঠিক চূড়ান্ত বিলের পরিমাণ লিখুন।');
                return;
            }

            const amountPaid = parseFloat(amountPaidInput.value) || 0;
            const paymentMethod = paymentMethodSelect.value;
            const custName = customerNameInput.value.trim();
            const custPhone = customerPhoneInput.value.trim();

            const payload = {
                items: cart.map(item => ({
                    variant_id: item.variant_id,
                    quantity: item.quantity,
                    unit_price: item.unit_price,
                    discount_percent: item.discount_percent
                })),
                manual_final_total: finalTotal,
                payment_method: paymentMethod,
                amount_paid: amountPaid,
                customer_name: custName,
                customer_phone: custPhone,
            };

            if (paymentMethod === 'SPLIT') {
                const cAmt = parseFloat(splitCashInput.value) || 0;
                const dMethod = splitDigitalMethodSelect ? splitDigitalMethodSelect.value : 'BKASH';
                const dAmt = parseFloat(splitDigitalInput.value) || 0;
                payload.split_payments = [];
                if (cAmt > 0) payload.split_payments.push({ payment_method: 'CASH', amount: cAmt });
                if (dAmt > 0) payload.split_payments.push({ payment_method: dMethod, amount: dAmt });
            }

            submitInvoiceBtn.disabled = true;
            submitInvoiceBtn.textContent = 'বিল সংরক্ষণ হচ্ছে...';

            fetch('/pos/api/create-sale/', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'X-CSRFToken': getCookie('csrftoken')
                },
                body: JSON.stringify(payload)
            })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    // Open print receipt modal/view
                    window.location.href = `/pos/receipt/${data.sale_id}/?auto_print=true`;
                } else {
                    alert('বিল সংরক্ষণে ত্রুটি: ' + (data.error || 'অজানা সমস্যা'));
                    submitInvoiceBtn.disabled = false;
                    submitInvoiceBtn.textContent = '✓ বিল সম্পন্ন ও প্রিন্ট করুন';
                }
            })
            .catch(err => {
                console.error(err);
                alert('সার্ভারের সাথে যোগাযোগে ত্রুটি হয়েছে।');
                submitInvoiceBtn.disabled = false;
                submitInvoiceBtn.textContent = '✓ বিল সম্পন্ন ও প্রিন্ট করুন';
            });
        });
    }

    function getCookie(name) {
        let cookieValue = null;
        if (document.cookie && document.cookie !== '') {
            const cookies = document.cookie.split(';');
            for (let i = 0; i < cookies.length; i++) {
                const cookie = cookies[i].trim();
                if (cookie.substring(0, name.length + 1) === (name + '=')) {
                    cookieValue = decodeURIComponent(cookie.substring(name.length + 1));
                    break;
                }
            }
        }
        return cookieValue;
    }
});
