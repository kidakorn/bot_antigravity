"""
OpenClaw V7.2 — Config
Exness Cent | XAUUSDc M15 entry | H4 HTF | Windows VPS Singapore UTC+8

v7.2:
  - TIMEFRAME M5 → M15
  - HTF H1 → H4
  - รอ candle close ก่อนเข้า
  - ลด filter เหลือ EMA+MACD+RSI
  - BOUNCE_GUARD คง (ป้องกันสวนเทรนด์)
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Instrument ────────────────────────────────
SYMBOL            : str   = "XAUUSDc"
TIMEFRAME         : str   = "M5"
HTF_TIMEFRAME     : str   = "H4"
MAGIC             : int   = 20260331

# ── Risk ──────────────────────────────────────
RISK_PCT          : float = 0.020   # 2% -> ~34 USC lot
MIN_LOT           : float = 0.01
MAX_LOT           : float = 1.00
MAX_SPREAD_POINTS : int   = 400
MAX_OPEN_TRADES   : int   = 5
MAX_TRADES_PER_DAY: int   = 50
COOLDOWN_MINUTES  : int   = 0

# ── Martingale ────────────────────────────────
MARTINGALE_MULTIPLIER : float = 1.5
MARTINGALE_MAX_LEVELS : int   = 5
MARTINGALE_STEP_POINTS: int   = 150


MAX_DAILY_LOSS_PCT       : float = 0.05
EQUITY_DRAWDOWN_STOP_PCT : float = 0.10
MAX_CONSECUTIVE_LOSS     : int   = 3

# ── Pause Protection ──────────────────────────
LOSS_STREAK_PAUSE_COUNT   : int = 3
LOSS_STREAK_PAUSE_MINUTES : int = 120

# ── Entry Quality ─────────────────────────────
REQUIRE_NEW_SETUP           : bool = True
SAME_DIRECTION_REENTRY_BARS : int  = 1
MIN_SCORE_TO_TRADE          : int  = 20

# ── Candle Close Wait ─────────────────────────
CANDLE_CLOSE_WAIT_SEC : int = 5  # เข้าได้เมื่อเหลือ < 5 วิก่อน candle close

# ── Bounce Guard ──────────────────────────────
BOUNCE_GUARD_BARS     : int   = 2
BOUNCE_GUARD_ATR_MULT : float = 2.0

# ── SL/TP ─────────────────────────────────────
SL_ATR_MULT : float = 1.50
TP_RR       : float = 1.00

# ── Strategy ──────────────────────────────────
PULLBACK_ZONE_ATR_MULT     : float = 1.60
CONTINUATION_ZONE_ATR_MULT : float = 1.25

PULLBACK_RSI_BUY_MIN  : int = 38
PULLBACK_RSI_BUY_MAX  : int = 72
PULLBACK_RSI_SELL_MIN : int = 28
PULLBACK_RSI_SELL_MAX : int = 62

CONTINUATION_RSI_BUY_MIN  : int = 45
CONTINUATION_RSI_BUY_MAX  : int = 75
CONTINUATION_RSI_SELL_MIN : int = 25
CONTINUATION_RSI_SELL_MAX : int = 55

# ── Profit Protection ─────────────────────────
TRAILING_ENABLED        : bool  = True
TRAILING_ATR_MULT       : float = 0.65
TRAILING_CHECK_EVERY_SEC: int   = 15
TRAILING_START_ATR      : float = 0.40

BREAKEVEN_ENABLED     : bool  = True
BREAKEVEN_TRIGGER_ATR : float = 0.30
BREAKEVEN_LOCK_POINTS : int   = 20

PARTIAL_TP_ENABLED   : bool  = True
PARTIAL_TP_TRIGGER_R : float = 0.70
PARTIAL_TP_CLOSE_PCT : float = 0.50

# ── AI / Session UTC+8 ────────────────────────
OPENCLAW_AI_ENABLED : bool = True
AI_SESSION_FILTER   : bool = False
AI_REGIME_FILTER    : bool = True
AI_VOL_FILTER       : bool = True
AI_TREND_STRENGTH   : bool = True

AI_ASIAN_START_HHMM  : tuple = (9,  0)
AI_ASIAN_END_HHMM    : tuple = (13, 0)
AI_LONDON_START_HHMM : tuple = (15, 0)
AI_LONDON_END_HHMM   : tuple = (21, 0)
AI_NY_START_HHMM     : tuple = (20, 30)
AI_NY_END_HHMM       : tuple = (23, 59)

# ── News Blackout ─────────────────────────────
NEWS_BLACKOUT_ENABLED  : bool = False
NEWS_BLACKOUT_WINDOWS  : list = []
NEWS_BUFFER_MIN_BEFORE : int  = 15
NEWS_BUFFER_MIN_AFTER  : int  = 30

# ── Google Sheets ─────────────────────────────
SHEET_ID           : str  = os.getenv("OPENCLAW_SHEET_ID", "")
SHEET_TAB          : str  = os.getenv("OPENCLAW_SHEET_TAB", "Sheet1")
BASE_DIR           : str  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
GOOGLE_CREDS_JSON  : str  = os.path.join(BASE_DIR, "service_account.json")
SHEET_AUTO_TRIM    : bool = True
SHEET_KEEP_LAST_ROWS: int = 500

# ── Telegram ──────────────────────────────────
NOTIFY_ENABLED     : bool = os.getenv("OPENCLAW_NOTIFY_ENABLED", "true").lower() == "true"
TELEGRAM_BOT_TOKEN : str  = os.getenv("OPENCLAW_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   : str  = os.getenv("OPENCLAW_TELEGRAM_CHAT_ID", "")

# ── Stability ─────────────────────────────────
SAFE_MODE_MAX_MT5_FAILS : int = 3
SAFE_MODE_RETRY_SEC     : int = 60
MARKET_CLOSED_SLEEP_SEC : int = 3600  # 1 ชม.
ORDER_FAIL_RETRY_SEC    : int = 120

# ── Logging ───────────────────────────────────
INFO_LOG_EVERY_SEC          : int  = 600   # 10 นาที
HEALTH_LOG_EVERY_SEC        : int  = 1800
CLOSED_TRADE_SCAN_EVERY_SEC : int  = 30
DAILY_SUMMARY_ON_ROLLOVER   : bool = True

LOG_NO_SETUP        : bool = False  # ปิด no_setup log ลดขยะ
LOG_BLOCKED_AI      : bool = False  # ปิดโชว์เหตุผลที่ AI บล็อก
LOG_BLOCKED_SCORE   : bool = False  # ปิดโชว์ที่เข้าไม่ได้เพราะคะแนนน้อย
LOG_SKIP_SPREAD     : bool = False  # ปิดสแปมเรื่อง Spread ถ่าง
LOG_HEALTH_SNAPSHOT : bool = True   # เปิดให้เห็นชีวิตบอท
LOG_NEWS_BLOCK      : bool = False
LOG_TRAIL_UPDATES   : bool = True
LOG_PARTIAL_TP      : bool = True
LOG_PAUSE_STATE     : bool = False
LOG_BLOCKED_HTF     : bool = False
LOG_DUPLICATE_SETUP : bool = False
LOG_MARKET_STATUS   : bool = True
LOG_COOLDOWN        : bool = False