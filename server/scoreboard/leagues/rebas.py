"""中職資料來源：野球革命 Rebas（rebas.tw）網站前端使用的公開 JSON。

GET https://www.rebas.tw/api/leagues/CPBL 列出所有賽季（uniqid、type、start_at、end_at），
例如 CPBL-2026-oB 例行賽、CPBL-2026-YQ 季後挑戰賽、CPBL-2026-LU 台灣大賽，
所以每天自動挑出日期涵蓋當天的賽季，不用手動設定代碼。

GET https://www.rebas.tw/api/seasons/{賽季代碼}/games 會回傳整季的比賽，每場有：
  away / home：team（隊名）、runs（得分）、scores（每局得分）、hits、errors、scheduled_SP（預告先發）
  info：status（FINISHED…）、scheduled_start_at（"2026-10-06 18:35"）、location_abbr、innings
  group：例行賽 / 季後賽…
整季資料約 500KB，所以快取起來，比賽中也最多每分鐘重抓一次。
"""

from __future__ import annotations

import json
import time
from datetime import date, datetime, timedelta

import httpx

from ..config import Config
from ..models import Game, TeamLine
from ..teams import CPBL_TEAMS, match_tw_team
from .base import to_int

API = "https://www.rebas.tw/api/seasons/{season}/games"
LEAGUE_API = "https://www.rebas.tw/api/leagues/CPBL"
HEADERS = {"Accept": "application/json", "Origin": "https://www.rebas.tw", "Referer": "https://www.rebas.tw/"}
LIVE_TTL = 60  # 有比賽進行中：最多每 60 秒重抓整季資料
IDLE_TTL = 600
SEASONS_TTL = 6 * 3600  # 賽季清單很少變動


def default_seasons(year: int) -> list[str]:
    return [f"CPBL-{year}-oB"]


def seasons_for(seasons: list[dict], day: date) -> list[str]:
    """從賽季清單挑出日期涵蓋 day 的賽季（前後各放寬一天，因為延賽可能超出原定期間）。"""
    out = []
    for s in seasons:
        try:
            start = datetime.fromisoformat(str(s["start_at"])).date()
            end = datetime.fromisoformat(str(s["end_at"])).date()
        except (KeyError, ValueError):
            continue
        if start - timedelta(days=1) <= day <= end + timedelta(days=1) and s.get("uniqid"):
            out.append(str(s["uniqid"]))
    return out


class Rebas:
    def __init__(self):
        self._cache: dict[str, tuple[float, list[dict]]] = {}
        self._seasons: list[dict] = []
        self._seasons_at = 0.0

    async def _season_list(self, client: httpx.AsyncClient) -> list[dict]:
        if self._seasons and time.time() - self._seasons_at < SEASONS_TTL:
            return self._seasons
        r = await client.get(LEAGUE_API, headers=HEADERS)
        r.raise_for_status()
        data = json.loads(r.text, strict=False)  # 賽季說明欄位可能含換行字元
        self._seasons = (data.get("data") or {}).get("seasons") or []
        self._seasons_at = time.time()
        return self._seasons

    async def _seasons_for(self, client: httpx.AsyncClient, cfg: Config, day: date) -> list[str]:
        manual = cfg.league("cpbl").get("rebas_seasons")
        if manual:
            return manual
        try:
            found = seasons_for(await self._season_list(client), day)
        except Exception:  # 賽季清單抓不到時退回例行賽代碼
            return default_seasons(day.year)
        return found

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
        seasons = await self._seasons_for(client, cfg, day)
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
        season = g.get("season") or {}
        if group not in ("", "例行賽") or str(season.get("type", "")).upper() in ("POSTSEASON", "CHALLENGE"):
            # 季後賽的 group 只寫「季後賽」，用賽季標題「中職2026年-台灣大賽」＋場次 seq 組成「台灣大賽G7」
            name = str(season.get("title") or "").split("-")[-1].strip() or group
            label = f"{name}G{g['seq']}" if to_int(g.get("seq")) else name
        else:
            label = ""
        out.append(
            Game(
                league="CPBL",
                id=str(g.get("uniqid")),
                start=start,
                state=state,  # type: ignore[arg-type]
                away=lines[0],
                home=lines[1],
                venue=str(info.get("location_abbr") or info.get("location") or ""),
                label=label,
                # 進行中：客隊已有第 n 局成績、主隊還沒有 → n 局上；兩隊一樣多 → n 局下
                inning=(a_innings or None) if state == "live" else (to_int(info.get("innings")) or None),
                top=(a_innings > h_innings) if state == "live" else None,
                detail=str(info.get("status", "")),
                extra={"source": "rebas"},
            )
        )
    return out
