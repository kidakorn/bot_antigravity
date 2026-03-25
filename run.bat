@echo off
title OpenClaw V7
cd /d "%~dp0"

:: สร้างโฟลเดอร์ logs ถ้ายังไม่มี
if not exist logs mkdir logs

:: Log filename วันนี้
set TODAY=%date:~0,4%%date:~5,2%%date:~8,2%
set LOGFILE=logs\openclaw_%TODAY%.log

echo [%date% %time%] OpenClaw V7 starting... >> %LOGFILE%

:: รัน watchdog แบบ minimized + เก็บ log
start "OpenClaw-V7" /min cmd /c "python watchdog.py >> %LOGFILE% 2>&1"

echo.
echo ====================================
echo  OpenClaw V7 running in background
echo  Log: %LOGFILE%
echo ====================================
echo.
echo ดู log แบบ real-time:
echo   Get-Content %LOGFILE% -Wait -Tail 50
echo.
echo หยุดบอท:
echo   taskkill /f /im python.exe
echo.
timeout /t 5
