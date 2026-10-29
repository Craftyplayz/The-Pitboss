import asyncio

import discord
from discord import app_commands
from discord.ext import commands

from core import db
from core.api import APIError
from cogs._profile_embed import build_profile_embed, trend
from core.shared import window_start
from core.graphs import line_graph


class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(description="Show a Player's Profile: stats, heroes, teammates and records")
    @app_commands.describe(member="Whose Profile to show (default: you)")
    async def profile(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        link = db.get_link(self.bot.db, member.id)
        if not link:
            who = "You haven't" if member == interaction.user else f"{member.display_name} hasn't"
            await interaction.response.send_message(f"{who} linked a Deadlock account. Use /link first.", ephemeral=True)
            return
        await interaction.response.defer()
        aid, since = link["account_id"], window_start()
        api = self.bot.api
        try:
            steam, rank, history, hero_stats, mates, heroes, ranks = await asyncio.gather(
                api.get("/v1/players/steam", account_ids=aid),
                api.get(f"/v1/players/{aid}/rank"),
                api.get(f"/v1/players/{aid}/match-history"),
                api.get("/v1/players/hero-stats", account_ids=aid, min_unix_timestamp=since),
                api.get(f"/v1/players/{aid}/mate-stats", min_unix_timestamp=since),
                api.heroes(),
                api.ranks(),
            )
            mates = sorted(mates or [], key=lambda x: -x["matches_played"])[:3]
            names = {}
            if mates:
                found = await api.get("/v1/players/steam", account_ids=",".join(str(x["mate_id"]) for x in mates))
                names = {p["account_id"]: p["personaname"] for p in found or []}
        except APIError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        badge = (rank or {}).get("badge") or 0
        tier, sub = divmod(badge, 10)
        rank_asset = ranks.get(tier) if badge else None
        rank_text = f"{rank_asset['name']} {sub}" if rank_asset else "Unranked"
        rank_icon = (rank_asset.get("images") or {}).get(f"small_subrank{sub}") if rank_asset else None
        window = [m for m in history or [] if m["start_time"] >= since]
        linked = {r["account_id"]: r["member_id"] for r in db.all_links(self.bot.db)}

        embed = build_profile_embed(member, aid, (steam or [None])[0], rank_text, rank_icon, window,
                                    hero_stats or [], mates, names, linked, heroes)
        graph = trend(window, ranked=bool(badge))
        if graph is None:
            await interaction.followup.send(embed=embed)
            return
        points, title, kwargs = graph
        embed.set_image(url="attachment://trend.png")
        await interaction.followup.send(embed=embed, file=discord.File(line_graph(points, title, **kwargs), "trend.png"))


async def setup(bot):
    await bot.add_cog(Profile(bot))
