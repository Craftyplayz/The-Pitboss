"""Scrims: /scrim opens a sign-up channel, the creator makes teams, the bot makes a deadlock-api custom lobby,
then saves the Match's scoreboard once it is over and posts it to the scrim log channel."""
import html
import json
import random
import time
from datetime import datetime, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

from core import db
from core.api import APIError
from cogs._item_emojis import ItemEmojis
from core.dashboard import match_detail
from core.recap_images import scoreboard_image
from core.shared import SITE_URL

TEAMS = ("Amber", "Sapphire")
TEAM_SIZE = 6
LOBBY_TTL = 20 * 60  # the API's lobby bot leaves 15 minutes after making the lobby; stop asking for a match id after this
LIVE_TTL = 12 * 3600  # give up on the scoreboard this long after the lobby was made
CREATOR_ONLY = {"start", "random", "pick", "lobby", "cancel"}


def random_teams(member_ids, rng=random):
    """{member_id: team}; team sizes differ by at most one."""
    ids = list(member_ids)
    rng.shuffle(ids)
    return {m: i % 2 for i, m in enumerate(ids)}


def button(label, action, scrim_id, style=discord.ButtonStyle.secondary, disabled=False):
    # custom ids carry the scrim, so buttons keep working after a restart (handled in on_interaction)
    return discord.ui.Button(label=label, custom_id=f"scrim:{action}:{scrim_id}", style=style, disabled=disabled)


def mentions(ids):
    return "\n".join(f"<@{m}>" for m in ids) or "–"


STATE_WORDS = {"open": "sign-up open", "picking": "picking teams", "creating": "making the lobby", "lobby": "lobby open",
               "live": "match live", "done": "finished", "failed": "no scoreboard", "cancelled": "cancelled"}
SQUARES = ("🟧", "🟦")  # Amber, Sapphire
COLORS = (discord.Color.orange(), discord.Color.blue())


def signup(scrim, players):
    """(embed, view) for the sign-up message in the scrim's current state. players: [(member_id, team)]."""
    sid, state = scrim["id"], scrim["state"]
    embed = discord.Embed(title=f"Scrim #{sid}", color=discord.Color.gold())
    embed.set_author(name=f"Scrim · {STATE_WORDS.get(state, state)}")
    lines = [f"Created by <@{scrim['creator_id']}>."]
    view = discord.ui.View(timeout=None)
    if state == "open":
        embed.add_field(name=f"Players ({len(players)}/{2 * TEAM_SIZE})", value=mentions(m for m, _ in players), inline=False)
        embed.set_footer(text="Press Join to play. The creator presses Start scrim when everyone is in.")
        view.add_item(button("Join", "join", sid, discord.ButtonStyle.success, len(players) >= 2 * TEAM_SIZE))
        view.add_item(button("Leave", "leave", sid))
        view.add_item(button("Start scrim", "start", sid, discord.ButtonStyle.primary, len(players) < 2))
    else:
        for t, name in enumerate(TEAMS):
            team = [m for m, pt in players if pt == t]
            embed.add_field(name=f"{SQUARES[t]} {name} ({len(team)}/{TEAM_SIZE})", value=mentions(team))
    if state == "picking":
        unpicked = [m for m, t in players if t is None]
        if unpicked:
            embed.add_field(name=f"Not picked yet ({len(unpicked)})", value=mentions(unpicked), inline=False)
        embed.set_footer(text="Pick your team. The creator presses Make lobby when everyone has picked.")
        ready = not unpicked and all(any(t == team for _, t in players) for team in (0, 1))
        view.add_item(button(f"Join {TEAMS[0]}", "team0", sid, discord.ButtonStyle.primary))
        view.add_item(button(f"Join {TEAMS[1]}", "team1", sid, discord.ButtonStyle.primary))
        view.add_item(button("Leave", "leave", sid))
        view.add_item(button("Make lobby", "lobby", sid, discord.ButtonStyle.success, not ready))
    elif state == "creating":
        lines.append("Making the lobby…")
    elif state == "lobby":
        embed.add_field(name="Lobby code", value=f"```\n{scrim['party_code']}\n```", inline=False)  # keep last
        lines.append("In Deadlock, join the custom lobby with this code and take your team's side. "
                     "The code works for 15 minutes; if it runs out, the creator presses New code.")
        view.add_item(button("New code", "lobby", sid))
    elif state == "live":
        lines.append(f"Match {scrim['match_id']} is live. The scoreboard is posted here when it's over.")
    elif state == "done":
        lines.append(f"Finished. Full scoreboard: {SITE_URL}/#scrims/{sid}")
    elif state == "failed":
        lines.append("No scoreboard turned up for this Match, so it wasn't saved.")
    elif state == "cancelled":
        lines.append("Cancelled.")
    if state in ("open", "picking", "lobby"):
        view.add_item(button("Cancel", "cancel", sid, discord.ButtonStyle.danger))
    embed.description = "\n".join(lines)
    return embed, view


