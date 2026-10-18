@echo off
title Lotus Footwear POS - Safe Shutdown
echo =====================================================================
echo                STOPPING LOTUS FOOTWEAR POS SERVER
echo =====================================================================
echo.

echo Searching for running server processes on port 8000...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8000 ^| findstr LISTENING') do (
    echo Stopping process PID: %%a
    taskkill /f /pid %%a >nul 2>&1
)

echo [OK] Lotus Footwear POS local server has been safely stopped.
echo.
pause
