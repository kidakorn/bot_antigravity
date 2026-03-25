# OpenClaw V7 — Windows Task Scheduler Setup
# Run as Administrator ใน PowerShell
# แก้ PYTHON_PATH และ BOT_DIR ก่อนรัน

$PYTHON_PATH = "C:\Python311\python.exe"   # แก้ตาม path จริง
$BOT_DIR     = "C:\openclaw_v7"            # แก้ตาม path จริง
$WATCHDOG    = "$BOT_DIR\watchdog.py"

$action = New-ScheduledTaskAction `
    -Execute $PYTHON_PATH `
    -Argument $WATCHDOG `
    -WorkingDirectory $BOT_DIR

$triggers = @(
    $(New-ScheduledTaskTrigger -AtStartup),
    $(New-ScheduledTaskTrigger -AtLogOn)
)

$settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -StartWhenAvailable

Register-ScheduledTask `
    -TaskName "OpenClaw_V7_Watchdog" `
    -Action   $action `
    -Trigger  $triggers `
    -Settings $settings `
    -RunLevel Highest `
    -Force

Write-Host "✅ Task Scheduler ตั้งค่าเรียบร้อย"
Write-Host "Watchdog จะ start อัตโนมัติทุกครั้งที่ Windows boot"
