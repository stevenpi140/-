from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

DEFAULTS = {
    "timezone": "Asia/Taipei",
    "display": {
        "width": 128,
        "height": 64,
        "page_seconds": 8,
        "live_page_seconds": 12,
        "fonts": {},  # small / large 可指定字型檔
    },
    "brightness": {"day": 160, "night": 30, "night_start": "23:30", "night_end": "07:00"},
    "poll": {"live_seconds": 15, "soon_seconds": 60, "idle_seconds": 600},
    "leagues": {
        "cpbl": {"enabled": True, "teams": []},
        "mlb": {"enabled": True, "teams": []},
        "nba": {"enabled": True, "teams": []},
        "tpbl": {"enabled": True, "teams": []},
        "plg": {"enabled": True, "teams": []},
    },
    # 依季節決定顯示哪一類運動。兩季重疊的期間才會全部一起輪播。
    "season": {
        "mode": "auto",  # auto = 依日期自動切換；也可以固定成 basketball / baseball / all
        "baseball": ["03-01", "10-15"],  # 月-日，含頭尾
        "basketball": ["10-01", "06-30"],  # 跨年：10/1 到隔年 6/30
    },
    "aliases": {},
}

SPORTS = {
    "baseball": ("cpbl", "mlb"),
    "basketball": ("nba", "tpbl", "plg"),
}


def _md(s: str) -> tuple[int, int]:
    m, d = s.split("-")
    return int(m), int(d)


def in_window(day: date, window) -> bool:
    start, end, md = _md(window[0]), _md(window[1]), (day.month, day.day)
    if start <= end:
        return start <= md <= end
    return md >= start or md <= end  # 跨年的區間


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


@dataclass
class Config:
    raw: dict = field(default_factory=lambda: dict(DEFAULTS))

    @classmethod
    def load(cls, path: str | Path | None) -> "Config":
        data = {}
        if path and Path(path).exists():
            data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        return cls(_merge(DEFAULTS, data))

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.raw["timezone"])

    @property
    def display(self) -> dict:
        return self.raw["display"]

    @property
    def aliases(self) -> dict[str, str]:
        return self.raw.get("aliases") or {}

    def active_sports(self, day: date) -> list[str]:
        """今天要顯示的運動：baseball / basketball，重疊期間兩個都有。"""
        season = self.raw["season"]
        mode = season.get("mode", "auto")
        if mode in SPORTS:
            return [mode]
        if mode == "all":
            return list(SPORTS)
        active = [sport for sport in SPORTS if in_window(day, season[sport])]
        return active or list(SPORTS)  # 兩季都沒涵蓋到的日子就全部顯示，避免整天空白

    def league_active(self, key: str, day: date) -> bool:
        return any(key in SPORTS[s] for s in self.active_sports(day))

    def league(self, key: str) -> dict:
        return self.raw["leagues"].get(key, {"enabled": False})

    def follows(self, league_key: str, *names: str) -> bool:
        """teams 為空代表該聯盟全部都看；否則任一隊的代碼 / 中文名有出現在清單即顯示。"""
        teams = [str(t).upper() for t in (self.league(league_key).get("teams") or [])]
        if not teams:
            return True
        for n in names:
            if not n:
                continue
            u = n.upper()
            if any(t == u or (len(t) >= 2 and not t.isascii() and t in u) for t in teams):
                return True
        return False
