"""The /meta heroes embed: every hero as a numbered icon line, laid out as a grid of inline fields."""
import discord

FIELD_MAX = 1024


def _wr(wins, matches):
    return 100 * wins / matches if matches else 0.0


def heroes_embed(rows, heroes, hero_emojis, sort, rank_name, days):
    """rows: hero-stats rows (hero_id, wins, matches) of known heroes; sort: "win" or "pick"; hero_emojis: {id: str}."""
    total = sum(r["matches"] for r in rows) or 1
    by_win = sort == "win"
    key = (lambda r: _wr(r["wins"], r["matches"])) if by_win else (lambda r: r["matches"])
    rows = sorted(rows, key=lambda r: (-key(r), r["hero_id"]))

    embed = discord.Embed(title=f"Heroes by {'win' if by_win else 'pick'} rate", color=discord.Color.gold())
    embed.set_author(name=f"Hero meta · last {days} days" + (f" · {rank_name}" if rank_name else ""))
    embed.set_footer(text=f"Pick rate = share of all hero picks · last {days} days")
    if not rows:
        embed.description = "No matches in this window."
        return embed

    name = lambda r: heroes[r["hero_id"]]["name"]
    hi, lo = rows[0], rows[-1]
    embed.description = (f"Best **{name(hi)}** {_wr(hi['wins'], hi['matches']):.1f}% · worst **{name(lo)}** {_wr(lo['wins'], lo['matches']):.1f}% win rate."
                         if by_win else
                         f"Most picked **{name(hi)}** {100 * hi['matches'] / total:.1f}% · least **{name(lo)}** {100 * lo['matches'] / total:.1f}%.")

    lines = []
    for i, r in enumerate(rows, 1):
        w = _wr(r["wins"], r["matches"])
        icon = hero_emojis.get(r["hero_id"], "")
        lines.append(f"`{i}.` {icon} **{name(r)}** · {'▲' if w >= 50 else '▼'}{w:.1f}% · {100 * r['matches'] / total:.1f}%".replace("  ", " "))

    cols = 3
    while True:  # more columns (wrapping to extra rows) only if 3 would overflow a field
        size = -(-len(lines) // cols)
        chunks = ["\n".join(lines[i:i + size]) for i in range(0, len(lines), size)]
        if all(len(c) <= FIELD_MAX for c in chunks):
            break
        cols += 1
    for n, c in enumerate(chunks):
        embed.add_field(name="Hero · win · pick" if n == 0 else "\u200b", value=c)
    return embed
