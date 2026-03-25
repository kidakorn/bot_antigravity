"""
OpenClaw V7 - News Filter
ปรับปรุง: เพิ่ม buffer ±15 นาที (V7 default), เพิ่ม medium impact option
"""
from datetime import datetime, timedelta, timezone
import threading

import pandas as pd
import requests

FF_URL            = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FETCH_INTERVAL    = 3600   # 1 hr cache
BLACKOUT_MINUTES  = 15     # ±15 min ทั้งก่อนและหลังข่าว

_cache_lock = threading.Lock()
_NEWS_CACHE: dict = {"data": None, "last_fetch": None}


def _fetch_news() -> pd.DataFrame:
    try:
        r = requests.get(FF_URL, timeout=12)
        r.raise_for_status()
        data = r.json()
        df   = pd.DataFrame(data)

        if df.empty or "date" not in df.columns:
            return pd.DataFrame()

        df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
        df = df.dropna(subset=["date"])

        # กรอง USD เท่านั้น
        cur_col = "currency" if "currency" in df.columns else "country"
        if cur_col in df.columns:
            df = df[df[cur_col].astype(str).str.upper().isin(["USD", "US", "UNITED STATES"])]

        # กรอง high impact (red)
        if "impact" in df.columns:
            df = df[df["impact"].astype(str).str.contains("high|red", case=False, na=False)]

        if "title" not in df.columns:
            df["title"] = "USD News"

        return df[["date", "title"]].copy()

    except Exception as e:
        print(f"[news_filter] fetch error: {e}")
        return pd.DataFrame()


def get_news() -> pd.DataFrame:
    global _NEWS_CACHE
    now_utc = datetime.now(timezone.utc)
    with _cache_lock:
        last = _NEWS_CACHE["last_fetch"]
        if last is not None and (now_utc - last).total_seconds() < FETCH_INTERVAL:
            return _NEWS_CACHE["data"] if _NEWS_CACHE["data"] is not None else pd.DataFrame()
        df = _fetch_news()
        _NEWS_CACHE["data"]       = df
        _NEWS_CACHE["last_fetch"] = now_utc
        return df


def is_news_time(buffer_min: int = BLACKOUT_MINUTES) -> tuple[bool, str]:
    df = get_news()
    if df is None or df.empty:
        return False, ""

    now_utc = datetime.now(timezone.utc)
    buf     = timedelta(minutes=buffer_min)

    for _, row in df.iterrows():
        news_time = row["date"]
        if pd.isna(news_time):
            continue
        if getattr(news_time, "tzinfo", None) is None:
            news_time = news_time.tz_localize("UTC")
        else:
            news_time = news_time.tz_convert("UTC")

        if (news_time - buf) <= now_utc <= (news_time + buf):
            return True, str(row["title"])

    return False, ""
