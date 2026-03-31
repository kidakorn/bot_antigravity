"""
OpenClaw V7 - AI Evaluator
ปรับปรุง:
  - เปิด vol filter + trend strength ตามค่า default V7
  - เพิ่ม HTF alignment bonus
  - ปรับ session เวลาไทย (UTC+7) ให้ครอบคลุม overlap London/NY
  - momentum score calibrate ใหม่
"""
from dataclasses import dataclass
from datetime import datetime, time as dtime

import pandas as pd

from app.utils.utils import atr, ema, rsi


@dataclass
class AIDecision:
    allow_trade: bool
    score_delta: int
    reason_ai: str


def _in_time_range(now: dtime, start: dtime, end: dtime) -> bool:
    if start <= end:
        return start <= now <= end
    # overnight wrap
    return now >= start or now <= end


def session_filter(
    local_dt: datetime,
    enabled: bool,
    london: tuple,
    ny: tuple,
    asian: tuple = (8, 0, 12, 0),   # ✨ Asian session (เวลาไทย)
) -> tuple[bool, str]:
    if not enabled:
        return True, "session_disabled"

    now = local_dt.time()
    a_start = dtime(asian[0],  asian[1])
    a_end   = dtime(asian[2],  asian[3])
    l_start = dtime(london[0], london[1])
    l_end   = dtime(london[2], london[3])
    n_start = dtime(ny[0],     ny[1])
    n_end   = dtime(ny[2],     ny[3])

    if _in_time_range(now, a_start, a_end):
        return True, "session:Asian"
    if _in_time_range(now, l_start, l_end):
        return True, "session:London"
    if _in_time_range(now, n_start, n_end):
        return True, "session:NewYork"

    return False, f"outside_session ({now.strftime('%H:%M')})"


def regime_filter(df: pd.DataFrame, enabled: bool) -> AIDecision:
    if not enabled:
        return AIDecision(True, 0, "regime_disabled")

    close = df["close"]
    e20  = ema(close, 20)
    e50  = ema(close, 50)
    e200 = ema(close, 200)
    a    = atr(df, 14)
    idx  = df.index[-2]

    e20_v  = float(e20.loc[idx])  if pd.notna(e20.loc[idx])  else 0.0
    e50_v  = float(e50.loc[idx])  if pd.notna(e50.loc[idx])  else 0.0
    e200_v = float(e200.loc[idx]) if pd.notna(e200.loc[idx]) else 0.0
    atr_v  = float(a.loc[idx])    if pd.notna(a.loc[idx]) and float(a.loc[idx]) > 0 else 0.0

    if atr_v <= 0:
        return AIDecision(True, 0, "regime_unknown")

    sep_fast = abs(e20_v - e50_v)
    sep_slow = abs(e50_v - e200_v)

    if sep_fast < 0.18 * atr_v and sep_slow < 0.30 * atr_v:
        return AIDecision(True, -10, "regime:range → -10")   # เพิ่มบทลงโทษ range

    if sep_slow >= 0.85 * atr_v and sep_fast >= 0.18 * atr_v:
        return AIDecision(True, +7, "regime:strong_trend → +7")

    return AIDecision(True, 0, "regime:trend")


def volatility_filter(df: pd.DataFrame, enabled: bool) -> AIDecision:
    if not enabled:
        return AIDecision(True, 0, "vol_disabled")

    a     = atr(df, 14).iloc[-2]
    close = float(df["close"].iloc[-2])

    if pd.isna(a) or close <= 0:
        return AIDecision(False, -999, "vol_insufficient_data")

    ratio = float(a) / close

    if ratio >= 0.0090:
        return AIDecision(False, -30, f"vol_extreme ({ratio:.4%}) → BLOCK")

    if ratio >= 0.0060:
        return AIDecision(True, -6, f"vol_high ({ratio:.4%}) → -6")

    if ratio <= 0.0006:
        return AIDecision(True, -6, f"vol_dead ({ratio:.4%}) → -6")

    return AIDecision(True, 0, f"vol_ok ({ratio:.4%})")


