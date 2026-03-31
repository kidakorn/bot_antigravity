"""
OpenClaw V7 - Watchdog (Windows VPS)
Auto-restart main.py if crashed. Max 10 restarts/hour.
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
    print(f"[watchdog] {ts} - starting main.py")
    return subprocess.Popen(
        [PYTHON_EXE, "-u", BOT_SCRIPT],
        cwd=os.path.dirname(BOT_SCRIPT),
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
    )


def main():
    print(f"[watchdog] started | watching: {BOT_SCRIPT}")
    _notify("<b>OpenClaw V7 Watchdog started</b>\nBot is now being monitored.")

    proc = _start()
    restart_times: deque = deque()

    while True:
        time.sleep(CHECK_EVERY_SEC)
        now = datetime.now()

        cutoff = now - timedelta(hours=1)
        while restart_times and restart_times[0] < cutoff:
            restart_times.popleft()

        if proc.poll() is None:
            continue

        exit_code = proc.returncode
        print(f"[watchdog] {now.strftime('%H:%M:%S')} - main.py stopped (exit={exit_code})")

        if len(restart_times) >= MAX_RESTARTS_PER_HOUR:
            msg = (f"<b>Watchdog stopped restarting</b>\n"
                   f"Crashed {MAX_RESTARTS_PER_HOUR}x in 1 hour.\n"
                   f"Please check VPS manually.")
            print(f"[watchdog] {msg}")
            _notify(msg)
            time.sleep(3600)
            restart_times.clear()

        time.sleep(COOLDOWN_SEC)
        restart_times.append(now)
        n = len(restart_times)

        _notify(f"<b>Watchdog Restart #{n}</b>\n"
                f"exit={exit_code} | {now.strftime('%H:%M:%S')}\n"
                f"Restarting main.py...")

        proc = _start()


if __name__ == "__main__":
    main()
