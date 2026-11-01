"""Voice recording: /record start and stop, auto-join channels picked in The Pitstop, one .ogg clip per sentence for the transcriber."""
import asyncio
import logging
import os
import time
from pathlib import Path

import av
import discord
from discord import app_commands
from discord.ext import commands, tasks, voice_recv

from cogs.logs import who
from core import db
from core.events import KINDS
from core.voicerec import BYTES_PER_MS, Clipper, clip_path, encode_ogg, recordable

VOICE_DIR = Path(os.environ.get("DB_PATH", "data/pitboss.db")).parent / "voice"
STATUS = "🔴 Recording"  # shown under the channel name while recording

logging.getLogger("discord.ext.voice_recv.reader").setLevel(logging.WARNING)  # Discord's timing reports aren't problems


def people(channel):
    return [m for m in channel.members if recordable(m)]


class Sink(voice_recv.AudioSink):
    def __init__(self, clipper):
        super().__init__()
        self.clipper = clipper

    def wants_opus(self):
        return False

    def write(self, user, data):
        if recordable(user) and data.pcm:
            self.clipper.write(user, data.pcm)

    def cleanup(self):
        pass


class Record(commands.Cog):
    record = app_commands.Group(name="record", description="Record and transcribe a voice call", guild_only=True,
                                default_permissions=discord.Permissions(manage_guild=True))

    def __init__(self, bot):
        self.bot = bot
        # guild id: (call id, Clipper); Discord allows one voice connection per bot per server
        self.calls = {}
        self.lock = asyncio.Lock()  # two voice events at once would both try to join

    async def cog_load(self):
        # a restart drops the voice connection; close what this bot was recording
        self.stale = db.interrupt_calls(self.bot.db, self.bot.user.id, int(time.time()))  # their 🔴 status is cleared on_ready
        self.save_clips.start()

    async def cog_unload(self):
        self.save_clips.cancel()

    def log(self, kind, summary, channel, user=None):
        db.add_event(self.bot.db, int(time.time()), kind, KINDS[kind], summary, user_id=getattr(user, "id", None),
                     user_name=who(user), channel_id=channel.id, channel_name=channel.name)

    async def start(self, channel, user=None):
        """Join and record `channel`. Returns why it couldn't, or None."""
        guild = channel.guild
        async with self.lock:
            if guild.voice_client:
                return f"Already recording {guild.voice_client.channel.mention}. One bot records one channel at a time."
            if db.recording_in(self.bot.db, channel.id):
                return "Another recorder bot is already recording that channel."
            try:
                vc = await channel.connect(cls=voice_recv.VoiceRecvClient)
            except (discord.ClientException, asyncio.TimeoutError) as e:
                print(f"record: joining {channel.name} failed: {e!r}")
                return "Couldn't join the channel. Check the bot can see and connect to it."
            call_id = db.start_call(self.bot.db, self.bot.user.id, channel, getattr(user, "id", None), int(time.time()))
            clipper = Clipper()
            self.calls[guild.id] = (call_id, clipper)
            vc.listen(Sink(clipper))
        by = f" by {who(user)}" if user else " automatically"
        self.log("voice_recording_started", f"Recording 🔊{channel.name} started{by}", channel, user)
        await self.set_status(channel, STATUS)
        return None

    @staticmethod
    async def set_status(channel, status):
        try:
            await channel.edit(status=status)
        except discord.HTTPException as e:  # needs Set Voice Channel Status; hub channels may already be deleted
            print(f"record: status of {channel.name} failed: {e}")

    async def stop(self, guild, user=None):
        """Leave and save what's left. Safe to call twice: our own disconnect fires a voice event too."""
        async with self.lock:
            call = self.calls.pop(guild.id, None)
            vc = guild.voice_client
            channel = vc.channel if vc else None
            if vc:
                if call:
                    await self.set_status(channel, None)  # shortcut: clears any status members had set before, since discord.py can't read it
                await vc.disconnect()
        if call:
            await self.save(call, flush=True)
            db.end_call(self.bot.db, call[0], int(time.time()))
            if channel:
                by = f" by {who(user)}" if user else ""
                self.log("voice_recording_stopped", f"Recording 🔊{channel.name} stopped{by}", channel, user)

    async def autojoin(self, guild):
        for cid in db.autojoin_channels(self.bot.db):
            channel = guild.get_channel(int(cid))
            if isinstance(channel, discord.VoiceChannel) and people(channel):
                await self.start(channel)
                return

    async def save(self, call, flush=False):
        call_id, clipper = call
        for member, start_ms, pcm in clipper.finished(flush):
            path = clip_path(VOICE_DIR, call_id, member.id, start_ms)
            try:
                await asyncio.to_thread(encode_ogg, pcm, path)
            except (av.FFmpegError, OSError) as e:
                print(f"record: saving {path} failed: {e!r}")
                continue
            db.add_clip(self.bot.db, call_id, member.id, who(member), start_ms, len(pcm) // BYTES_PER_MS,
                        path.relative_to(VOICE_DIR).as_posix())

    @tasks.loop(seconds=0.25)
    async def save_clips(self):
        for call in list(self.calls.values()):
            await self.save(call)

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        guild = member.guild
        if member.id == self.bot.user.id:
            if not after.channel:  # kicked from the channel, or our own disconnect
                await self.stop(guild)
            # shortcut: if someone drags the bot to another channel, the call keeps the first channel's name; end and restart it if that matters
            return
        if before.channel == after.channel:
            return
        vc = guild.voice_client
        if vc and before.channel == vc.channel and not people(vc.channel):
            await self.stop(guild)
            await self.autojoin(guild)  # another listed channel may still have people in it
        elif not vc and after.channel and after.channel.id in db.autojoin_channels(self.bot.db) and recordable(member):
            await self.start(after.channel)

    @commands.Cog.listener()
    async def on_ready(self):
        for cid in self.stale:
            if channel := self.bot.get_channel(cid):
                await self.set_status(channel, None)
        self.stale = []
        # people may already be in a listed channel when the bot comes online
        for guild in self.bot.guilds:
            if not guild.voice_client:
                await self.autojoin(guild)

    @record.command(name="start", description="Join your voice channel and record it")
    async def record_start(self, interaction: discord.Interaction):
        channel = getattr(interaction.user.voice, "channel", None)
        if not channel:
            return await interaction.response.send_message("Join a voice channel first.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)  # joining voice can take a few seconds
        error = await self.start(channel, interaction.user)
        await interaction.followup.send(error or f"Recording {channel.mention}. Transcripts show up in The Pitstop's Voice tab.",
                                        ephemeral=True)

    @record.command(name="stop", description="Stop recording and leave the voice channel")
    async def record_stop(self, interaction: discord.Interaction):
        if interaction.guild.id not in self.calls:
            return await interaction.response.send_message("Not recording right now.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.stop(interaction.guild, interaction.user)
        await interaction.followup.send("Stopped recording.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(Record(bot))
