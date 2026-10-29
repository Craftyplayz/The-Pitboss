"""Souls-over-time line graph rendered with Pillow (no matplotlib)."""
import io
from math import ceil
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONT = Path(__file__).resolve().parent.parent / "assets" / "fonts" / "NotoSans.ttf"
W, H, S = 800, 300, 2  # final size, supersample factor
GOLD = (240, 195, 90)
LEFT, RIGHT, TOP, BOTTOM = 52, 28, 64, 34


def _font(px):
    try:
        return ImageFont.truetype(str(FONT), px * S)
    except OSError:  # font file missing: Pillow's built-in scalable default
        return ImageFont.load_default(size=px * S)


def _step(peak):
    for step in (m * 10**e for e in range(0, 9) for m in (1, 2, 5)):
        if ceil(peak / step) <= 4:
            return step


def _label(v):
    return f"{v // 1000}K" if v and v % 1000 == 0 else str(v)


def souls_graph(timeline: list[tuple[int, int]]) -> io.BytesIO:
    """PNG of a Player's souls over one Match. timeline = [(time_stamp_s, net_worth), ...] ascending."""
    img = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W * S - 1, H * S - 1), 12 * S, fill="#16171b", outline="#000", width=S)

    small = _font(11)
    x = 20 * S
    for ch in "SOULS OVER TIME":  # Pillow has no letter-spacing
        d.text((x, 18 * S), ch, font=_font(11), fill="#949ba4")
        x += d.textlength(ch, font=small) + 1.5 * S

    tmax = max(timeline[-1][0] if timeline else 0, 1)
    step = _step(max([v for _, v in timeline] + [1]))
    ymax = ceil(max([v for _, v in timeline] + [1]) / step) * step
    x0, x1 = LEFT * S, (W - RIGHT) * S
    y0, y1 = (H - BOTTOM) * S, TOP * S  # y0 = value 0, y1 = ymax

    def px(t, v):
        return x0 + (x1 - x0) * t / tmax, y0 - (y0 - y1) * v / ymax

    for v in range(step, ymax + 1, step):
        y = px(0, v)[1]
        d.line((x0, y, x1, y), fill="#2a2c33", width=S)
        d.text((x0 - 8 * S, y), _label(v), font=small, fill="#6b6f78", anchor="rm")

    mins = tmax // 60
    ticks = [(m * 60, str(m)) for m in range(0, mins, 10) if mins - m >= 4]
    for t, text in ticks + [(tmax, f"{mins} min")]:
        d.text((px(t, 0)[0], y0 + 10 * S), text, font=small, fill="#6b6f78", anchor="mt")

    pts = [px(t, v) for t, v in [(0, 0)] + list(timeline)]
    if len(pts) > 1:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).polygon(pts + [(pts[-1][0], y0), (pts[0][0], y0)], fill=GOLD + (36,))
        img = Image.alpha_composite(img, layer)
        d = ImageDraw.Draw(img)
        d.line(pts, fill=GOLD, width=3 * S, joint="curve")
        r = 1.5 * S  # round the joins and caps
        for cx, cy in pts:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GOLD)
    r = 5 * S
    cx, cy = pts[-1]
    d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=GOLD)

    buf = io.BytesIO()
    img.resize((W, H), Image.LANCZOS).save(buf, "PNG")
    buf.seek(0)
    return buf
