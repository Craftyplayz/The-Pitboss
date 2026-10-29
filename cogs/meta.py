import time

import discord
from discord import app_commands
from discord.ext import commands

from api import APIError

DAYS = 7
CACHE_SECONDS = 600
ITEM_MIN_HERO = 200
ITEM_MIN_ALL = 5000
PAIR_MIN = 100
# Rank tiers from /v1/assets/ranks, static so slash-command choices need no API call at load.
# A tier's badge is tier*10 + subtier, so min_average_badge = tier*10 + 1.
TIERS = ["Initiate", "Seeker", "Acolyte", "Sentinel", "Mystic", "Ritualist", "Emissary", "Oracle", "Phantom", "Ascendant", "Eternus"]

# shortcut: unbounded dict, no eviction; fine for a handful of param combos, upgrade if keys multiply.
_cache = {}


def win_rate(wins, matches):
    return 100 * wins / matches if matches else 0.0


def fmt_table(header, rows):
    """Monospace table in a code block; first column left-aligned, the rest right-aligned."""
    all_rows = [header] + rows
    widths = [max(len(str(r[i])) for r in all_rows) for i in range(len(header))]
    lines = []
    for r in all_rows:
        cells = [str(r[0]).ljust(widths[0])] + [str(c).rjust(w) for c, w in zip(r[1:], widths[1:])]
        lines.append("  ".join(cells))
    return "```\n" + "\n".join(lines) + "\n```"


def fit_table(header, rows, limit=4000):
    """Drop trailing rows until the table fits an embed description."""
    text = fmt_table(header, rows)
    while len(text) > limit and rows:
        rows = rows[:-1]
        text = fmt_table(header, rows)
    return text


def rank_by_wr(rows, wins_key, matches_key, min_matches):
    """Rows with enough matches, sorted by win rate descending."""
    ok = [r for r in rows if r[matches_key] >= min_matches]
    return sorted(ok, key=lambda r: win_rate(r[wins_key], r[matches_key]), reverse=True)


class Meta(commands.Cog):
    group = app_commands.Group(name="meta", description="Game-wide hero and item stats (last 7 days)")

    def __init__(self, bot):
        self.bot = bot

    async def fetch(self, path, **params):
        key = (path, tuple(sorted(params.items())))
        hit = _cache.get(key)
        if hit and time.time() - hit[0] < CACHE_SECONDS:
            return hit[1]
        data = await self.bot.api.get(path, min_unix_timestamp=int(time.time()) - DAYS * 86400, **params) or []
        _cache[key] = (time.time(), data)
        return data

    async def item_names(self):
        """{item_id: name} for shop items only; abilities and weapons share the asset list."""
        hit = _cache.get("items")
        if hit and time.time() - hit[0] < 6 * 3600:
            return hit[1]
        data = await self.bot.api.get("/v1/assets/items") or []
        names = {i["id"]: i["name"] for i in data if i.get("type") == "upgrade"}
        _cache["items"] = (time.time(), names)
        return names

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
        await interaction.followup.send(embed=embed)

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
            names = await self.bot.api.heroes()
            rows = [r for r in rows if r["hero_id"] in names]
            total = sum(r["matches"] for r in rows) or 1
            key = (lambda r: win_rate(r["wins"], r["matches"])) if sort.value == "win" else (lambda r: r["matches"])
            rows.sort(key=key, reverse=True)
            table = [(names[r["hero_id"]]["name"], f"{win_rate(r['wins'], r['matches']):.1f}%", f"{100 * r['matches'] / total:.1f}%", f"{r['matches']:,}") for r in rows]
            title = f"Hero meta by {sort.name.lower()}" + (f" ({rank.name})" if tier else "")
            embed = discord.Embed(title=title, description=fit_table(("Hero", "Win", "Pick", "Matches"), table), color=discord.Color.blurple())
            return embed.set_footer(text=f"Last {DAYS} days. Pick = share of all hero picks.")

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
            embed = discord.Embed(title=heroes[hero]["name"], color=discord.Color.blurple()).set_footer(text=f"Last {DAYS} days")
            if row:
                total = sum(r["matches"] for r in stats) or 1
                embed.description = f"Win rate **{win_rate(row['wins'], row['matches']):.1f}%**, pick rate **{100 * row['matches'] / total:.1f}%**, {row['matches']:,} matches"
            else:
                embed.description = "No matches in this window."

            names = await self.item_names()
            items = await self.fetch("/v1/analytics/item-stats", hero_id=hero, min_matches=ITEM_MIN_HERO)
            items = [r for r in rank_by_wr(items, "wins", "matches", ITEM_MIN_HERO) if r["item_id"] in names][:5]
            if items:
                rows = [(names[r["item_id"]], f"{win_rate(r['wins'], r['matches']):.1f}%", f"{r['matches']:,}") for r in items]
                embed.add_field(name="Top items", value=fmt_table(("Item", "Win", "Matches"), rows), inline=False)

            counters = [r for r in await self.fetch("/v1/analytics/hero-counter-stats", min_matches=PAIR_MIN) if r["hero_id"] == hero and r["enemy_hero_id"] in heroes]
            ranked = rank_by_wr(counters, "wins", "matches_played", PAIR_MIN)

            def vs(r):
                return (heroes[r["enemy_hero_id"]]["name"], f"{win_rate(r['wins'], r['matches_played']):.1f}%", f"{r['matches_played']:,}")

            if ranked:
                embed.add_field(name="Best matchups", value=fmt_table(("Vs", "Win", "Matches"), [vs(r) for r in ranked[:3]]), inline=False)
                embed.add_field(name="Worst matchups", value=fmt_table(("Vs", "Win", "Matches"), [vs(r) for r in ranked[::-1][:3]]), inline=False)

            # synergy rows are one per unordered pair, so the hero can be either side
            syn = []
            for r in await self.fetch("/v1/analytics/hero-synergy-stats", min_matches=PAIR_MIN):
                if hero in (r["hero_id1"], r["hero_id2"]):
                    other = r["hero_id2"] if r["hero_id1"] == hero else r["hero_id1"]
                    if other in heroes:
                        syn.append({"name": heroes[other]["name"], "wins": r["wins"], "matches_played": r["matches_played"]})
            best = rank_by_wr(syn, "wins", "matches_played", PAIR_MIN)[:3]
            if best:
                rows = [(r["name"], f"{win_rate(r['wins'], r['matches_played']):.1f}%", f"{r['matches_played']:,}") for r in best]
                embed.add_field(name="Best teammates", value=fmt_table(("With", "Win", "Matches"), rows), inline=False)
            return embed

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
            names = await self.item_names()
            rows = await self.fetch("/v1/analytics/item-stats", hero_id=hero, min_matches=minimum)
            rows = [r for r in rank_by_wr(rows, "wins", "matches", minimum) if r["item_id"] in names][:20]
            table = [(names[r["item_id"]], f"{win_rate(r['wins'], r['matches']):.1f}%", f"{r['matches']:,}") for r in rows]
            title = "Best items" + (f" for {heroes[hero]['name']}" if hero else "")
            desc = fit_table(("Item", "Win", "Matches"), table) if table else "No items with enough matches."
            return discord.Embed(title=title, description=desc, color=discord.Color.blurple()).set_footer(text=f"Last {DAYS} days, at least {minimum:,} matches")

        await self.run(interaction, build)


async def setup(bot):
    await bot.add_cog(Meta(bot))
