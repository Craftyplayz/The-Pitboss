import time

import discord
from discord import app_commands
from discord.ext import commands

from cogs._item_emojis import ItemEmojis
from cogs._meta_heroes_embed import heroes_embed
from cogs._meta_items_embed import items_embed
from core.api import APIError
from core.graphs import line_graph

DAYS = 7
CACHE_SECONDS = 600
ITEM_MIN_HERO = 200
ITEM_MIN_ALL = 5000
PAIR_MIN = 100
TREND_DAYS = 14
# Rank tiers from /v1/assets/ranks, static so slash-command choices need no API call at load.
# A tier's badge is tier*10 + subtier, so min_average_badge = tier*10 + 1.
TIERS = ["Initiate", "Seeker", "Acolyte", "Sentinel", "Mystic", "Ritualist", "Emissary", "Oracle", "Phantom", "Ascendant", "Eternus"]

# shortcut: unbounded dict, no eviction; fine for a handful of param combos, upgrade if keys multiply.
_cache = {}


def win_rate(wins, matches):
    return 100 * wins / matches if matches else 0.0


def rank_by_wr(rows, wins_key, matches_key, min_matches):
    """Rows with enough matches, sorted by win rate descending."""
    ok = [r for r in rows if r[matches_key] >= min_matches]
    return sorted(ok, key=lambda r: win_rate(r[wins_key], r[matches_key]), reverse=True)


def place(rows, key, hero):
    """1-based position of hero among rows by key, highest first, and the row count."""
    order = sorted(rows, key=key, reverse=True)
    return next((i for i, r in enumerate(order, 1) if r["hero_id"] == hero), len(order)), len(order)


def trend_points(daily, now):
    """[(day start, win %)] from bucket=start_time_day rows, oldest first, leaving out today's partial day."""
    today = now - now % 86400
    days = sorted((r for r in daily if r["bucket"] < today and r["matches"]), key=lambda r: r["bucket"])
    return [(r["bucket"], win_rate(r["wins"], r["matches"])) for r in days]


def week_change(points):
    """Win rate change in points: last 7 days vs the 7 before, or None without both weeks."""
    if len(points) < 14:
        return None
    avg = lambda ps: sum(v for _, v in ps) / len(ps)
    return avg(points[-7:]) - avg(points[-14:-7])


def hero_embed(hero, row, stats, items, item_assets, item_emojis, counters, synergy, hero_assets, hero_emojis, change):
    """The /meta hero embed. item_emojis / hero_emojis: {id: "<:x:1>"}; a missing id shows no icon."""
    ui = (hero.get("colors") or {}).get("ui")
    embed = discord.Embed(title=hero["name"], color=discord.Color.from_rgb(*ui) if ui else discord.Color.blurple())
    embed.set_author(name=f"Hero meta · last {DAYS} days · all players")
    if icon := (hero.get("images") or {}).get("icon_image_small"):
        embed.set_thumbnail(url=icon)
    embed.set_footer(text=f"Last {DAYS} days · graph: last {TREND_DAYS} days")
    if not row:
        embed.description = "No matches in this window."
        return embed

    m = row["matches"]
    wr = win_rate(row["wins"], m)
    total = sum(r["matches"] for r in stats) or 1
    wr_place, n = place(stats, lambda r: win_rate(r["wins"], r["matches"]), hero["id"])
    pick_place, _ = place(stats, lambda r: r["matches"], hero["id"])
    lines = [f"**{wr:.1f}%** win rate, #{wr_place} of {n} heroes."]
    if change is not None and abs(change) >= 0.5:
        lines.append(f"{'Up' if change > 0 else 'Down'} {abs(change):.1f} points on the week before.")
    embed.description = "\n".join(lines)

    add = embed.add_field
    add(name="Win rate", value=f"{wr:.1f}% · #{wr_place}")
    add(name="Pick rate", value=f"{100 * m / total:.1f}% · #{pick_place}")
    add(name="Matches", value=f"{m:,}")
    if "total_kills" in row:
        shots = row["total_shots_hit"] + row["total_shots_missed"]
        add(name="Avg K / D / A", value=f"{row['total_kills'] / m:.1f} / {row['total_deaths'] / m:.1f} / {row['total_assists'] / m:.1f}")
        add(name="Avg souls", value=f"{row['total_net_worth'] / m:,.0f}")
        add(name="Accuracy", value=f"{row['total_shots_hit'] / shots:.1%}" if shots else "-")

    def item_line(r):
        icon = item_emojis.get(r["item_id"], "")
        return f"{icon} **{item_assets[r['item_id']]['name']}** · {win_rate(r['wins'], r['matches']):.1f}% · {r['matches']:,}".strip()

    def hero_line(hid, wins, matches):
        return f"{hero_emojis.get(hid, '')} **{hero_assets[hid]['name']}** · {win_rate(wins, matches):.1f}%".strip()

    if items:
        add(name="Top items · win rate · matches", value="\n".join(map(item_line, items)), inline=False)
    if counters:
        add(name="Best matchups", value="\n".join(hero_line(r["enemy_hero_id"], r["wins"], r["matches_played"]) for r in counters[:3]))
        add(name="Worst matchups", value="\n".join(hero_line(r["enemy_hero_id"], r["wins"], r["matches_played"]) for r in counters[::-1][:3]))
    if synergy:
        add(name="Best teammates", value="\n".join(hero_line(r["hero_id"], r["wins"], r["matches_played"]) for r in synergy[:3]))
    return embed