def short(n):
    return f"{n / 1000:.1f}K" if n >= 1000 else str(n)


def scoreboard_png(detail, hero_names):
    """The scoreboard image (BytesIO) for result_embed's attachment://scoreboard.png, drawn like the recaps'."""
    teams = []
    for t in (0, 1):
        rows = sorted((p for p in detail["pl"] if p["team"] == t), key=lambda p: -p["nw"])
        teams.append((TEAMS[t].upper(), t == detail["win"], sum(p["nw"] for p in rows), [
            (hero_names.get(p["hero"], "Hero"), f"{p['k']}/{p['d']}/{p['a']}", p["nw"], p["dmg"], False) for p in rows]))
    return scoreboard_image(teams)


def result_embed(scrim_id, detail, hero_names, linked, hero_emojis=None):
    """The finished scrim's scoreboard. detail: match_detail output. linked: {account_id: member_id}.
    hero_emojis: {hero_id: emoji text}, missing heroes get no icon. The caller attaches scoreboard_png as scoreboard.png."""
    win, dur, hero_emojis = detail["win"], detail["dur"], hero_emojis or {}

    def who(p):  # nm is HTML-escaped for the website
        return f"<@{linked[p['id']]}>" if p["id"] in linked else discord.utils.escape_markdown(html.unescape(p["nm"]))

    def hero(p):
        return f"{hero_emojis.get(p['hero'], '')} **{hero_names.get(p['hero'], 'Hero')}**".strip()

    embed = discord.Embed(title=f"{TEAMS[win]} wins", url=f"{SITE_URL}/#scrims/{scrim_id}", color=COLORS[win],
                          timestamp=datetime.fromtimestamp(detail["t"] + dur, timezone.utc))
    embed.set_author(name=f"Scrim #{scrim_id} · finished")
    for t in (0, 1):
        rows = sorted((p for p in detail["pl"] if p["team"] == t), key=lambda p: -p["nw"])
        name = (f"{SQUARES[t]} {TEAMS[t]}{' 🏆' if t == win else ''} · {short(sum(p['nw'] for p in rows))} souls"
                f" · {sum(p['k'] for p in rows)} kills")
        embed.add_field(name=name, inline=False, value="\n".join(
            f"{hero(p)} · {who(p)} · {p['k']}/{p['d']}/{p['a']} · {short(p['nw'])} souls · {short(p['dmg'])} dmg"
            for p in rows) or "–")
    if detail["pl"]:
        mvp = max(detail["pl"], key=lambda p: p["dmg"])  # MVP = most damage
        embed.description = f"MVP (most damage): {hero(mvp)} · {who(mvp)} · {short(mvp['dmg'])} dmg"
    embed.set_image(url="attachment://scoreboard.png")
    embed.set_footer(text=f"Match {detail['id']} · {dur // 60}:{dur % 60:02d}")
    return embed


