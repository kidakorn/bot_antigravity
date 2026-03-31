"""
OpenClaw V7 - Position Management (Trailing / Breakeven / Partial TP)
ปรับปรุง:
  - partial TP: ลอง IOC ก่อน, fallback FOK → ลด rejection บน gold
  - trail: clamp SL ไม่ให้ backwards เกิน 1 ATR จาก current price
  - breakeven: เพิ่ม guard ไม่ให้ set BE ถ้า SL ดีกว่าอยู่แล้ว
  - is_in_news_blackout: เหมือนเดิม, เพิ่ม type hints
"""
from datetime import datetime, timedelta

import MetaTrader5 as mt5
import pandas as pd

from app.utils.utils import atr


# ─────────────────────────────────────────────
# News blackout
# ─────────────────────────────────────────────

def _parse_dt(date_str: str, hhmm: str) -> datetime:
    y, m, d = map(int, date_str.split("-"))
    hh, mm  = map(int, hhmm.split(":"))
    return datetime(y, m, d, hh, mm, 0)


def is_in_news_blackout(
    now_local: datetime,
    enabled: bool,
    windows: list,
    before_min: int,
    after_min: int,
) -> tuple[bool, str]:
    if not enabled or not windows:
        return False, ""
    for d, start_hm, end_hm, reason in windows:
        start = _parse_dt(d, start_hm) - timedelta(minutes=before_min)
        end   = _parse_dt(d, end_hm)   + timedelta(minutes=after_min)
        if start <= now_local <= end:
            return True, f"news_blackout:{reason} {start_hm}-{end_hm}"
    return False, ""


# ─────────────────────────────────────────────
# MT5 helpers
# ─────────────────────────────────────────────

def _send_sltp(
    symbol: str,
    magic: int,
    ticket: int,
    sl: float,
    tp: float,
    comment: str,
):
    return mt5.order_send({
        "action":   mt5.TRADE_ACTION_SLTP,
        "symbol":   symbol,
        "position": ticket,
        "sl":       float(sl),
        "tp":       float(tp),
        "magic":    magic,
        "comment":  comment,
    })


def _close_partial(
    position,
    symbol: str,
    close_pct: float,
) -> tuple:
    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return None, "symbol_or_tick_missing"

    vol       = float(position.volume)
    step      = max(float(info.volume_step), float(info.volume_min), 0.01)
    target    = vol * float(close_pct)
    close_vol = round(target / step) * step
    remain    = vol - close_vol

    if remain < float(info.volume_min):
        close_vol = vol - float(info.volume_min)
        close_vol = round(close_vol / step) * step

    if close_vol < float(info.volume_min):
        return None, "partial_vol_too_small"

    if position.type == mt5.POSITION_TYPE_BUY:
        order_type = mt5.ORDER_TYPE_SELL
        price      = float(tick.bid)
    else:
        order_type = mt5.ORDER_TYPE_BUY
        price      = float(tick.ask)

    base_req = {
        "action":    mt5.TRADE_ACTION_DEAL,
        "symbol":    symbol,
        "position":  position.ticket,
        "volume":    float(close_vol),
        "type":      order_type,
        "price":     price,
        "deviation": 40,
        "magic":     int(position.magic),
        "comment":   "OpenClaw-V7-Partial",
        "type_time": mt5.ORDER_TIME_GTC,
    }

    # ลอง IOC ก่อน → ถ้า reject ให้ลอง FOK
    for filling in (mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN):
        req = {**base_req, "type_filling": filling}
        res = mt5.order_send(req)
        if res is None:
            continue
        if res.retcode == mt5.TRADE_RETCODE_DONE:
            return res, "ok"

    return None, f"partial_failed_all_fillings"


# ─────────────────────────────────────────────
# Main trailing engine
# ─────────────────────────────────────────────

