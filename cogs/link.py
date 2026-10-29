import re
import time

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from core import db
from core.api import APIError

STEAM64_BASE = 76561197960265728
URL_RE = re.compile(r"^(?:https?://)?(?:www\.)?steamcommunity\.com/profiles/(\d+)/?$", re.I)
VANITY_RE = re.compile(r"^(?:https?://)?(?:www\.)?steamcommunity\.com/id/([\w-]+)/?$", re.I)
STEAMID64_RE = re.compile(r"<steamID64>(\d+)</steamID64>")


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


async def resolve_vanity(name, api):
    """Custom URL name -> 32-bit account ID via Steam's public profile XML, else None. Logged through `api`."""
    url, params = f"https://steamcommunity.com/id/{name}/", {"xml": 1}
    started, status, size, text = time.monotonic(), "error", 0, ""
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as s:
            async with s.get(url, params=params) as resp:
                status, text = resp.status, await resp.text()
                size = len(text)
                m = STEAMID64_RE.search(text)
    except (aiohttp.ClientError, TimeoutError) as e:
        raise APIError("Couldn't reach Steam to look up that custom URL.") from e
    finally:
        api.log(url, params, status, started, size, text.encode())
    return parse_player(m.group(1)) if m else None


def flag(country):
    """Two-letter country code -> flag emoji, else ""."""
    if not country or len(country) != 2 or not country.isalpha():
        return ""
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in country.upper())


def choice_name(p):
    return " · ".join(filter(None, [p["personaname"], flag(p.get("countrycode")), str(p["account_id"])]))[:100]


def confirm_embed(player, history):
    """Private card asking 'is this you?' before a Link is made."""
    url = player.get("profileurl")
    embed = discord.Embed(title=player["personaname"], url=url, color=discord.Color.gold(),
                          description="Is this your Steam account?")
    if avatar := player.get("avatarfull") or player.get("avatarmedium"):
        embed.set_thumbnail(url=avatar)
    country = player.get("countrycode")
    if country:
        embed.add_field(name="Country", value=f"{flag(country)} {country}")
    embed.add_field(name="Deadlock Matches", value=f"{len(history):,}" if history else "None found")
    if history:
        last = max(m["start_time"] + m["match_duration_s"] for m in history)
        embed.add_field(name="Last played", value=f"<t:{last}:R>")
    embed.set_footer(text=f"Account ID {player['account_id']}")
    return embed


class ConfirmLink(discord.ui.View):
    def __init__(self, cog, account_id, name):
        super().__init__(timeout=120)
        self.cog, self.account_id, self.name = cog, account_id, name

    async def finish(self, interaction, content):
        self.stop()
        await interaction.response.edit_message(content=content, embed=None, view=None)

    @discord.ui.button(label="That's me", style=discord.ButtonStyle.success)
    async def confirm(self, interaction, button):
        bot_db = self.cog.bot.db
        # re-checked: someone else may have linked this Player while the card was open
        taken = db.get_link_by_account(bot_db, self.account_id)
        if taken and taken["member_id"] != interaction.user.id:
            return await self.finish(interaction, "That Player was just linked to another Member.")
        db.set_link(bot_db, interaction.user.id, self.account_id, int(time.time()))
        await self.finish(interaction, f"Linked to **{self.name}**. Your recaps start in a minute or two.")
        await interaction.followup.send(f"Linked {interaction.user.mention} to **{self.name}**.")
        if recaps := self.cog.bot.get_cog("Recaps"):
            recaps.recap_now(interaction.user.id)  # don't make a new Member wait for the 5-minute loop

    @discord.ui.button(label="Not me", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction, button):
        await self.finish(interaction, "Not linked. Run /link again and pick a different account, "
                                       "or paste your Steam profile URL.")


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
    @app_commands.describe(player="Type your Steam name and pick from the list, or give a Steam ID or profile URL")
    async def link(self, interaction: discord.Interaction, player: str):
        account_id = parse_player(player)
        vanity = VANITY_RE.match(player.strip())
        if account_id is None and not vanity:
            return await interaction.response.send_message(
                "I couldn't read that. Type your Steam name and pick yourself from the suggestions, "
                "or give a Steam ID or steamcommunity.com profile URL.",
                ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        try:
            if vanity:
                account_id = await resolve_vanity(vanity.group(1), self.bot.api)
                if account_id is None:
                    return await interaction.followup.send("No Steam profile has that custom URL.", ephemeral=True)
            taken = db.get_link_by_account(self.bot.db, account_id)
            if taken and taken["member_id"] != interaction.user.id:
                return await interaction.followup.send("That Player is already linked to another Member.", ephemeral=True)
            found = await self.bot.api.get("/v1/players/steam", account_ids=account_id)
            history = await self.bot.api.get(f"/v1/players/{account_id}/match-history") if found else None
        except APIError as e:
            return await interaction.followup.send(str(e), ephemeral=True)
        if not found:
            return await interaction.followup.send(
                "I couldn't find that Player on deadlock-api.com (wrong ID, or they opted out of data sharing).",
                ephemeral=True)
        name = found[0]["personaname"]
        await interaction.followup.send(embed=confirm_embed(found[0], history or []),
                                        view=ConfirmLink(self, account_id, name), ephemeral=True)

    @link.autocomplete("player")
    async def player_autocomplete(self, interaction: discord.Interaction, current: str):
        current = current.strip()
        if len(current) < 2 or parse_player(current) is not None or VANITY_RE.match(current):
            return []
        try:
            found = await self.bot.api.get("/v1/players/steam-search", search_query=current, limit=25) or []
        except APIError:
            return []
        # value is the account ID, so picking a suggestion goes through parse_player
        return [app_commands.Choice(name=choice_name(p), value=str(p["account_id"])) for p in found]

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
