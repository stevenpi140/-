"""中職資料來源：野球革命 Rebas（rebas.tw）網站前端使用的公開 JSON。

GET https://www.rebas.tw/api/seasons/{賽季代碼}/games 會回傳整季的比賽，每場有：
  away / home：team（隊名）、runs（得分）、scores（每局得分）、hits、errors、scheduled_SP（預告先發）
  info：status（FINISHED…）、scheduled_start_at（"2026-10-06 18:35"）、location_abbr、innings
  group：例行賽 / 季後賽…
整季資料約 500KB，所以快取起來，比賽中也最多每分鐘重抓一次。
"""

from __future__ import annotations

import time
from datetime import date, datetime

import httpx

from ..config import Config
from ..models import Game, TeamLine
from ..teams import CPBL_TEAMS, match_tw_team
from .base import to_int

API = "https://www.rebas.tw/api/seasons/{season}/games"
HEADERS = {"Accept": "application/json", "Origin": "https://www.rebas.tw", "Referer": "https://www.rebas.tw/"}
LIVE_TTL = 60  # 有比賽進行中：最多每 60 秒重抓整季資料
IDLE_TTL = 600


def default_seasons(year: int) -> list[str]:
    return [f"CPBL-{year}-oB"]


class Rebas:
    def __init__(self):
        self._cache: dict[str, tuple[float, list[dict]]] = {}

    async def _season(self, client: httpx.AsyncClient, season: str, ttl: float) -> list[dict]:
        at, rows = self._cache.get(season, (0.0, []))
        if rows and time.time() - at < ttl:
            return rows
        r = await client.get(API.format(season=season), headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        rows = data.get("data", []) if isinstance(data, dict) else data
        self._cache[season] = (time.time(), rows)
        return rows

    async def fetch(self, client: httpx.AsyncClient, cfg: Config, day: date) -> list[Game]:
        seasons = cfg.league("cpbl").get("rebas_seasons") or default_seasons(day.year)
        had_live = any(g.state == "live" for g in getattr(self, "_last", []))
        games: list[Game] = []
        for s in seasons:
            games += parse(await self._season(client, s, LIVE_TTL if had_live else IDLE_TTL), cfg, day)
        self._last = games
        return games


def _sp(side: dict) -> str | None:
    sp = side.get("scheduled_SP")
    if isinstance(sp, dict):
        return sp.get("name") or sp.get("player_name")
    return sp or None


def _state(info: dict) -> str:
    status = str(info.get("status", "")).upper()
    finished = str(info.get("finished_status", "NORMAL")).upper()
    if any(w in status or w in finished for w in ("POSTPON", "CANCEL", "SUSPEND", "DELAY")):
        return "postponed"
    if status == "FINISHED":
        return "final"
    if any(w in status for w in ("PLAYING", "LIVE", "PROGRESS")):
        return "live"
    if info.get("started_at") and not info.get("ended_at"):
        return "live"
    return "pre"


def parse(rows: list[dict], cfg: Config, day: date) -> list[Game]:
    tz = cfg.tz
    out: list[Game] = []
    for g in rows:
        info = g.get("info") or {}
        when = str(info.get("scheduled_start_at") or "")
        try:
            start = datetime.strptime(when[:16], "%Y-%m-%d %H:%M").replace(tzinfo=tz)
        except ValueError:
            continue
        if start.date() != day:
            continue
        away, home = g.get("away") or {}, g.get("home") or {}
        state = _state(info)
        lines = []
        for side in (away, home):
            code, short, color = match_tw_team(CPBL_TEAMS, str(side.get("team", "")), cfg.aliases)
            score = to_int(side.get("runs")) if state != "pre" else None
            lines.append(TeamLine(code, short, str(side.get("team", "")), color, score, _sp(side)))
        a_innings, h_innings = len(away.get("scores") or []), len(home.get("scores") or [])
        group = str(g.get("group") or "")
        out.append(
            Game(
                league="CPBL",
                id=str(g.get("uniqid")),
                start=start,
                state=state,  # type: ignore[arg-type]
                away=lines[0],
                home=lines[1],
                venue=str(info.get("location_abbr") or info.get("location") or ""),
                label="" if group in ("", "例行賽") else group,
                # 進行中：客隊已有第 n 局成績、主隊還沒有 → n 局上；兩隊一樣多 → n 局下
                inning=(a_innings or None) if state == "live" else (to_int(info.get("innings")) or None),
                top=(a_innings > h_innings) if state == "live" else None,
                detail=str(info.get("status", "")),
                extra={"source": "rebas"},
            )
        )
    return out
