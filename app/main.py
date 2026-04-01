# -*- coding: utf-8 -*-
import sys
import io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

"""
OpenClaw V7.2 — Main Bot Loop
M15 entry | H4 HTF | Candle Close Wait | Bounce Guard
"""
import time
from datetime import date, datetime, timedelta
from datetime import time as dtime

import MetaTrader5 as mt5

import app.config as cfg
from app.data.analytics import (
    build_signal_context,
    compute_dynamic_trade_params,
    log_health_snapshot,
    scan_closed_trades,
    summarize_day,
)
from app.core.bot_state import BotState
from app.core.mt5_client import (
    connect,
    ensure_symbol,
    get_rates,
    positions_by_magic,
    shutdown,
    spread_points,
    today_deals_profit,
)
from app.data.news_filter import is_news_time
from app.utils.notifier import notify_telegram
from app.ai.openclaw_ai import openclaw_ai_evaluate
from app.trading.openclaw_v4 import is_in_news_blackout, trail_positions_atr
from app.trading.risk import calc_lot, sl_tp_from_points
from app.data.sheets_logger import (
    append_log,
    ensure_sheet_header,
    start_log_worker,
    trim_sheet_logs,
)
from app.trading.strategy import assess_htf_trend, decide_signal
from app.utils.utils import safe_float

STATE = BotState.load_or_new()
LAST_MARKET_STATUS: str | None = None


# ─────────────────────────────────────────────
# Candle Close Timer
# รอให้ candle M15 ปิดก่อนเข้า trade
# ─────────────────────────────────────────────

def _seconds_to_candle_close(now: datetime, tf_minutes: int = 15) -> int:
    """วินาทีที่เหลือจนกว่า candle จะปิด"""
    tf_sec    = tf_minutes * 60
    elapsed   = (now.minute % tf_minutes) * 60 + now.second
    remaining = tf_sec - elapsed
    return remaining


def _near_candle_close(now: datetime, tf_minutes: int = 15) -> bool:
    """True ถ้าเหลือน้อยกว่า CANDLE_CLOSE_WAIT_SEC วิก่อน candle close"""
    remaining = _seconds_to_candle_close(now, tf_minutes)
    return remaining <= cfg.CANDLE_CLOSE_WAIT_SEC


# ─────────────────────────────────────────────
# Smart Sleep
# ─────────────────────────────────────────────

def _in_any_session(now: datetime) -> bool:
    t = now.time()
    sessions = [
        (dtime(*cfg.AI_ASIAN_START_HHMM),  dtime(*cfg.AI_ASIAN_END_HHMM)),
        (dtime(*cfg.AI_LONDON_START_HHMM), dtime(*cfg.AI_LONDON_END_HHMM)),
        (dtime(*cfg.AI_NY_START_HHMM),     dtime(*cfg.AI_NY_END_HHMM)),
    ]
    for start, end in sessions:
        if start <= end:
            if start <= t <= end: return True
        else:
            if t >= start or t <= end: return True
    return False


def _seconds_to_next_session(now: datetime) -> int:
    starts  = [dtime(*cfg.AI_ASIAN_START_HHMM),
               dtime(*cfg.AI_LONDON_START_HHMM),
               dtime(*cfg.AI_NY_START_HHMM)]
    min_wait = 8 * 3600
    for s in starts:
        target = now.replace(hour=s.hour, minute=s.minute, second=0, microsecond=0)
        if target <= now: target += timedelta(days=1)
        wait = int((target - now).total_seconds())
        if wait < min_wait: min_wait = wait
    return max(60, min_wait)


def smart_sleep(now: datetime, default_sec: int = 15) -> None:
    if _in_any_session(now):
        time.sleep(default_sec)
        return
    wait = _seconds_to_next_session(now)
    if STATE.should_log("off_session_sleep", 1800):
        next_dt = datetime.now() + timedelta(seconds=wait)
        print(f"[bot] off-session — sleep {wait // 60} min -> {next_dt.strftime('%H:%M')}")
        log_event({"event": "off_session_sleep",
                   "sleep_min": wait // 60,
                   "next_session": next_dt.strftime("%H:%M")})
    time.sleep(min(wait, 3600))


