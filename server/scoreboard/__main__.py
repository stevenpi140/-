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
    day = day or agg.today()
    sports = "、".join({"baseball": "棒球", "basketball": "籃球"}[x] for x in cfg.active_sports(day))
    print(f"  {day} 季節：{sports}")
    for s in agg.active_states(day):
        print(f"  {s.league.name:5} {len(s.games)} 場 {('錯誤：' + s.error) if s.error else ''}")
    return agg.games(day)


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
    async with make_client() as client:
        for cls in ALL:
            if which and cls.key not in which:
                continue
            lg = cls()
            try:
                if cls.key == "cpbl":
                    raw = await lg.fetch_raw(client, day)
                    (out / "cpbl_raw.json").write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
                games = await lg.fetch(client, cfg, day)
                (out / f"{cls.key}_games.json").write_text(
                    json.dumps([g.to_dict() for g in games], ensure_ascii=False, indent=1), encoding="utf-8"
                )
                print(f"{cls.name:5} OK，{len(games)} 場")
                for g in games:
                    print(f"      {g.start:%H:%M} {g.away.name} {g.away.score} - {g.home.score} {g.home.name}  [{g.status_text()}]")
            except Exception as e:
                print(f"{cls.name:5} 失敗：{type(e).__name__}: {e}")


def cmd_probe(a):
    cfg = Config.load(a.config)
    day = date.fromisoformat(a.date) if a.date else datetime.now(cfg.tz).date()
    asyncio.run(_probe(cfg, a.leagues, day, Path(a.out)))


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
    pr.set_defaults(fn=cmd_probe)

    a = ap.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
