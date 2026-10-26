"""指令列工具。

  python -m scoreboard serve            啟動伺服器（給 ESP32 連）
  python -m scoreboard preview --demo   用假資料輸出預覽 PNG（不需網路）
  python -m scoreboard preview          抓今天的真實資料輸出預覽 PNG
  python -m scoreboard probe cpbl       把某聯盟的原始回應存成 JSON，介面改版時用來除錯
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, datetime
from pathlib import Path

from .aggregator import Aggregator, make_client
from .config import Config
from . import playlist
from .render import Renderer


def cmd_serve(a):
    import os

    import uvicorn

    os.environ["SCOREBOARD_CONFIG"] = a.config
    uvicorn.run("scoreboard.server:app", host=a.host, port=a.port)


async def _real_games(cfg: Config, day: date | None):
    agg = Aggregator(cfg)
    async with make_client() as client:
        await agg.refresh_all(client, day)
    for s in agg.states:
        print(f"  {s.league.name:5} {len(s.games)} 場 {('錯誤：' + s.error) if s.error else ''}")
    return agg.games()


def cmd_preview(a):
    cfg = Config.load(a.config)
    if a.demo:
        from .demo import demo_games

        games = demo_games(cfg)
    else:
        games = asyncio.run(_real_games(cfg, date.fromisoformat(a.date) if a.date else None))
    r = Renderer(cfg.display["width"], cfg.display["height"], cfg.display.get("fonts"))
    pages = playlist.build(r, cfg, games, datetime.now(cfg.tz))
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for i, p in enumerate(pages):
        Renderer.led_preview(p.image).save(out / f"page{i}_{p.kind}.png")
        p.image.save(out / f"page{i}_{p.kind}_raw.png")
    print(f"已輸出 {len(pages)} 頁到 {out.resolve()}")


async def _probe(cfg: Config, which: list[str], day: date, out: Path):
    from .leagues import ALL

    out.mkdir(parents=True, exist_ok=True)
    raw_dir = out / "raw"
    raw_dir.mkdir(exist_ok=True)
    counter = {"n": 0}

    async def save_response(r):
        # 把每一個 HTTP 回應原封不動存下來，官網改版時拿來對照欄位
        await r.aread()
        counter["n"] += 1
        name = f"{counter['n']:02d}_{r.request.method}_{r.url.host}{r.url.path}".replace("/", "_")[:120]
        body = f"{r.request.method} {r.url}\nHTTP {r.status_code}\n\n" + r.text
        (raw_dir / f"{name}.txt").write_text(body, encoding="utf-8")

    async with make_client(event_hooks={"response": [save_response]}) as client:
        for cls in ALL:
            if which and cls.key not in which:
                continue
            lg = cls()
            try:
                games = await lg.fetch(client, cfg, day)
                (out / f"{cls.key}_games.json").write_text(
                    json.dumps([g.to_dict() for g in games], ensure_ascii=False, indent=1), encoding="utf-8"
                )
                print(f"{cls.name:5} OK，{len(games)} 場")
                for g in games:
                    print(f"      {g.start:%H:%M} {g.away.name} {g.away.score} - {g.home.score} {g.home.name}"
                          f"  [{g.status_text()}] 原始狀態={g.detail} {g.label}")
            except Exception as e:
                print(f"{cls.name:5} 失敗：{type(e).__name__}: {e}")


# 診斷用：找出中職官網現在的賽程網址，以及野球革命（Rebas）有哪些賽季代碼（季後賽、總冠軍賽）
DIAG_URLS = [
    "https://www.cpbl.com.tw/",
    "https://www.rebas.tw/api/seasons/CPBL-2026-oB/games",
    "https://www.rebas.tw/api/leagues/CPBL/seasons",
    "https://www.rebas.tw/api/seasons?league=CPBL",
    "https://www.rebas.tw/league/CPBL",
]


def _summarize(url: str, r) -> None:
    import re
    from collections import Counter

    if "cpbl.com.tw" in url and r.status_code == 200:
        links = sorted(set(re.findall(r'href="(/[^"#?]*(?:schedule|game|box|standing)[^"]*)"', r.text, re.I)))
        print("    官網連結：", links[:40])
    if "rebas.tw" in url and r.status_code == 200:
        seasons = sorted(set(re.findall(r"CPBL-\d{4}-[A-Za-z0-9]+", r.text)))
        print("    出現的賽季代碼：", seasons[:40])
        try:
            data = r.json()
        except ValueError:
            return
        rows = data.get("data") if isinstance(data, dict) else data
        if isinstance(rows, list) and rows and isinstance(rows[0], dict) and "info" in rows[0]:
            info = [x.get("info", {}) for x in rows]
            print("    比賽數：", len(rows))
            print("    status：", Counter(i.get("status") for i in info))
            print("    finished_status：", Counter(i.get("finished_status") for i in info))
            print("    group：", Counter(x.get("group") for x in rows))
            dates = sorted(str(i.get("scheduled_start_at")) for i in info)
            print("    日期範圍：", dates[0], "~", dates[-1])
            sp = [x["away"].get("scheduled_SP") for x in rows if x.get("away", {}).get("scheduled_SP")]
            print("    scheduled_SP 範例：", sp[:2])
        elif isinstance(rows, (list, dict)):
            print("    內容開頭：", str(rows)[:600])


async def _diagnose(out: Path):
    raw_dir = out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    async with make_client() as client:
        for i, url in enumerate(DIAG_URLS, 1):
            try:
                r = await client.get(url)
                print(f"  {r.status_code}  {url}  ({len(r.content)} bytes)")
                (raw_dir / f"diag{i:02d}.txt").write_text(f"GET {url}\nHTTP {r.status_code}\n\n{r.text}", encoding="utf-8")
                _summarize(url, r)
            except Exception as e:
                print(f"  失敗  {url}  {type(e).__name__}: {e}")


def cmd_probe(a):
    cfg = Config.load(a.config)
    day = date.fromisoformat(a.date) if a.date else datetime.now(cfg.tz).date()
    asyncio.run(_probe(cfg, a.leagues, day, Path(a.out)))
    if a.diagnose:
        print("診斷：")
        asyncio.run(_diagnose(Path(a.out)))


def main():
    ap = argparse.ArgumentParser(prog="scoreboard")
    ap.add_argument("--config", default="config.yaml")
    sub = ap.add_subparsers(required=True)

    s = sub.add_parser("serve")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", type=int, default=8080)
    s.set_defaults(fn=cmd_serve)

    p = sub.add_parser("preview")
    p.add_argument("--demo", action="store_true", help="使用假資料預覽版面")
    p.add_argument("--date", help="YYYY-MM-DD，預設今天")
    p.add_argument("--out", default="preview")
    p.set_defaults(fn=cmd_preview)

    pr = sub.add_parser("probe")
    pr.add_argument("leagues", nargs="*", help="cpbl mlb nba tpbl plg，不填代表全部")
    pr.add_argument("--date", help="YYYY-MM-DD，預設今天")
    pr.add_argument("--out", default="probe")
    pr.add_argument("--diagnose", action="store_true", help="另外測試幾個備用網址")
    pr.set_defaults(fn=cmd_probe)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
