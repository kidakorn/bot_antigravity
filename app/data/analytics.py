"""
OpenClaw V7 - Analytics
ปรับปรุง:
  - dynamic params calibrate ใหม่ให้ SL จริงกว่า (ไม่ถูก whipsaw บน gold)
  - infer_market_regime ใช้ EMA slope เพิ่มเติม
  - log_health_snapshot เพิ่ม drawdown_pct
"""
from datetime import datetime, timedelta

import MetaTrader5 as mt5
import pandas as pd

from app.utils.utils import atr, ema, rsi, safe_float


# ─────────────────────────────────────────────
# Market regime
# ─────────────────────────────────────────────

def infer_market_regime(df: pd.DataFrame) -> tuple[str, str]:
    close = df["close"]
    e20  = ema(close, 20)
    e50  = ema(close, 50)
    e200 = ema(close, 200)
    a    = atr(df, 14)
    idx  = df.index[-2]

    e20_v  = safe_float(e20.loc[idx])
    e50_v  = safe_float(e50.loc[idx])
    e200_v = safe_float(e200.loc[idx])
    atr_v  = safe_float(a.loc[idx])

    if atr_v <= 0:
        return "unknown", "unknown"

    sep_fast = abs(e20_v - e50_v)
    sep_slow = abs(e50_v - e200_v)

    # slope over 3 bars
    slope20 = float(e20.iloc[-2]) - float(e20.iloc[-5]) if len(e20) >= 5 else 0.0
    slope50 = float(e50.iloc[-2]) - float(e50.iloc[-5]) if len(e50) >= 5 else 0.0

    if sep_fast < 0.18 * atr_v and sep_slow < 0.30 * atr_v:
        return "range", "range market (EMAs flat)"

    if sep_slow >= 0.85 * atr_v and sep_fast >= 0.18 * atr_v and slope50 * slope20 > 0:
        return "trend_strong", "strong trending market"

    return "trend", "trending market"


# ─────────────────────────────────────────────
# Dynamic trade params
# ─────────────────────────────────────────────

def compute_dynamic_trade_params(
    df: pd.DataFrame,
    entry_type: str,
    final_score: int,
    point: float,
    fallback_sl_mult: float = 1.30,
    fallback_tp_rr: float = 1.25,
) -> dict:

    a_val     = safe_float(atr(df, 14).iloc[-2])
    close_val = safe_float(df["close"].iloc[-2])

    def _build(sl_m, tp_r, be_t, ts_a, tr_m):
        sl_pts = max(1, int((a_val * sl_m) / point)) if point > 0 else 1
        tp_pts = max(1, int(sl_pts * tp_r))
        return {
            "atr14": round(a_val, 3),
            "vol_ratio": round(a_val / close_val, 6) if close_val > 0 else 0.0,
            "market_regime": regime,
            "market_reason": regime_reason,
            "sl_atr_mult": round(sl_m, 2),
            "tp_rr": round(tp_r, 2),
            "sl_points": sl_pts,
            "tp_points": tp_pts,
            "breakeven_trigger_atr": round(be_t, 2),
            "trailing_start_atr": round(ts_a, 2),
            "trailing_atr_mult": round(tr_m, 2),
        }

    if a_val <= 0 or point <= 0 or close_val <= 0:
        regime, regime_reason = "unknown", "fallback"
        return _build(fallback_sl_mult, fallback_tp_rr, 0.55, 0.80, 0.85)

    vol_ratio = a_val / close_val
    regime, regime_reason = infer_market_regime(df)

    # ── Base params by entry type + regime ───────────
    if entry_type == "continuation":
        params = {
            "trend_strong": (1.55, 1.40),
            "trend":        (1.40, 1.28),
            "range":        (1.25, 1.05),
        }
    else:  # pullback
        params = {
            "trend_strong": (1.45, 1.25),
            "trend":        (1.35, 1.15),
            "range":        (1.20, 1.00),
        }
    sl_m, tp_r = params.get(regime, params["trend"])

    # ── Score modifiers ──────────────────────────────
    if final_score >= 80:
        tp_r += 0.12; sl_m += 0.05
        be_t, ts_a, tr_m = 0.38, 0.55, 0.65
    elif final_score >= 70:
        tp_r += 0.06
        be_t, ts_a, tr_m = 0.40, 0.60, 0.68
    elif final_score >= 62:
        be_t, ts_a, tr_m = 0.42, 0.65, 0.72
    else:
        tp_r -= 0.05
        be_t, ts_a, tr_m = 0.45, 0.70, 0.78

    # ── Volatility adjustments ────────────────────────
    if vol_ratio >= 0.0050:
        sl_m += 0.10; tp_r += 0.05
    elif vol_ratio <= 0.0008:
        sl_m -= 0.05; tp_r -= 0.05

    # ── Clamp ────────────────────────────────────────
    sl_m = max(1.15, min(sl_m, 1.90))
    tp_r = max(0.95, min(tp_r, 1.60))
    be_t = max(0.35, min(be_t, 0.70))
    ts_a = max(0.50, min(ts_a, 1.10))
    tr_m = max(0.55, min(tr_m, 1.00))

    return _build(sl_m, tp_r, be_t, ts_a, tr_m)