def trend_strength_score(df: pd.DataFrame, enabled: bool) -> tuple[int, str]:
    if not enabled:
        return 0, "trend_strength_disabled"

    close = df["close"]
    e50   = ema(close, 50)
    e200  = ema(close, 200)
    e20   = ema(close, 20)
    a     = atr(df, 14)
    idx   = df.index[-2]

    if any(pd.isna(s.loc[idx]) for s in [e20, e50, e200, a]):
        return 0, "trend_strength_insufficient"

    sep_main = abs(float(e50.loc[idx]) - float(e200.loc[idx]))
    sep_fast = abs(float(e20.loc[idx]) - float(e50.loc[idx]))
    atr_v    = float(a.loc[idx])

    if atr_v > 0 and sep_main >= 0.80 * atr_v and sep_fast >= 0.18 * atr_v:
        return 8, "trend_strong +8"
    if atr_v > 0 and sep_main >= 0.45 * atr_v:
        return 4, "trend_moderate +4"
    return 0, "trend_normal"


def momentum_score(df: pd.DataFrame, base_action: str) -> tuple[int, str]:
    """RSI momentum ปรับ calibration ใหม่ให้สม่ำเสมอ"""
    r   = rsi(df["close"], 14)
    idx = df.index[-2]
    rv  = float(r.loc[idx]) if pd.notna(r.loc[idx]) else 50.0

    if base_action == "BUY":
        if 50 <= rv <= 63:   return  6, f"RSI_ideal_buy {rv:.0f} +6"
        if 63 < rv <= 72:    return  3, f"RSI_strong_buy {rv:.0f} +3"
        if 40 <= rv < 50:    return  2, f"RSI_ok_buy {rv:.0f} +2"
        if rv < 38:          return -6, f"RSI_weak_buy {rv:.0f} -6"
        return 0, f"RSI {rv:.0f}"

    if base_action == "SELL":
        if 37 <= rv <= 50:   return  6, f"RSI_ideal_sell {rv:.0f} +6"
        if 28 <= rv < 37:    return  3, f"RSI_strong_sell {rv:.0f} +3"
        if 50 < rv <= 60:    return  2, f"RSI_ok_sell {rv:.0f} +2"
        if rv > 62:          return -6, f"RSI_weak_sell {rv:.0f} -6"
        return 0, f"RSI {rv:.0f}"

    return 0, f"RSI {rv:.0f}"


def continuation_bonus(df: pd.DataFrame, base_action: str) -> tuple[int, str]:
    close = df["close"]
    e20   = ema(close, 20)
    e50   = ema(close, 50)
    idx   = df.index[-2]

    cv   = float(close.loc[idx])
    e20v = float(e20.loc[idx])
    e50v = float(e50.loc[idx])

    if base_action == "BUY"  and cv >= e20v >= e50v: return 4, "cont_align_bull +4"
    if base_action == "SELL" and cv <= e20v <= e50v: return 4, "cont_align_bear +4"
    return 0, "no_cont_bonus"


def openclaw_ai_evaluate(
    df: pd.DataFrame,
    base_action: str,
    base_score: int,
    local_dt: datetime,
    session_enabled: bool = True,
    regime_enabled: bool = True,
    vol_enabled: bool = True,
    trend_strength_enabled: bool = True,
    london: tuple = (14, 0, 20, 0),
    ny: tuple = (19, 30, 23, 59),
    asian: tuple = (8, 0, 12, 0),      # ✨ Asian session
) -> tuple[bool, int, str]:
    """
    Returns: (allow_trade, final_score, reason_string)
    """
    reasons = []

    # 1. Session gate (hard block)
    ok_sess, sess_reason = session_filter(local_dt, session_enabled, london, ny, asian)
    reasons.append(sess_reason)
    if not ok_sess:
        return False, max(0, base_score - 999), " | ".join(reasons)

    # 2. Volatility gate (hard block on extreme)
    vol_dec = volatility_filter(df, vol_enabled)
    reasons.append(vol_dec.reason_ai)
    if not vol_dec.allow_trade:
        return False, max(0, base_score + vol_dec.score_delta), " | ".join(reasons)

    # 3. Regime (soft penalty/bonus)
    regime_dec = regime_filter(df, regime_enabled)
    reasons.append(regime_dec.reason_ai)

    # 4. Trend strength bonus
    delta_trend, trend_reason = trend_strength_score(df, trend_strength_enabled)
    reasons.append(trend_reason)

    # 5. Momentum
    delta_momo, momo_reason = momentum_score(df, base_action)
    reasons.append(momo_reason)

    # 6. Continuation alignment
    delta_cont, cont_reason = continuation_bonus(df, base_action)
    reasons.append(cont_reason)

    final_score = (
        base_score
        + regime_dec.score_delta
        + vol_dec.score_delta
        + delta_trend
        + delta_momo
        + delta_cont
    )
    final_score = max(0, min(final_score, 100))

    if base_action == "NONE":
        return False, final_score, " | ".join(reasons)

    return True, final_score, " | ".join(reasons)
