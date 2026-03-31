"""
OpenClaw V7 - Google Sheets Logger
ปรับปรุงหลัก:
  - Non-blocking: ใช้ background thread + queue
    → บอทไม่หยุดแม้ Google API ช้า/timeout
  - Connection reuse ผ่าน _get_ws() cache
  - Retry 2 ครั้งก่อน drop log
"""
import queue
import threading
import time

import gspread

HEADER_COLUMNS = [
    "timestamp", "symbol", "tf", "event",
    "balance", "equity", "margin_free", "drawdown_pct",
    "spread", "atr14", "vol_ratio",
    "trades_today", "m_level", "safe_mode", "safe_reason",
    "signal", "entry_type", "score", "reason",
    "close_price", "high_price", "low_price",
]

_WS_CACHE: dict = {}
_WS_LOCK = threading.Lock()
_LOG_QUEUE: queue.Queue = queue.Queue(maxsize=500)
_WORKER_STARTED = False
_WORKER_LOCK = threading.Lock()


# ─────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────

def _open_ws(creds_json: str, sheet_id: str, tab: str):
    key = f"{sheet_id}:{tab}"
    with _WS_LOCK:
        if key in _WS_CACHE:
            return _WS_CACHE[key]
        gc = gspread.service_account(filename=creds_json)
        ws = gc.open_by_key(sheet_id).worksheet(tab)
        _WS_CACHE[key] = ws
        return ws


def _invalidate_cache(sheet_id: str, tab: str):
    key = f"{sheet_id}:{tab}"
    with _WS_LOCK:
        _WS_CACHE.pop(key, None)


def _write_row(creds_json: str, sheet_id: str, tab: str, payload: dict):
    row = [payload.get(k, "") for k in HEADER_COLUMNS]
    for attempt in range(2):
        try:
            ws = _open_ws(creds_json, sheet_id, tab)
            ws.append_row(row, value_input_option="USER_ENTERED")
            return True
        except gspread.exceptions.APIError as e:
            _invalidate_cache(sheet_id, tab)
            if attempt == 0:
                time.sleep(3)
        except Exception as e:
            _invalidate_cache(sheet_id, tab)
            if attempt == 0:
                time.sleep(3)
    return False


def _worker(creds_json: str, sheet_id: str, tab: str):
    """Background thread: drain queue and write to Sheets"""
    while True:
        try:
            payload = _LOG_QUEUE.get(timeout=5)
            _write_row(creds_json, sheet_id, tab, payload)
            _LOG_QUEUE.task_done()
        except queue.Empty:
            continue
        except Exception:
            pass


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def start_log_worker(creds_json: str, sheet_id: str, tab: str):
    """เรียกครั้งเดียวตอน startup"""
    global _WORKER_STARTED
    with _WORKER_LOCK:
        if _WORKER_STARTED:
            return
        t = threading.Thread(
            target=_worker,
            args=(creds_json, sheet_id, tab),
            daemon=True,
            name="sheets-log-worker",
        )
        t.start()
        _WORKER_STARTED = True


def ensure_sheet_header(creds_json: str, sheet_id: str, tab: str) -> None:
    try:
        ws = _open_ws(creds_json, sheet_id, tab)
        first = ws.row_values(1)
        if first != HEADER_COLUMNS:
            ws.update("A1", [HEADER_COLUMNS])
    except Exception as e:
        print(f"[sheets] header error: {e}")


def append_log(creds_json: str, sheet_id: str, tab: str, payload: dict) -> bool:
    """Non-blocking: enqueue และ return ทันที"""
    try:
        _LOG_QUEUE.put_nowait(payload)
        return True
    except queue.Full:
        print("[sheets] log queue full — dropping entry")
        return False


def trim_sheet_logs(
    creds_json: str,
    sheet_id: str,
    tab: str,
    keep_last_rows: int = 500,
) -> None:
    try:
        ws         = _open_ws(creds_json, sheet_id, tab)
        total      = len(ws.get_all_values())
        max_rows   = keep_last_rows + 1   # +1 for header
        
        if total <= max_rows:
            return
            
        to_delete = total - max_rows
        
        # Try batch deletion (Gspread 3.2.0+)
        try:
            ws.delete_rows(2, to_delete + 2) # Google API expects end_index (exclusive)
        except Exception:
            # Fallback for old gspread
            for _ in range(to_delete):
                ws.delete_row(2)

    except Exception as e:
        print(f"[sheets] trim error: {e}")
