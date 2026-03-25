"""
OpenClaw V7 - Telegram Notifier
ปรับปรุง: เพิ่ม retry 1 ครั้ง, timeout สั้นลง, non-blocking option
"""
import threading
import time

import requests


def notify_telegram(
    enabled: bool,
    token: str,
    chat_id: str,
    message: str,
    non_blocking: bool = True,
) -> bool:
    if not enabled or not token or not chat_id:
        return False

    def _send():
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": message, "parse_mode": "HTML"}
        for attempt in range(2):
            try:
                r = requests.post(url, json=payload, timeout=6)
                if r.status_code == 200:
                    return True
            except Exception:
                pass
            if attempt == 0:
                time.sleep(2)
        return False

    if non_blocking:
        threading.Thread(target=_send, daemon=True).start()
        return True
    return _send()
