@echo off
title Lotus Footwear POS - Initial Installation
echo =====================================================================
echo          LOTUS FOOTWEAR POS - SYSTEM SETUP & INITIALIZATION
echo =====================================================================
echo.

cd /d "%~dp0"

echo [1/4] Checking Python environment...
set "PY_CMD=python"
%PY_CMD% --version >nul 2>&1
if %errorlevel% neq 0 (
    py --version >nul 2>&1
    if %errorlevel% equ 0 (
        set "PY_CMD=py"
    ) else (
        echo [ERROR] Python is not installed or not in PATH!
        echo Please install Python 3.11+ and check 'Add Python to PATH'.
        pause
        exit /b 1
    )
)

echo [2/4] Setting up Virtual Environment...
if not exist "venv" (
    echo Creating virtual environment in .\venv...
    %PY_CMD% -m venv venv
)

echo [3/4] Installing Required Dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt

echo [4/4] Applying Database Migrations & Initializing System...
python manage.py migrate
python manage.py init_system

echo.
echo =====================================================================
echo [SUCCESS] Lotus Footwear POS has been installed successfully!
echo To start the application, double-click 'start_pos.bat'.
echo =====================================================================
echo.
pause
