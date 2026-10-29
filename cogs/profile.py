import discord
from discord import app_commands
from discord.ext import commands

import db
from api import APIError
from cogs._insights import profile_insights
from cogs._shared import WINDOW_DAYS, window_start, won


def kda(ms):
    return sum(m["player_kills"] + m["player_assists"] for m in ms) / max(sum(m["player_deaths"] for m in ms), 1)


class Profile(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(description="Show a Player's Profile: rank, win rate, heroes and insights")
    @app_commands.describe(member="Whose Profile to show (default: you)")
    async def profile(self, interaction: discord.Interaction, member: discord.Member | None = None):
        member = member or interaction.user
        link = db.get_link(self.bot.db, member.id)
        if not link:
            who = "You haven't" if member == interaction.user else f"{member.display_name} hasn't"
            await interaction.response.send_message(f"{who} linked a Deadlock account. Use /link first.", ephemeral=True)
            return
        await interaction.response.defer()
        aid = link["account_id"]
        try:
            api = self.bot.api
            info = await api.get("/v1/players/steam", account_ids=aid)
            rank = await api.get(f"/v1/players/{aid}/rank")
            ranks = await api.get("/v1/assets/ranks")
            history = await api.get(f"/v1/players/{aid}/match-history") or []
            heroes = await api.heroes()
        except APIError as e:
            await interaction.followup.send(str(e), ephemeral=True)
            return

        names = {i: h["name"] for i, h in heroes.items()}
        name = info[0]["personaname"] if info else f"Player {aid}"
        embed = discord.Embed(title=f"{name}'s Profile", description=f"Linked to {member.mention}")
        if rank and rank.get("badge"):
            tier, sub = divmod(rank["badge"], 10)
            tier_name = next((r["name"] for r in ranks or [] if r["tier"] == tier), f"Tier {tier}")
            embed.add_field(name="Rank", value=f"{tier_name} {sub}" if sub else tier_name)
        else:
            embed.add_field(name="Rank", value="Unranked")

        recent = [m for m in history if m["start_time"] >= window_start()]
        if recent:
            wins = sum(map(won, recent))
            mins = sum(m["match_duration_s"] for m in recent) / 60
            embed.add_field(name=f"Last {WINDOW_DAYS} days", value=(
                f"{len(recent)} matches, {wins / len(recent):.0%} win rate\n"
                f"KDA {kda(recent):.2f}, {sum(m['net_worth'] for m in recent) / max(mins, 1):.0f} souls/min"), inline=False)
        else:
            embed.add_field(name=f"Last {WINDOW_DAYS} days", value="No matches", inline=False)

        # shortcut: top heroes use all stored history, not just the window; narrow if that confuses
        by_hero = {}
        for m in history:
            by_hero.setdefault(m["hero_id"], []).append(won(m))
        top = sorted(by_hero.items(), key=lambda kv: -len(kv[1]))[:3]
        if top:
            embed.add_field(name="Most played", inline=False, value="\n".join(
                f"{names.get(h, 'Hero ' + str(h))}: {len(w)} matches, {sum(w) / len(w):.0%} win rate" for h, w in top))
        lines = profile_insights(history, names)
        if lines:
            embed.add_field(name="Insights", value="\n".join(lines), inline=False)
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Profile(bot))
