"""中華職棒。

主要來源是野球革命 Rebas 的公開 JSON（見 rebas.py），抓不到時才改用中職官網。

官網 www.cpbl.com.tw 內部使用的 AJAX 介面（非公開 API，官網改版可能失效）流程：
1. GET /schedule 取得 cookie 與頁面裡的 RequestVerificationToken
2. POST /schedule/getgamedatas（calendar=YYYY/MM/01, kindCode=A/E/C/G）取得當月賽程與比分
3. 比賽進行中時，POST /box/getlive 取得局數（盡力而為，失敗就只顯示比分）

欄位名稱來自社群專案的觀察，所以每個欄位都準備了幾個候選 key。
若抓不到資料，執行 `python -m scoreboard probe cpbl` 把原始回應存下來對照修正。
"""

from __future__ import annotations

import json
import re
from datetime import date

import httpx

from ..config import Config
from ..models import Game, TeamLine
from ..teams import CPBL_TEAMS, match_tw_team
from .base import parse_iso, to_int
from .rebas import LIVE_TTL, Rebas

BASE = "https://www.cpbl.com.tw"
# A 例行賽、E 季後挑戰賽、C 總冠軍賽、G 熱身賽
KINDS = {"A": "", "E": "季後挑戰", "C": "總冠軍賽", "G": "熱身賽"}
TOKEN_RE = re.compile(r"RequestVerificationToken['\"]?\s*[:=]\s*['\"]([^'\"]{20,})['\"]")
INPUT_TOKEN_RE = re.compile(r'name="__RequestVerificationToken"[^>]*value="([^"]+)"')


def pick(row: dict, *keys, default=None):
    for k in keys:
        if k in row and row[k] not in (None, ""):
            return row[k]
    return default


def find_token(html: str) -> str | None:
    m = TOKEN_RE.search(html) or INPUT_TOKEN_RE.search(html)
    return m.group(1) if m else None


def decode_list(payload) -> list[dict]:
    """GameDatas 有時是 JSON 字串、有時是 list。"""
    if isinstance(payload, dict):
        for k in ("GameDatas", "gameDatas", "data", "Data"):
            if k in payload:
                return decode_list(payload[k])
        return []
    if isinstance(payload, str):
        try:
            return decode_list(json.loads(payload))
        except json.JSONDecodeError:
            return []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


class CPBL:
    key = "cpbl"
    name = "CPBL"
    min_live_seconds = LIVE_TTL  # 野球革命每次都要下載整季資料，比賽中最快 10 秒更新一次

    def __init__(self):
        self._token: str | None = None
        self.rebas = Rebas()

    async def _get_token(self, client: httpx.AsyncClient, path: str = "/schedule") -> str:
        r = await client.get(BASE + path)
        r.raise_for_status()
        tok = find_token(r.text)
        if not tok:
            raise RuntimeError("CPBL：頁面裡找不到 RequestVerificationToken，官網可能改版了")
        return tok

    async def _post(self, client: httpx.AsyncClient, path: str, data: dict, referer: str) -> dict:
        headers = {
            "RequestVerificationToken": self._token or "",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BASE + referer,
            "Origin": BASE,
        }
        r = await client.post(BASE + path, data=data, headers=headers)
        if r.status_code in (400, 401, 403, 500):
            # token 過期：重新取得一次
            self._token = await self._get_token(client, referer)
            headers["RequestVerificationToken"] = self._token
            r = await client.post(BASE + path, data=data, headers=headers)
        r.raise_for_status()
        return r.json()

    async def fetch_raw(self, client: httpx.AsyncClient, day: date) -> dict[str, list[dict]]:
        if not self._token:
            self._token = await self._get_token(client)
        out: dict[str, list[dict]] = {}
        for kind in KINDS:
            data = await self._post(
                client,
                "/schedule/getgamedatas",
                {"calendar": f"{day.year}/{day.month:02d}/01", "location": "", "kindCode": kind},
                "/schedule",
            )
            out[kind] = decode_list(data)
        return out

    async def fetch(self, client: httpx.AsyncClient, cfg: Config, day: date) -> list[Game]:
        try:
            return await self.rebas.fetch(client, cfg, day)
        except Exception as e:  # 野球革命抓不到時改用官網
            rebas_error = e
        try:
            return await self.fetch_official(client, cfg, day)
        except Exception as e:
            raise RuntimeError(f"野球革命：{type(rebas_error).__name__}: {rebas_error}；官網：{type(e).__name__}: {e}") from e

    async def fetch_official(self, client: httpx.AsyncClient, cfg: Config, day: date) -> list[Game]:
        raw = await self.fetch_raw(client, day)
        games: list[Game] = []
        for kind, rows in raw.items():
            games += parse_rows(rows, kind, cfg, day)
        for g in games:
            if g.state == "live":
                try:
                    await self._enrich_live(client, g)
                except Exception:  # 局數只是加分項目，失敗不影響比分顯示
                    pass
        return games

    async def _enrich_live(self, client: httpx.AsyncClient, g: Game):
        kind, sno, year = g.extra["kind"], g.extra["sno"], g.start.year
        referer = f"/box/index?year={year}&kindCode={kind}&gameSno={sno}"
        data = await self._post(
            client,
            "/box/getlive",
            {"GameSno": sno, "KindCode": kind, "Year": year, "PrevOrNext": "", "PresentStatus": ""},
            referer,
        )
        apply_live(g, data)


