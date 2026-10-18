# Lotus Footwear POS
## Windows Installation, Printer Setup & Operations Guide

### 1. System Requirements & Prerequisites
- **Operating System:** Windows 10 or Windows 11 (64-bit)
- **Processor:** Dual Core 2.0 GHz or higher
- **RAM:** 4 GB or higher
- **Disk Space:** Minimum 1 GB free space for database and daily backup retention
- **Python:** Python 3.11, 3.12, 3.13, or 3.14 (Ensure "Add Python to PATH" is ticked during installation)
- **Web Browser:** Google Chrome, Microsoft Edge, or Mozilla Firefox
- **Thermal Printer:** Xprinter XP-58IIIA (58mm thermal receipt printer) connected via USB

---

### 2. One-Click Installation Procedure

1. Open the project folder `Lotus POS` on your Desktop:
   ```
   C:\Users\User\Desktop\Lotus POS
   ```
2. Double-click the file:
   ```
   setup.bat
   ```
3. The setup script will automatically:
   - Verify Python environment
   - Create local virtual environment (`.\venv`)
   - Install required dependencies (`Django`, `openpyxl`)
   - Apply database migrations to `db.sqlite3`
   - Execute `init_system` to set up initial accounts (`admin`, `staff`), shop settings, and expense categories.
4. When installation completes, press any key to close the window.

---

### 3. Everyday Operating Procedures

#### Starting the System (Every Morning)
1. Double-click:
   ```
   start_pos.bat
   ```
2. This will start the local POS engine bound securely to `127.0.0.1:8000` (offline localhost) and automatically open the application in your default web browser.
3. Keep the black console window minimized during the day. Do not close it until the end of the day.

#### Safe System Shutdown (Every Night)
1. First, complete the **"🌙 দিন সমাপ্তি (Save & Close Day)"** workflow inside the web application so that cash is balanced and a verified day-end backup is saved.
2. Close the web browser.
3. Double-click:
   ```
   stop_pos.bat
   ```
   Or press `Ctrl + C` in the console window to stop the server cleanly.

---

### 4. Thermal Printer Setup: Xprinter XP-58IIIA (58mm)

#### Driver Installation
1. Connect the Xprinter XP-58IIIA USB cable to the Windows PC and turn on power.
2. Install the manufacturer's Windows driver (usually `POS-58` or `XP-58 Driver`).
3. In Windows **Settings > Bluetooth & Devices > Printers & Scanners**, verify that the printer appears (e.g., `POS-58 Printer`).
4. Set it as the default printer if this PC is solely dedicated to billing.

#### Printing Preferences for 58mm Paper Roll
1. Right-click the printer > **Printing Preferences**.
2. Set **Paper Size / Media** to `58 x 210 mm` or `58 x 297 mm` (or `User Defined 58mm Continuous Roll`).
3. In Chrome / Edge print preview (when clicking "Print Receipt"):
   - **Destination:** Select your 58mm printer.
   - **Paper Size:** Select `58mm` (or `Roll Paper 58 x 297 mm`).
   - **Margins:** Set to **None** or **Minimum** (to avoid unwanted blank margins).
   - **Headers and Footers:** **Uncheck** (to hide browser URL and date headers).
   - Once set, the browser permanently remembers these options for subsequent single-click prints.

---

### 5. File & Data Directory Structure

| Item | Location | Purpose |
| :--- | :--- | :--- |
| **Active Database** | `C:\Users\User\Desktop\Lotus POS\db.sqlite3` | SQLite production database in WAL mode |
| **Local Backups** | `C:\Users\User\Desktop\Lotus POS\backups\` | Hot SQLite verified backup archives |
| **Documentation** | `C:\Users\User\Desktop\Lotus POS\docs\` | Manuals, guides, architecture, test reports |
| **Static Assets** | `C:\Users\User\Desktop\Lotus POS\static\` | CSS and JavaScript client engines |
| **CSV Migration** | `C:\Users\User\Desktop\Lotus POS\sample_paper_ledger_stock.csv` | Sample CSV for paper ledger migration |