class Scrims(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.emojis = ItemEmojis(bot)

    async def cog_load(self):
        self.watch.start()

    async def cog_unload(self):
        self.watch.cancel()

    @app_commands.command(name="scrimlog", description="Choose the channel where finished scrims are logged.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.guild_only()
    async def scrimlog(self, interaction: discord.Interaction, channel: discord.TextChannel):
        db.set_setting(self.bot.db, "scrim_log_id", channel.id)
        await interaction.response.send_message(f"Finished scrims will be logged in {channel.mention}.", ephemeral=True)

    @app_commands.command(name="scrim", description="Start a scrim: opens a sign-up channel with a Join button.")
    @app_commands.guild_only()
    async def scrim(self, interaction: discord.Interaction):
        await interaction.response.defer()
        now = int(time.time())
        sid = db.create_scrim(self.bot.db, interaction.user.id, now)
        db.add_scrim_player(self.bot.db, sid, interaction.user.id, now)
        channel = None
        try:
            channel = await interaction.guild.create_text_channel(
                f"scrim-{sid}", category=getattr(interaction.channel, "category", None), reason=f"Scrim by {interaction.user}")
            msg = await channel.send(**self.render(sid))
        except discord.HTTPException as e:
            print(f"scrims: couldn't open scrim {sid}: {e}")
            db.update_scrim(self.bot.db, sid, state="cancelled")
            if channel:
                await channel.delete()
            return await interaction.followup.send(
                "I couldn't make the scrim channel. Give me the Manage Channels permission.", ephemeral=True)
        db.update_scrim(self.bot.db, sid, channel_id=channel.id, message_id=msg.id)
        await interaction.followup.send(f"Scrim #{sid} is open: join in {channel.mention}.")

    def render(self, sid):
        embed, view = signup(db.get_scrim(self.bot.db, sid), db.scrim_players(self.bot.db, sid))
        return {"embed": embed, "view": view}

    async def refresh(self, sid, interaction=None):
        """Redraw the sign-up message, through the button press when it came from that message."""
        scrim = db.get_scrim(self.bot.db, sid)
        if interaction and interaction.message and interaction.message.id == scrim["message_id"]:
            return await interaction.response.edit_message(**self.render(sid))
        if channel := self.bot.get_channel(scrim["channel_id"] or 0):
            try:
                await channel.get_partial_message(scrim["message_id"]).edit(**self.render(sid))
            except discord.HTTPException as e:
                print(f"scrims: couldn't redraw scrim {sid}: {e}")

    async def say(self, sid, text):
        if channel := self.bot.get_channel(db.get_scrim(self.bot.db, sid)["channel_id"] or 0):
            await channel.send(text)

    @commands.Cog.listener()
    async def on_interaction(self, interaction: discord.Interaction):
        if interaction.type != discord.InteractionType.component:
            return
        parts = (interaction.data or {}).get("custom_id", "").split(":")
        if len(parts) != 3 or parts[0] != "scrim":
            return
        action, sid = parts[1], int(parts[2])
        scrim = db.get_scrim(self.bot.db, sid)
        handler = getattr(self, f"do_{action}", None)
        if scrim is None or handler is None:
            return await interaction.response.send_message("That scrim no longer exists.", ephemeral=True)
        if (action in CREATOR_ONLY and interaction.user.id != scrim["creator_id"]
                and not interaction.permissions.manage_channels):
            return await interaction.response.send_message("Only the scrim's creator can do that.", ephemeral=True)
        await handler(interaction, scrim)

    async def reject(self, interaction, text):
        await interaction.response.send_message(text, ephemeral=True)

    async def do_join(self, interaction, scrim):
        players = db.scrim_players(self.bot.db, scrim["id"])
        if scrim["state"] != "open":
            return await self.reject(interaction, "Sign-up for this scrim is closed.")
        if len(players) >= 2 * TEAM_SIZE:
            return await self.reject(interaction, "This scrim is full.")
        db.add_scrim_player(self.bot.db, scrim["id"], interaction.user.id, int(time.time()))
        await self.refresh(scrim["id"], interaction)

    async def do_leave(self, interaction, scrim):
        if scrim["state"] not in ("open", "picking"):
            return await self.reject(interaction, "Teams are locked in for this scrim.")
        db.remove_scrim_player(self.bot.db, scrim["id"], interaction.user.id)
        await self.refresh(scrim["id"], interaction)

    async def do_start(self, interaction, scrim):
        if scrim["state"] != "open" or len(db.scrim_players(self.bot.db, scrim["id"])) < 2:
            return await self.reject(interaction, "A scrim needs at least 2 players to start.")
        view = discord.ui.View(timeout=None)
        view.add_item(button("Random teams", "random", scrim["id"], discord.ButtonStyle.primary))
        view.add_item(button("Players pick", "pick", scrim["id"], discord.ButtonStyle.primary))
        await interaction.response.send_message("How should teams be made?", view=view, ephemeral=True)

    async def do_random(self, interaction, scrim):
        if scrim["state"] != "open":
            return await self.reject(interaction, "Teams are already being made.")
        players = db.scrim_players(self.bot.db, scrim["id"])
        db.set_scrim_teams(self.bot.db, scrim["id"], random_teams(m for m, _ in players))
        db.update_scrim(self.bot.db, scrim["id"], state="creating")  # before any await, so a double click is rejected
        await interaction.response.edit_message(content="Random teams made.", view=None)
        await self.make_lobby(scrim["id"], "picking")

    async def do_pick(self, interaction, scrim):
        if scrim["state"] != "open":
            return await self.reject(interaction, "Teams are already being made.")
        db.update_scrim(self.bot.db, scrim["id"], state="picking")
        await interaction.response.edit_message(content="Players can pick their team now.", view=None)
        await self.refresh(scrim["id"])
        await self.say(scrim["id"], "Pick your team with the buttons above.")

    async def do_team0(self, interaction, scrim, team=0):
        if scrim["state"] != "picking":
            return await self.reject(interaction, "Teams are locked in for this scrim.")
        players = db.scrim_players(self.bot.db, scrim["id"])
        if sum(t == team for m, t in players if m != interaction.user.id) >= TEAM_SIZE:
            return await self.reject(interaction, f"{TEAMS[team]} is full.")
        # late arrivals can still get in by picking a team
        if interaction.user.id not in {m for m, _ in players} and len(players) >= 2 * TEAM_SIZE:
            return await self.reject(interaction, "This scrim is full.")
        db.add_scrim_player(self.bot.db, scrim["id"], interaction.user.id, int(time.time()), team)
        await self.refresh(scrim["id"], interaction)

    async def do_team1(self, interaction, scrim):
        await self.do_team0(interaction, scrim, team=1)

    async def do_lobby(self, interaction, scrim):
        if scrim["state"] not in ("picking", "lobby"):
            return await self.reject(interaction, "The lobby is already being made.")
        prev = scrim["state"]
        db.update_scrim(self.bot.db, scrim["id"], state="creating")
        await interaction.response.defer()
        await self.make_lobby(scrim["id"], prev)

    async def do_cancel(self, interaction, scrim):
        if scrim["state"] not in ("open", "picking", "lobby"):
            return await self.reject(interaction, "This scrim can't be cancelled now.")
        db.update_scrim(self.bot.db, scrim["id"], state="cancelled")
        await interaction.response.send_message("Scrim cancelled. This channel will be deleted.", ephemeral=True)
        try:
            await interaction.channel.delete(reason="Scrim cancelled")
        except discord.HTTPException:
            await self.refresh(scrim["id"])

    async def make_lobby(self, sid, fail_state):
        """Make a deadlock-api custom lobby and post its code. On failure the scrim goes back to `fail_state`."""
        await self.refresh(sid)
        try:
            lobby = await self.bot.api.post("/v1/matches/custom/create", {})
            error = "the API sent no lobby" if not lobby else None
        except APIError as e:
            lobby, error = None, str(e)
        if error:
            db.update_scrim(self.bot.db, sid, state=fail_state)
            await self.refresh(sid)
            return await self.say(sid, f"Couldn't make the lobby ({error}). Press Make lobby to try again.")
        db.update_scrim(self.bot.db, sid, state="lobby", party_id=lobby["party_id"], party_code=lobby["party_code"],
                        lobby_at=int(time.time()))
        await self.refresh(sid)
        players = db.scrim_players(self.bot.db, sid)
        teams = "\n".join(f"**{name}**: {' '.join(f'<@{m}>' for m, t in players if t == i)}" for i, name in enumerate(TEAMS))
        await self.say(sid, f"Lobby code: **{lobby['party_code']}**\n{teams}")

    @tasks.loop(minutes=2)
    async def watch(self):
        for scrim in db.scrims_in(self.bot.db, "lobby", "live"):
            try:
                await self.check(scrim, time.time())
            except Exception as e:  # an unhandled error would stop the loop for good
                print(f"scrims: scrim {scrim['id']} failed: {e}")

    @watch.before_loop
    async def before_watch(self):
        await self.bot.wait_until_ready()

    async def check(self, scrim, now):
        sid, api = scrim["id"], self.bot.api
        if scrim["state"] == "lobby":
            if now - scrim["lobby_at"] > LOBBY_TTL:
                return  # code ran out; waits for New code
            found = await api.get(f"/v1/matches/custom/{scrim['party_id']}/match-id")
            if found and found.get("match_id"):
                db.update_scrim(self.bot.db, sid, state="live", match_id=found["match_id"])
                await self.refresh(sid)
                await self.say(sid, f"Match {found['match_id']} started. Good luck!")
            return
        meta = await api.get(f"/v1/matches/{scrim['match_id']}/metadata")
        if not meta:  # not over yet, or not processed yet
            if now - scrim["lobby_at"] > LIVE_TTL:
                db.update_scrim(self.bot.db, sid, state="failed")
                await self.refresh(sid)
            return
        ids = ",".join(str(p["account_id"]) for p in meta["match_info"]["players"])
        try:
            names = {p["account_id"]: p["personaname"] for p in await api.get("/v1/players/steam", account_ids=ids) or []}
        except APIError:
            names = {}
        detail = match_detail(meta, await api.items(), names)
        db.update_scrim(self.bot.db, sid, state="done", detail=json.dumps(detail, separators=(",", ":")))
        await self.refresh(sid)
        linked = {l["account_id"]: l["member_id"] for l in db.all_links(self.bot.db)}
        heroes = await api.heroes()
        shown = {p["hero"] for p in detail["pl"]}
        hero_emojis = {i: await self.emojis.hero(h) for i, h in heroes.items() if i in shown}
        hero_names = {i: h["name"] for i, h in heroes.items()}
        embed = result_embed(sid, detail, hero_names, linked, hero_emojis)
        log_id = db.get_setting(self.bot.db, "scrim_log_id")
        for channel_id in {scrim["channel_id"], int(log_id) if log_id else None} - {None}:
            if channel := self.bot.get_channel(channel_id):
                await channel.send(embed=embed, file=discord.File(scoreboard_png(detail, hero_names), "scoreboard.png"))

async def setup(bot):
    await bot.add_cog(Scrims(bot))