# ─────────────────────────────────────────────
# Logging
# ─────────────────────────────────────────────

def log_event(data: dict) -> bool:
    payload = {
        "timestamp": datetime.now().isoformat(),
        "symbol":    cfg.SYMBOL,
        "tf":        cfg.TIMEFRAME,
    }
    payload.update(data)
    try:
        ok = append_log(cfg.GOOGLE_CREDS_JSON, cfg.SHEET_ID, cfg.SHEET_TAB, payload)
        STATE.consecutive_log_failures = 0 if ok else STATE.consecutive_log_failures + 1
        return ok
    except Exception as e:
        STATE.consecutive_log_failures += 1
        print(f"[log] ERROR: {e}")
        return False


# ─────────────────────────────────────────────
# Daily reset
# ─────────────────────────────────────────────

def reset_daily():
    today = date.today().isoformat()
    if STATE.today != today:
        if cfg.DAILY_SUMMARY_ON_ROLLOVER:
            summarize_day(STATE.today, cfg.MAGIC, log_event)
        if cfg.SHEET_AUTO_TRIM:
            try:
                trim_sheet_logs(cfg.GOOGLE_CREDS_JSON, cfg.SHEET_ID, cfg.SHEET_TAB,
                                keep_last_rows=cfg.SHEET_KEEP_LAST_ROWS)
            except Exception as e:
                print(f"[sheets] trim error: {e}")
        STATE.reset_for_new_day(today)


# ─────────────────────────────────────────────
# MT5
# ─────────────────────────────────────────────

def ensure_mt5_alive() -> bool:
    try:
        if mt5.terminal_info() is not None and mt5.account_info() is not None:
            if STATE.safe_mode:
                STATE.exit_safe_mode()
                log_event({"event": "safe_mode_exit", "reason": "mt5 restored"})
            return True
        try: mt5.shutdown()
        except Exception: pass
        connect()
        ensure_symbol(cfg.SYMBOL)
        if mt5.terminal_info() is not None and mt5.account_info() is not None:
            if STATE.safe_mode:
                STATE.exit_safe_mode()
                log_event({"event": "safe_mode_exit", "reason": "mt5 reconnected"})
            return True
        return False
    except Exception as e:
        print(f"[mt5] reconnect error: {e}")
        return False


def is_market_open() -> tuple[bool, str]:
    info = mt5.symbol_info(cfg.SYMBOL)
    if info is None: return False, "symbol_info_none"
    try:
        if not getattr(info, "visible", True): mt5.symbol_select(cfg.SYMBOL, True)
    except Exception: pass
    if int(getattr(info, "trade_mode", 0) or 0) == 0: return False, "trade_disabled"
    tick = mt5.symbol_info_tick(cfg.SYMBOL)
    if tick is None: return False, "no_tick"
    if float(getattr(tick, "bid", 0.0) or 0.0) <= 0: return False, "no_valid_prices"
    return True, "ok"


# ─────────────────────────────────────────────
# Order
# ─────────────────────────────────────────────

def _normalize_volume(lot: float, info) -> float:
    vol_min  = float(getattr(info, "volume_min",  0.01) or 0.01)
    vol_max  = float(getattr(info, "volume_max",  100.) or 100.)
    vol_step = float(getattr(info, "volume_step", 0.01) or 0.01)
    lot = max(vol_min, min(vol_max, lot))
    return round(round(lot / vol_step) * vol_step, 2)


def _normalize_stops(action: str, entry: float, sl: float, tp: float, info):
    point       = float(info.point)
    digits      = int(info.digits)
    stops_level = int(getattr(info, "trade_stops_level", 0) or 0)
    min_dist    = max(point * stops_level, point * 35)
    if action == "BUY":
        if (entry - sl) < min_dist: sl = entry - min_dist
        if (tp - entry) < min_dist: tp = entry + min_dist
    else:
        if (sl - entry) < min_dist: sl = entry + min_dist
        if (entry - tp) < min_dist: tp = entry - min_dist
    return round(sl, digits), round(tp, digits)


