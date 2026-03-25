"""
OpenClaw V7 — Config
Exness Cent Account | XAUUSDc M5 | Windows VPS
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ── Instrument ────────────────────────────────
SYMBOL            : str   = "XAUUSDc"
TIMEFRAME         : str   = "M5"
HTF_TIMEFRAME     : str   = "H1"
MAGIC             : int   = 20260324

# ── Risk ──────────────────────────────────────
RISK_PCT          : float = 0.010     # 1% / trade (~15 USC บนพอร์ต 1,500 USC)
MIN_LOT           : float = 0.01
MAX_LOT           : float = 1.00
MAX_SPREAD_POINTS : int   = 400
MAX_OPEN_TRADES   : int   = 1
MAX_TRADES_PER_DAY: int   = 99
COOLDOWN_MINUTES  : int   = 0

MAX_DAILY_LOSS_PCT       : float = 0.05
EQUITY_DRAWDOWN_STOP_PCT : float = 0.10
MAX_CONSECUTIVE_LOSS     : int   = 3

# ── Pause Protection ──────────────────────────
LOSS_STREAK_PAUSE_COUNT   : int = 3
LOSS_STREAK_PAUSE_MINUTES : int = 120

# ── Entry Quality ─────────────────────────────
REQUIRE_NEW_SETUP           : bool = True
SAME_DIRECTION_REENTRY_BARS : int  = 1
MIN_SCORE_TO_TRADE          : int  = 58

# ── SL/TP Fallback ────────────────────────────
SL_ATR_MULT : float = 1.30
TP_RR       : float = 1.25

# ── Strategy Tuning ───────────────────────────
PULLBACK_ZONE_ATR_MULT     : float = 1.10
CONTINUATION_ZONE_ATR_MULT : float = 0.85

PULLBACK_RSI_BUY_MIN  : int = 40
PULLBACK_RSI_BUY_MAX  : int = 68
PULLBACK_RSI_SELL_MIN : int = 32
PULLBACK_RSI_SELL_MAX : int = 60

CONTINUATION_RSI_BUY_MIN  : int = 50
CONTINUATION_RSI_BUY_MAX  : int = 74
CONTINUATION_RSI_SELL_MIN : int = 26
CONTINUATION_RSI_SELL_MAX : int = 50

# ── Profit Protection ─────────────────────────
TRAILING_ENABLED        : bool  = True
TRAILING_ATR_MULT       : float = 0.60
TRAILING_CHECK_EVERY_SEC: int   = 10
TRAILING_START_ATR      : float = 0.55

BREAKEVEN_ENABLED     : bool  = True
BREAKEVEN_TRIGGER_ATR : float = 0.40
BREAKEVEN_LOCK_POINTS : int   = 15

PARTIAL_TP_ENABLED   : bool  = True
PARTIAL_TP_TRIGGER_R : float = 0.65
PARTIAL_TP_CLOSE_PCT : float = 0.50

# ── AI / Session ──────────────────────────────
OPENCLAW_AI_ENABLED : bool = True
AI_SESSION_FILTER   : bool = True
AI_REGIME_FILTER    : bool = True
AI_VOL_FILTER       : bool = True
AI_TREND_STRENGTH   : bool = True

# เวลาไทย UTC+7
AI_ASIAN_START_HHMM  : tuple = (8,  0)
AI_ASIAN_END_HHMM    : tuple = (12, 0)
AI_LONDON_START_HHMM : tuple = (14, 0)
AI_LONDON_END_HHMM   : tuple = (20, 0)
AI_NY_START_HHMM     : tuple = (19, 30)
AI_NY_END_HHMM       : tuple = (23, 59)

# ── News Blackout ─────────────────────────────
NEWS_BLACKOUT_ENABLED  : bool  = True
NEWS_BLACKOUT_WINDOWS  : list  = []
NEWS_BUFFER_MIN_BEFORE : int   = 15
NEWS_BUFFER_MIN_AFTER  : int   = 15

# ── Google Sheets ─────────────────────────────
SHEET_ID           : str  = os.getenv("OPENCLAW_SHEET_ID", "")
SHEET_TAB          : str  = os.getenv("OPENCLAW_SHEET_TAB", "Sheet1")
BASE_DIR           : str  = os.path.dirname(os.path.abspath(__file__))
GOOGLE_CREDS_JSON  : str  = os.path.join(BASE_DIR, "service_account.json")
SHEET_AUTO_TRIM    : bool = True
SHEET_KEEP_LAST_ROWS: int = 1000

# ── Telegram ──────────────────────────────────
NOTIFY_ENABLED     : bool = os.getenv("OPENCLAW_NOTIFY_ENABLED", "true").lower() == "true"
TELEGRAM_BOT_TOKEN : str  = os.getenv("OPENCLAW_TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   : str  = os.getenv("OPENCLAW_TELEGRAM_CHAT_ID", "")

# ── Stability ─────────────────────────────────
SAFE_MODE_MAX_MT5_FAILS : int = 3
SAFE_MODE_RETRY_SEC     : int = 60
MARKET_CLOSED_SLEEP_SEC : int = 120
ORDER_FAIL_RETRY_SEC    : int = 120

# ── Logging ───────────────────────────────────
INFO_LOG_EVERY_SEC          : int  = 300
HEALTH_LOG_EVERY_SEC        : int  = 1800
CLOSED_TRADE_SCAN_EVERY_SEC : int  = 30
DAILY_SUMMARY_ON_ROLLOVER   : bool = True

LOG_NO_SETUP        : bool = True
LOG_BLOCKED_AI      : bool = True
LOG_BLOCKED_SCORE   : bool = True
LOG_SKIP_SPREAD     : bool = True
LOG_HEALTH_SNAPSHOT : bool = True
LOG_NEWS_BLOCK      : bool = True
LOG_TRAIL_UPDATES   : bool = True
LOG_PARTIAL_TP      : bool = True
LOG_PAUSE_STATE     : bool = True
LOG_BLOCKED_HTF     : bool = True
LOG_DUPLICATE_SETUP : bool = True
LOG_MARKET_STATUS   : bool = True
LOG_COOLDOWN        : bool = False
