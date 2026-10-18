# Lotus Footwear POS & Inventory Management System

A production-ready, offline-first Point of Sale (POS), Inventory Management, Accounting, and Reporting system built for **Lotus Footwear**, a physical retail shoe shop in Bangladesh.

---

## Key Features

- **Offline-First Windows Operation:** Runs completely locally bound to `127.0.0.1:8000`. Does not require internet connectivity or third-party cloud APIs.
- **Fast POS Billing Interface:**
  - Fast product search by code (printed on shoe) with keyboard shortcuts (`F2`, `F4`, `Enter`).
  - Dynamic size selector generated from registered variants.
  - Dynamic colour selector with live stock indicators.
  - Dynamic quantity control: `[ - ] 1 [ + ]` bounded by available inventory.
  - **Full Staff Freedom:** Sales staff can enter/change unit selling price, set discount %, and override the final invoice total without requiring Admin PIN approval.
  - Separate tracking of subtotal, discounts, manual adjustments, amount paid, change returned, and balance due.
- **Customer Receipts (English Only):** Dedicated layout optimized for the **Xprinter XP-58IIIA 58mm thermal printer**. Clean typography, no clipping or unnecessary blank margins, and auto-print support.
- **Inventory & Costing:**
  - Product model and variant matrix (Size, Colour, SKU).
  - Immutable stock movement ledger (Opening, Purchase, Sale, Sale Return, Adjustment).
  - **Weighted Average Cost (WAC)** calculation with cost snapshots captured at time of sale.
  - CSV/Excel initial stock migration tool with dry-run validation preview and error detection (supporting ~3,528 pairs and 1,000+ models).
- **Admin Dashboard & Accounting Reports:**
  - Sales analytics: Daily, Friday-to-Wednesday Business Week (Thursday weekly closing day behavior), and Calendar Monthly views.
  - Strict distinction between pair count (sum of line quantities) and completed invoice count.
  - Profit & Loss overview: Net Sales, COGS, Gross Profit, Operating Expenses, Net Profit, and Profit Margins.
  - Historical sale search by product code: lifetime pairs sold, total revenue, gross profit, and line-level sale records.
- **Day Open & Close Workflow:**
  - Day Opening: Records opening cash drawer balance.
  - Day Closing: Reconciles cash (Opening + Cash Receipts - Cash Refunds - Cash Expenses) against physical count, logs discrepancy reasons, and enforces a mandatory day-end hot backup.
- **Robust Backup & Safe Disaster Recovery:**
  - SQLite hot online backup API (`sqlite3.backup()`).
  - Automatic `PRAGMA integrity_check` verification.
  - External USB mirror backup support.
  - Safe restoration workflow with automated pre-restore rollback backup copy.
- **Security & Audit Logs:**
  - Argon2/PBKDF2 hashed credentials for Admin and Staff.
  - System-wide audit log for sales, cancellations, adjustments, migrations, day open/close, and backups.

---

## Quick Start on Windows

### 1. One-Click Setup
Double-click:
```cmd
setup.bat
```
This automatically sets up Python virtualenv, installs dependencies (`requirements.txt`), applies migrations, and initializes the system.

### 2. Starting the Application
Double-click:
```cmd
start_pos.bat
```
Opens the browser automatically to `http://127.0.0.1:8000`.

### 3. Default Login Credentials
- **Admin / Owner:** `username: admin` | `password: admin123`
- **Sales Staff:** `username: staff` | `password: staff123`

### 4. Safe Shutdown
Double-click:
```cmd
stop_pos.bat
```

---

## Documentation Directory

- [Architecture & Database Design](docs/ARCHITECTURE.md)
- [Staff User Guide in Bengali (বিক্রয় কর্মী নির্দেশিকা)](docs/STAFF_USER_GUIDE_BN.md)
- [Admin & Owner Guide in Bengali (মালিক ও এডমিন নির্দেশিকা)](docs/ADMIN_OWNER_GUIDE_BN.md)
- [Windows Installation & Printer Setup Guide](docs/WINDOWS_INSTALLATION_AND_OPERATIONS.md)
- [Troubleshooting & Disaster Recovery Guide](docs/TROUBLESHOOTING_AND_DISASTER_RECOVERY.md)
- [Automated Test Execution Report](docs/TEST_REPORT.md)
- [Sample Migration CSV](sample_paper_ledger_stock.csv)

---

## Automated Test Suite

All 18 tests across Billing, Inventory WAC, Reports, Backups, and Integration pass with 100% success rate:
```cmd
.\venv\Scripts\python manage.py test
```
Result: `Ran 18 tests in 24.78s - OK (0 failures, 0 errors)`.