def _dynamic_deviation(atr_val: float, point: float) -> int:
    if point <= 0 or atr_val <= 0: return 40
    return max(20, min(int(atr_val / point * 0.25), 80))


def place_order(action: str, lot: float, sl: float, tp: float, atr_val: float = 0.0):
    info = mt5.symbol_info(cfg.SYMBOL)
    tick = mt5.symbol_info_tick(cfg.SYMBOL)
    if info is None or tick is None: return None, "symbol_or_tick_missing"

    price      = tick.ask if action == "BUY" else tick.bid
    sl, tp     = _normalize_stops(action, price, sl, tp, info)
    lot        = _normalize_volume(lot, info)
    order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
    deviation  = _dynamic_deviation(atr_val, float(info.point))

    last_result, last_status = None, "unknown"
    for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
        result = mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       cfg.SYMBOL,
            "volume":       float(lot),
            "type":         order_type,
            "price":        float(price),
            "sl":           float(sl),
            "tp":           float(tp),
            "deviation":    deviation,
            "magic":        cfg.MAGIC,
            "comment":      "OpenClaw-V7.2",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": filling,
        })
        last_result = result
        if result is None:
            last_status = f"send_none filling={filling}"
            continue
        if result.retcode == mt5.TRADE_RETCODE_DONE:
            return result, f"ok filling={filling}"
        last_status = f"retcode={result.retcode} filling={filling}"
    return last_result, last_status


# ─────────────────────────────────────────────
# Main loop
# ─────────────────────────────────────────────

