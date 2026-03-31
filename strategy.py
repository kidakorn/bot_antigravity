"""
OpenClaw V7.2 — Strategy Engine
M15 entry | H4 HTF | Simple filter | Bounce Guard

v7.2:
  - ลด filter เหลือ EMA + MACD + RSI
  - ตัด volume, engulfing, pin bar ออก (ซับซ้อนเกิน)
  - Bounce Guard คง
  - assess_htf_trend ใช้ H4
"""
from dataclasses import dataclass
import pandas as pd

from config import (
    BOUNCE_GUARD_ATR_MULT,
    BOUNCE_GUARD_BARS,
    CONTINUATION_RSI_BUY_MAX,
    CONTINUATION_RSI_BUY_MIN,
    CONTINUATION_RSI_SELL_MAX,
    CONTINUATION_RSI_SELL_MIN,
    CONTINUATION_ZONE_ATR_MULT,
    PULLBACK_RSI_BUY_MAX,
    PULLBACK_RSI_BUY_MIN,
    PULLBACK_RSI_SELL_MAX,
    PULLBACK_RSI_SELL_MIN,
    PULLBACK_ZONE_ATR_MULT,
)
from utils import atr, ema, macd, rsi, safe_float


@dataclass
class Signal:
    action: str
    score: int
    reason: str
    entry_type: str
    setup_key: str


@dataclass
class HTFTrend:
    mode: str   # BUY_ONLY | SELL_ONLY | NEUTRAL | NONE
    reason: str


def _ema_slope(series: pd.Series, period: int, lookback: int = 3) -> float:
    e = ema(series, period)
    if len(e) < lookback + 2:
        return 0.0
    return float(e.iloc[-2]) - float(e.iloc[-2 - lookback])


def _candle_parts(o, c, h, l):
    rng = max(h - l, 1e-9)
    body = abs(c - o)
    return rng, body / rng, h - max(o, c), min(o, c) - l


# ─────────────────────────────────────────────
# Bounce Guard
# ─────────────────────────────────────────────

def _bounce_guard(df: pd.DataFrame, action: str, atr_val: float) -> tuple[bool, str]:
    if atr_val <= 0 or len(df) < BOUNCE_GUARD_BARS + 3:
        return False, ""
    closes    = df["close"].iloc[-(BOUNCE_GUARD_BARS + 3):-2]
    threshold = atr_val * BOUNCE_GUARD_ATR_MULT
    if action == "SELL":
        bounce = float(closes.iloc[-1]) - float(closes.min())
        if bounce >= threshold:
            return True, f"bounce_guard:SELL ({bounce:.1f}>{threshold:.1f})"
    if action == "BUY":
        drop = float(closes.max()) - float(closes.iloc[-1])
        if drop >= threshold:
            return True, f"bounce_guard:BUY ({drop:.1f}>{threshold:.1f})"
    return False, ""


# ─────────────────────────────────────────────
# H4 HTF Trend
# ─────────────────────────────────────────────

def assess_htf_trend(df_htf: pd.DataFrame) -> HTFTrend:
    if len(df_htf) < 200:
        return HTFTrend("NONE", "HTF not enough bars")

    close = df_htf["close"]
    e20   = ema(close, 20)
    e50   = ema(close, 50)
    e200  = ema(close, 200)
    macd_line, sig_line, _ = macd(close)

    idx    = df_htf.index[-2]
    e20_v  = safe_float(e20.loc[idx])
    e50_v  = safe_float(e50.loc[idx])
    e200_v = safe_float(e200.loc[idx])
    macd_v = safe_float(macd_line.loc[idx])
    sig_v  = safe_float(sig_line.loc[idx])
    sl20   = _ema_slope(close, 20)
    sl50   = _ema_slope(close, 50)

    strong_bull = e20_v > e50_v > e200_v and macd_v > sig_v and sl20 > 0
    weak_bull   = e20_v > e50_v and macd_v >= sig_v
    strong_bear = e20_v < e50_v < e200_v and macd_v < sig_v and sl20 < 0
    weak_bear   = e20_v < e50_v and macd_v <= sig_v

    if strong_bull: return HTFTrend("BUY_ONLY",  "H4 strong bull")
    if strong_bear: return HTFTrend("SELL_ONLY", "H4 strong bear")
    if weak_bull:   return HTFTrend("BUY_ONLY",  "H4 weak bull")
    if weak_bear:   return HTFTrend("SELL_ONLY", "H4 weak bear")
    return HTFTrend("NEUTRAL", "H4 ranging")


# ─────────────────────────────────────────────
# M15 Signal Engine
# ─────────────────────────────────────────────

