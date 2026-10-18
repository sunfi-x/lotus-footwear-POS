# Lotus Footwear POS
## Troubleshooting & Disaster Recovery Guide

This guide provides procedures for handling hardware failures, power outages, and database restoration for **Lotus Footwear POS**.

---

### 1. Common Operational Issues & Quick Fixes

#### Issue 1: "That port is already in use" Error on Startup
- **Cause:** A previous Python process did not close completely when the window was closed.
- **Solution:**
  1. Double-click `stop_pos.bat`. It will kill any stuck processes on port 8000.
  2. Double-click `start_pos.bat` again.

#### Issue 2: Sudden Power Outage / Computer Crash During Sale
- **Behavior:** Lotus POS operates SQLite in **WAL (Write-Ahead Logging)** mode with `PRAGMA synchronous = NORMAL`.
- **Recovery:** When power returns and `start_pos.bat` is launched, SQLite automatically plays back the WAL log and recovers uncommitted changes to a consistent state. No database corruption occurs.
- If a sale was mid-transaction when power failed, the database automatically rolled it back so that neither stock nor invoices were left in an inconsistent state.

#### Issue 3: "External Backup Drive Not Found" Warning
- **Cause:** The USB flash drive configured in Shop Settings is not plugged into the PC.
- **Solution:** Normal operations and local backups will continue uninterrupted in `.\backups\`. Insert the USB pen drive so that mirror backups can resume.

#### Issue 4: Receipt Printing Margins Cut Off
- **Cause:** Printer margins in the browser are set to "Default" instead of "None".
- **Solution:**
  1. In the print dialog, click "More settings".
  2. Change **Margins** from *Default* to **None**.
  3. Uncheck **Headers and footers**.

---

### 2. Step-by-Step Disaster Recovery Procedure

If the computer hard drive fails, a virus corrupts files, or the database needs to be restored to a prior date:

#### Scenario A: In-App Safe Restore (Recommended)
1. Log into Lotus POS as **Admin** (`admin`).
2. Navigate to **"💾 ব্যাকআপ ও রিস্টোর"** (`http://127.0.0.1:8000/backups/`).
3. Locate the desired verified backup file from the list (look for green badge: `✓ ত্রুটিমুক্ত (Passed)`).
4. Click **"⚠️ রিস্টোর করুন"**.
5. In the confirmation dialog, type the word **`RESTORE`** in all capital letters.
6. Click **"✓ নিশ্চিতভাবে রিস্টোর সম্পন্ন করুন"**.
7. The system will:
   - Create an emergency safety copy of the current database (`lotus_pos_backup_..._pre_restore.sqlite3`).
   - Copy the selected backup over the active database.
   - Run `PRAGMA integrity_check` on the restored database.
   - If verified, show a success message.

#### Scenario B: Manual Disaster Recovery (When App Cannot Boot)
1. Copy the latest `.sqlite3` backup file from your USB flash drive or `backups/` folder.
2. In the `Lotus POS` directory, locate the active database file `db.sqlite3`.
3. Rename the current broken `db.sqlite3` to `db.sqlite3.broken.bak`.
4. Copy your backup file into the directory and rename it to:
   ```
   db.sqlite3
   ```
5. Remove any leftover `db.sqlite3-wal` or `db.sqlite3-shm` files.
6. Double-click `start_pos.bat`.
7. The system will boot with your restored data intact.
