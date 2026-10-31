"""Embeds admins design in the control panel: stored as a small config, filled with placeholders when the bot posts.
Used by welcome messages; role menus will reuse it."""
import re

# Discord's limits for each text part
LIMITS = {"content": 2000, "author": 256, "title": 256, "description": 4096, "footer": 2048}
COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
GOLD = "#F0C35A"


def fill(text, values):
    # replace, not str.format: a stray { in an admin's text would crash format()
    for key, value in values.items():
        text = text.replace("{" + key + "}", str(value))
    return text


def clean(form, prefix="embed_"):
    """An embed config from the panel's form fields, trimmed to Discord's limits. Bad colours and image links are dropped."""
    get = lambda k: (form.get(prefix + k) or "").strip()  # noqa: E731
    cfg = {k: get(k)[:n] for k, n in LIMITS.items()}
    cfg["color"] = get("color") if COLOR_RE.match(get("color")) else GOLD
    cfg["image"] = get("image") if get("image").startswith("https://") else ""
    for flag in ("show_author", "thumbnail", "timestamp"):
        cfg[flag] = bool(form.get(prefix + flag))
    return cfg


def render(cfg, values, avatar=None, now=None):
    """(message text, embed dict for Discord's API) with placeholders filled in.
    avatar is the member's picture URL; now an ISO timestamp for the footer."""
    embed = {"color": int(cfg.get("color", GOLD)[1:], 16)}
    for key in ("title", "description"):
        if cfg.get(key):
            embed[key] = fill(cfg[key], values)[:LIMITS[key]]
    if cfg.get("show_author"):
        embed["author"] = {"name": fill(cfg.get("author") or "{name}", values)[:LIMITS["author"]], **({"icon_url": avatar} if avatar else {})}
    if cfg.get("thumbnail") and avatar:
        embed["thumbnail"] = {"url": avatar}
    if cfg.get("image"):
        embed["image"] = {"url": cfg["image"]}
    if cfg.get("footer"):
        embed["footer"] = {"text": fill(cfg["footer"], values)[:LIMITS["footer"]]}
    if cfg.get("timestamp") and now:
        embed["timestamp"] = now
    if len(embed) == 1:
        embed["description"] = "​"  # Discord rejects an embed with nothing in it
    return fill(cfg.get("content", ""), values)[:LIMITS["content"]], embed
