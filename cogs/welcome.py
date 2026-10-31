"""Welcome messages: posts the server's custom message in the welcome channel when someone joins."""
import discord
from discord import app_commands
from discord.ext import commands

from core import db

DEFAULT = "Welcome to **{server}**, {user}! You're member #{count}."
PLACEHOLDERS = "`{user}` mentions them, `{name}` is their name, `{server}` is the server name, `{count}` is the member count."


def fill(template, member):
    # replace, not str.format: a stray { in an admin's message would crash format()
    for key, value in {"{user}": member.mention, "{name}": member.display_name,
                       "{server}": member.guild.name, "{count}": str(member.guild.member_count)}.items():
        template = template.replace(key, value)
    return template


class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    def message(self):
        return db.get_setting(self.bot.db, "welcome_message") or DEFAULT

    @commands.Cog.listener()
    async def on_member_join(self, member):
        cid = db.get_setting(self.bot.db, "welcome_channel_id")
        channel = self.bot.get_channel(int(cid)) if cid else None
        if member.bot or not channel:
            return
        try:
            # only the new member gets pinged, even if the message has @everyone in it
            await channel.send(fill(self.message(), member), allowed_mentions=discord.AllowedMentions(users=[member]))
        except discord.HTTPException as e:
            print(f"welcome: posting for {member} failed: {e}")

    @app_commands.command(name="welcome", description="Change the welcome message. Leave it empty to see the current one.")
    @app_commands.describe(message="Use {user} {name} {server} {count}, and \\n for a new line. Type reset for the default.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def welcome(self, interaction: discord.Interaction, message: str | None = None):
        if message:
            # an empty setting falls back to DEFAULT
            db.set_setting(self.bot.db, "welcome_message", "" if message.strip().lower() == "reset" else message.replace("\\n", "\n"))
        cid = db.get_setting(self.bot.db, "welcome_channel_id")
        where = f"Posted in <#{cid}>." if cid else "No welcome channel yet: pick one with /setup welcome:."
        await interaction.response.send_message(
            f"{'Saved. ' if message else ''}{where} Preview, with you as the new member:\n\n"
            f"{fill(self.message(), interaction.user)}\n\n{PLACEHOLDERS}", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Welcome(bot))