def decide_signal(df: pd.DataFrame) -> Signal:
    if len(df) < 200:
        return Signal("NONE", 0, "not enough bars", "none", "none")

    close = df["close"]
    open_ = df["open"]
    high  = df["high"]
    low   = df["low"]

    e20  = ema(close, 20)
    e50  = ema(close, 50)
    e200 = ema(close, 200)
    r    = rsi(close, 14)
    a    = atr(df, 14)
    macd_line, sig_line, hist = macd(close)

    idx       = df.index[-2]
    prev_idx  = df.index[-3]
    prev2_idx = df.index[-4]

    c_v   = safe_float(close.loc[idx])
    o_v   = safe_float(open_.loc[idx])
    h_v   = safe_float(high.loc[idx])
    l_v   = safe_float(low.loc[idx])
    pc_v  = safe_float(close.loc[prev_idx])
    ph_v  = safe_float(high.loc[prev_idx])
    pl_v  = safe_float(low.loc[prev_idx])
    p2h_v = safe_float(high.loc[prev2_idx])
    p2l_v = safe_float(low.loc[prev2_idx])

    e20_v  = safe_float(e20.loc[idx])
    e50_v  = safe_float(e50.loc[idx])
    e200_v = safe_float(e200.loc[idx])
    atr_v  = safe_float(a.loc[idx])
    rsi_v  = safe_float(r.loc[idx], 50.0)
    macd_v = safe_float(macd_line.loc[idx])
    sig_v  = safe_float(sig_line.loc[idx])
    hist_v = safe_float(hist.loc[idx])

    if atr_v <= 0:
        return Signal("NONE", 0, "ATR unavailable", "none", "none")

    rng, body_ratio, upper_wick, lower_wick = _candle_parts(o_v, c_v, h_v, l_v)
    bull_candle = c_v > o_v
    bear_candle = c_v < o_v

    trend_up   = e20_v > e50_v and c_v > e200_v
    trend_down = e20_v < e50_v and c_v < e200_v
    sl50       = _ema_slope(close, 50)

    # Sideway check
    ema_sep = abs(e20_v - e50_v)
    sl20    = _ema_slope(close, 20)
    if ema_sep < 0.008 * atr_v and abs(sl20) < 0.001 * atr_v and body_ratio < 0.15:
        return Signal("NONE", 28, "sideway", "none", "none")

    near_ema50 = abs(c_v - e50_v) <= atr_v * PULLBACK_ZONE_ATR_MULT
    near_ema20 = abs(c_v - e20_v) <= atr_v * CONTINUATION_ZONE_ATR_MULT

    macd_bull = macd_v > sig_v and hist_v >= 0
    macd_bear = macd_v < sig_v and hist_v <= 0

    # ── Score ─────────────────────────────────
    score   = 50
    reasons = []

    if trend_up:
        score += 8; reasons.append("EMA+")
    elif trend_down:
        score += 8; reasons.append("EMA-")
    else:
        reasons.append("EMA_weak")

    if macd_bull:
        score += 6; reasons.append("MACD+")
    elif macd_bear:
        score += 6; reasons.append("MACD-")

    if sl50 > 0 and trend_up:
        score += 3; reasons.append("slope+")
    elif sl50 < 0 and trend_down:
        score += 3; reasons.append("slope-")

    # ── Setups ────────────────────────────────
    cont_buy = (
        trend_up and macd_bull and near_ema20
        and bull_candle and body_ratio >= 0.10
        and c_v >= ph_v
        and CONTINUATION_RSI_BUY_MIN <= rsi_v <= CONTINUATION_RSI_BUY_MAX
    )
    cont_sell = (
        trend_down and macd_bear and near_ema20
        and bear_candle and body_ratio >= 0.10
        and c_v <= pl_v
        and CONTINUATION_RSI_SELL_MIN <= rsi_v <= CONTINUATION_RSI_SELL_MAX
    )
    pull_buy = (
        trend_up and macd_bull and near_ema50
        and bull_candle and body_ratio >= 0.10
        and c_v > pc_v
        and PULLBACK_RSI_BUY_MIN <= rsi_v <= PULLBACK_RSI_BUY_MAX
    )
    pull_sell = (
        trend_down and macd_bear and near_ema50
        and bear_candle and body_ratio >= 0.10
        and c_v < pc_v
        and PULLBACK_RSI_SELL_MIN <= rsi_v <= PULLBACK_RSI_SELL_MAX
    )

    def _buy_bonus(s, r):
        r = r[:]
        if c_v > max(ph_v, p2h_v): s += 5; r.append("fresh_high")
        if lower_wick >= rng * 0.15: s += 3; r.append("tail+")
        r.append(f"RSI{rsi_v:.0f}")
        return s, r

    def _sell_bonus(s, r):
        r = r[:]
        if c_v < min(pl_v, p2l_v): s += 5; r.append("fresh_low")
        if upper_wick >= rng * 0.15: s += 3; r.append("tail-")
        r.append(f"RSI{rsi_v:.0f}")
        return s, r

    if cont_buy:
        blocked, bg = _bounce_guard(df, "BUY", atr_v)
        if blocked: return Signal("NONE", score, bg, "none", "none")
        score += 12
        score, reasons = _buy_bonus(score, reasons)
        return Signal("BUY", min(score, 100), " | ".join(reasons), "continuation", f"BUY_cont_{idx}")

    if cont_sell:
        blocked, bg = _bounce_guard(df, "SELL", atr_v)
        if blocked: return Signal("NONE", score, bg, "none", "none")
        score += 12
        score, reasons = _sell_bonus(score, reasons)
        return Signal("SELL", min(score, 100), " | ".join(reasons), "continuation", f"SELL_cont_{idx}")

    if pull_buy:
        blocked, bg = _bounce_guard(df, "BUY", atr_v)
        if blocked: return Signal("NONE", score, bg, "none", "none")
        score += 10
        score, reasons = _buy_bonus(score, reasons)
        return Signal("BUY", min(score, 100), " | ".join(reasons), "pullback", f"BUY_pull_{idx}")

    if pull_sell:
        blocked, bg = _bounce_guard(df, "SELL", atr_v)
        if blocked: return Signal("NONE", score, bg, "none", "none")
        score += 10
        score, reasons = _sell_bonus(score, reasons)
        return Signal("SELL", min(score, 100), " | ".join(reasons), "pullback", f"SELL_pull_{idx}")

    if near_ema50: reasons.append("near_EMA50")
    if near_ema20: reasons.append("near_EMA20")
    reasons.append(f"RSI{rsi_v:.0f}")
    return Signal("NONE", max(min(score, 100), 0), " | ".join(reasons), "none", "none")
