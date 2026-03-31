@echo off
title OpenClaw V7
cd /d "C:\Users\Administrator\Desktop\bot_antigravity"

:: --- Start MT5 ---
set "MT5_PATH=C:\Program Files\MetaTrader 5 EXNESS\terminal64.exe"

if exist "%MT5_PATH%" (
    echo Starting MetaTrader 5...
    start "" "%MT5_PATH%"
    echo Waiting for MT5 to load...
    timeout /t 15 /nobreak >nul
) else (
    echo MT5 not found - please start MT5 manually then press any key
    pause
    exit /b 1
)

:: --- Start bot ---
echo Starting OpenClaw V7...
set PYTHONPATH=.
start "OpenClaw-V7" /min cmd /c "python watchdog.py"

echo.
echo ====================================
echo  OpenClaw V7 is running
echo  Logs: Google Sheets
echo ====================================
echo.
echo To stop bot: double-click stop.bat
echo.
timeout /t 5
