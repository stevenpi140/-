"""HTTP 伺服器：ESP32 用 GET /frame?page=N 取得一頁 RGB565 畫面。

回應標頭：
  X-Page / X-Pages  這是第幾頁 / 總共幾頁
  X-Hold-Ms         這頁要停留多久（毫秒）
  X-Brightness      建議亮度 0-255
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from io import BytesIO

from fastapi import FastAPI, Query, Response
from fastapi.responses import HTMLResponse, JSONResponse

from . import playlist
from .aggregator import Aggregator, make_client
from .config import Config
from .render import Renderer

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

cfg = Config.load(os.environ.get("SCOREBOARD_CONFIG", "config.yaml"))
agg = Aggregator(cfg)
renderer = Renderer(cfg.display["width"], cfg.display["height"], cfg.display.get("fonts"))


@asynccontextmanager
async def lifespan(_app):
    agg.start()
    yield


app = FastAPI(title="Scoreboard", lifespan=lifespan)


def _pages():
    now = datetime.now(cfg.tz)
    games = agg.games()
    note = ""
    if not games and agg.states and all(s.error and not s.last_ok for s in agg.states):
        note = "資料來源連線失敗"
    return now, games, playlist.build(renderer, cfg, games, now, note)


@app.get("/frame")
def frame(page: int = Query(0, ge=0)):
    now, games, pages = _pages()
    idx = page % len(pages)
    p = pages[idx]
    return Response(
        content=Renderer.rgb565(p.image),
        media_type="application/octet-stream",
        headers={
            "X-Page": str(idx),
            "X-Pages": str(len(pages)),
            "X-Hold-Ms": str(p.hold_ms),
            "X-Brightness": str(playlist.brightness(cfg, now, any(g.state == "live" for g in games))),
            "Cache-Control": "no-store",
        },
    )


@app.get("/preview/{page}.png")
def preview_png(page: int, led: bool = True):
    _, _, pages = _pages()
    img = pages[page % len(pages)].image
    if led:
        img = Renderer.led_preview(img)
    buf = BytesIO()
    img.save(buf, "PNG")
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "no-store"})


@app.get("/", response_class=HTMLResponse)
def index():
    _, _, pages = _pages()
    imgs = "".join(
        f'<figure><img src="/preview/{i}.png?t=0" data-i="{i}"><figcaption>{i}: {p.kind} · {p.hold_ms // 1000}s</figcaption></figure>'
        for i, p in enumerate(pages)
    )
    return f"""<!doctype html><meta charset="utf-8"><title>Scoreboard 預覽</title>
<style>body{{background:#111;color:#ccc;font-family:sans-serif;margin:16px}}
img{{width:min(768px,100%);image-rendering:pixelated;border-radius:8px}}figure{{margin:0 0 16px}}</style>
<h3>點陣看板預覽（每 10 秒更新）</h3>{imgs}
<p><a href="/api/games" style="color:#8cf">/api/games</a> · <a href="/api/status" style="color:#8cf">/api/status</a></p>
<script>setInterval(()=>document.querySelectorAll('img').forEach(i=>i.src=`/preview/${{i.dataset.i}}.png?t=${{Date.now()}}`),10000)</script>"""


@app.get("/api/games")
def api_games():
    return JSONResponse([g.to_dict() for g in agg.games()])


@app.get("/api/status")
def api_status():
    return {"updated_at": agg.updated_at, "leagues": agg.status()}


@app.post("/api/refresh")
async def api_refresh():
    async with make_client() as client:
        await agg.refresh_all(client)
    return api_status()
