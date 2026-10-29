"""Panels rendered with Pillow: the Match Recap's souls by source and scoreboard, and the /build buy path."""
import io

from PIL import Image, ImageDraw

from core.graphs import GOLD, S, W, _font, souls_graph

BG, TEXT, MUTED, DIM, LINE = "#16171b", "#dbdee1", "#949ba4", "#6b6f78", "#2a2c33"
WIN, LOSS = "#57f287", "#ed4245"
GAP = 10


def _panel(h):
    """Blank rounded panel, W wide and h tall, at supersampled size."""
    img = Image.new("RGBA", (W * S, h * S), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle((0, 0, W * S - 1, h * S - 1), 12 * S, fill=BG, outline="#000", width=S)
    return img


def _title(d, x, y, text, fill=MUTED):
    small = _font(11)
    for ch in text:  # Pillow has no letter-spacing
        d.text((x, y), ch, font=small, fill=fill)
        x += d.textlength(ch, font=small) + 1.5 * S


def _final(img):
    return img.resize((img.width // S, img.height // S), Image.LANCZOS)


def _png(img):
    buf = io.BytesIO()
    img.save(buf, "PNG")
    buf.seek(0)
    return buf


def sources_panel(sources):
    """Final-size panel of gold bars, one per (label, souls); negative rows show as red text only."""
    row_h, top = 28, 50
    img = _panel(top + row_h * len(sources) + 14)
    d = ImageDraw.Draw(img)
    _title(d, 20 * S, 18 * S, "SOULS BY SOURCE")
    font = _font(15)
    peak = max([v for _, v in sources] + [1])
    bar_x0, bar_x1 = 230 * S, (W - 24) * S
    for i, (label, v) in enumerate(sources):
        y = (top + row_h * i + row_h / 2) * S
        d.text((20 * S, y), label, font=font, fill=TEXT, anchor="lm")
        d.text((212 * S, y), f"{v:,}", font=font, fill=TEXT if v >= 0 else LOSS, anchor="rm")
        if v > 0:
            x = bar_x0 + (bar_x1 - bar_x0) * v / peak
            d.rounded_rectangle((bar_x0, y - 7 * S, max(x, bar_x0 + 6 * S), y + 7 * S), 4 * S, fill=GOLD)
    return _final(img)


def souls_image(timeline, sources) -> io.BytesIO:
    """PNG of the souls-over-time graph with the souls-by-source bars under it."""
    graph, bars = Image.open(souls_graph(timeline)), sources_panel(sources)
    img = Image.new("RGBA", (W, graph.height + GAP + bars.height), (0, 0, 0, 0))
    img.paste(graph, (0, 0))
    img.paste(bars, (0, graph.height + GAP))
    return _png(img)


def _fit(d, text, font, width):
    """text cut with an ellipsis to fit width (Pillow units)."""
    if d.textlength(text, font=font) <= width:
        return text
    while text and d.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def buy_path_image(columns, baseline) -> io.BytesIO:
    """PNG of the /build buy path. columns = [(label, [(name, icon PNG bytes or None, buy share, win share)])]."""
    row_h, top, icon = 58, 48, 40
    col_w = W // len(columns)
    img = _panel(top + row_h * max(len(rows) for _, rows in columns) + 8)
    d = ImageDraw.Draw(img)
    font, small = _font(13), _font(12)
    for c, (label, rows) in enumerate(columns):
        x = (c * col_w + 16) * S
        _title(d, x, 18 * S, label.upper(), GOLD)
        for i, (name, png, buy, win) in enumerate(rows):
            y = (top + row_h * i) * S
            d.rounded_rectangle((x, y, x + icon * S, y + icon * S), 6 * S, fill="#2b2d31")
            if png:
                try:
                    pic = Image.open(io.BytesIO(png)).convert("RGBA").resize((icon * S, icon * S), Image.LANCZOS)
                    img.alpha_composite(pic, (x, y))
                except OSError:  # not an image: keep the blank tile
                    pass
            tx = x + (icon + 8) * S
            d.text((tx, y + 2 * S), _fit(d, name, font, (col_w - icon - 30) * S), font=font, fill=TEXT)
            d.text((tx, y + 22 * S), f"{buy:.0%} buy", font=small, fill=MUTED)
            colour = WIN if win > baseline + 0.01 else LOSS if win < baseline - 0.01 else TEXT
            d.text((tx + 66 * S, y + 22 * S), f"{win:.1%} win", font=small, fill=colour)
    return _png(_final(img))


def scoreboard_image(teams) -> io.BytesIO:
    """PNG of both teams side by side. teams = [(label, won, team souls, [(hero, kda, souls, damage, is_me)])]."""
    row_h, top = 30, 70
    col_w = (W - GAP) // 2
    img = _panel(top + row_h * max(len(t[3]) for t in teams) + 14)
    d = ImageDraw.Draw(img)
    mid = (col_w + GAP // 2) * S
    d.line((mid, 16 * S, mid, img.height - 16 * S), fill=LINE, width=S)
    font, small = _font(15), _font(11)
    for c, (label, won, total, rows) in enumerate(teams):
        x = c * (col_w + GAP) * S
        right = x + (col_w - 16) * S
        _title(d, x + 18 * S, 18 * S, f"{label} · {'WIN' if won else 'LOSS'}", WIN if won else LOSS)
        d.text((right, 18 * S), f"{total:,} souls", font=small, fill=MUTED, anchor="ra")
        cols = [(x + 18 * S, "HERO", "l"), (x + 228 * S, "K/D/A", "r"), (x + 304 * S, "SOULS", "r"), (right, "DMG", "r")]
        for cx, head, align in cols:
            d.text((cx, 44 * S), head, font=small, fill=DIM, anchor=align + "a")
        for i, (hero, kda, souls, dmg, is_me) in enumerate(rows):
            y = (top + row_h * i) * S
            if is_me:
                d.rounded_rectangle((x + 8 * S, y, x + (col_w - 6) * S, y + row_h * S), 6 * S, fill="#2b2619")
            for (cx, _, align), text in zip(cols, (hero, kda, f"{souls:,}", f"{dmg:,}")):
                d.text((cx, y + row_h * S // 2), text, font=font,
                       fill=GOLD if is_me else TEXT, anchor=align + "m")
    return _png(_final(img))
