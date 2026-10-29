import asyncio

import discord
from discord import app_commands
from discord.ext import commands

import db
from api import APIError
from cogs import _leaderboard_math as lb
from cogs._shared import WINDOW_DAYS, WINDOW_MIN_MATCHES, window_start

METRICS = ["Rank", "Win rate", "KDA", "Matches played", "Souls per minute", "Rank Climb"]
CHUNK = 50  # account ids per bulk request, keeps URLs short
TOP = 10


def fmt(metric, v):
    if metric == "Win rate":
        return f"{v:.1%}"
    if metric == "KDA":
        return f"{v:.2f}"
    if metric == "Rank Climb":
        return f"{v:+.0f}"
    return f"{v:.0f}"


async def fail(interaction, text):
    """Error after a public defer: drop the placeholder so the followup can be ephemeral."""
    await interaction.delete_original_response()
    await interaction.followup.send(text, ephemeral=True)


class Leaderboard(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def hero_choices(self, interaction, current):
        heroes = await self.bot.api.heroes()
        names = sorted(h["name"] for h in heroes.values())
        return [app_commands.Choice(name=n, value=n) for n in names if current.lower() in n.lower()][:25]

    async def bulk(self, path, accounts, **params):
        """Fetch a bulk endpoint in chunks. Returns (rows, accounts whose chunk failed)."""
        rows, failed = [], set()
        for i in range(0, len(accounts), CHUNK):
            chunk = accounts[i:i + CHUNK]
            try:
                rows += await self.bot.api.get(path, account_ids=",".join(map(str, chunk)), **params) or []
            except APIError:
                failed.update(chunk)
        return rows, failed

    async def climb_aggs(self, accounts, hero_id):
        """Rank Climb needs per-match ranked_delta, so one stored-history request per Player."""
        # shortcut: N requests per board (no bulk delta endpoint), upgrade if the server grows past ~100 Linked Members
        sem, since = asyncio.Semaphore(5), window_start()

        async def one(acc):
            async with sem:
                try:
                    hist = await self.bot.api.get(f"/v1/players/{acc}/match-history") or []
                    return acc, lb.from_history(hist, since, hero_id)
                except APIError:
                    return acc, None

        results = await asyncio.gather(*(one(a) for a in accounts))
        return {a: g for a, g in results if g}, {a for a, g in results if g is None}

    @app_commands.command(description="Rank this server's linked members by a stat")
    @app_commands.choices(metric=[app_commands.Choice(name=m, value=m) for m in METRICS])
    @app_commands.autocomplete(hero=hero_choices)
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction, metric: str, hero: str | None = None):
        await interaction.response.defer()
        try:
            heroes = await self.bot.api.heroes()
        except APIError as e:
            return await fail(interaction, str(e))
        hero_id = None
        if hero:
            hero_id = next((i for i, h in heroes.items() if h["name"].lower() == hero.lower()), None)
            if hero_id is None:
                return await fail(interaction, "I don't know that hero. Pick one from the list.")
        if metric == "Rank" and hero_id is not None:
            return await fail(interaction, "Rank has no per-hero board: Deadlock keeps one rank per Player.")

        owner = {r["account_id"]: r["member_id"] for r in db.all_links(self.bot.db)}
        accounts = list(owner)
        try:
            if metric == "Rank":
                rows, failed = await self.bulk("/v1/players/rank", accounts)
                board = lb.rank_by_badge({r["account_id"]: r.get("badge") for r in rows})
                names = {r["tier"]: r["name"] for r in await self.bot.api.get("/v1/assets/ranks") or []}

                def show(b):
                    return f"{names.get(b // 10, '?')} {b % 10}"
            else:
                if metric == "Rank Climb":
                    aggs, failed = await self.climb_aggs(accounts, hero_id)
                else:
                    rows, failed = await self.bulk(
                        "/v1/players/hero-stats", accounts, min_unix_timestamp=window_start(), hero_ids=hero_id)
                    by_acc = {}
                    for r in rows:
                        by_acc.setdefault(r["account_id"], []).append(r)
                    aggs = {a: lb.from_hero_stats(rs, hero_id) for a, rs in by_acc.items()}
                board = lb.rank_board(aggs, metric)

                def show(v):
                    return fmt(metric, v)
        except APIError as e:
            return await fail(interaction, str(e))

        board = [(owner[a], v) for a, v in board if interaction.guild.get_member(owner[a])]  # skip members who left
        if not board:
            return await interaction.followup.send("Nobody qualifies for that board yet.")
        lines = [f"**{i}.** <@{m}> {show(v)}" for i, (m, v) in enumerate(board[:TOP], 1)]
        me = next((i for i, (m, _) in enumerate(board) if m == interaction.user.id), None)
        if me is not None and me >= TOP:
            lines += ["...", f"**{me + 1}.** <@{board[me][0]}> {show(board[me][1])}"]

        title = metric + (f" - {await self.bot.api.hero_name(hero_id)}" if hero_id else "")
        foot = "Current rank" if metric == "Rank" else f"Last {WINDOW_DAYS} days, min {WINDOW_MIN_MATCHES} matches"
        if failed:
            foot += f" | {len(failed)} player(s) skipped: stats API error"
        embed = discord.Embed(title=f"Leaderboard: {title}", description="\n".join(lines))
        embed.set_footer(text=foot)
        await interaction.followup.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())


async def setup(bot):
    await bot.add_cog(Leaderboard(bot))