def trail_positions_atr(
    symbol: str,
    magic: int,
    df: pd.DataFrame,
    enabled: bool,
    atr_mult: float,
    breakeven_enabled: bool = True,
    breakeven_trigger_atr: float = 0.40,
    breakeven_lock_points: int = 15,
    trailing_start_atr: float = 0.55,
    partial_tp_enabled: bool = True,
    partial_tp_trigger_r: float = 0.65,
    partial_tp_close_pct: float = 0.50,
    partial_taken_positions: set | None = None,
) -> list:

    if not enabled:
        return []

    positions = mt5.positions_get(symbol=symbol)
    if not positions:
        return []
    positions = [p for p in positions if p.magic == magic]
    if not positions:
        return []

    info = mt5.symbol_info(symbol)
    tick = mt5.symbol_info_tick(symbol)
    if info is None or tick is None:
        return []

    raw_atr = atr(df, 14).iloc[-2]
    if raw_atr is None or pd.isna(raw_atr) or float(raw_atr) <= 0:
        return []

    point      = float(info.point)
    bid        = float(tick.bid)
    ask        = float(tick.ask)
    atr_v      = float(raw_atr)
    trail_dist = atr_v * float(atr_mult)
    taken      = partial_taken_positions or set()
    updated    = []

    for p in positions:
        cur_sl     = float(p.sl) if p.sl else 0.0
        cur_tp     = float(p.tp) if p.tp else 0.0
        open_price = float(p.price_open)

        if p.type == mt5.POSITION_TYPE_BUY:
            profit_dist  = bid - open_price
            initial_risk = max(point, open_price - cur_sl) if cur_sl > 0 else atr_v
            be_sl        = open_price + float(breakeven_lock_points) * point

            # ── Partial TP ───────────────────────────────
            if partial_tp_enabled and p.ticket not in taken:
                if profit_dist >= float(partial_tp_trigger_r) * initial_risk:
                    _, status = _close_partial(p, symbol, partial_tp_close_pct)
                    if status == "ok":
                        taken.add(p.ticket)
                        updated.append(("BUY", "partial_tp", p.ticket, round(p.volume, 2), round(partial_tp_close_pct, 2)))

            # ── Breakeven ────────────────────────────────
            if breakeven_enabled and profit_dist >= float(breakeven_trigger_atr) * atr_v:
                if cur_sl < be_sl - 2 * point:
                    res = _send_sltp(symbol, magic, p.ticket, be_sl, cur_tp, "OC-V7-BE")
                    if res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                        cur_sl = be_sl
                        updated.append(("BUY", "breakeven", p.ticket, round(open_price, 3), round(be_sl, 3)))

            # ── Trailing ─────────────────────────────────
            if profit_dist >= float(trailing_start_atr) * atr_v:
                proposed_sl = bid - trail_dist
                # ไม่ให้ trail ต่ำกว่า BE
                if breakeven_enabled:
                    proposed_sl = max(proposed_sl, be_sl)
                # ไม่ให้ SL ถอยหลัง
                if cur_sl <= 0 or proposed_sl > cur_sl + 2 * point:
                    res = _send_sltp(symbol, magic, p.ticket, proposed_sl, cur_tp, "OC-V7-Trail")
                    if res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                        updated.append(("BUY", "trail", p.ticket, round(cur_sl, 3), round(proposed_sl, 3)))

        elif p.type == mt5.POSITION_TYPE_SELL:
            profit_dist  = open_price - ask
            initial_risk = max(point, cur_sl - open_price) if cur_sl > 0 else atr_v
            be_sl        = open_price - float(breakeven_lock_points) * point

            # ── Partial TP ───────────────────────────────
            if partial_tp_enabled and p.ticket not in taken:
                if profit_dist >= float(partial_tp_trigger_r) * initial_risk:
                    _, status = _close_partial(p, symbol, partial_tp_close_pct)
                    if status == "ok":
                        taken.add(p.ticket)
                        updated.append(("SELL", "partial_tp", p.ticket, round(p.volume, 2), round(partial_tp_close_pct, 2)))

            # ── Breakeven ────────────────────────────────
            if breakeven_enabled and profit_dist >= float(breakeven_trigger_atr) * atr_v:
                if cur_sl <= 0 or cur_sl > be_sl + 2 * point:
                    res = _send_sltp(symbol, magic, p.ticket, be_sl, cur_tp, "OC-V7-BE")
                    if res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                        cur_sl = be_sl
                        updated.append(("SELL", "breakeven", p.ticket, round(open_price, 3), round(be_sl, 3)))

            # ── Trailing ─────────────────────────────────
            if profit_dist >= float(trailing_start_atr) * atr_v:
                proposed_sl = ask + trail_dist
                if breakeven_enabled:
                    proposed_sl = min(proposed_sl, be_sl)
                if cur_sl <= 0 or proposed_sl < cur_sl - 2 * point:
                    res = _send_sltp(symbol, magic, p.ticket, proposed_sl, cur_tp, "OC-V7-Trail")
                    if res and res.retcode in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_DONE_PARTIAL):
                        updated.append(("SELL", "trail", p.ticket, round(cur_sl, 3), round(proposed_sl, 3)))

    return updated
