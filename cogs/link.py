import re
import time

import discord
from discord import app_commands
from discord.ext import commands

import db
from api import APIError

STEAM64_BASE = 76561197960265728
URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?steamcommunity\.com/profiles/(\d+)/?$", re.I)
VANITY_RE = re.compile(r"steamcommunity\.com/id/", re.I)


def parse_player(text):
    """Steam64 ID, 32-bit account ID or /profiles/ URL -> 32-bit account ID, else None."""
    text = text.strip()
    m = URL_RE.match(text)
    digits = m.group(1) if m else text
    if not digits.isdigit():
        return None
    n = int(digits)
    if n >= STEAM64_BASE:
        n -= STEAM64_BASE
    return n if 0 < n < 2**32 else None


class Link(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup", description="Choose the forum channel where Recap Threads are created.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def setup_cmd(self, interaction: discord.Interaction, recap_forum: discord.ForumChannel):
        db.set_setting(self.bot.db, "recap_forum_id", recap_forum.id)
        perms = recap_forum.permissions_for(interaction.guild.me)
        msg = f"Recaps will be posted in {recap_forum.mention}."
        if not (perms.view_channel and perms.create_public_threads and perms.send_messages_in_threads):
            msg += " Warning: I can't create posts there. Give me View Channel, Create Posts and Send Messages in Posts."
        await interaction.response.send_message(msg, ephemeral=True)

    @app_commands.command(name="link", description="Link your Deadlock account to get match recaps.")
    @app_commands.describe(player="Steam64 ID, account ID, or steamcommunity.com/profiles/... URL")
    async def link(self, interaction: discord.Interaction, player: str):
        if VANITY_RE.search(player):
            return await interaction.response.send_message(
                "Vanity /id/ URLs aren't supported. Use your steamcommunity.com/profiles/<number> URL or your Steam ID.",
                ephemeral=True)
        account_id = parse_player(player)
        if account_id is None:
            return await interaction.response.send_message(
                "I couldn't read that. Give a Steam64 ID, a 32-bit account ID, or a steamcommunity.com/profiles/<number> URL.",
                ephemeral=True)
        taken = db.get_link_by_account(self.bot.db, account_id)
        if taken and taken["member_id"] != interaction.user.id:
            return await interaction.response.send_message(
                "That Player is already linked to another Member.", ephemeral=True)
        await interaction.response.defer()
        try:
            found = await self.bot.api.get("/v1/players/steam", account_ids=account_id)
        except APIError as e:
            return await interaction.followup.send(str(e), ephemeral=True)
        if not found:
            return await interaction.followup.send(
                "I couldn't find that Player on deadlock-api.com (wrong ID, or they opted out of data sharing).",
                ephemeral=True)
        db.set_link(self.bot.db, interaction.user.id, account_id, int(time.time()))
        await interaction.followup.send(f"Linked {interaction.user.mention} to **{found[0]['personaname']}**.")

    @app_commands.command(name="unlink", description="Remove your Link and close your Recap Thread.")
    async def unlink(self, interaction: discord.Interaction):
        if not db.get_link(self.bot.db, interaction.user.id):
            return await interaction.response.send_message("You have no Link.", ephemeral=True)
        await self._unlink(interaction.user.id)
        await interaction.response.send_message("Unlinked. Your Recap Thread is archived.")

    @commands.Cog.listener()
    async def on_member_remove(self, member):
        await self._unlink(member.id)

    async def _unlink(self, member_id):
        link = db.get_link(self.bot.db, member_id)
        if not link:
            return
        db.delete_link(self.bot.db, member_id)
        if link["thread_id"]:
            try:
                thread = self.bot.get_channel(link["thread_id"]) or await self.bot.fetch_channel(link["thread_id"])
                await thread.edit(archived=True, locked=True)
            except (discord.NotFound, discord.Forbidden):
                pass


async def setup(bot):
    await bot.add_cog(Link(bot))
