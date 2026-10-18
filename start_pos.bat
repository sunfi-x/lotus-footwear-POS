@echo off
title Lotus Footwear POS - Server
cd /d "%~dp0"

echo =====================================================================
echo                STARTING LOTUS FOOTWEAR POS SYSTEM
echo                      Offline Local Instance
echo =====================================================================
echo.

:: Ensure venv exists
if not exist "venv\Scripts\activate.bat" (
    echo [ERROR] Virtual environment not found. Running setup.bat first...
    call setup.bat
)

call venv\Scripts\activate.bat

echo Starting server on http://127.0.0.1:8000 ...
echo [NOTE] Keep this window open during business hours.
echo To safely stop the server, run 'stop_pos.bat' or press Ctrl+C.
echo.

:: Launch default browser after 2 seconds in background
start "" cmd /c "timeout /t 2 >nul & start http://127.0.0.1:8000"

:: Start Django development server bound to 127.0.0.1
python manage.py runserver 127.0.0.1:8000 --noreload
