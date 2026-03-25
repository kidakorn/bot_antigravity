"""
OpenClaw V7 - Strategy Engine
ปรับปรุงจาก V6:
  - เพิ่ม volume confirmation (tick volume proxy)
  - เพิ่ม candle pattern: engulfing, pin bar → quality filter
  - HTF: ผ่อนเงื่อนไขเป็น BUY_ONLY/SELL_ONLY/NEUTRAL (เดิมแข็งเกิน)
  - sideway detection ใช้ EMA slope แทน distance เพียงอย่างเดียว
  - score calibrate ใหม่ให้สม่ำเสมอ
"""
from dataclasses import dataclass

import pandas as pd

from config import (
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
    action: str        # BUY | SELL | NONE
    score: int
    reason: str
    entry_type: str    # continuation | pullback | none
    setup_key: str


@dataclass
class HTFTrend:
    mode: str          # BUY_ONLY | SELL_ONLY | NEUTRAL | NONE
    reason: str


# ─────────────────────────────────────────────
# Candle helpers
# ─────────────────────────────────────────────

def _candle_parts(o: float, c: float, h: float, l: float):
    rng = max(h - l, 1e-9)
    body = abs(c - o)
    body_ratio = body / rng
    upper_wick = h - max(o, c)
    lower_wick = min(o, c) - l
    return rng, body_ratio, upper_wick, lower_wick


def _is_bullish_engulfing(c_o, c_c, p_o, p_c) -> bool:
    """แท่งปัจจุบัน bullish กลืน body แท่งก่อน (bearish)"""
    return c_c > c_o and p_c < p_o and c_c >= p_o and c_o <= p_c


def _is_bearish_engulfing(c_o, c_c, p_o, p_c) -> bool:
    return c_c < c_o and p_c > p_o and c_c <= p_o and c_o >= p_c


def _is_bullish_pin_bar(o, c, h, l) -> bool:
    """Lower wick ≥ 55% ของ range, body ≤ 35%"""
    rng, body_ratio, _, lower_wick = _candle_parts(o, c, h, l)
    return lower_wick / rng >= 0.55 and body_ratio <= 0.35


def _is_bearish_pin_bar(o, c, h, l) -> bool:
    rng, body_ratio, upper_wick, _ = _candle_parts(o, c, h, l)
    return upper_wick / rng >= 0.55 and body_ratio <= 0.35


def _ema_slope(series: pd.Series, period: int, lookback: int = 3) -> float:
    """slope ของ EMA: บวก = ขึ้น, ลบ = ลง"""
    e = ema(series, period)
    if len(e) < lookback + 1:
        return 0.0
    return float(e.iloc[-2]) - float(e.iloc[-2 - lookback])


# ─────────────────────────────────────────────
# HTF Trend Assessment
# ─────────────────────────────────────────────

def assess_htf_trend(df_htf: pd.DataFrame) -> HTFTrend:
    if len(df_htf) < 200:
        return HTFTrend("NONE", "HTF not enough bars")

    close = df_htf["close"]
    e20 = ema(close, 20)
    e50 = ema(close, 50)
    e200 = ema(close, 200)
    macd_line, signal_line, hist = macd(close)

    idx = df_htf.index[-2]

    e20_v = safe_float(e20.loc[idx])
    e50_v = safe_float(e50.loc[idx])
    e200_v = safe_float(e200.loc[idx])
    macd_v = safe_float(macd_line.loc[idx])
    sig_v = safe_float(signal_line.loc[idx])
    hist_v = safe_float(hist.loc[idx])

    slope20 = _ema_slope(close, 20)
    slope50 = _ema_slope(close, 50)

    # Strong bull: alignment + slope + MACD
    strong_bull = e20_v > e50_v > e200_v and macd_v > sig_v and slope20 > 0 and slope50 > 0
    # Weak bull: partial alignment
    weak_bull = e20_v > e50_v and (macd_v >= sig_v or slope20 > 0)

    strong_bear = e20_v < e50_v < e200_v and macd_v < sig_v and slope20 < 0 and slope50 < 0
    weak_bear = e20_v < e50_v and (macd_v <= sig_v or slope20 < 0)

    if strong_bull:
        return HTFTrend("BUY_ONLY", "HTF strong bull | EMA stacked | MACD+")
    if strong_bear:
        return HTFTrend("SELL_ONLY", "HTF strong bear | EMA stacked | MACD-")
    if weak_bull:
        return HTFTrend("BUY_ONLY", "HTF weak bull | EMA20>50 | MACD mixed")
    if weak_bear:
        return HTFTrend("SELL_ONLY", "HTF weak bear | EMA20<50 | MACD mixed")

    # NEUTRAL: ยังเทรดได้ทั้งสองทาง แต่ลด score
    return HTFTrend("NEUTRAL", "HTF ranging | both sides allowed")


# ─────────────────────────────────────────────
# Main Signal Engine
# ─────────────────────────────────────────────

def decide_signal(df: pd.DataFrame) -> Signal:
    if len(df) < 200:
        return Signal("NONE", 0, "not enough bars", "none", "none")

    close = df["close"]
    open_ = df["open"]
    high = df["high"]
    low = df["low"]

    e20 = ema(close, 20)
    e50 = ema(close, 50)
    e200 = ema(close, 200)
    r = rsi(close, 14)
    a = atr(df, 14)
    macd_line, signal_line, hist = macd(close)

    # Use [-2] = last CLOSED candle (not live)
    idx      = df.index[-2]
    prev_idx = df.index[-3]
    prev2_idx = df.index[-4]

    c_v  = safe_float(close.loc[idx])
    o_v  = safe_float(open_.loc[idx])
    h_v  = safe_float(high.loc[idx])
    l_v  = safe_float(low.loc[idx])

    pc_v = safe_float(close.loc[prev_idx])
    po_v = safe_float(open_.loc[prev_idx])
    ph_v = safe_float(high.loc[prev_idx])
    pl_v = safe_float(low.loc[prev_idx])

    p2h_v = safe_float(high.loc[prev2_idx])
    p2l_v = safe_float(low.loc[prev2_idx])

    e20_v  = safe_float(e20.loc[idx])
    e50_v  = safe_float(e50.loc[idx])
    e200_v = safe_float(e200.loc[idx])
    atr_v  = safe_float(a.loc[idx])
    rsi_v  = safe_float(r.loc[idx], 50.0)
    macd_v = safe_float(macd_line.loc[idx])
    sig_v  = safe_float(signal_line.loc[idx])
    hist_v = safe_float(hist.loc[idx])

    if atr_v <= 0:
        return Signal("NONE", 0, "ATR unavailable", "none", "none")

    # ── Candle metrics ────────────────────────────────
    rng, body_ratio, upper_wick, lower_wick = _candle_parts(o_v, c_v, h_v, l_v)
    prng, pbody_ratio, pupper_wick, plower_wick = _candle_parts(po_v, pc_v, ph_v, pl_v)

    bull_candle = c_v > o_v
    bear_candle = c_v < o_v

    # ── Trend conditions ─────────────────────────────
    trend_up   = e20_v > e50_v and c_v > e200_v
    trend_down = e20_v < e50_v and c_v < e200_v

    slope20 = _ema_slope(close, 20)
    slope50 = _ema_slope(close, 50)

    # Sideway: EMAs flat + small body → ข้าม
    ema_sep = abs(e20_v - e50_v)
    sideways = ema_sep < (0.015 * atr_v) and abs(slope20) < (0.002 * atr_v)
    if sideways and body_ratio < 0.15:
        return Signal("NONE", 28, "sideway compression", "none", "none")

    # ── Zone proximity ────────────────────────────────
    near_ema50 = abs(c_v - e50_v) <= (atr_v * PULLBACK_ZONE_ATR_MULT)
    near_ema20 = abs(c_v - e20_v) <= (atr_v * CONTINUATION_ZONE_ATR_MULT)

    # ── MACD ─────────────────────────────────────────
    macd_bull = macd_v > sig_v and hist_v >= 0
    macd_bear = macd_v < sig_v and hist_v <= 0

    # ── Candle patterns ──────────────────────────────
    engulf_bull = _is_bullish_engulfing(o_v, c_v, po_v, pc_v)
    engulf_bear = _is_bearish_engulfing(o_v, c_v, po_v, pc_v)
    pin_bull    = _is_bullish_pin_bar(o_v, c_v, h_v, l_v)
    pin_bear    = _is_bearish_pin_bar(o_v, c_v, h_v, l_v)

    # ── Volume proxy: use tick_volume if available ────
    vol_col = "tick_volume" if "tick_volume" in df.columns else "real_volume"
    vol_confirm = True
    if vol_col in df.columns and df[vol_col].iloc[-2] > 0:
        recent_vol = df[vol_col].iloc[-2]
        avg_vol = df[vol_col].iloc[-21:-2].mean()
        vol_confirm = float(recent_vol) >= float(avg_vol) * 0.85  # อย่างน้อย 85% ของค่าเฉลี่ย

    # ── Base score ────────────────────────────────────
    score = 50
    reasons = []

    if trend_up:
        score += 8; reasons.append("EMA↑")
    elif trend_down:
        score += 8; reasons.append("EMA↓")
    else:
        reasons.append("EMA_weak")

    if macd_bull:
        score += 5; reasons.append("MACD+")
    elif macd_bear:
        score += 5; reasons.append("MACD-")

    if vol_confirm:
        score += 3; reasons.append("vol_ok")

    # ─── CONTINUATION setup ──────────────────────────
    cont_buy = (
        trend_up and macd_bull and near_ema20
        and bull_candle and body_ratio >= 0.18
        and c_v >= ph_v                          # break prev high
        and CONTINUATION_RSI_BUY_MIN <= rsi_v <= CONTINUATION_RSI_BUY_MAX
    )
    cont_sell = (
        trend_down and macd_bear and near_ema20
        and bear_candle and body_ratio >= 0.18
        and c_v <= pl_v                          # break prev low
        and CONTINUATION_RSI_SELL_MIN <= rsi_v <= CONTINUATION_RSI_SELL_MAX
    )

    # ─── PULLBACK setup ──────────────────────────────
    pull_buy = (
        trend_up and macd_bull and near_ema50
        and bull_candle and body_ratio >= 0.18
        and c_v > pc_v
        and PULLBACK_RSI_BUY_MIN <= rsi_v <= PULLBACK_RSI_BUY_MAX
    )
    pull_sell = (
        trend_down and macd_bear and near_ema50
        and bear_candle and body_ratio >= 0.18
        and c_v < pc_v
        and PULLBACK_RSI_SELL_MIN <= rsi_v <= PULLBACK_RSI_SELL_MAX
    )

    # ─── Score bonuses ────────────────────────────────
    def _buy_bonuses(base_score, base_reasons):
        s, r = base_score, base_reasons[:]
        if c_v > max(ph_v, p2h_v):
            s += 5; r.append("fresh_high")
        if engulf_bull:
            s += 6; r.append("engulf↑")
        elif pin_bull:
            s += 4; r.append("pin↑")
        if pbody_ratio >= 0.15:
            s += 2
        if lower_wick >= rng * 0.10:
            s += 2; r.append("tail↑")
        if slope50 > 0:
            s += 2; r.append("slope50↑")
        r.append(f"RSI{rsi_v:.0f}")
        return s, r

    def _sell_bonuses(base_score, base_reasons):
        s, r = base_score, base_reasons[:]
        if c_v < min(pl_v, p2l_v):
            s += 5; r.append("fresh_low")
        if engulf_bear:
            s += 6; r.append("engulf↓")
        elif pin_bear:
            s += 4; r.append("pin↓")
        if pbody_ratio >= 0.15:
            s += 2
        if upper_wick >= rng * 0.10:
            s += 2; r.append("tail↓")
        if slope50 < 0:
            s += 2; r.append("slope50↓")
        r.append(f"RSI{rsi_v:.0f}")
        return s, r

    if cont_buy:
        score += 12
        score, reasons = _buy_bonuses(score, reasons)
        return Signal("BUY", min(score, 100), " | ".join(reasons), "continuation", f"BUY_cont_{idx}")

    if cont_sell:
        score += 12
        score, reasons = _sell_bonuses(score, reasons)
        return Signal("SELL", min(score, 100), " | ".join(reasons), "continuation", f"SELL_cont_{idx}")

    if pull_buy:
        score += 10
        score, reasons = _buy_bonuses(score, reasons)
        return Signal("BUY", min(score, 100), " | ".join(reasons), "pullback", f"BUY_pull_{idx}")

    if pull_sell:
        score += 10
        score, reasons = _sell_bonuses(score, reasons)
        return Signal("SELL", min(score, 100), " | ".join(reasons), "pullback", f"SELL_pull_{idx}")

    # No valid setup
    if near_ema50: reasons.append("near_EMA50")
    if near_ema20: reasons.append("near_EMA20")
    reasons.append(f"RSI{rsi_v:.0f}")
    return Signal("NONE", max(min(score, 100), 0), " | ".join(reasons), "none", "none")
