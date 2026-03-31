"""
OpenClaw V7 - Bot State
ปรับปรุง:
  - เพิ่ม setup_key persistence (ป้องกัน duplicate trade หลัง restart)
  - เพิ่ม equity_peak tracking สำหรับ drawdown protection
  - ใช้ JSON file save/load แทนเก็บ in-memory อย่างเดียว
"""
import json
import os
from dataclasses import dataclass, field
from datetime import date, datetime


_STATE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".bot_state.json")


@dataclass
class BotState:
    today: str = field(default_factory=lambda: date.today().isoformat())
    trades_today: int = 0
    last_trade_time: datetime | None = None
    last_trail_time: datetime | None = None

    # ── persistence: ป้องกัน duplicate หลัง restart ──
    last_setup_key: str = ""
    last_setup_time: datetime | None = None

    processed_closed_positions: set = field(default_factory=set)
    partial_taken_positions: set = field(default_factory=set)

    safe_mode: bool = False
    safe_reason: str = ""
    consecutive_mt5_failures: int = 0
    consecutive_log_failures: int = 0

    pause_until: datetime | None = None
    pause_reason: str = ""

    failed_order_cooldown_until: datetime | None = None
    failed_order_reason: str = ""
    failed_order_signal_key: str = ""

    equity_peak: float = 0.0   # ติดตาม equity สูงสุด (rolling drawdown)

    last_log_times: dict = field(default_factory=dict)

    # ── throttle helpers ──────────────────────────────
    def should_log(self, key: str, throttle_sec: int) -> bool:
        now = datetime.now()
        last = self.last_log_times.get(key)
        if last is None or (now - last).total_seconds() >= throttle_sec:
            self.last_log_times[key] = now
            return True
        return False

    # ── trade guards ─────────────────────────────────
    def cooldown_active(self, cooldown_minutes: int) -> bool:
        if self.last_trade_time is None:
            return False
        return (datetime.now() - self.last_trade_time).total_seconds() < cooldown_minutes * 60

    def can_trail(self, now: datetime, interval_sec: int) -> bool:
        if self.last_trail_time is None:
            return True
        return (now - self.last_trail_time).total_seconds() >= interval_sec

    # ── setup dedup (persisted) ──────────────────────
    def is_duplicate_setup(self, setup_key: str, now: datetime, bars_window_min: int) -> bool:
        if not self.last_setup_key or self.last_setup_time is None:
            return False
        if setup_key != self.last_setup_key:
            return False
        return (now - self.last_setup_time).total_seconds() < bars_window_min * 60

    def remember_setup(self, setup_key: str, now: datetime):
        self.last_setup_key = setup_key
        self.last_setup_time = now
        self._save()

    # ── state mutations ──────────────────────────────
    def mark_trade(self, when: datetime):
        self.last_trade_time = when
        self.trades_today += 1
        self.clear_failed_order()
        self._save()

    def mark_trail(self, when: datetime):
        self.last_trail_time = when

    def update_equity_peak(self, equity: float):
        if equity > self.equity_peak:
            self.equity_peak = equity

    # ── safe mode ────────────────────────────────────
    def enter_safe_mode(self, reason: str):
        self.safe_mode = True
        self.safe_reason = reason

    def exit_safe_mode(self):
        self.safe_mode = False
        self.safe_reason = ""
        self.consecutive_mt5_failures = 0

    # ── pause ────────────────────────────────────────
    def pause(self, until: datetime, reason: str):
        self.pause_until = until
        self.pause_reason = reason

    def clear_pause(self):
        self.pause_until = None
        self.pause_reason = ""

    def pause_active(self, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        return self.pause_until is not None and now < self.pause_until

    # ── failed order ─────────────────────────────────
    def set_failed_order(self, until: datetime, reason: str, signal_key: str):
        self.failed_order_cooldown_until = until
        self.failed_order_reason = reason
        self.failed_order_signal_key = signal_key

    def failed_order_active(self, signal_key: str, now: datetime | None = None) -> bool:
        now = now or datetime.now()
        return (
            self.failed_order_cooldown_until is not None
            and now < self.failed_order_cooldown_until
            and self.failed_order_signal_key == signal_key
        )

    def clear_failed_order(self):
        self.failed_order_cooldown_until = None
        self.failed_order_reason = ""
        self.failed_order_signal_key = ""

    # ── daily reset ──────────────────────────────────
    def reset_for_new_day(self, new_day: str):
        self.today = new_day
        self.trades_today = 0
        self.processed_closed_positions = set()
        self.partial_taken_positions = set()
        self.clear_pause()
        self.clear_failed_order()
        self.last_setup_key = ""
        self.last_setup_time = None
        self._save()

    # ── persistence ──────────────────────────────────
    def _save(self):
        """บันทึก state สำคัญลงไฟล์ เพื่อ survive restart"""
        try:
            data = {
                "today": self.today,
                "trades_today": self.trades_today,
                "last_setup_key": self.last_setup_key,
                "last_setup_time": self.last_setup_time.isoformat() if self.last_setup_time else None,
                "last_trade_time": self.last_trade_time.isoformat() if self.last_trade_time else None,
                "equity_peak": self.equity_peak,
            }
            with open(_STATE_FILE, "w") as f:
                json.dump(data, f)
        except Exception:
            pass  # ไม่ให้ crash หากเขียนไฟล์ไม่ได้

    @classmethod
    def load_or_new(cls) -> "BotState":
        """โหลด state จากไฟล์ หากมี (เช่น หลัง restart)"""
        state = cls()
        try:
            if not os.path.exists(_STATE_FILE):
                return state
            with open(_STATE_FILE) as f:
                data = json.load(f)
            today = date.today().isoformat()
            if data.get("today") == today:
                state.today = today
                state.trades_today = int(data.get("trades_today", 0))
                state.last_setup_key = data.get("last_setup_key", "")
                raw_setup = data.get("last_setup_time")
                state.last_setup_time = datetime.fromisoformat(raw_setup) if raw_setup else None
                raw_trade = data.get("last_trade_time")
                state.last_trade_time = datetime.fromisoformat(raw_trade) if raw_trade else None
                state.equity_peak = float(data.get("equity_peak", 0.0))
        except Exception:
            pass
        return state
