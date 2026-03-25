"""
OpenClaw V7 - MT5 Client
ปรับปรุง: เพิ่ม explicit index ใน DataFrame, type hints ครบ
"""
from datetime import datetime

import MetaTrader5 as mt5
import pandas as pd

TF_MAP: dict[str, int] = {
    "M1":  mt5.TIMEFRAME_M1,
    "M5":  mt5.TIMEFRAME_M5,
    "M15": mt5.TIMEFRAME_M15,
    "H1":  mt5.TIMEFRAME_H1,
    "H4":  mt5.TIMEFRAME_H4,
    "D1":  mt5.TIMEFRAME_D1,
}


def connect() -> None:
    if not mt5.initialize():
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")


def shutdown() -> None:
    mt5.shutdown()


def ensure_symbol(symbol: str) -> None:
    info = mt5.symbol_info(symbol)
    if info is None:
        raise RuntimeError(f"Symbol not found: {symbol}")
    if not info.visible:
        if not mt5.symbol_select(symbol, True):
            raise RuntimeError(f"Failed to select symbol: {symbol}")


def get_rates(symbol: str, timeframe: str, n: int = 400) -> pd.DataFrame:
    tf = TF_MAP.get(timeframe)
    if tf is None:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    rates = mt5.copy_rates_from_pos(symbol, tf, 0, n)
    if rates is None or len(rates) == 0:
        raise RuntimeError(f"No rates returned: {mt5.last_error()}")
    df = pd.DataFrame(rates)
    df["time"] = pd.to_datetime(df["time"], unit="s")
    df.set_index("time", inplace=True)
    return df


def get_tick(symbol: str):
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        raise RuntimeError(f"No tick data: {mt5.last_error()}")
    return tick


def spread_points(symbol: str) -> int:
    info = mt5.symbol_info(symbol)
    tick = get_tick(symbol)
    if info is None:
        return 9999
    return int(round((tick.ask - tick.bid) / info.point))


def positions_by_magic(symbol: str, magic: int) -> list:
    pos = mt5.positions_get(symbol=symbol)
    if pos is None:
        return []
    return [p for p in pos if p.magic == magic]


def today_deals_profit(magic: int) -> tuple[float, int]:
    now   = datetime.now()
    start = datetime(now.year, now.month, now.day)
    deals = mt5.history_deals_get(start, now)
    if deals is None:
        return 0.0, 0

    bot_deals = [d for d in deals if getattr(d, "magic", None) == magic]
    profit_today = sum(float(getattr(d, "profit", 0.0)) for d in bot_deals)

    consecutive_losses = 0
    for d in reversed(bot_deals):
        p = float(getattr(d, "profit", 0.0))
        if p > 0:
            break
        if p < 0:
            consecutive_losses += 1

    return float(profit_today), int(consecutive_losses)
