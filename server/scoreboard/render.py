"""把比賽資料畫成點陣圖（預設 128x64），輸出 RGB565 給 ESP32，或放大成 LED 預覽 PNG。

為什麼在伺服器畫而不是在 ESP32 畫？繁體中文字型很大，ESP32 放不下完整字集；
在伺服器用 Pillow 畫好整張圖再傳過去（128x64x2 = 16KB），韌體就能非常單純。
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .models import LEAGUE_COLORS, Game

WHITE = (255, 255, 255)
DIM = (110, 110, 110)
DARK = (50, 50, 50)
YELLOW = (255, 210, 60)
RED = (255, 50, 50)
GREEN = (60, 230, 90)
WEEKDAYS = "一二三四五六日"
OVERVIEW_TOP = 12  # 總覽頁標題列高度
OVERVIEW_ROW_H = 12  # 12px 字型剛好一列

HERE = Path(__file__).resolve().parent.parent / "fonts"

# 依序尋找可用的點陣中文字型。(路徑 glob, 大小, ttc index)
SMALL_CANDIDATES = [
    (str(HERE / "*fusion-pixel-12px*zh_hant*.otf"), 12, 0),
    (str(HERE / "*fusion-pixel-12px*zh_hant*.ttf"), 12, 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 12, 1),  # 文泉驛點陣正黑（內嵌 12px 點陣）
    ("/usr/share/fonts/opentype/unifont/unifont.otf", 16, 0),
]
LARGE_CANDIDATES = [
    ("/usr/share/fonts/opentype/unifont/unifont.otf", 16, 0),  # GNU Unifont 16px
    (str(HERE / "unifont*.otf"), 16, 0),
    ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", 16, 1),
]

# 5x7 點陣數字（比分、時鐘用），每列 5 bit
DIGITS = {
    "0": ["01110", "10001", "10011", "10101", "11001", "10001", "01110"],
    "1": ["00100", "01100", "00100", "00100", "00100", "00100", "01110"],
    "2": ["01110", "10001", "00001", "00010", "00100", "01000", "11111"],
    "3": ["11111", "00010", "00100", "00010", "00001", "10001", "01110"],
    "4": ["00010", "00110", "01010", "10010", "11111", "00010", "00010"],
    "5": ["11111", "10000", "11110", "00001", "00001", "10001", "01110"],
    "6": ["00110", "01000", "10000", "11110", "10001", "10001", "01110"],
    "7": ["11111", "00001", "00010", "00100", "01000", "01000", "01000"],
    "8": ["01110", "10001", "10001", "01110", "10001", "10001", "01110"],
    "9": ["01110", "10001", "10001", "01111", "00001", "00010", "01100"],
    ":": ["00000", "01100", "01100", "00000", "01100", "01100", "00000"],
    "-": ["00000", "00000", "00000", "11111", "00000", "00000", "00000"],
    " ": ["00000"] * 7,
}


def _load(candidates, override: str | None, size: int | None):
    if override:
        return ImageFont.truetype(override, size or 12)
    for pattern, sz, idx in candidates:
        for path in sorted(glob.glob(pattern)):
            if os.path.exists(path):
                return ImageFont.truetype(path, size or sz, index=idx)
    return ImageFont.load_default()


@dataclass
class Page:
    kind: str  # overview / game / idle
    hold_ms: int
    image: Image.Image
    live: bool = False  # 這頁有進行中的比賽：看板停留期間會定期重抓，比分才會即時更新


class Renderer:
    def __init__(self, width: int = 128, height: int = 64, fonts: dict | None = None):
        fonts = fonts or {}
        self.w, self.h = width, height
        self.small = _load(SMALL_CANDIDATES, fonts.get("small"), fonts.get("small_size"))
        self.large = _load(LARGE_CANDIDATES, fonts.get("large"), fonts.get("large_size"))

    # ---------- 基本繪圖 ----------
    def _canvas(self):
        img = Image.new("RGB", (self.w, self.h), (0, 0, 0))
        d = ImageDraw.Draw(img)
        d.fontmode = "1"  # 不要反鋸齒，LED 上才會銳利
        return img, d

    def tw(self, text: str, font) -> int:
        return int(font.getlength(text))

    def text(self, d, xy, text, font, fill, max_w: int | None = None, anchor_right=False):
        if max_w is not None:
            while text and self.tw(text, font) > max_w:
                text = text[:-1]
        x, y = xy
        if anchor_right:
            x -= self.tw(text, font)
        d.text((x, y), text, font=font, fill=fill)
        return self.tw(text, font)

    def digits(self, d, x, y, s: str, scale: int, fill, right=False) -> int:
        cw = 5 * scale + scale  # 字寬 + 間距
        width = len(s) * cw - scale
        if right:
            x -= width
        for i, ch in enumerate(s):
            rows = DIGITS.get(ch, DIGITS[" "])
            for ry, row in enumerate(rows):
                for rx, bit in enumerate(row):
                    if bit == "1":
                        px, py = x + i * cw + rx * scale, y + ry * scale
                        d.rectangle([px, py, px + scale - 1, py + scale - 1], fill=fill)
        return width

    # ---------- 頁面 ----------
    def overview(self, games: list[Game], now: datetime, page: int = 1, pages: int = 1) -> Image.Image:
        img, d = self._canvas()
        title = f"今日 {now.month}/{now.day}({WEEKDAYS[now.weekday()]})"
        self.text(d, (1, 0), title, self.small, YELLOW)
        if pages > 1:
            self.text(d, (self.w - 1, 0), f"{page}/{pages}", self.small, DIM, anchor_right=True)
        for i, g in enumerate(games[: self.overview_rows]):
            y = OVERVIEW_TOP + i * OVERVIEW_ROW_H
            d.rectangle([0, y + 2, 1, y + 11], fill=LEAGUE_COLORS.get(g.league, WHITE))
            live = g.state == "live"
            win_a, win_h = _winner(g)
            if g.state == "pre":
                mid, mid_color = g.start.strftime("%H:%M"), DIM
            elif g.state == "postponed":
                mid, mid_color = "延賽", DIM
            else:
                mid, mid_color = f"{g.away.score or 0}-{g.home.score or 0}", WHITE if live else DIM
            away, home = _tiny(g.away.name), _tiny(g.home.name)
            aw, hw, mw = self.tw(away, self.small), self.tw(home, self.small), self.tw(mid, self.small)
            st = g.short_status()
            sw = self.tw(st, self.small) + 3 if st else 0
            if 4 + aw + mw + hw + sw + 4 > self.w and g.state == "final":
                st, sw = "", 0  # 放不下時，終場的「終」可以省略（比分已變暗）
            home_x = self.w - sw - hw
            self.text(d, (4, y), away, self.small, DIM if win_h else g.away.color)
            self.text(d, (home_x, y), home, self.small, DIM if win_a else g.home.color)
            self.text(d, ((4 + aw + home_x - mw) // 2, y), mid, self.small, mid_color)
            if st:
                self.text(d, (self.w, y), st, self.small, GREEN if live else DIM, anchor_right=True)
        return img

    @property
    def overview_rows(self) -> int:
        return (self.h - OVERVIEW_TOP) // OVERVIEW_ROW_H

    def game(self, g: Game, now: datetime) -> Image.Image:
        img, d = self._canvas()
        lc = LEAGUE_COLORS.get(g.league, WHITE)
        # 第一列：聯盟、賽事標籤、場地
        x = 1 + self.text(d, (1, 0), g.league, self.small, lc)
        if g.label:
            x += 4 + self.text(d, (x + 4, 0), g.label, self.small, YELLOW)
        if g.venue and x + 8 < self.w:
            self.text(d, (self.w - 1, 0), _short_venue(g.venue, self.w - x - 8, self), self.small, DIM, anchor_right=True)

        win_a, win_h = _winner(g)
        for row, (t, win, lose, batting) in enumerate(
            [
                (g.away, win_a, win_h, g.state == "live" and g.is_baseball and g.top is True),
                (g.home, win_h, win_a, g.state == "live" and g.is_baseball and g.top is False),
            ]
        ):
            y = 14 + row * 17
            name_color = DIM if lose else t.color
            d.rectangle([0, y, 1, y + 14], fill=t.color)
            self.text(d, (4, y - 1), t.name, self.large, name_color, max_w=66)
            if g.state == "pre":
                if t.pitcher:
                    self.text(d, (self.w - 1, y + 2), t.pitcher, self.small, YELLOW, max_w=56, anchor_right=True)
            elif t.score is not None:
                score_color = DIM if lose else WHITE
                w = self.digits(d, self.w - 2, y + 1, str(t.score), 2, score_color, right=True)
                if batting:  # 進攻方：比分左邊一個小三角形
                    bx = self.w - 2 - w - 6
                    d.polygon([(bx, y + 4), (bx, y + 10), (bx + 3, y + 7)], fill=YELLOW)

        # 底列：狀態
        y = 51
        status = g.status_text()
        color = GREEN if g.state == "live" else (YELLOW if g.state == "pre" else DIM)
        sw = self.text(d, (1, y), status, self.small, color)
        if g.state == "pre":
            mins = int((g.start - now).total_seconds() // 60)
            if 0 < mins < 180:
                hint = f"{mins}分後" if mins < 60 else f"{mins // 60}時{mins % 60:02d}分後"
                self.text(d, (self.w - 1, y), hint, self.small, DIM, anchor_right=True)
            elif g.away.pitcher or g.home.pitcher:
                self.text(d, (self.w - 1, y), "先發", self.small, DIM, anchor_right=True)
        if g.state == "live" and g.is_baseball:
            self._outs(d, sw + 6, y + 6, g.outs)
            self._bases(d, self.w - 12, y + 1, g.bases)
        return img

    def _outs(self, d, x, cy, outs):
        if outs is None:
            return
        for i in range(3):
            fill = RED if i < outs else None
            d.ellipse([x + i * 7, cy - 2, x + i * 7 + 4, cy + 2], fill=fill, outline=RED if i < outs else DARK)

    def _bases(self, d, cx, y, bases):
        if bases is None:
            return
        r = 3
        pos = [(cx + 6, y + 7), (cx, y + 2), (cx - 6, y + 7)]  # 一、二、三壘
        for on, (bx, by) in zip(bases, pos):
            poly = [(bx, by - r), (bx + r, by), (bx, by + r), (bx - r, by)]
            if on:
                d.polygon(poly, fill=YELLOW)
            else:
                d.polygon(poly, outline=DIM)

    def idle(self, now: datetime, note: str = "") -> Image.Image:
        img, d = self._canvas()
        hhmm = now.strftime("%H:%M")
        scale = 3 if self.w >= 96 else 2
        cw = len(hhmm) * 6 * scale - scale
        self.digits(d, (self.w - cw) // 2, 4, hhmm, scale, WHITE)
        date_s = f"{now.month}/{now.day}（{WEEKDAYS[now.weekday()]}）"
        self.text(d, ((self.w - self.tw(date_s, self.small)) // 2, 7 * scale + 9), date_s, self.small, YELLOW)
        msg = note or "今日沒有追蹤的比賽"
        self.text(d, ((self.w - min(self.tw(msg, self.small), self.w)) // 2, self.h - 13), msg, self.small, DIM, max_w=self.w)
        return img

    # ---------- 輸出 ----------
    @staticmethod
    def rgb565(img: Image.Image) -> bytes:
        """RGB565 little-endian，ESP32 直接 memcpy 就能用。"""
        rgb = img.convert("RGB").tobytes()
        out = bytearray(len(rgb) // 3 * 2)
        for i in range(0, len(rgb) // 3):
            r, g, b = rgb[i * 3], rgb[i * 3 + 1], rgb[i * 3 + 2]
            v = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
            out[i * 2] = v & 0xFF
            out[i * 2 + 1] = v >> 8
        return bytes(out)

    @staticmethod
    def led_preview(img: Image.Image, pitch: int = 6) -> Image.Image:
        """模擬 LED 點陣的放大圖，方便沒有硬體時先看效果。"""
        w, h = img.size
        out = Image.new("RGB", (w * pitch, h * pitch), (12, 12, 12))
        d = ImageDraw.Draw(out)
        px = img.load()
        for y in range(h):
            for x in range(w):
                c = px[x, y]
                if c == (0, 0, 0):
                    c = (28, 28, 28)
                d.ellipse([x * pitch + 1, y * pitch + 1, x * pitch + pitch - 2, y * pitch + pitch - 2], fill=c)
        return out


def _winner(g: Game) -> tuple[bool, bool]:
    if g.state != "final" or g.away.score is None or g.home.score is None:
        return False, False
    return g.away.score > g.home.score, g.home.score > g.away.score


def _tiny(name: str) -> str:
    return name[:2] if len(name) > 3 else name


VENUE_SUFFIXES = ("棒球場", "體育館", "球場", " Stadium", " Field", " Park", " Arena", " Center")


def _short_venue(v: str, max_w: int, r: Renderer) -> str:
    """場地名稱放得下就顯示，太長先去掉「棒球場」之類的字尾，還是太長就不顯示。"""
    if r.tw(v, r.small) <= max_w:
        return v
    for suffix in VENUE_SUFFIXES:
        if v.endswith(suffix):
            v = v[: -len(suffix)]
            break
    return v if r.tw(v, r.small) <= max_w else ""