# ─────────────────────────────────────────────
# Signal context for logging
# ─────────────────────────────────────────────

def build_signal_context(
    df: pd.DataFrame,
    pullback_mult: float,
    continuation_mult: float,
) -> dict:
    close = df["close"]
    open_ = df["open"]
    high  = df["high"]
    low   = df["low"]

    e20  = ema(close, 20)
    e50  = ema(close, 50)
    e200 = ema(close, 200)
    r    = rsi(close, 14)
    a    = atr(df, 14)

    idx      = df.index[-2]
    prev_idx = df.index[-3] if len(df.index) >= 3 else idx

    c_v    = safe_float(close.loc[idx])
    o_v    = safe_float(open_.loc[idx])
    h_v    = safe_float(high.loc[idx])
    l_v    = safe_float(low.loc[idx])
    e20_v  = safe_float(e20.loc[idx])
    e50_v  = safe_float(e50.loc[idx])
    e200_v = safe_float(e200.loc[idx])
    rsi_v  = safe_float(r.loc[idx], 50.0)
    atr_v  = safe_float(a.loc[idx])
    ph_v   = safe_float(high.loc[prev_idx], h_v)
    pl_v   = safe_float(low.loc[prev_idx], l_v)

    near_ema50      = atr_v > 0 and abs(c_v - e50_v) <= atr_v * pullback_mult
    continuation_up = atr_v > 0 and e50_v > e200_v and c_v >= e20_v and abs(c_v - e20_v) <= atr_v * continuation_mult and c_v >= ph_v
    continuation_dn = atr_v > 0 and e50_v < e200_v and c_v <= e20_v and abs(c_v - e20_v) <= atr_v * continuation_mult and c_v <= pl_v

    return {
        "close_price":      round(c_v, 3),
        "high_price":       round(h_v, 3),
        "low_price":        round(l_v, 3),
        "ema20":            round(e20_v, 3),
        "ema50":            round(e50_v, 3),
        "ema200":           round(e200_v, 3),
        "rsi14":            round(rsi_v, 2),
        "atr14":            round(atr_v, 3),
        "trend_up":         e50_v > e200_v,
        "trend_down":       e50_v < e200_v,
        "near_ema50":       near_ema50,
        "continuation_up":  continuation_up,
        "continuation_dn":  continuation_dn,
        "candle_bias":      "bull" if c_v > o_v else "bear" if c_v < o_v else "flat",
    }


# ─────────────────────────────────────────────
# Health snapshot
# ─────────────────────────────────────────────

def log_health_snapshot(state, symbol: str, timeframe: str, get_rates_fn, log_event):
    acc  = mt5.account_info()
    tick = mt5.symbol_info_tick(symbol)
    info = mt5.symbol_info(symbol)

    if acc is None or tick is None or info is None:
        return

    df    = get_rates_fn(symbol, timeframe, 200)
    a_val = safe_float(atr(df, 14).iloc[-2])
    cv    = safe_float(df["close"].iloc[-2])

    vol_ratio = a_val / cv if cv > 0 else 0.0
    spread    = int(round((tick.ask - tick.bid) / info.point))

    equity    = float(acc.equity)
    balance   = float(acc.balance)
    drawdown_pct = round((balance - equity) / balance * 100, 2) if balance > 0 else 0.0

    # update rolling equity peak
    state.update_equity_peak(equity)
    peak_dd_pct = round((state.equity_peak - equity) / state.equity_peak * 100, 2) if state.equity_peak > 0 else 0.0

    log_event({
        "event":        "health_snapshot",
        "balance":      round(balance, 2),
        "equity":       round(equity, 2),
        "margin_free":  round(float(acc.margin_free), 2),
        "drawdown_pct": drawdown_pct,
        "peak_dd_pct":  peak_dd_pct,
        "spread":       spread,
        "atr14":        round(a_val, 3),
        "vol_ratio":    round(vol_ratio, 6),
        "trades_today": state.trades_today,
        "safe_mode":    state.safe_mode,
        "safe_reason":  state.safe_reason,
    })


