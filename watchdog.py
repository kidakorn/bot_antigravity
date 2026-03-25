"""
OpenClaw V7 — Watchdog (Windows VPS)
ตรวจสอบ main.py ทุก 60 วินาที — restart อัตโนมัติถ้า crash
จำกัด restart 10 ครั้ง/ชั่วโมง ป้องกัน crash loop
แจ้ง Telegram ทุกครั้งที่ restart
"""
import os
import subprocess
import sys
import time
from collections import deque
from datetime import datetime, timedelta

import requests
from dotenv import load_dotenv

load_dotenv()

BOT_SCRIPT            = os.path.join(os.path.dirname(os.path.abspath(__file__)), "main.py")
PYTHON_EXE            = sys.executable
CHECK_EVERY_SEC       = 60
MAX_RESTARTS_PER_HOUR = 10
COOLDOWN_SEC          = 30

TOKEN   = os.getenv("OPENCLAW_TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("OPENCLAW_TELEGRAM_CHAT_ID", "")


def _notify(msg: str):
    if not TOKEN or not CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TOKEN}/sendMessage",
            json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "HTML"},
            timeout=8,
        )
    except Exception:
        pass


def _start() -> subprocess.Popen:
    ts = datetime.now().strftime("%H:%M:%S")
    print(f"[watchdog] {ts} — starting main.py")
    return subprocess.Popen(
        [PYTHON_EXE, BOT_SCRIPT],
        cwd=os.path.dirname(BOT_SCRIPT),
    )


def main():
    print(f"[watchdog] เริ่มต้น | ดูแล: {BOT_SCRIPT}")
    _notify("🐾 <b>Watchdog เริ่มทำงาน</b>\nOpenClaw V7 กำลังถูกดูแล")

    proc = _start()
    restart_times: deque = deque()

    while True:
        time.sleep(CHECK_EVERY_SEC)
        now = datetime.now()

        # ลบ timestamp เก่ากว่า 1 ชม.
        cutoff = now - timedelta(hours=1)
        while restart_times and restart_times[0] < cutoff:
            restart_times.popleft()

        if proc.poll() is None:
            continue  # ยังรันปกติ

        exit_code = proc.returncode
        print(f"[watchdog] {now.strftime('%H:%M:%S')} — main.py หยุด (exit={exit_code})")

        if len(restart_times) >= MAX_RESTARTS_PER_HOUR:
            msg = (f"🚨 <b>Watchdog หยุด restart</b>\n"
                   f"crash {MAX_RESTARTS_PER_HOUR}x ใน 1 ชม.\n"
                   f"กรุณาตรวจสอบ VPS ด้วยตัวเองครับ")
            print(f"[watchdog] {msg}")
            _notify(msg)
            time.sleep(3600)
            restart_times.clear()

        time.sleep(COOLDOWN_SEC)
        restart_times.append(now)
        n = len(restart_times)

        _notify(f"⚠️ <b>Watchdog Restart #{n}</b>\n"
                f"exit={exit_code} | {now.strftime('%H:%M:%S')}\n"
                f"กำลัง restart main.py...")

        proc = _start()


if __name__ == "__main__":
    main()
