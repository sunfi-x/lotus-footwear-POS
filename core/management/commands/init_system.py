from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from core.models import ApplicationSetting, AuditLog
from expenses.models import ExpenseCategory
from inventory.models import Supplier

class Command(BaseCommand):
    help = 'Initialize Lotus Footwear POS system with default users, settings, and expense categories'

    def handle(self, *args, **options):
        self.stdout.write(self.style.NOTICE("Initializing Lotus Footwear POS System..."))

        # 1. Admin User
        admin_user, admin_created = User.objects.get_or_create(
            username='admin',
            defaults={
                'email': 'admin@lotusfootwear.local',
                'is_staff': True,
                'is_superuser': True,
                'first_name': 'Owner / Admin'
            }
        )
        if admin_created:
            admin_user.set_password('admin123')
            admin_user.save()
            self.stdout.write(self.style.SUCCESS("[OK] Admin user created (username: 'admin', default password: 'admin123')"))
        else:
            self.stdout.write("[OK] Admin user already exists.")

        # 2. Staff User (Shared Staff Account)
        staff_user, staff_created = User.objects.get_or_create(
            username='staff',
            defaults={
                'email': 'staff@lotusfootwear.local',
                'is_staff': False,
                'is_superuser': False,
                'first_name': 'Sales Staff'
            }
        )
        if staff_created:
            staff_user.set_password('staff123')
            staff_user.save()
            self.stdout.write(self.style.SUCCESS("[OK] Staff user created (username: 'staff', default password: 'staff123')"))
        else:
            self.stdout.write("[OK] Staff user already exists.")

        # 3. Application Settings
        settings = ApplicationSetting.get_settings()
        settings.shop_name = 'LOTUS FOOTWEAR'
        settings.shop_phone = '01700-000000'
        settings.shop_address = 'Shop # 12, Ground Floor, Elephant Road, Dhaka, Bangladesh'
        settings.receipt_header = 'LOTUS FOOTWEAR'
        settings.receipt_footer = 'THANK YOU FOR SHOPPING!\nExchange within 7 days with original cash receipt.'
        settings.low_stock_threshold = 5
        settings.save()
        self.stdout.write(self.style.SUCCESS("[OK] Shop settings initialized."))

        # 4. Standard Expense Categories
        categories = [
            ("Shop Rent (দোকান ভাড়া)", "Monthly shop premises rent"),
            ("Staff Salary (কর্মচারী বেতন)", "Monthly or daily sales staff remuneration"),
            ("Electricity Bill (বিদ্যুৎ বিল)", "Monthly utility & power charges"),
            ("Transport & Logistics (মালামাল পরিবহন)", "Shoe carton transport, courier and carrying expenses"),
            ("Packaging (বক্স ও শপিং ব্যাগ)", "Customer shoe boxes, shopping polythene & paper bags"),
            ("Repairs & Maintenance (মেরামত)", "Shop fitting, electrical, AC, or fixture maintenance"),
            ("Entertainment (আপ্যায়ন ও জলখাবার)", "Tea, snacks, water, and staff refreshments"),
            ("Miscellaneous (বিবিধ খরচ)", "General unexpected day-to-day retail expenses"),
        ]
        count = 0
        for name, desc in categories:
            cat, created = ExpenseCategory.objects.get_or_create(name=name, defaults={'description': desc})
            if created:
                count += 1
        self.stdout.write(self.style.SUCCESS(f"[OK] Added {count} standard expense categories."))

        # 5. Default Supplier
        Supplier.objects.get_or_create(
            name="Lotus Central Wholesale Factory",
            defaults={
                'phone': '01800-000000',
                'address': 'Sadarghat / Siddique Bazar, Dhaka',
                'contact_person': 'Haji Md. Rafiqul Islam'
            }
        )
        self.stdout.write(self.style.SUCCESS("[OK] Default supplier initialized."))

        # 6. Audit Log
        AuditLog.log(
            action_type='SETTINGS_CHANGE',
            user=admin_user,
            role='admin',
            details='System initialized via init_system command.'
        )

        self.stdout.write(self.style.SUCCESS("\n[SUCCESS] Lotus Footwear POS system setup completed successfully!"))
