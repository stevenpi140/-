"""中華職棒。

主要來源是中職官網 www.cpbl.com.tw，抓不到時改用野球革命 Rebas（見 rebas.py）。
官網從國外機房連線會被 HiNet CDN 回 404，在台灣的網路才連得上；所以伺服器要放在台灣。

官網內部使用的 AJAX 介面（非公開 API，官網改版可能失效）：
1. GET /schedule 取得 cookie 與頁面裡的 RequestVerificationToken
2. POST /schedule/getgamedatas（kindCode=A/E/C/G、year、calendar=YYYY/MM/01）取得當月賽程
   注意：這裡沒有 GameStatus，PresentStatus 的意義也和單場介面不同，不能當比賽狀態用
3. POST /box/getlive（Year、KindCode、GameSno）取得單場完整資料：
   - GameDetailJson：GameStatus（1 未開打、2 比賽中、3 比賽結束）、GameStatusChi、比分
   - ScoreboardJson：每個半局的得分、安打、失誤 → R / H / E
   - LiveLogJson：逐球紀錄 → 目前局數、出局數、壘包、好壞球
   多數區塊是「JSON 字串」，要再解碼一次。

若抓不到資料，執行 `python -m scoreboard probe cpbl` 把原始回應存下來對照修正。
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import date, datetime

import httpx

from ..config import Config
from ..models import Game, TeamLine
from ..teams import CPBL_TEAMS, match_tw_team
from .base import parse_iso, to_int
from .rebas import Rebas

log = logging.getLogger("scoreboard")

BASE = "https://www.cpbl.com.tw"
# A 一軍例行賽、E 季後挑戰賽、C 台灣大賽（總冠軍賽）、G 熱身賽
KINDS = {"A": "", "E": "季後挑戰賽", "C": "台灣大賽", "G": "熱身賽"}
SCHEDULE_TTL = 600  # 整月賽程 10 分鐘重抓一次；比賽中的狀態和比分改由 /box/getlive 更新
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


def decode(v):
    """官網的資料區塊常常是 JSON 字串，解開成 list / dict。"""
    if isinstance(v, str):
        try:
            return json.loads(v)
        except json.JSONDecodeError:
            return None
    return v


def decode_list(payload) -> list[dict]:
    """GameDatas 有時是 JSON 字串、有時是 list。"""
    if isinstance(payload, dict):
        for k in ("GameDatas", "gameDatas", "data", "Data"):
            if k in payload:
                return decode_list(payload[k])
        return []
    if isinstance(payload, str):
        v = decode(payload)
        return decode_list(v) if v is not None else []
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    return []


class CPBL:
    key = "cpbl"
    name = "CPBL"
    min_live_seconds = 5  # /box/getlive 每次都回傳整場逐球紀錄，比賽中最快 5 秒抓一次

    def __init__(self):
        self._token: str | None = None
        self._schedule: dict[tuple, tuple[float, list[dict]]] = {}
        self._finished: dict[str, dict] = {}  # 已結束比賽的 getlive 結果，不會再變，不用重抓
        self.rebas = Rebas()

    async def fetch(self, client: httpx.AsyncClient, cfg: Config, day: date) -> list[Game]:
        try:
            return await self.fetch_official(client, cfg, day)
        except Exception as e:  # 官網抓不到（例如伺服器不在台灣）時改用野球革命
            official_error = e
            log.info("中職官網抓不到，改用野球革命：%s: %s", type(e).__name__, e)
        try:
            return await self.rebas.fetch(client, cfg, day)
        except Exception as e:
            raise RuntimeError(
                f"官網：{type(official_error).__name__}: {official_error}；野球革命：{type(e).__name__}: {e}"
            ) from e

    # ---------- 官網 ----------

    async def _get_token(self, client: httpx.AsyncClient, path: str = "/schedule") -> str:
        r = await client.get(BASE + path)
        r.raise_for_status()
        tok = find_token(r.text)
        if not tok:
            raise RuntimeError("CPBL：頁面裡找不到 RequestVerificationToken，官網可能改版了")
        return tok

    async def _post(self, client: httpx.AsyncClient, path: str, data: dict, referer: str) -> dict:
        if not self._token:
            self._token = await self._get_token(client)
        headers = {
            "RequestVerificationToken": self._token,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": BASE + referer,
            "Origin": BASE,
        }
        r = await client.post(BASE + path, data=data, headers=headers)
        if r.status_code in (400, 401, 403, 500) or "json" not in r.headers.get("content-type", ""):
            # token 過期，或回了 HTML 錯誤頁：重新取得 token 再試一次
            self._token = await self._get_token(client, referer)
            headers["RequestVerificationToken"] = self._token
            r = await client.post(BASE + path, data=data, headers=headers)
        r.raise_for_status()
        out = r.json()
        if isinstance(out, dict) and out.get("Success") is False:
            raise RuntimeError(f"CPBL：{path} 回傳 Success=false")
        return out

    async def fetch_raw(self, client: httpx.AsyncClient, day: date) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        errors = []
        for kind in KINDS:
            key = (day.year, day.month, kind)
            at, rows = self._schedule.get(key, (0.0, []))
            if time.time() - at >= SCHEDULE_TTL:
                try:
                    data = await self._post(
                        client,
                        "/schedule/getgamedatas",
                        {"calendar": f"{day.year}/{day.month:02d}/01", "location": "", "kindCode": kind,
                         "year": str(day.year), "teamNo": ""},
                        "/schedule",
                    )
                except Exception as e:  # 單一賽事類別失敗時，先沿用上次的資料
                    errors.append(f"{kind}: {type(e).__name__}: {e}")
                    out[kind] = rows
                    continue
                rows = decode_list(data)
                self._schedule[key] = (time.time(), rows)
            out[kind] = rows
        if len(errors) == len(KINDS):
            raise RuntimeError("賽程都抓不到（" + "；".join(errors) + "）")
        return out

    async def fetch_official(self, client: httpx.AsyncClient, cfg: Config, day: date) -> list[Game]:
        raw = await self.fetch_raw(client, day)
        games: list[Game] = []
        for kind, rows in raw.items():
            games += parse_rows(rows, kind, cfg, day)
        now = datetime.now(cfg.tz)
        for g in games:
            # 賽程表看不出比賽中的狀態：開打時間到了、還沒確定結束的比賽，都用單場介面更新
            if g.state == "postponed" or (g.state == "pre" and g.start > now):
                continue
            cached = self._finished.get(g.id)
            try:
                data = cached or await self._box(client, g)
            except Exception as e:  # 單場資料失敗時，至少還有賽程表的比分
                log.info("中職 %s 單場資料抓不到：%s", g.id, e)
                continue
            apply_live(g, data)
            if g.state == "final":
                self._finished[g.id] = data
        return games

    async def _box(self, client: httpx.AsyncClient, g: Game) -> dict:
        kind, sno, year = g.extra["kind"], g.extra["sno"], g.start.year
        return await self._post(
            client,
            "/box/getlive",
            {"GameSno": sno, "KindCode": kind, "Year": year, "PrevOrNext": "", "PresentStatus": ""},
            f"/box?year={year}&kindCode={kind}&gameSno={sno}",
        )


# ---------- 解析 ----------

STATUS_CODES = {0: "pre", 1: "pre", 2: "live", 3: "final"}


def _state_from_text(text: str) -> str | None:
    if any(w in text for w in ("延", "取消", "保留", "暫停", "中止")):
        return "postponed"
    if any(w in text for w in ("結束", "終")):
        return "final"
    if any(w in text for w in ("比賽中", "進行")):
        return "live"
    if any(w in text for w in ("未開", "尚未")):
        return "pre"
    return None


def _yes(v) -> bool:
    return str(v).strip().upper() in ("Y", "1", "TRUE")


def schedule_state(row: dict, has_score: bool, start: datetime, now: datetime) -> str:
    """賽程表（getgamedatas）的比賽狀態。

    這個介面沒有 GameStatus，PresentStatus 在已結束的比賽也可能是 1，所以改看：
    結束時間 GameDateTimeE、比賽結果 GameResult、保留比賽 IsGameStop、開打 IsPlayBall。
    """
    text = str(pick(row, "GameStatusChi", "GameResultName", default=""))
    by_text = _state_from_text(text)
    if by_text:
        return by_text
    if "GameStatus" in row and to_int(row["GameStatus"]) is not None:
        code = to_int(row["GameStatus"])
        return STATUS_CODES.get(code, "postponed")
    if _yes(row.get("IsGameStop")):
        return "postponed"
    if row.get("GameDateTimeE"):
        return "final"
    if has_score and str(row.get("GameResult") or "").strip() not in ("", "-1"):
        return "final"
    if has_score and start.date() < now.date():
        return "final"  # 以前的日期還有比分：一定已經打完
    if start <= now and (_yes(row.get("IsPlayBall")) or row.get("GameDateTimeS")):
        return "live"
    return "pre"


def parse_rows(rows: list[dict], kind: str, cfg: Config, day: date, now: datetime | None = None) -> list[Game]:
    tz = cfg.tz
    now = now or datetime.now(tz)
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
        has_score = a_score is not None and h_score is not None and (a_score + h_score > 0 or row.get("GameDateTimeE"))
        state = schedule_state(row, bool(has_score), start, now)
        if state in ("pre", "postponed"):
            a_score = h_score = None

        sno = pick(row, "GameSno", "GameNo", "Sno")
        label = KINDS.get(kind, "")
        if kind in ("C", "E") and sno:
            label = f"{label}G{sno}"

        games.append(
            Game(
                league="CPBL",
                id=f"{start.year}-{kind}-{sno}",
                start=start,
                state=state,  # type: ignore[arg-type]
                away=TeamLine(ac, an, away_full, acol, a_score,
                              pick(row, "VisitingPitcherName", "VisitingFirstMover")),
                home=TeamLine(hc, hn, home_full, hcol, h_score,
                              pick(row, "HomePitcherName", "HomeFirstMover")),
                venue=str(pick(row, "FieldAbbe", "FieldName", "Field", default="")),
                label=label,
                detail=str(pick(row, "GameStatusChi", "GameResultName", default="")),
                extra={"kind": kind, "sno": sno, "source": "official"},
            )
        )
    return games


def _first(v) -> dict:
    v = decode(v)
    if isinstance(v, list):
        return v[0] if v and isinstance(v[0], dict) else {}
    return v if isinstance(v, dict) else {}


def _rows(v) -> list[dict]:
    v = decode(v)
    return [x for x in v if isinstance(x, dict)] if isinstance(v, list) else []


def apply_live(g: Game, data: dict):
    """用 /box/getlive 的回應更新比賽狀態、比分、RHE、局數、出局數與壘包。"""
    detail = _first(data.get("GameDetailJson")) or _first(data.get("CurtGameDetailJson"))
    if detail:
        state = _state_from_text(str(detail.get("GameStatusChi") or ""))
        code = to_int(detail.get("GameStatus"))
        if state is None and code is not None:
            state = STATUS_CODES.get(code, "postponed")
        if state:
            g.state = state  # type: ignore[assignment]
        if detail.get("GameStatusChi"):
            g.detail = str(detail["GameStatusChi"])
    if g.state in ("pre", "postponed"):
        g.away.score = g.home.score = None
        return

    # 比分板：每個半局一列，VisitingHomeType 1 = 客隊、2 = 主隊
    board = _rows(data.get("ScoreboardJson"))
    if board:
        for line, side in ((g.away, 1), (g.home, 2)):
            rows = [b for b in board if to_int(b.get("VisitingHomeType")) == side]
            line.score = sum(to_int(b.get("ScoreCnt")) or 0 for b in rows)
            line.hits = sum(to_int(b.get("HittingCnt")) or 0 for b in rows)
            line.errors = sum(to_int(b.get("ErrorCnt")) or 0 for b in rows)
        last = max(board, key=lambda b: (to_int(b.get("InningSeq")) or 0, to_int(b.get("VisitingHomeType")) or 0))
        g.inning = to_int(last.get("InningSeq"))
        g.top = to_int(last.get("VisitingHomeType")) == 1
    if detail:
        a = to_int(pick(detail, "VisitingTotalScore", "VisitingScore"))
        h = to_int(pick(detail, "HomeTotalScore", "HomeScore"))
        if a is not None and h is not None:
            g.away.score, g.home.score = a, h
    if g.state != "live":
        g.outs = g.bases = None
        return

    # 逐球紀錄：照局數、上下半局、事件編號排序後取最後一筆（換人等事件也會是一列，不能只看陣列長度）
    logs = _rows(data.get("LiveLogJson"))
    if not logs:
        return
    order = {id(x): i for i, x in enumerate(logs)}
    last = max(logs, key=lambda x: (to_int(x.get("InningSeq")) or 0, to_int(x.get("VisitingHomeType")) or 0,
                                    to_int(x.get("MainEventNo")) or 0, order[id(x)]))
    inning, top, outs = to_int(last.get("InningSeq")), to_int(last.get("VisitingHomeType")) == 1, to_int(last.get("OutCnt"))
    bases = tuple(bool(str(last.get(k) or "").strip()) for k in ("FirstBase", "SecondBase", "ThirdBase"))
    if outs is not None and outs >= 3 and inning:
        # 三出局：攻守交換中，直接顯示下一個半局
        inning, top, outs, bases = (inning if top else inning + 1), not top, 0, (False, False, False)
    g.inning, g.top, g.outs, g.bases = inning, top, outs, bases  # type: ignore[assignment]
    g.extra.update(balls=to_int(last.get("BallCnt")), strikes=to_int(last.get("StrikeCnt")),
                   pitcher=last.get("PitcherName"), batter=last.get("HitterName"))
