from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Protocol

import httpx

from ..config import Config
from ..models import Game

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)


class League(Protocol):
    key: str  # config.yaml 裡的名稱，例如 "mlb"
    name: str  # 顯示名稱，例如 "MLB"

    async def fetch(self, client: httpx.AsyncClient, cfg: Config, day: date) -> list[Game]: ...


def parse_iso(s: str, tz) -> datetime:
    """解析 ISO 時間；沒有時區資訊的當作 tz（台灣聯盟的時間都是台灣時間）。"""
    s = s.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    return dt.astimezone(tz)


def us_dates_for(day: date) -> list[date]:
    """台灣的某一天，對應到美國的前一天與當天（美國比賽在台灣是早上到下午）。"""
    return [day - timedelta(days=1), day]


def to_int(v):
    try:
        if v is None or v == "":
            return None
        return int(float(v))
    except (TypeError, ValueError):
        return None
