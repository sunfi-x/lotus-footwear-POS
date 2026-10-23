@echo off
title Lotus Footwear POS - Push to GitHub
cd /d "%~dp0"
set "PATH=C:\Users\USER\.cache\codex-runtimes\codex-primary-runtime\dependencies\native\git\cmd;%PATH%"

echo =====================================================================
echo           LOTUS FOOTWEAR POS - PUSH CODE TO GITHUB
echo =====================================================================
echo.
echo Pushing latest committed changes to:
echo https://github.com/sunfi-x/lotus-footwear-POS
echo.

git push origin main

if %errorlevel% equ 0 (
    echo.
    echo =====================================================================
    echo [SUCCESS] Code pushed to GitHub successfully!
    echo =====================================================================
) else (
    echo.
    echo =====================================================================
    echo [FAILED] Push failed. If prompted for GitHub login, complete it.
    echo =====================================================================
)
echo.
pause
