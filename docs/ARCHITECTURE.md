# System Architecture & Technical Specification
## Lotus Footwear POS & Inventory Management System

### 1. System Overview
**Lotus Footwear POS** is an offline-first, enterprise-grade Point of Sale, Inventory Management, Accounting, and Reporting system specifically tailored for physical footwear retail operations in Bangladesh.

- **Primary Platform:** Windows Desktop PC (Single-node offline operation, bound to `127.0.0.1:8000`).
- **Core Technology Stack:**
  - Runtime: Python 3.14+
  - Web Framework: Django 6.x (MVC/MVT pattern with robust ORM and atomic database transactions)
  - Database: SQLite in WAL (Write-Ahead Logging) mode with foreign keys enabled, indexed query paths, and online backup API.
  - UI/UX: Lightweight, high-contrast, keyboard-friendly HTML5 / CSS3 / Vanilla JavaScript. Staff UI in clear Bengali with standard shoe sizing/terminology; Receipts in English.
  - Thermal Printing: Native 58mm thermal receipt layout (Xprinter XP-58IIIA driver compatible, window.print auto-trigger & optional raw ESC/POS endpoint).
  - Timezone: `Asia/Dhaka` (UTC+6).
  - Currency: Bangladeshi Taka (BDT / ৳).

---

### 2. Database Entities & Relationship Design

#### 2.1 Core App
- `BusinessDay`: Represents an operational business day.
  - Fields: `date` (DateField, unique), `status` (OPEN, CLOSED), `opened_at`, `closed_at`, `opened_by`, `closed_by`, `opening_cash`, `closing_cash_system`, `closing_cash_actual`, `cash_discrepancy`, `discrepancy_reason`, `notes`.
- `ApplicationSetting`: Key-value or singleton configuration for shop profile.
  - Fields: `shop_name`, `shop_phone`, `shop_address`, `receipt_header`, `receipt_footer`, `backup_directory`, `external_backup_directory`, `low_stock_threshold`.
- `AuditLog`: System-wide audit trail.
  - Fields: `timestamp`, `user_role`, `username`, `action_type`, `entity_type`, `entity_id`, `details`, `ip_address`.

#### 2.2 Inventory App
- `ProductModel`: Master footwear model.
  - Fields: `code` (CharField, unique, indexed - e.g. "M-102"), `name`, `brand`, `category`, `is_active`, `notes`, `created_at`.
- `ProductVariant`: Specific size and color permutation of a model.
  - Fields: `product` (FK to ProductModel), `size` (CharField - e.g. "39", "40", "41"), `colour` (CharField - e.g. "Black", "Brown"), `sku` (CharField, unique, indexed), `current_stock` (IntegerField, default=0), `weighted_avg_cost` (DecimalField, default=0.00), `is_active`.
  - Unique constraint: `(product, size, colour)`.
- `Supplier`: Shoe vendor/wholesaler.
  - Fields: `name`, `phone`, `address`, `contact_person`, `notes`.
- `Purchase`: Wholesale incoming consignment.
  - Fields: `supplier` (FK), `invoice_no` (vendor bill reference), `purchase_date`, `total_amount`, `paid_amount`, `notes`, `created_by`, `created_at`.
- `PurchaseLine`: Line items in a purchase.
  - Fields: `purchase` (FK), `variant` (FK), `quantity`, `unit_cost`, `line_total`.
- `StockMovement`: Append-only immutable inventory ledger.
  - Fields: `timestamp`, `variant` (FK), `movement_type` (OPENING, PURCHASE, SALE, SALE_RETURN, ADJUSTMENT), `quantity_delta` (positive or negative), `resulting_stock`, `reference_type`, `reference_id`, `unit_cost`, `notes`, `created_by`.
- `StockAdjustment`: Discrepancy reconciliation record.
  - Fields: `variant` (FK), `old_quantity`, `new_quantity`, `difference`, `reason`, `authorized_by`, `timestamp`.

#### 2.3 POS App
- `Sale`: Customer invoice.
  - Fields: `invoice_no` (unique, indexed - e.g. "INV-20261018-0001"), `business_day` (FK), `customer_name` (optional), `customer_phone` (optional), `subtotal`, `discount_percent`, `discount_amount`, `calculated_total`, `manual_adjustment`, `final_total`, `payment_method` (CASH, BKASH, CARD, etc.), `amount_paid`, `balance_due`, `status` (COMPLETED, CANCELLED), `created_at`, `created_by`.
- `SaleLine`: Individual pair sale line item.
  - Fields: `sale` (FK), `variant` (FK), `quantity`, `unit_price`, `line_subtotal`, `discount_percent`, `discount_amount`, `final_line_total`, `cost_snapshot` (unit WAC at moment of sale), `gross_profit`.