def _state(row: dict, has_score: bool) -> str:
    text = str(pick(row, "GameStatusChi", "GameStatusName", "PresentStatusChi", "GameResultName", default=""))
    code = to_int(pick(row, "GameStatus", "PresentStatus"))
    if any(w in text for w in ("延", "取消", "保留", "暫停")):
        return "postponed"
    if any(w in text for w in ("結束", "終")):
        return "final"
    if any(w in text for w in ("比賽中", "進行")):
        return "live"
    if code is not None:
        # 官網常見代碼：1 未開賽、2 比賽中、3 比賽結束、其他為延賽/保留/取消
        return {1: "pre", 2: "live", 3: "final"}.get(code, "postponed" if code > 3 else "pre")
    if str(pick(row, "GameResult", default="")) not in ("", "-1") and has_score:
        return "final"
    return "pre"


def parse_rows(rows: list[dict], kind: str, cfg: Config, day: date) -> list[Game]:
    tz = cfg.tz
    games: list[Game] = []
    for row in rows:
        when = pick(row, "PreExeDate", "GameDateTimeS", "GameDateTime", "StartDateTime")
        gdate = pick(row, "GameDate", "GameDateS", "Date")
        try:
            start = parse_iso(str(when or gdate), tz)
        except ValueError:
            continue
        if gdate:
            try:
                if parse_iso(str(gdate), tz).date() != day:
                    continue
            except ValueError:
                pass
        if start.date() != day:
            continue

        away_full = str(pick(row, "VisitingTeamName", "VisitingName", "AwayTeamName", default=""))
        home_full = str(pick(row, "HomeTeamName", "HomeName", default=""))
        ac, an, acol = match_tw_team(CPBL_TEAMS, away_full, cfg.aliases)
        hc, hn, hcol = match_tw_team(CPBL_TEAMS, home_full, cfg.aliases)
        a_score = to_int(pick(row, "VisitingScore", "VisitingTotalScore", "AwayScore"))
        h_score = to_int(pick(row, "HomeScore", "HomeTotalScore"))
        state = _state(row, a_score is not None and h_score is not None)
        if state == "pre":
            a_score = h_score = None

        sno = pick(row, "GameSno", "GameNo", "Sno")
        label = KINDS.get(kind, "")
        if kind in ("C", "E") and sno:
            label = f"{label}G{sno}"
        elif kind == "A" and sno:
            label = f"#{sno}"

        games.append(
            Game(
                league="CPBL",
                id=f"{kind}-{sno}",
                start=start,
                state=state,  # type: ignore[arg-type]
                away=TeamLine(ac, an, away_full, acol, a_score,
                              pick(row, "VisitingFirstMover", "VisitingPitcherName")),
                home=TeamLine(hc, hn, home_full, hcol, h_score,
                              pick(row, "HomeFirstMover", "HomePitcherName")),
                venue=str(pick(row, "FieldAbbe", "FieldName", "Field", default="")),
                label=label,
                detail=str(pick(row, "GameStatusChi", "GameResultName", default="")),
                extra={"kind": kind, "sno": sno},
            )
        )
    return games


def apply_live(g: Game, data: dict):
    """從 /box/getlive 的回應中取出目前局數、出局數與比分。"""
    def load(key):
        v = data.get(key)
        if isinstance(v, str):
            try:
                return json.loads(v)
            except json.JSONDecodeError:
                return None
        return v

    board = load("ScoreboardJson") or []
    if isinstance(board, list) and board:
        last = max(board, key=lambda b: (to_int(b.get("InningSeq")) or 0, to_int(b.get("VisitingHomeType")) or 0))
        g.inning = to_int(last.get("InningSeq"))
        vh = to_int(last.get("VisitingHomeType"))
        if vh is not None:
            g.top = vh == 1
        a = sum(to_int(b.get("ScoreCnt")) or 0 for b in board if to_int(b.get("VisitingHomeType")) == 1)
        h = sum(to_int(b.get("ScoreCnt")) or 0 for b in board if to_int(b.get("VisitingHomeType")) == 2)
        g.away.score = max(g.away.score or 0, a)
        g.home.score = max(g.home.score or 0, h)

    detail = load("CurtGameDetailJson") or {}
    if isinstance(detail, list):
        detail = detail[-1] if detail else {}
    if isinstance(detail, dict):
        outs = to_int(pick(detail, "OutCnt", "Out", "OutCount"))
        if outs is not None:
            g.outs = outs
        bases = [pick(detail, k) for k in ("FirstBase", "SecondBase", "ThirdBase")]
        if any(b is not None for b in bases):
            g.bases = tuple(bool(b) and str(b) not in ("0", "False") for b in bases)  # type: ignore[assignment]
