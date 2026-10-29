"""Line graphs rendered with Pillow (no matplotlib): souls over a Match, and Profile trends."""
import io
from math import ceil, floor
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


def _step(span):
    for step in (m * 10**e for e in range(0, 9) for m in (1, 2, 5)):
        if ceil(span / step) <= 4:
            return step


def _label(v):
    return f"{v // 1000}K" if v and v % 1000 == 0 else str(v)


def line_graph(points, title, x_ticks=(), y_label=_label, y_range=None, origin=None, midline=None):
    """PNG of a gold line graph.

    points: [(x, y), ...] ascending x. x_ticks: [(x, text), ...] labels under the axis.
    y_range: fixed (low, high), else rounded from the data (always including 0).
    origin: a point drawn before the first one, e.g. (0, 0). midline: y value drawn as a dashed reference line.
    """
    img = Image.new("RGBA", (W * S, H * S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, W * S - 1, H * S - 1), 12 * S, fill="#16171b", outline="#000", width=S)

    small = _font(11)
    x = 20 * S
    for ch in title.upper():  # Pillow has no letter-spacing
        d.text((x, 18 * S), ch, font=small, fill="#949ba4")
        x += d.textlength(ch, font=small) + 1.5 * S

    pts_in = ([origin] if origin else []) + list(points)
    ys = [y for _, y in pts_in] + [0]
    if y_range:
        ylo, yhi = y_range
        step = _step(yhi - ylo)
    else:
        step = _step(max(max(ys) - min(ys), 1))
        ylo, yhi = floor(min(ys) / step) * step, ceil(max(max(ys), 1) / step) * step
    xs = [x for x, _ in pts_in] or [0]
    xlo, xhi = min(xs), max(max(xs), min(xs) + 1)
    x0, x1 = LEFT * S, (W - RIGHT) * S
    yb, yt = (H - BOTTOM) * S, TOP * S

    def px(xv, yv):
        return x0 + (x1 - x0) * (xv - xlo) / (xhi - xlo), yb - (yb - yt) * (yv - ylo) / (yhi - ylo)

    for v in range(ylo + step, yhi + 1, step):
        y = px(xlo, v)[1]
        d.line((x0, y, x1, y), fill="#2a2c33", width=S)
        d.text((x0 - 8 * S, y), y_label(v), font=small, fill="#6b6f78", anchor="rm")
    if midline is not None:
        y = px(xlo, midline)[1]
        for sx in range(x0, x1, 12 * S):
            d.line((sx, y, min(sx + 6 * S, x1), y), fill="#4a4d57", width=S)

    for xv, text in x_ticks:
        d.text((px(xv, ylo)[0], yb + 10 * S), text, font=small, fill="#6b6f78", anchor="mt")

    pts = [px(xv, yv) for xv, yv in pts_in]
    if not pts:
        pts = [px(xlo, ylo)]
    base = px(xlo, max(ylo, min(0, yhi)))[1]  # fill down to zero, or the bottom edge
    if len(pts) > 1:
        layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(layer).polygon(pts + [(pts[-1][0], base), (pts[0][0], base)], fill=GOLD + (36,))
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


def souls_graph(timeline: list[tuple[int, int]]) -> io.BytesIO:
    """PNG of a Player's souls over one Match. timeline = [(time_stamp_s, net_worth), ...] ascending."""
    tmax = max(timeline[-1][0] if timeline else 0, 1)
    mins = tmax // 60
    ticks = [(m * 60, str(m)) for m in range(0, mins, 10) if mins - m >= 4] + [(tmax, f"{mins} min")]
    return line_graph(timeline, "Souls over time", x_ticks=ticks, origin=(0, 0))
