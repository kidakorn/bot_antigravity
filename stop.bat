@echo off
title Stop OpenClaw V7
echo [%date% %time%] Stopping OpenClaw V7...

taskkill /f /im python.exe >nul 2>&1
taskkill /f /im pythonw.exe >nul 2>&1

echo.
echo ====================================
echo  OpenClaw V7 stopped
echo ====================================
echo.
timeout /t 3
