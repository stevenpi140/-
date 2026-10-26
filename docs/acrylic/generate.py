"""產生壓克力訂製圖：DXF（給廠商的雷射切割機用）與 PNG（可以直接貼到聊天視窗給廠商看）。

用法：python3 docs/acrylic/generate.py
尺寸要改的話，改下面的常數再重跑一次。
"""

from pathlib import Path

import ezdxf
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent

W, H = 414.0, 222.0  # 外框（mm）
HOLE_D = 3.2  # M3 螺絲穿孔
HOLE_EDGE = 7.5  # 孔中心離邊緣
HOLES = [(x, y) for y in (HOLE_EDGE, H - HOLE_EDGE) for x in (HOLE_EDGE, W / 2, W - HOLE_EDGE)]

NOTES = [
    "材質：LED 屏用茶色（或黑色）透光壓克力，透光率約 30–50%",
    "厚度：3 mm　　數量：1 片",
    f"外形：{W:g} × {H:g} mm，雷射切割，邊緣拋光",
    f"孔：Ø{HOLE_D:g} mm 穿孔 × {len(HOLES)}（M3 螺絲用），孔中心離邊 {HOLE_EDGE:g} mm",
    "公差：±0.5 mm　　雙面保留保護膜",
]


def make_dxf(path: Path):
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    msp = doc.modelspace()
    doc.layers.add("CUT", color=1)
    doc.layers.add("DIM", color=3)
    # DXF 座標原點在左下角；圖面上孔位以左上角量，這裡換算成左下角
    msp.add_lwpolyline([(0, 0), (W, 0), (W, H), (0, H)], close=True, dxfattribs={"layer": "CUT"})
    for x, y in HOLES:
        msp.add_circle((x, H - y), HOLE_D / 2, dxfattribs={"layer": "CUT"})
    dim = {"layer": "DIM"}
    msp.add_linear_dim(base=(0, H + 15), p1=(0, H), p2=(W, H), dimstyle="EZDXF", dxfattribs=dim).render()
    msp.add_linear_dim(base=(-15, 0), p1=(0, 0), p2=(0, H), angle=90, dimstyle="EZDXF", dxfattribs=dim).render()
    # 孔位：從左邊、從上面量（和 PNG 圖面一致）
    for i, x in enumerate((HOLE_EDGE, W / 2, W - HOLE_EDGE)):
        msp.add_linear_dim(base=(0, -10 - 12 * i), p1=(0, H), p2=(x, HOLE_EDGE), dimstyle="EZDXF",
                           dxfattribs=dim).render()
    for i, y in enumerate((HOLE_EDGE, H - HOLE_EDGE)):
        msp.add_linear_dim(base=(W + 12 + 12 * i, 0), p1=(W, H), p2=(W - HOLE_EDGE, H - y), angle=90,
                           dimstyle="EZDXF", dxfattribs=dim).render()
    doc.saveas(path)


def _font(size, bold=False):
    for p in ("/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",):
        try:
            return ImageFont.truetype(p, size, index=0)
        except OSError:
            pass
    return ImageFont.load_default()


