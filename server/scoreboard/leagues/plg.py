"""P. LEAGUE+：官網 pleagueofficial.com。

- 賽程：解析 /schedule-regular-season（以及季後賽頁）HTML
- 比分：/api/boxscore.preciser.php?id={game_id}，比賽中用來更新即時比分

官網沒有公開 API，HTML 結構改版時需要調整選擇器（見 parse_schedule）。
"""

from __future__ import annotations

import re
import time
from datetime import date, datetime, timedelta

import httpx
from bs4 import BeautifulSoup

from ..config import Config
from ..models import Game, TeamLine
from ..teams import PLG_TEAMS, match_tw_team
from .base import to_int

BASE = "https://pleagueofficial.com"
PAGES = ["/schedule-regular-season", "/schedule-playoffs", "/schedule-finals"]
# 官網賽程頁看不出比賽是否「進行中」，開打後這段時間內都視為比賽中，再由 boxscore 更新比分
GAME_LENGTH = timedelta(hours=2, minutes=30)


class PLG:
    key = "plg"
    name = "PLG"

    def __init__(self):
        self._rows: list[dict] = []
        self._at = 0.0

    async def _schedule(self, client: httpx.AsyncClient) -> list[dict]:
        if time.time() - self._at < 600 and self._rows:
            return self._rows
        rows: list[dict] = []
        errors: list[Exception] = []
        for p in PAGES:
            try:
                r = await client.get(BASE + p)
                if r.status_code == 200:
                    rows += parse_schedule(r.text)
            except httpx.HTTPError as e:  # 季後賽頁面不一定存在，個別失敗沒關係
                errors.append(e)
        if len(errors) == len(PAGES):
            raise errors[0]
        self._rows, self._at = rows, time.time()
        return rows

    async def fetch(self, client: httpx.AsyncClient, cfg: Config, day: date) -> list[Game]:
        rows = [r for r in await self._schedule(client) if r["date"] == day]
        now = datetime.now(cfg.tz)
        games = [to_game(r, cfg, now) for r in rows]
        for g in games:
            if g.state == "live":
                try:
                    r = await client.get(
                        f"{BASE}/api/boxscore.preciser.php",
                        params={"id": g.id, "away_tab": "total", "home_tab": "total"},
                    )
                    r.raise_for_status()
                    apply_box(g, r.json())
                except Exception:
                    pass
        return games


def parse_schedule(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for row in soup.select(".match_row"):
        link = row.select_one('a[href*="/game/"]')
        if not link:
            continue
        gid = link["href"].rstrip("/").split("/")[-1]
        ym = re.search(r"d-(\d{4})-(\d{2})", " ".join(row.get("class", [])))
        dt = row.select_one(".match_row_datetime")
        md = re.search(r"(\d{1,2})/(\d{1,2})", dt.select_one("h5").get_text() if dt and dt.select_one("h5") else "")
        tm = re.search(r"(\d{1,2}):(\d{2})", dt.select_one("h6").get_text() if dt and dt.select_one("h6") else "")
        if not (ym and md):
            continue
        d = date(int(ym.group(1)), int(md.group(1)), int(md.group(2)))
        names = [s.get_text(strip=True) for s in row.select(".text-black > span.PC_only")]
        scores = [to_int(s.get_text(strip=True)) for s in row.select("h6.PC_only.ff8bit")]
        if len(names) < 2:
            continue
        future = "is-future" in row.get("class", [])
        out.append(
            {
                "id": gid,
                "date": d,
                "time": (int(tm.group(1)), int(tm.group(2))) if tm else (19, 0),
                "away": names[0],
                "home": names[1],
                "away_score": scores[0] if len(scores) > 1 else None,
                "home_score": scores[1] if len(scores) > 1 else None,
                "future": future,
            }
        )
    return out


def to_game(r: dict, cfg: Config, now: datetime) -> Game:
    tz = cfg.tz
    start = datetime(r["date"].year, r["date"].month, r["date"].day, *r["time"], tzinfo=tz)
    ac, an, acol = match_tw_team(PLG_TEAMS, r["away"], cfg.aliases)
    hc, hn, hcol = match_tw_team(PLG_TEAMS, r["home"], cfg.aliases)
    has_score = r["away_score"] is not None and r["home_score"] is not None and (r["away_score"] + r["home_score"]) > 0
    if start <= now < start + GAME_LENGTH:
        state = "live"
    elif not r["future"] and has_score:
        state = "final"
    else:
        state = "pre"
    return Game(
        league="PLG",
        id=r["id"],
        start=start,
        state=state,  # type: ignore[arg-type]
        away=TeamLine(ac, an, r["away"], acol, r["away_score"] if has_score else None),
        home=TeamLine(hc, hn, r["home"], hcol, r["home_score"] if has_score else None),
    )


def apply_box(g: Game, data: dict):
    d = data.get("data", data)
    a, h = to_int(d.get("score_away")), to_int(d.get("score_home"))
    if a is not None and h is not None and (a + h) > 0:
        g.away.score, g.home.score = a, h
    status = str(d.get("status") or d.get("game_status") or "")
    if any(w in status for w in ("結束", "Final", "FINAL", "END")):
        g.state = "final"
    q = to_int(d.get("quarter") or d.get("current_quarter"))
    if q:
        g.period = q
