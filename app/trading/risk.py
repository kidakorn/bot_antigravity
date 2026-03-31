"""
OpenClaw V7 - Risk Calculator
ปรับปรุง: ไม่ import app.config โดยตรง (ป้องกัน circular), รับ min/max lot เป็น param
"""
import MetaTrader5 as mt5


def calc_lot(
    symbol: str,
    risk_pct: float,
    sl_points: int,
    min_lot: float = 0.01,
    max_lot: float = 100.0,
    martingale_multiplier: float = 1.0,
    martingale_level: int = 1,
) -> float:
    acc  = mt5.account_info()
    info = mt5.symbol_info(symbol)
    if acc is None or info is None:
        return min_lot

    balance     = float(acc.balance)
    risk_money  = balance * float(risk_pct)
    tick_value  = float(info.trade_tick_value)
    tick_size   = float(info.trade_tick_size)
    point       = float(info.point)

    if tick_size <= 0 or point <= 0 or sl_points <= 0:
        return min_lot

    value_per_point = (tick_value / tick_size) * point
    if value_per_point <= 0:
        return min_lot

    loss_per_lot = sl_points * value_per_point
    if loss_per_lot <= 0:
        return min_lot

    lot  = risk_money / loss_per_lot
    
    # Apply Martingale
    if martingale_level > 1:
        lot = lot * (martingale_multiplier ** (martingale_level - 1))

    step = float(info.volume_step)
    if step > 0:
        lot = round(lot / step) * step

    lot = max(float(min_lot), min(float(max_lot), lot))
    lot = max(float(info.volume_min), min(lot, float(info.volume_max)))
    return float(lot)


def sl_tp_from_points(
    entry: float,
    action: str,
    sl_points: int,
    tp_points: int,
    point: float,
) -> tuple[float, float]:
    if action == "BUY":
        return entry - sl_points * point, entry + tp_points * point
    return entry + sl_points * point, entry - tp_points * point