- `Payment`: Audit trail for initial & subsequent due collections.
  - Fields: `sale` (FK), `amount`, `payment_method`, `payment_type` (INITIAL, DUE_PAYMENT), `received_at`, `received_by`, `notes`.
- `SaleReturn`: Customer return record.
  - Fields: `sale` (FK), `return_no` (unique), `business_day` (FK), `refund_amount`, `reason`, `returned_at`, `processed_by`.
- `SaleReturnLine`: Line item of returned pairs.
  - Fields: `return_record` (FK), `sale_line` (FK), `variant` (FK), `quantity`, `refund_amount`, `disposition` (RESTOCK, DAMAGED).

#### 2.4 Expenses App
- `ExpenseCategory`: Category grouping (Rent, Salaries, Electricity, Transport, Packaging, Repairs, Miscellaneous).
- `Expense`: Operating expenditure.
  - Fields: `category` (FK), `amount`, `payment_method`, `expense_date`, `business_day` (FK), `description`, `recipient`, `created_by`, `created_at`.

#### 2.5 Backup System App
- `BackupRecord`: Backup execution audit log.
  - Fields: `timestamp`, `file_name`, `file_path`, `file_size_bytes`, `backup_type` (MANUAL, DAY_CLOSE, AUTO), `integrity_check_passed` (Boolean), `schema_version`, `status` (SUCCESS, FAILED), `error_message`.

---

### 3. Business Logic, Formulas & Accounting Policies

1. **Pairs Sold vs. Invoices:**
   - Pairs Sold = $\sum_{\text{qualifying sales}} \sum \text{SaleLine.quantity}$.
   - Completed Invoices = $\text{Count(qualifying Sale where status='COMPLETED')}$.
2. **Staff Price Freedom & Calculations:**
   - $\text{Line Subtotal} = \text{Unit Selling Price} \times \text{Quantity}$.
   - $\text{Discount Amount} = \text{Line Subtotal} \times \frac{\text{Discount Percentage}}{100}$.
   - $\text{Calculated Total} = \text{Subtotal} - \text{Discount Amount}$.
   - If Staff manually adjusts the final total:
     $\text{Manual Adjustment} = \text{Final Total} - \text{Calculated Total}$.
   - Final Total is authoritative for cash collection and revenue accounting. Manual adjustment is allocated proportionately across sale lines for accurate per-model profit reporting.
3. **Inventory Valuation & COGS:**
   - Costing method: **Weighted Average Cost (WAC)**.
   - Upon purchase of $Q_{\text{new}}$ pairs at $C_{\text{new}}$ with existing stock $Q_{\text{curr}}$ at average cost $C_{\text{curr}}$:
     $$\text{New WAC} = \frac{(Q_{\text{curr}} \times C_{\text{curr}}) + (Q_{\text{new}} \times C_{\text{new}})}{Q_{\text{curr}} + Q_{\text{new}}}$$
   - When a sale is confirmed, the current WAC is saved into `SaleLine.cost_snapshot`.
   - $\text{Line COGS} = \text{SaleLine.cost\_snapshot} \times \text{Quantity}$.
   - $\text{Gross Profit} = \text{Final Line Total} - \text{Line COGS}$.
   - $\text{Operating Expenses} = \sum \text{Expenses in period}$.
   - $\text{Net Profit} = \text{Total Gross Profit} - \text{Operating Expenses}$.
4. **Business Week Definition:**
   - Cycle: Friday to Wednesday.
   - Thursday is the weekly shop closing day.
   - Friday always begins a fresh business week. Wednesday night ends that business week.
   - Calendar month reports strictly run from day 1 to end-of-month.
5. **Day Opening & Closing Workflow:**
   - Day Open: Verify previous day was closed; enter opening cash drawer balance; verify backup status.
   - Day Close: Calculate expected cash drawer = Opening Cash + Cash Receipts from Sales + Cash Due Collections - Cash Refunds - Cash Expenses.
   - Enter physical cash count. Flag discrepancies. Force SQLite online backup to local disk and configured USB destination.

---

### 4. Risks & Mitigations

| Risk | Mitigation |
| :--- | :--- |
| Sudden power outage during sale transaction | Atomic transactions (`@transaction.atomic`), SQLite WAL mode with `PRAGMA synchronous = NORMAL`, all stock and finance written together. |
| Negative stock due to rapid sales | Select for update (`select_for_update()`) on ProductVariant during checkout; strict stock validation. |
| Accidental overwrite of database during backup | SQLite Online Backup API (`sqlite3.backup()`) creating hot backups without lock contention; date-stamped backup archives. |
| Accidental restore destroying current data | Pre-restore snapshot taken automatically before any restore; candidate verified with `PRAGMA integrity_check` before activation. |
| Staff changing prices causing audit gap | Original price, discount %, discount amount, manual adjustment, and final price all stored permanently. |
