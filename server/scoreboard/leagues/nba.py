"""NBA：ESPN 公開 scoreboard JSON（免金鑰，非官方文件化）。"""

from __future__ import annotations

from datetime import date

import httpx

from ..config import Config
from ..models import Game, TeamLine
from ..teams import nba_team
from .base import parse_iso, to_int, us_dates_for

URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"


class NBA:
    key = "nba"
    name = "NBA"

    async def fetch(self, client: httpx.AsyncClient, cfg: Config, day: date) -> list[Game]:
        events: list[dict] = []
        for d in us_dates_for(day):
            r = await client.get(URL, params={"dates": d.strftime("%Y%m%d")})
            r.raise_for_status()
            events += r.json().get("events", [])
        return parse({"events": events}, cfg, day)


def _side(c: dict) -> TeamLine:
    t = c.get("team", {})
    code, zh, color = nba_team(t.get("abbreviation", ""), t.get("shortDisplayName", ""))
    return TeamLine(code=code, name=zh, full=t.get("displayName", ""), color=color, score=to_int(c.get("score")))


def parse(data: dict, cfg: Config, day: date) -> list[Game]:
    tz = cfg.tz
    games: list[Game] = []
    seen: set[str] = set()
    for ev in data.get("events", []):
        if ev.get("id") in seen:
            continue
        seen.add(ev.get("id"))
        start = parse_iso(ev["date"], tz)
        if start.date() != day:
            continue
        comp = ev["competitions"][0]
        st = comp.get("status") or ev.get("status") or {}
        stype = st.get("type", {})
        state_raw = stype.get("state", "pre")
        name = stype.get("name", "")
        if name in ("STATUS_POSTPONED", "STATUS_CANCELED"):
            state = "postponed"
        else:
            state = {"pre": "pre", "in": "live", "post": "final"}.get(state_raw, "pre")
        sides = {c.get("homeAway"): c for c in comp.get("competitors", [])}
        if "home" not in sides or "away" not in sides:
            continue
        clock = st.get("displayClock", "")
        if name == "STATUS_HALFTIME":
            clock = "中場"
        elif name == "STATUS_END_PERIOD":
            clock = "節末"
        label = ""
        notes = comp.get("notes") or []
        if notes and notes[0].get("headline"):
            h = notes[0]["headline"]
            label = "季後賽" if "Game" in h else ("季中賽" if "Cup" in h else "")
            if "Game" in h:
                num = h.split("Game")[-1].strip().split(" ")[0]
                if num.isdigit():
                    label += f"G{num}"
        games.append(
            Game(
                league="NBA",
                id=str(ev.get("id")),
                start=start,
                state=state,  # type: ignore[arg-type]
                away=_side(sides["away"]),
                home=_side(sides["home"]),
                venue=(comp.get("venue") or {}).get("fullName", ""),
                label=label,
                period=to_int(st.get("period")) or None,
                clock=clock,
                detail=stype.get("shortDetail", ""),
            )
        )
    return games
