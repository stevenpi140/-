"""MLB：官方 Stats API（statsapi.mlb.com，免金鑰）。"""

from __future__ import annotations

from datetime import date

import httpx

from ..config import Config
from ..models import Game, TeamLine
from ..teams import mlb_team
from .base import parse_iso, to_int, us_dates_for

URL = "https://statsapi.mlb.com/api/v1/schedule"

SERIES = {"F": "外卡", "D": "分區", "L": "聯盟冠軍", "W": "世界大賽", "S": "春訓", "E": "表演賽", "A": "明星賽"}


class MLB:
    key = "mlb"
    name = "MLB"

    async def fetch(self, client: httpx.AsyncClient, cfg: Config, day: date) -> list[Game]:
        us = us_dates_for(day)
        r = await client.get(
            URL,
            params={
                "sportId": 1,
                "startDate": us[0].isoformat(),
                "endDate": us[-1].isoformat(),
                "hydrate": "linescore,probablePitcher,venue",
            },
        )
        r.raise_for_status()
        return parse(r.json(), cfg, day)


def _side(t: dict) -> TeamLine:
    team = t.get("team", {})
    code, zh, color = mlb_team(team.get("id", 0), team.get("name", ""))
    pp = t.get("probablePitcher") or {}
    return TeamLine(
        code=code,
        name=zh,
        full=team.get("name", ""),
        color=color,
        score=to_int(t.get("score")),
        pitcher=pp.get("lastName") or pp.get("fullName"),
    )


def parse(data: dict, cfg: Config, day: date) -> list[Game]:
    tz = cfg.tz
    games: list[Game] = []
    for d in data.get("dates", []):
        for g in d.get("games", []):
            start = parse_iso(g["gameDate"], tz)
            if start.date() != day:
                continue
            st = g.get("status", {})
            abstract = st.get("abstractGameState", "")
            coded = st.get("codedGameState", "")
            detailed = st.get("detailedState", "")
            if coded in ("D", "C") or "Postponed" in detailed or "Cancelled" in detailed:
                state = "postponed"
            elif abstract == "Final":
                state = "final"
            elif abstract == "Live":
                state = "live"
            else:
                state = "pre"
            ls = g.get("linescore") or {}
            offense = ls.get("offense") or {}
            label = ""
            gt = g.get("gameType", "R")
            if gt in SERIES:
                label = SERIES[gt]
                if g.get("seriesGameNumber") and gt in "FDLW":
                    label += f"G{g['seriesGameNumber']}"
            inning = to_int(ls.get("currentInning"))
            inning_state = ls.get("inningState", "")
            top = ls.get("isTopInning")
            # 局間攻守交換時，直接顯示即將開始的半局
            if state == "live" and inning_state == "Middle":
                top = False
            elif state == "live" and inning_state == "End" and inning:
                inning, top = inning + 1, True
            away, home = _side(g["teams"]["away"]), _side(g["teams"]["home"])
            if state in ("live", "final"):
                for line, key in ((away, "away"), (home, "home")):
                    t = (ls.get("teams") or {}).get(key) or {}
                    line.hits, line.errors = to_int(t.get("hits")), to_int(t.get("errors"))
            games.append(
                Game(
                    league="MLB",
                    id=str(g.get("gamePk")),
                    start=start,
                    state=state,  # type: ignore[arg-type]
                    away=away,
                    home=home,
                    venue=(g.get("venue") or {}).get("name", ""),
                    label=label,
                    inning=inning,
                    top=top,
                    outs=to_int(ls.get("outs")),
                    bases=(bool(offense.get("first")), bool(offense.get("second")), bool(offense.get("third")))
                    if state == "live"
                    else None,
                    detail="延賽" if state == "postponed" else detailed,
                )
            )
    return games
