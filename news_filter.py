"""
OpenClaw V7 - News Filter
Cache 4 hours to avoid 429 Too Many Requests
"""
from datetime import datetime, timedelta, timezone
import threading

import pandas as pd
import requests

FF_URL           = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
FETCH_INTERVAL   = 14400  # 4 hours cache — prevents 429 rate limit
BLACKOUT_MINUTES = 15

_cache_lock = threading.Lock()
_NEWS_CACHE: dict = {"data": None, "last_fetch": None}


def _fetch_news() -> pd.DataFrame:
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(FF_URL, timeout=12, headers=headers)
        if r.status_code == 429:
            print("[news_filter] rate limited (429) — using cached data")
            return _NEWS_CACHE.get("data") or pd.DataFrame()
        r.raise_for_status()
        data = r.json()
        df   = pd.DataFrame(data)

        if df.empty or "date" not in df.columns:
            return pd.DataFrame()

        df["date"] = pd.to_datetime(df["date"], errors="coerce", utc=True)
        df = df.dropna(subset=["date"])

        cur_col = "currency" if "currency" in df.columns else "country"
        if cur_col in df.columns:
            df = df[df[cur_col].astype(str).str.upper().isin(["USD", "US", "UNITED STATES"])]

        if "impact" in df.columns:
            df = df[df["impact"].astype(str).str.contains("high|red", case=False, na=False)]

        if "title" not in df.columns:
            df["title"] = "USD News"

        return df[["date", "title"]].copy()

    except Exception as e:
        print(f"[news_filter] fetch error: {e}")
        return _NEWS_CACHE.get("data") or pd.DataFrame()


def get_news() -> pd.DataFrame:
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
