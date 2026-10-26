"""TPBL：官網使用的 api.tpbl.basketball（未公開文件化，官網改版可能失效）。

- /api/seasons                取得賽季清單（用 started_at 找最新賽季）
- /api/seasons/{id}/games     整季賽程，欄位 game_date / game_time / status / home_team / away_team
- /api/games/{id}/stats       單場數據，比賽中用來更新比分
"""

from __future__ import annotations

import time
from datetime import date, datetime, timedelta

import httpx

from ..config import Config
from ..models import Game, TeamLine
from ..teams import TPBL_TEAMS, match_tw_team
from .base import to_int

API = "https://api.tpbl.basketball/api"
LIVE_STATUS = {"IN_PROGRESS", "LIVE", "PLAYING", "STARTED", "ONGOING"}
POSTPONED_STATUS = {"POSTPONED", "CANCELLED", "CANCELED", "SUSPENDED"}
GAME_LENGTH = timedelta(hours=2, minutes=30)


class TPBL:
    key = "tpbl"
    name = "TPBL"

    def __init__(self):
        self._season_games: list[dict] = []
        self._season_at = 0.0

    async def _games(self, client: httpx.AsyncClient) -> list[dict]:
        # 整季賽程很大，每 10 分鐘才重抓；比分另外用 /stats 更新
        if time.time() - self._season_at < 600 and self._season_games:
            return self._season_games
        r = await client.get(f"{API}/seasons")
        r.raise_for_status()
        seasons = r.json()
        if isinstance(seasons, dict):
            seasons = seasons.get("data", [])
        seasons = sorted(seasons, key=lambda s: str(s.get("started_at", "")), reverse=True)
        games: list[dict] = []
        for s in seasons[:2]:  # 最新兩個賽季（例行賽與季後賽可能分開）
            r = await client.get(f"{API}/seasons/{s['id']}/games")
            r.raise_for_status()
            data = r.json()
            games += data.get("data", []) if isinstance(data, dict) else data
        self._season_games, self._season_at = games, time.time()
        return games

    async def fetch(self, client: httpx.AsyncClient, cfg: Config, day: date) -> list[Game]:
        rows = await self._games(client)
        games = parse(rows, cfg, day)
        for g in games:
            if g.state == "live" or (g.state == "pre" and g.start <= datetime.now(cfg.tz)):
                try:
                    r = await client.get(f"{API}/games/{g.id}/stats")
                    r.raise_for_status()
                    apply_stats(g, r.json())
                    if g.state == "pre" and (g.away.score or g.home.score):
                        g.state = "live"
                except Exception:
                    pass
        return games


def _team(t: dict, cfg: Config) -> TeamLine:
    full = t.get("name", "") if isinstance(t, dict) else str(t)
    code, short, color = match_tw_team(TPBL_TEAMS, full, cfg.aliases)
    return TeamLine(code, short, full, color, to_int(t.get("won_score")) if isinstance(t, dict) else None)


def parse(rows: list[dict], cfg: Config, day: date) -> list[Game]:
    tz = cfg.tz
    out: list[Game] = []
    for x in rows:
        if str(x.get("game_date", ""))[:10] != day.isoformat():
            continue
        hhmm = str(x.get("game_time") or "00:00")[:5]
        start = datetime.fromisoformat(f"{day.isoformat()}T{hhmm}").replace(tzinfo=tz)
        status = str(x.get("status", "")).upper()
        if status == "COMPLETED":
            state = "final"
        elif x.get("is_live") or status in LIVE_STATUS:
            state = "live"
        elif status in POSTPONED_STATUS:
            state = "postponed"
        else:
            state = "pre"
        away, home = _team(x.get("away_team") or {}, cfg), _team(x.get("home_team") or {}, cfg)
        # 有些已打完的比賽 status 還沒更新成 COMPLETED：有比分且開打超過 2.5 小時就當作終場
        has_score = (away.score or 0) + (home.score or 0) > 0
        if state == "pre" and has_score and datetime.now(tz) >= start + GAME_LENGTH:
            state = "final"
        if state == "pre":
            away.score = home.score = None
        out.append(
            Game(
                league="TPBL",
                id=str(x.get("id")),
                start=start,
                state=state,  # type: ignore[arg-type]
                away=away,
                home=home,
                venue=str((x.get("venue") or {}).get("name", "") if isinstance(x.get("venue"), dict) else x.get("venue") or ""),
                detail=status,
            )
        )
    return out


def apply_stats(g: Game, data: dict):
    for side, line in (("home_team", g.home), ("away_team", g.away)):
        t = data.get(side) or {}
        total = ((t.get("teams") or {}).get("total")) if isinstance(t.get("teams"), dict) else None
        score = to_int((total or {}).get("won_score")) if isinstance(total, dict) else None
        if score is None:
            score = to_int(t.get("won_score"))
        if score is not None:
            line.score = score
    q = to_int(data.get("quarter") or data.get("current_quarter"))
    if q:
        g.period = q
    clock = data.get("quarter_time") or data.get("clock")
    if clock:
        g.clock = str(clock)