def main():
    global LAST_MARKET_STATUS

    connect()
    ensure_symbol(cfg.SYMBOL)
    print("OpenClaw V7.2 starting...")

    start_log_worker(cfg.GOOGLE_CREDS_JSON, cfg.SHEET_ID, cfg.SHEET_TAB)
    ensure_sheet_header(cfg.GOOGLE_CREDS_JSON, cfg.SHEET_ID, cfg.SHEET_TAB)

    if cfg.SHEET_AUTO_TRIM:
        try:
            trim_sheet_logs(cfg.GOOGLE_CREDS_JSON, cfg.SHEET_ID, cfg.SHEET_TAB,
                            keep_last_rows=cfg.SHEET_KEEP_LAST_ROWS)
        except Exception as e:
            print(f"[sheets] startup trim: {e}")

    notify_telegram(
        cfg.NOTIFY_ENABLED, cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
        f"<b>OpenClaw V7.2</b> started\n{cfg.SYMBOL} | {cfg.TIMEFRAME} | HTF {cfg.HTF_TIMEFRAME}"
    )
    log_event({"event": "bot_start"})

    while True:
        try:
            reset_daily()
            now = datetime.now()

            # 1. MT5
            if not ensure_mt5_alive():
                STATE.consecutive_mt5_failures += 1
                if STATE.consecutive_mt5_failures >= cfg.SAFE_MODE_MAX_MT5_FAILS:
                    STATE.enter_safe_mode("mt5 unavailable")
                time.sleep(cfg.SAFE_MODE_RETRY_SEC if STATE.safe_mode else 10)
                continue
            STATE.consecutive_mt5_failures = 0

            # 2. Market open
            market_open, market_reason = is_market_open()
            if not market_open:
                if LAST_MARKET_STATUS != "closed":
                    log_event({"event": "market_closed", "reason": market_reason})
                    LAST_MARKET_STATUS = "closed"
                # วันเสาร์-อาทิตย์ sleep 1 ชม. แทน loop ถี่
                if now.weekday() in (5, 6):  # 5=Sat, 6=Sun
                    if STATE.should_log("weekend_sleep", 3600):
                        print(f"[bot] weekend — market closed, sleeping 1hr")
                    time.sleep(3600)
                else:
                    time.sleep(cfg.MARKET_CLOSED_SLEEP_SEC)
                continue
            if LAST_MARKET_STATUS != "open":
                log_event({"event": "market_open"})
                LAST_MARKET_STATUS = "open"

            # 3. Health
            if cfg.LOG_HEALTH_SNAPSHOT and STATE.should_log("health", cfg.HEALTH_LOG_EVERY_SEC):
                log_health_snapshot(STATE, cfg.SYMBOL, cfg.TIMEFRAME, get_rates, log_event)

            # 4. Closed trades scan
            if STATE.should_log("closed_scan", cfg.CLOSED_TRADE_SCAN_EVERY_SEC):
                scan_closed_trades(STATE, cfg.MAGIC, cfg.SYMBOL, log_event)

            if STATE.safe_mode:
                time.sleep(cfg.SAFE_MODE_RETRY_SEC)
                continue

            # 5. Pause
            if STATE.pause_active(now):
                if cfg.LOG_PAUSE_STATE and STATE.should_log("pause", 120):
                    log_event({"event": "pause_active", "reason": STATE.pause_reason})
                time.sleep(30)
                continue

            # 6. News
            manual_block, manual_reason = is_in_news_blackout(
                now, cfg.NEWS_BLACKOUT_ENABLED, cfg.NEWS_BLACKOUT_WINDOWS,
                cfg.NEWS_BUFFER_MIN_BEFORE, cfg.NEWS_BUFFER_MIN_AFTER,
            )
            api_block, api_title = is_news_time(cfg.NEWS_BUFFER_MIN_BEFORE)
            if manual_block or api_block:
                if cfg.LOG_NEWS_BLOCK and STATE.should_log("news_block", 300):
                    log_event({"event": "halt_news",
                               "reason": manual_reason if manual_block else api_title})
                time.sleep(60)
                continue

            # 7. Spread
            sp = spread_points(cfg.SYMBOL)
            if sp > cfg.MAX_SPREAD_POINTS:
                if cfg.LOG_SKIP_SPREAD and STATE.should_log("spread", 120):
                    log_event({"event": "skip_spread", "spread": sp})
                smart_sleep(now)
                continue

            # 8. Account
            acc = mt5.account_info()
            if acc is None:
                time.sleep(10)
                continue

            balance = float(acc.balance)
            equity  = float(acc.equity)
            STATE.update_equity_peak(equity)

            if equity <= balance * (1.0 - cfg.EQUITY_DRAWDOWN_STOP_PCT):
                log_event({"event": "equity_drawdown_stop",
                           "balance": round(balance, 2), "equity": round(equity, 2)})
                time.sleep(60)
                continue

            profit_today, cons_losses = today_deals_profit(cfg.MAGIC)
            if profit_today <= -(balance * cfg.MAX_DAILY_LOSS_PCT):
                log_event({"event": "halt_daily_loss",
                           "balance": round(balance, 2),
                           "profit_today": round(profit_today, 2)})
                time.sleep(60)
                continue

            if cons_losses >= cfg.LOSS_STREAK_PAUSE_COUNT:
                pause_until = now + timedelta(minutes=cfg.LOSS_STREAK_PAUSE_MINUTES)
                STATE.pause(pause_until, f"loss_streak({cons_losses})")
                log_event({"event": "loss_streak_pause", "streak": cons_losses})
                time.sleep(30)
                continue

            # 9. Position management
            positions = positions_by_magic(cfg.SYMBOL, cfg.MAGIC)
            if positions:
                if STATE.can_trail(now, cfg.TRAILING_CHECK_EVERY_SEC):
                    info_sym = mt5.symbol_info(cfg.SYMBOL)
                    if info_sym:
                        df_m  = get_rates(cfg.SYMBOL, getattr(cfg, "TIMEFRAME", "M5"), 300)
                        dyn_m = compute_dynamic_trade_params(
                            df=df_m, entry_type="continuation", final_score=65,
                            point=float(info_sym.point),
                            fallback_sl_mult=cfg.SL_ATR_MULT,
                            fallback_tp_rr=cfg.TP_RR,
                        )
                        trail_positions_atr(
                            cfg.SYMBOL, cfg.MAGIC, df_m,
                            cfg.TRAILING_ENABLED, dyn_m["trailing_atr_mult"],
                            breakeven_enabled=cfg.BREAKEVEN_ENABLED,
                            breakeven_trigger_atr=dyn_m["breakeven_trigger_atr"],
                            breakeven_lock_points=cfg.BREAKEVEN_LOCK_POINTS,
                            trailing_start_atr=dyn_m["trailing_start_atr"],
                            partial_tp_enabled=cfg.PARTIAL_TP_ENABLED,
                            partial_tp_trigger_r=cfg.PARTIAL_TP_TRIGGER_R,
                            partial_tp_close_pct=cfg.PARTIAL_TP_CLOSE_PCT,
                            partial_taken_positions=STATE.partial_taken_positions,
                        )
                        STATE.mark_trail(now)
                        
                # --- Grid Martingale Entry (ไม้แก้ตามระยะ) ---
                if len(positions) < getattr(cfg, "MAX_OPEN_TRADES", 1):
                    last_pos = sorted(positions, key=lambda p: p.time)[-1]
                    info_sym = mt5.symbol_info(cfg.SYMBOL)
                    tick_sym = mt5.symbol_info_tick(cfg.SYMBOL)
                    step_points = getattr(cfg, "MARTINGALE_STEP_POINTS", 150)
                    
                    if info_sym and tick_sym and step_points > 0:
                        point = float(info_sym.point)
                        dist = 0.0
                        action = "BUY" if last_pos.type == mt5.POSITION_TYPE_BUY else "SELL"
                        
                        if action == "BUY":
                            dist = (last_pos.price_open - tick_sym.ask) / point
                        else:
                            dist = (tick_sym.bid - last_pos.price_open) / point
                            
                        if dist >= step_points:
                            df_grid = get_rates(cfg.SYMBOL, getattr(cfg, "TIMEFRAME", "M5"), 300)
                            dyn_grid = compute_dynamic_trade_params(
                                df=df_grid, entry_type="grid", final_score=50,
                                point=point, fallback_sl_mult=cfg.SL_ATR_MULT, fallback_tp_rr=cfg.TP_RR,
                            )
                            m_level = len(positions) + 1
                            lot = calc_lot(
                                cfg.SYMBOL, cfg.RISK_PCT, int(dyn_grid["sl_points"]), cfg.MIN_LOT, cfg.MAX_LOT,
                                martingale_multiplier=getattr(cfg, "MARTINGALE_MULTIPLIER", 1.5),
                                martingale_level=m_level,
                            )
                            lot = _normalize_volume(lot, info_sym)
                            entry_price = tick_sym.ask if action == "BUY" else tick_sym.bid
                            sl_pts, tp_pts = int(dyn_grid["sl_points"]), int(dyn_grid["tp_points"])
                            sl, tp = sl_tp_from_points(entry_price, action, sl_pts, tp_pts, point)
                            
                            res, status = place_order(action, lot, sl, tp, dyn_grid["atr14"])
                            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                                STATE.mark_trade(now)
                                log_event({"event": "trade_opened", "signal": action, "entry_type": "grid", "score": dist, "reason": "grid_recovery", "m_level": m_level})
                                notify_telegram(cfg.NOTIFY_ENABLED, cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                                    f"<b>GRID {action}</b> {cfg.SYMBOL}\nLv{m_level} | lot={lot} | dist={dist:.1f} pts\nSL={sl} TP={tp}")
                                time.sleep(15)
                                continue

                if len(positions) >= getattr(cfg, "MAX_OPEN_TRADES", 1):
                    time.sleep(cfg.TRAILING_CHECK_EVERY_SEC)
                    continue

            # 10. Max trades
            if STATE.trades_today >= getattr(cfg, "MAX_TRADES_PER_DAY", 50):
                if STATE.should_log("max_trades", 600):
                    log_event({"event": "max_trades_reached", "trades_today": STATE.trades_today})
                smart_sleep(now, 60)
                continue

            # ── Candle Close Wait ──────────────────
            # รอให้ candle เกือบปิดก่อน evaluate signal
            import re
            m = re.search(r'\d+', cfg.TIMEFRAME)
            tf_min = int(m.group()) if m else 5
            remaining = _seconds_to_candle_close(now, tf_min)
            if remaining > cfg.CANDLE_CLOSE_WAIT_SEC:
                # ยังไม่ถึงเวลา — sleep ไปก่อน
                sleep_time = min(remaining - cfg.CANDLE_CLOSE_WAIT_SEC, 30)
                time.sleep(max(5, sleep_time))
                continue

            # 11. Signal
            df     = get_rates(cfg.SYMBOL, cfg.TIMEFRAME, 300)
            df_htf = get_rates(cfg.SYMBOL, cfg.HTF_TIMEFRAME, 300)
            sig    = decide_signal(df)
            htf    = assess_htf_trend(df_htf)
            ctx    = build_signal_context(df, cfg.PULLBACK_ZONE_ATR_MULT,
                                          cfg.CONTINUATION_ZONE_ATR_MULT)

            if sig.action == "NONE":
                if cfg.LOG_NO_SETUP and STATE.should_log("no_setup", cfg.INFO_LOG_EVERY_SEC):
                    log_event({"event": "no_setup", "score": sig.score,
                               "reason": sig.reason, **ctx})
                time.sleep(15)
                continue

            # 12. HTF H4 filter
            htf_penalty = 0
            if htf.mode == "NONE":
                if cfg.LOG_BLOCKED_HTF and STATE.should_log("htf_none", 120):
                    log_event({"event": "blocked_htf_none", "signal": sig.action,
                               "reason": htf.reason, **ctx})
                time.sleep(15)
                continue

            if htf.mode == "NEUTRAL":
                htf_penalty = -5

            if sig.action == "BUY" and htf.mode == "SELL_ONLY":
                if cfg.LOG_BLOCKED_HTF and STATE.should_log("htf_conflict", 120):
                    log_event({"event": "blocked_htf_conflict", "signal": "BUY",
                               "htf": htf.mode, **ctx})
                time.sleep(15)
                continue

            if sig.action == "SELL" and htf.mode == "BUY_ONLY":
                if cfg.LOG_BLOCKED_HTF and STATE.should_log("htf_conflict", 120):
                    log_event({"event": "blocked_htf_conflict", "signal": "SELL",
                               "htf": htf.mode, **ctx})
                time.sleep(15)
                continue

            # 13. Duplicate
            bars_min = cfg.SAME_DIRECTION_REENTRY_BARS * tf_min
            if STATE.is_duplicate_setup(sig.setup_key, now, bars_min):
                if cfg.LOG_DUPLICATE_SETUP and STATE.should_log("dup_setup", 60):
                    log_event({"event": "duplicate_setup",
                               "setup_key": sig.setup_key, **ctx})
                time.sleep(15)
                continue

            # 14. AI
            base_score  = sig.score + htf_penalty
            ai_allow    = True
            ai_reason   = "AI disabled"
            final_score = base_score

            if cfg.OPENCLAW_AI_ENABLED:
                ai_allow, final_score, ai_reason = openclaw_ai_evaluate(
                    df=df,
                    base_action=sig.action,
                    base_score=base_score,
                    local_dt=now,
                    session_enabled=cfg.AI_SESSION_FILTER,
                    regime_enabled=cfg.AI_REGIME_FILTER,
                    vol_enabled=cfg.AI_VOL_FILTER,
                    trend_strength_enabled=cfg.AI_TREND_STRENGTH,
                    london=(*cfg.AI_LONDON_START_HHMM, *cfg.AI_LONDON_END_HHMM),
                    ny=(*cfg.AI_NY_START_HHMM,         *cfg.AI_NY_END_HHMM),
                    asian=(*cfg.AI_ASIAN_START_HHMM,   *cfg.AI_ASIAN_END_HHMM),
                )

            if not ai_allow:
                if cfg.LOG_BLOCKED_AI and STATE.should_log("blocked_ai", 120):
                    log_event({"event": "blocked_ai", "signal": sig.action,
                               "score": final_score, "reason": ai_reason, **ctx})
                time.sleep(15)
                continue

            if final_score < cfg.MIN_SCORE_TO_TRADE:
                if cfg.LOG_BLOCKED_SCORE and STATE.should_log("blocked_score", 120):
                    log_event({"event": "blocked_score", "signal": sig.action,
                               "score": final_score, "reason": sig.reason, **ctx})
                time.sleep(15)
                continue

            # 15. SL/TP
            info_sym = mt5.symbol_info(cfg.SYMBOL)
            tick_sym = mt5.symbol_info_tick(cfg.SYMBOL)
            if info_sym is None or tick_sym is None:
                time.sleep(10)
                continue

            dyn    = compute_dynamic_trade_params(
                df=df, entry_type=sig.entry_type, final_score=final_score,
                point=float(info_sym.point),
                fallback_sl_mult=cfg.SL_ATR_MULT, fallback_tp_rr=cfg.TP_RR,
            )
            sl_pts = int(dyn["sl_points"])
            tp_pts = int(dyn["tp_points"])
            if sl_pts <= 0 or tp_pts <= 0:
                time.sleep(10)
                continue

            # Martingale tracking
            same_dir_pos = [p for p in (positions or []) if (p.type == mt5.POSITION_TYPE_BUY and sig.action == "BUY") or (p.type == mt5.POSITION_TYPE_SELL and sig.action == "SELL")]
            m_level = min(len(same_dir_pos) + 1, getattr(cfg, "MARTINGALE_MAX_LEVELS", 5))

            lot   = calc_lot(
                cfg.SYMBOL, cfg.RISK_PCT, sl_pts, cfg.MIN_LOT, cfg.MAX_LOT,
                martingale_multiplier=getattr(cfg, "MARTINGALE_MULTIPLIER", 1.0),
                martingale_level=m_level,
            )
            lot   = _normalize_volume(lot, info_sym)
            entry = tick_sym.ask if sig.action == "BUY" else tick_sym.bid
            sl, tp = sl_tp_from_points(entry, sig.action, sl_pts, tp_pts,
                                        float(info_sym.point))

            log_event({
                "m_level":     m_level,
                "event":       "trade_attempt",
                "signal":      sig.action,
                "entry_type":  sig.entry_type,
                "score":       final_score,
                "reason":      sig.reason,
                "safe_reason": ai_reason,
                "atr14":       dyn["atr14"],
                "vol_ratio":   dyn["vol_ratio"],
                "close_price": safe_float(entry),
                "spread":      sp,
            })

            # 16. Order
            result, status = place_order(sig.action, lot, sl, tp, dyn["atr14"])

            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                STATE.remember_setup(sig.setup_key, now)
                STATE.mark_trade(now)
                log_event({
                    "event":      "trade_opened",
                    "signal":     sig.action,
                    "entry_type": sig.entry_type,
                    "score":      final_score,
                    "reason":     status,
                    "close_price": safe_float(entry),
                })
                notify_telegram(
                    cfg.NOTIFY_ENABLED, cfg.TELEGRAM_BOT_TOKEN, cfg.TELEGRAM_CHAT_ID,
                    (f"<b>OPEN {sig.action}</b> {cfg.SYMBOL}\n"
                     f"type={sig.entry_type} | lot={lot} (Lv{m_level}) | score={final_score}\n"
                     f"SL x{dyn['sl_atr_mult']} | RR={dyn['tp_rr']} | {sig.reason}")
                )
            else:
                log_event({
                    "event":      "trade_failed",
                    "signal":     sig.action,
                    "entry_type": sig.entry_type,
                    "score":      final_score,
                    "reason":     status,
                    "close_price": safe_float(entry),
                })

            time.sleep(15)

        except KeyboardInterrupt:
            print("\n[bot] stopped by user")
            log_event({"event": "bot_stop", "reason": "keyboard_interrupt"})
            break
        except Exception as e:
            print(f"[bot] ERROR: {e}")
            if STATE.should_log("bot_error", 60):
                log_event({"event": "bot_error", "reason": str(e)})
            time.sleep(15)

    shutdown()
    print("[bot] shutdown complete")


if __name__ == "__main__":
    main()
