"""Welcome messages: posts the server's custom embed in the welcome channel when someone joins.
Admins design it in the control panel (Welcome & Roles tab); /welcome changes the main text from Discord."""
import json

import discord
from discord import app_commands
from discord.ext import commands

from core import db
from core.embeds import GOLD, render

DEFAULT_TEXT = "Hey {user}, glad you're here! You're member **#{count}**."
DEFAULT = {"content": "{user}", "author": "", "title": "Welcome to {server}!", "description": DEFAULT_TEXT, "footer": "",
           "color": GOLD, "image": "", "show_author": False, "thumbnail": True, "timestamp": True}
PLACEHOLDERS = "`{user}` mentions them, `{name}` is their name, `{server}` is the server name, `{count}` is the member count."


def load(conn):
    """The welcome embed config. Before embeds, only the text was saved: that becomes the description."""
    saved = db.get_setting(conn, "welcome_embed")
    if saved:
        return {**DEFAULT, **json.loads(saved)}
    return {**DEFAULT, "description": db.get_setting(conn, "welcome_message") or DEFAULT_TEXT}


def values(member):
    return {"user": member.mention, "name": member.display_name, "server": member.guild.name,
            "count": member.guild.member_count}


def welcome_message(conn, member):
    """(text, discord.Embed) welcoming this member."""
    content, embed = render(load(conn), values(member), member.display_avatar.url, discord.utils.utcnow().isoformat())
    return content, discord.Embed.from_dict(embed)


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member):
        cid = db.get_setting(self.bot.db, "welcome_channel_id")
        channel = self.bot.get_channel(int(cid)) if cid else None
        if member.bot or not channel:
            return
        content, embed = welcome_message(self.bot.db, member)
        try:
            # only the new member gets pinged, even if the message has @everyone in it
            await channel.send(content or None, embed=embed, allowed_mentions=discord.AllowedMentions(users=[member]))
        except discord.HTTPException as e:
            print(f"welcome: posting for {member} failed: {e}")

    @app_commands.command(name="welcome", description="Change the welcome message's main text. Leave it empty to see a preview.")
    @app_commands.describe(message="Use {user} {name} {server} {count}, and \\n for a new line. Type reset for the default.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def welcome(self, interaction: discord.Interaction, message: str | None = None):
        if message:
            text = DEFAULT_TEXT if message.strip().lower() == "reset" else message.replace("\\n", "\n")
            db.set_setting(self.bot.db, "welcome_embed", json.dumps({**load(self.bot.db), "description": text}))
        cid = db.get_setting(self.bot.db, "welcome_channel_id")
        where = f"Posted in <#{cid}>." if cid else "No welcome channel yet: pick one with /setup welcome:."
        content, embed = welcome_message(self.bot.db, interaction.user)
        await interaction.response.send_message(
            f"{'Saved. ' if message else ''}{where} Preview, with you as the new member "
            f"(design the whole embed in the control panel):\n\n{content}", embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
