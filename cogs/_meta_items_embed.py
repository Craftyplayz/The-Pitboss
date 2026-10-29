"""The /meta items embed. Pure: no network calls here."""
import discord

SLOTS = [("weapon", "Weapon"), ("vitality", "Vitality"), ("spirit", "Spirit")]
FIELD_MAX = 1024


def _wr(r):
    return 100 * r["wins"] / r["matches"] if r["matches"] else 0.0


def items_embed(rows, item_assets, item_emojis, hero, days, minimum):
    """rows: ranked item-stats rows (best first, up to 20); hero: hero asset dict or None; item_emojis: {item_id: emoji}."""
    ui = ((hero or {}).get("colors") or {}).get("ui")
    color = discord.Color.from_rgb(*ui) if ui else discord.Color.gold()
    embed = discord.Embed(title="Best items" + (f" for {hero['name']}" if hero else ""), color=color)
    embed.set_author(name=f"Item meta · last {days} days")
    embed.set_footer(text=f"Last {days} days · at least {minimum:,} matches per item")
    if hero and (icon := (hero.get("images") or {}).get("icon_image_small")):
        embed.set_thumbnail(url=icon)
    rows = rows[:20]
    if not rows:
        embed.description = "No items with enough matches."
        return embed

    top = rows[0]
    embed.description = f"**{item_assets[top['item_id']]['name']}** leads at **{_wr(top):.1f}%** win rate."
    for slot, label in SLOTS:
        lines = [f"`{n}.` {item_emojis.get(r['item_id'], '')} **{item_assets[r['item_id']]['name']}** · {_wr(r):.1f}% · {r['matches']:,} matches".replace("`  ", "` ")
                 for n, r in enumerate(rows, 1) if item_assets[r["item_id"]].get("item_slot_type") == slot]
        chunk, size, part = [], 0, 0
        for line in lines + [None]:
            if line is None or size + len(line) + 1 > FIELD_MAX:
                if chunk:
                    embed.add_field(name=label if not part else f"{label} (cont.)", value="\n".join(chunk), inline=False)
                    part += 1
                chunk, size = [], 0
            if line is not None:
                chunk.append(line)
                size += len(line) + 1
    return embed