def trend_graph(points):
    """PNG of the daily win rate, y axis in 5-point steps and always showing 50%."""
    lo, hi = min(v for _, v in points), max(v for _, v in points)
    y_range = (int(min(lo, 50) // 5 * 5), int(-(-max(hi, 50) // 5) * 5))
    day = lambda ts: time.strftime("%b %d", time.gmtime(ts)).replace(" 0", " ")
    return line_graph([(i, v) for i, (_, v) in enumerate(points)], f"Win rate · last {TREND_DAYS} days",
                      x_ticks=[(0, day(points[0][0])), (len(points) - 1, day(points[-1][0]))],
                      y_label=lambda v: f"{v}%", y_range=y_range, midline=50)


class Meta(commands.Cog):
    group = app_commands.Group(name="meta", description="Game-wide hero and item stats (last 7 days)")

    def __init__(self, bot):
        self.bot = bot
        self.emojis = ItemEmojis(bot)

    async def fetch(self, path, days=DAYS, **params):
        key = (path, days, tuple(sorted(params.items())))
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        data = await self.bot.api.get(path, min_unix_timestamp=int(time.time()) - days * 86400, **params) or []
        _cache[key] = (time.time(), data)
        return data

    async def hero_autocomplete(self, interaction, current):
        heroes = await self.bot.api.heroes()
        found = sorted((h for h in heroes.values() if current.lower() in h["name"].lower()), key=lambda h: h["name"])
        return [app_commands.Choice(name=h["name"], value=h["id"]) for h in found[:25]]

    async def run(self, interaction, build):
        await interaction.response.defer()
        try:
            embed = await build()
        except APIError as e:
            return await interaction.followup.send(str(e), ephemeral=True)
        # a build may return (embed, file) to attach an image
        embed, file = embed if isinstance(embed, tuple) else (embed, None)
        await interaction.followup.send(embed=embed, **({"file": file} if file else {}))

    @group.command(name="heroes", description="Win rate and pick rate of every hero, last 7 days")
    @app_commands.describe(sort="What to sort by", rank="Only matches at or above this rank")
    @app_commands.choices(
        sort=[app_commands.Choice(name="Win rate", value="win"), app_commands.Choice(name="Pick rate", value="pick")],
        rank=[app_commands.Choice(name="All", value=0)] + [app_commands.Choice(name=f"{t}+", value=i + 1) for i, t in enumerate(TIERS)],
    )
    async def heroes(self, interaction: discord.Interaction, sort: app_commands.Choice[str], rank: app_commands.Choice[int] = None):
        tier = rank.value if rank else 0

        async def build():
            rows = await self.fetch("/v1/analytics/hero-stats", min_average_badge=tier * 10 + 1 if tier else None)
            heroes = await self.bot.api.heroes()
            rows = [r for r in rows if r["hero_id"] in heroes]
            hero_emojis = {r["hero_id"]: await self.emojis.hero(heroes[r["hero_id"]]) for r in rows}
            return heroes_embed(rows, heroes, hero_emojis, sort.value, rank.name if tier else None, DAYS)

        await self.run(interaction, build)

    @group.command(name="hero", description="Items, matchups and teammates for one hero, last 7 days")
    @app_commands.autocomplete(hero=hero_autocomplete)
    async def hero(self, interaction: discord.Interaction, hero: int):
        async def build():
            heroes = await self.bot.api.heroes()
            if hero not in heroes:
                return discord.Embed(description="Unknown hero. Pick one from the list.", color=discord.Color.red())
            stats = [r for r in await self.fetch("/v1/analytics/hero-stats") if r["hero_id"] in heroes]
            row = next((r for r in stats if r["hero_id"] == hero), None)

            item_assets = {i: a for i, a in (await self.bot.api.items()).items() if a.get("type") == "upgrade"}
            items = await self.fetch("/v1/analytics/item-stats", hero_id=hero, min_matches=ITEM_MIN_HERO)
            items = [r for r in rank_by_wr(items, "wins", "matches", ITEM_MIN_HERO) if r["item_id"] in item_assets][:5]

            counters = [r for r in await self.fetch("/v1/analytics/hero-counter-stats", min_matches=PAIR_MIN)
                        if r["hero_id"] == hero and r["enemy_hero_id"] in heroes]
            counters = rank_by_wr(counters, "wins", "matches_played", PAIR_MIN)

            # synergy rows are one per unordered pair, so the hero can be either side
            syn = []
            for r in await self.fetch("/v1/analytics/hero-synergy-stats", min_matches=PAIR_MIN):
                if hero in (r["hero_id1"], r["hero_id2"]):
                    other = r["hero_id2"] if r["hero_id1"] == hero else r["hero_id1"]
                    if other in heroes:
                        syn.append({"hero_id": other, "wins": r["wins"], "matches_played": r["matches_played"]})
            syn = rank_by_wr(syn, "wins", "matches_played", PAIR_MIN)

            daily = [r for r in await self.fetch("/v1/analytics/hero-stats", days=TREND_DAYS + 1, bucket="start_time_day")
                     if r["hero_id"] == hero]
            # the window starts mid-day, so the oldest bucket is partial: keep the last TREND_DAYS full days
            points = trend_points(daily, int(time.time()))[-TREND_DAYS:]

            item_emojis = {r["item_id"]: await self.emojis.get(item_assets[r["item_id"]]) for r in items}
            shown = {r["enemy_hero_id"] for r in counters[:3] + counters[::-1][:3]} | {r["hero_id"] for r in syn[:3]}
            hero_emojis = {h: await self.emojis.hero(heroes[h]) for h in shown}

            embed = hero_embed(heroes[hero], row, stats, items, item_assets, item_emojis, counters, syn,
                               heroes, hero_emojis, week_change(points))
            if len(points) < 2:
                return embed
            embed.set_image(url="attachment://trend.png")
            return embed, discord.File(trend_graph(points), "trend.png")

        await self.run(interaction, build)

    @group.command(name="items", description="Best items by win rate, last 7 days")
    @app_commands.autocomplete(hero=hero_autocomplete)
    @app_commands.describe(hero="Only this hero's games")
    async def items(self, interaction: discord.Interaction, hero: int = None):
        async def build():
            heroes = await self.bot.api.heroes()
            if hero is not None and hero not in heroes:
                return discord.Embed(description="Unknown hero. Pick one from the list.", color=discord.Color.red())
            minimum = ITEM_MIN_HERO if hero else ITEM_MIN_ALL
            item_assets = {i: a for i, a in (await self.bot.api.items()).items() if a.get("type") == "upgrade"}
            rows = await self.fetch("/v1/analytics/item-stats", hero_id=hero, min_matches=minimum)
            rows = [r for r in rank_by_wr(rows, "wins", "matches", minimum) if r["item_id"] in item_assets][:20]
            item_emojis = {r["item_id"]: await self.emojis.get(item_assets[r["item_id"]]) for r in rows}
            return items_embed(rows, item_assets, item_emojis, heroes[hero] if hero else None, DAYS, minimum)

        await self.run(interaction, build)


async def setup(bot):
    await bot.add_cog(Meta(bot))