# ─────────────────────────────────────────────
# Scan closed trades
# ─────────────────────────────────────────────

def _day_bounds(day_str: str):
    from datetime import date
    d = datetime.strptime(day_str, "%Y-%m-%d")
    start = datetime(d.year, d.month, d.day)
    return start, start + timedelta(days=1)


def scan_closed_trades(state, magic: int, symbol: str, log_event):
    start, _ = _day_bounds(state.today)
    now = datetime.now()
    deals = mt5.history_deals_get(start, now)
    if deals is None:
        return

    open_ids = set()
    open_pos = mt5.positions_get(symbol=symbol)
    if open_pos:
        for p in open_pos:
            if getattr(p, "magic", None) == magic:
                open_ids.add(getattr(p, "ticket", None))

    by_pos: dict = {}
    for d in deals:
        if getattr(d, "magic", None) != magic:
            continue
        pid    = getattr(d, "position_id", None)
        if pid is None:
            continue
        entry  = getattr(d, "entry", None)
        rec    = by_pos.setdefault(pid, {"out_profit": 0.0, "commission": 0.0, "swap": 0.0,
                                         "symbol": getattr(d, "symbol", symbol),
                                         "time": 0, "has_partial": False})
        if entry == mt5.DEAL_ENTRY_OUT:
            rec["out_profit"]   += float(getattr(d, "profit", 0.0))
            rec["commission"]   += float(getattr(d, "commission", 0.0))
            rec["swap"]         += float(getattr(d, "swap", 0.0))
            rec["time"]          = max(rec["time"], getattr(d, "time", 0))
        elif entry == mt5.DEAL_ENTRY_OUT_BY:
            rec["has_partial"] = True

    for pid, rec in by_pos.items():
        if pid in state.processed_closed_positions or pid in open_ids:
            continue
        net  = rec["out_profit"] + rec["swap"] + rec["commission"]
        outcome = "win" if net > 0 else "loss" if net < 0 else "breakeven"
        ctime = datetime.fromtimestamp(rec["time"]).isoformat() if rec["time"] else ""
        log_event({
            "event":        "closed_trade",
            "position_id":  pid,
            "close_time":   ctime,
            "symbol_closed": rec["symbol"],
            "profit":       round(rec["out_profit"], 2),
            "commission":   round(rec["commission"], 2),
            "swap":         round(rec["swap"], 2),
            "net_profit":   round(net, 2),
            "outcome":      outcome,
            "partial_taken": rec["has_partial"],
        })
        state.processed_closed_positions.add(pid)

    state.partial_taken_positions = {
        p for p in state.partial_taken_positions if p in open_ids
    }


# ─────────────────────────────────────────────
# Daily summary
# ─────────────────────────────────────────────

def summarize_day(day_str: str, magic: int, log_event):
    start, end = _day_bounds(day_str)
    deals = mt5.history_deals_get(start, end)
    if not deals:
        return

    by_pos: dict = {}
    for d in deals:
        if getattr(d, "magic", None) != magic:
            continue
        if getattr(d, "entry", None) != mt5.DEAL_ENTRY_OUT:
            continue
        pid = getattr(d, "position_id", None)
        if pid is None:
            continue
        rec = by_pos.setdefault(pid, {"profit": 0.0, "commission": 0.0, "swap": 0.0})
        rec["profit"]     += float(getattr(d, "profit", 0.0))
        rec["commission"] += float(getattr(d, "commission", 0.0))
        rec["swap"]       += float(getattr(d, "swap", 0.0))

    if not by_pos:
        return

    total = len(by_pos)
    wins = losses = be = 0
    gross_profit = gross_loss = net_profit = 0.0

    for rec in by_pos.values():
        net = rec["profit"] + rec["swap"] + rec["commission"]
        net_profit += net
        if net > 0:
            wins += 1; gross_profit += net
        elif net < 0:
            losses += 1; gross_loss += abs(net)
        else:
            be += 1

    pf = gross_profit / gross_loss if gross_loss > 0 else 0.0
    log_event({
        "event":         "daily_summary",
        "day":           day_str,
        "trades":        total,
        "wins":          wins,
        "losses":        losses,
        "breakeven":     be,
        "winrate_pct":   round(wins / total * 100, 2) if total else 0.0,
        "net_profit":    round(net_profit, 2),
        "gross_profit":  round(gross_profit, 2),
        "gross_loss":    round(gross_loss, 2),
        "profit_factor": round(pf, 2),
    })
