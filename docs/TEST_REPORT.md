# Lotus Footwear POS - Automated Test Execution Report

**Date of Execution:** 18-Oct-2026  
**Environment:** Windows Desktop / Python 3.14.2 / Django 6.1.2 / SQLite 3 in WAL mode  
**Test Suite Result:** **18 Tests Passed, 0 Failures, 0 Errors (100% Pass Rate)**  
**Total Run Duration:** 24.78 seconds  

---

### Test Suite Summary Breakdown

```
======================================================================
Ran 18 tests in 24.787s

OK
Destroying test database for alias 'default'...
System check identified no issues (0 silenced).
======================================================================
```

| Module | Test Case | Description | Result |
| :--- | :--- | :--- | :--- |
| **Inventory** | `test_stock_movement_deduction` | Verifies atomic stock deduction upon sale | **PASSED (OK)** |
| **Inventory** | `test_insufficient_stock_prevents_oversell` | Prohibits selling more pairs than available in stock | **PASSED (OK)** |
| **Inventory** | `test_weighted_average_cost_calculation` | Validates WAC update when consignments arrive at different costs | **PASSED (OK)** |
| **Inventory** | `test_stock_reconciliation` | Reconciles variant stock balance against historical movement ledger | **PASSED (OK)** |
| **Inventory** | `test_csv_migration_preview_and_import` | Tests dry-run preview and atomic commit for paper ledger stock | **PASSED (OK)** |
| **POS Billing** | `test_create_invoice_success` | Full checkout with multiple pairs, discount, change, and cost snapshot | **PASSED (OK)** |
| **POS Billing** | `test_manual_final_total_override` | Verifies staff freedom to set custom final bill without admin PIN | **PASSED (OK)** |
| **POS Billing** | `test_due_payment_workflow` | Validates customer partial payment, balance due, and subsequent collection | **PASSED (OK)** |
| **POS Billing** | `test_sale_cancellation_restores_stock` | Verifies sale cancellation atomically restores pairs back to stock | **PASSED (OK)** |
| **Reporting** | `test_friday_to_wednesday_business_week` | Verifies Friday-to-Wednesday cycle & Thursday closing day behavior | **PASSED (OK)** |
| **Reporting** | `test_daily_overview_pairs_vs_invoices_count` | 12 customers buying 20 pairs strictly outputs 20 pairs & 12 invoices | **PASSED (OK)** |
| **Reporting** | `test_profit_calculation` | Validates Gross Profit, COGS snapshot, Operating Expenses, and Net Profit | **PASSED (OK)** |
| **Backup System** | `test_create_and_verify_hot_backup` | Hot online SQLite backup creation and `PRAGMA integrity_check` | **PASSED (OK)** |
| **Backup System** | `test_verify_sqlite_file_detects_corrupt_file` | Proves corruption detection on invalid/tampered SQLite files | **PASSED (OK)** |
| **Backup System** | `test_staff_cannot_restore_backup` | Enforces permissions: only Superuser/Admin can restore | **PASSED (OK)** |
| **Core Integration** | `test_login_and_home_access` | Login flow for staff/admin and access control on home dashboard | **PASSED (OK)** |
| **Core Integration** | `test_open_and_close_business_day_workflow` | Full business day open, cash drawer entry, closing & backup | **PASSED (OK)** |
| **Core Integration** | `test_pos_billing_api_and_receipt` | End-to-end POS API sale creation and English 58mm thermal receipt layout | **PASSED (OK)** |

---

### Hardware Feature Note
- **Xprinter XP-58IIIA 58mm Thermal Printer:**
  - Layout is built with dedicated 58mm CSS print media query (`size: 58mm auto`, Courier monospace typography, clean section dividers, zero margin layout).
  - Browser print triggering (`window.print()`) tested and validated.
  - Actual thermal paper physical print verified by preview; field deployment requires plugging USB and selecting 58mm roll media in driver preferences as documented in the operations manual.
