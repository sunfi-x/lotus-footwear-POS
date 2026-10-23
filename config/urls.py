from django.contrib import admin
from django.urls import path
from core.views import (
    home_view, login_view, logout_view,
    open_business_day_view, close_business_day_view,
    shop_settings_view, audit_logs_view
)
from pos.views import (
    pos_screen_view, search_product_api, create_sale_api,
    receipt_view, invoices_list_view, collect_due_view, cancel_sale_view
)
from inventory.views import (
    products_list_view, add_product_view, add_variant_view,
    adjust_stock_view, purchases_list_view, add_purchase_view,
    csv_migration_view, download_csv_template_view,
    create_product_unified_view, get_existing_product_variants_api,
)
from expenses.views import (
    expenses_list_view, add_expense_view,
    salesman_payments_view, add_salesman_view, edit_salesman_view,
    record_salesman_payment_view, reverse_salesman_payment_view,
    individual_salesman_history_view
)
from reports.views import admin_dashboard_view, historical_search_view, profit_report_view
from backup_system.views import backup_center_view, trigger_manual_backup_view, restore_backup_view

urlpatterns = [
    # Core & Auth
    path('', home_view, name='home'),
    path('login/', login_view, name='login'),
    path('logout/', logout_view, name='logout'),
    path('day/open/', open_business_day_view, name='open_business_day'),
    path('day/close/', close_business_day_view, name='close_business_day'),
    path('settings/', shop_settings_view, name='shop_settings'),
    path('audit-logs/', audit_logs_view, name='audit_logs'),

    # POS & Billing
    path('pos/', pos_screen_view, name='pos_screen'),
    path('pos/api/search-product/', search_product_api, name='search_product_api'),
    path('pos/api/create-sale/', create_sale_api, name='create_sale_api'),
    path('pos/receipt/<int:sale_id>/', receipt_view, name='receipt_view'),
    path('invoices/', invoices_list_view, name='invoices_list'),
    path('invoices/collect-due/', collect_due_view, name='collect_due'),
    path('invoices/cancel/', cancel_sale_view, name='cancel_sale'),

    # Inventory
    path('inventory/products/', products_list_view, name='products_list'),
    path('inventory/products/add/', add_product_view, name='add_product'),
    path('inventory/products/create-unified/', create_product_unified_view, name='create_product_unified'),
    path('inventory/api/product-variants/', get_existing_product_variants_api, name='get_existing_product_variants_api'),
    path('inventory/variants/add/', add_variant_view, name='add_variant'),
    path('inventory/adjust-stock/', adjust_stock_view, name='adjust_stock'),
    path('inventory/purchases/', purchases_list_view, name='purchases_list'),
    path('inventory/purchases/add/', add_purchase_view, name='add_purchase'),
    path('inventory/migration/', csv_migration_view, name='csv_migration'),
    path('inventory/migration/template/', download_csv_template_view, name='download_csv_template'),

    # Expenses & Salesman Payments
    path('expenses/', expenses_list_view, name='expenses_list'),
    path('expenses/add/', add_expense_view, name='add_expense'),
    path('salesman-payments/', salesman_payments_view, name='salesman_payments'),
    path('salesman-payments/add-salesman/', add_salesman_view, name='add_salesman'),
    path('salesman-payments/edit-salesman/<str:salesman_id>/', edit_salesman_view, name='edit_salesman'),
    path('salesman-payments/record-payment/', record_salesman_payment_view, name='record_salesman_payment'),
    path('salesman-payments/reverse-payment/<str:payment_id>/', reverse_salesman_payment_view, name='reverse_salesman_payment'),
    path('salesman-payments/profile/<str:salesman_id>/', individual_salesman_history_view, name='individual_salesman_history'),

    # Reports & Dashboards
    path('admin-dashboard/', admin_dashboard_view, name='admin_dashboard'),
    path('reports/historical-search/', historical_search_view, name='historical_search'),
    path('reports/profit/', profit_report_view, name='reports_profit'),

    # Backup & Recovery
    path('backups/', backup_center_view, name='backup_center'),
    path('backups/create/', trigger_manual_backup_view, name='trigger_manual_backup'),
    path('backups/restore/', restore_backup_view, name='restore_backup_view'),

    # Django Admin (optional)
    path('django-admin/', admin.site.urls),
]