def make_png(path: Path):
    s = 3.0  # 每 mm 幾個像素
    ml, mt = 140, 150  # 左、上留白
    img = Image.new("RGB", (int(W * s) + ml + 260, int(H * s) + mt + 380), "white")
    d = ImageDraw.Draw(img)
    f, fs, ft = _font(26), _font(22), _font(34)
    ink, dim, acc = (20, 24, 30), (60, 110, 200), (200, 110, 20)

    def P(x, y):  # mm（左上角為原點）→ 像素
        return ml + x * s, mt + y * s

    d.text((ml, 30), "比分看板 前面板壓克力", font=ft, fill=ink)
    d.text((ml, 76), "單位：mm　孔位都從左上角量", font=fs, fill=(90, 98, 110))

    x0, y0 = P(0, 0)
    x1, y1 = P(W, H)
    d.rectangle([x0, y0, x1, y1], outline=ink, width=3, fill=(250, 236, 214))
    # 顯示區（面板範圍，參考用）
    a0, b0 = P(15, 15)
    a1, b1 = P(W - 15, H - 15)
    d.rectangle([a0, b0, a1, b1], outline=(180, 160, 130), width=1)
    d.text(((a0 + a1) / 2 - 120, (b0 + b1) / 2 - 14), "LED 顯示區 384 × 192（參考）", font=fs, fill=(150, 130, 100))

    for x, y in HOLES:
        cx, cy = P(x, y)
        r = HOLE_D / 2 * s + 2
        d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=acc, width=3)
        d.line([cx - 12, cy, cx + 12, cy], fill=acc, width=1)
        d.line([cx, cy - 12, cx, cy + 12], fill=acc, width=1)

    def hdim(xa, xb, y, label):
        pa, pb = P(xa, 0)[0], P(xb, 0)[0]
        d.line([pa, y, pb, y], fill=dim, width=2)
        for px in (pa, pb):
            d.line([px, y - 10, px, y + 10], fill=dim, width=2)
        tw = d.textlength(label, font=f)
        if pb - pa < tw + 30:  # 太短放不下文字：標在尺寸線右邊
            d.text((pb + 12, y - 15), label, font=f, fill=dim)
            return
        d.rectangle([(pa + pb) / 2 - tw / 2 - 6, y - 16, (pa + pb) / 2 + tw / 2 + 6, y + 16], fill="white")
        d.text(((pa + pb) / 2 - tw / 2, y - 15), label, font=f, fill=dim)

    def vdim(ya, yb, x, label):
        pa, pb = P(0, ya)[1], P(0, yb)[1]
        d.line([x, pa, x, pb], fill=dim, width=2)
        for py in (pa, pb):
            d.line([x - 10, py, x + 10, py], fill=dim, width=2)
        tw = d.textlength(label, font=f)
        d.rectangle([x - tw - 18, (pa + pb) / 2 - 16, x - 8, (pa + pb) / 2 + 16], fill="white")
        d.text((x - tw - 14, (pa + pb) / 2 - 15), label, font=f, fill=dim)

    hdim(0, W, y0 - 30, f"{W:g}")
    vdim(0, H, x0 - 30, f"{H:g}")
    # 孔位（從左邊量）
    yb = y1 + 40
    hdim(0, HOLE_EDGE, yb, f"{HOLE_EDGE:g}")
    hdim(0, W / 2, yb + 50, f"{W / 2:g}")
    hdim(0, W - HOLE_EDGE, yb + 100, f"{W - HOLE_EDGE:g}")
    # 孔位（從上面量）：右側兩條尺寸線
    for i, ya in enumerate((HOLE_EDGE, H - HOLE_EDGE)):
        xr = x1 + 50 + i * 70
        pa, pb = P(0, 0)[1], P(0, ya)[1]
        d.line([xr, pa, xr, pb], fill=dim, width=2)
        for py in (pa, pb):
            d.line([xr - 10, py, xr + 10, py], fill=dim, width=2)
        label = f"{ya:g}"
        ly = pb + 6 if ya < 20 else (pa + pb) / 2 - 15
        d.rectangle([xr - 4, ly - 2, xr + d.textlength(label, font=f) + 8, ly + 30], fill="white")
        d.text((xr + 2, ly), label, font=f, fill=dim)

    ny = yb + 150
    for i, line in enumerate(NOTES):
        d.text((ml, ny + i * 34), "・" + line, font=fs, fill=ink)
    img.save(path)


if __name__ == "__main__":
    make_dxf(OUT / "front-acrylic.dxf")
    make_png(OUT / "front-acrylic.png")
    print("已輸出", OUT / "front-acrylic.dxf", OUT / "front-acrylic.png")
