"""Voice Hub: joining the hub channel makes a "Deadlock N" voice channel next to it and moves you in; empty ones are deleted."""
import asyncio
import re

import discord
from discord.ext import commands

from core import db

NAME_RE = re.compile(r"^Deadlock (\d+)$")


def lowest_free(taken):
    """Smallest number from 1 up that isn't in `taken`."""
    n = 1
    while n in taken:
        n += 1
    return n


class Voice(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()  # two joins at once would both pick the same number

    def hub(self):
        cid = db.get_setting(self.bot.db, "voice_hub_id")
        channel = self.bot.get_channel(int(cid)) if cid else None
        return channel if isinstance(channel, discord.VoiceChannel) else None

    @staticmethod
    def made(hub):
        """{number: channel} for the Deadlock N channels in the hub's category."""
        siblings = hub.category.voice_channels if hub.category else [c for c in hub.guild.voice_channels if not c.category]
        return {int(m.group(1)): c for c in siblings if c != hub and (m := NAME_RE.match(c.name))}

    async def delete_if_empty(self, channel):
        if not channel.members:
            try:
                await channel.delete(reason="Voice hub channel is empty")
            except discord.NotFound:
                pass  # already gone
            except discord.HTTPException as e:
                print(f"voice: deleting {channel.name} failed: {e}")

    async def create_for(self, hub, member):
        # skip empty ones: they're being deleted, and the cache may not know yet
        made = {k: c for k, c in self.made(hub).items() if c.members}
        n = lowest_free(made)
        lower = [made[k] for k in sorted(made) if k < n]
        higher = [made[k] for k in sorted(made) if k > n]
        channel = None
        try:
            channel = await hub.guild.create_voice_channel(f"Deadlock {n}", category=hub.category,
                                                             rtc_region="sydney", reason="Voice hub")
            # keep them in number order: right above the next one up, else right below the previous one (or the hub)
            if higher:
                await channel.move(before=higher[0])
            else:
                await channel.move(after=lower[-1] if lower else hub)
            await member.move_to(channel)
        except discord.HTTPException as e:
            print(f"voice: making Deadlock {n} failed: {e}")
            if channel:
                await self.delete_if_empty(channel)  # they left before the move, or the move failed

    @commands.Cog.listener()
    async def on_voice_state_update(self, member, before, after):
        if before.channel == after.channel or not (hub := self.hub()):
            return
        async with self.lock:
            # delete first so someone hopping from an empty Deadlock 1 to the hub gets number 1 again
            if before.channel and before.channel in self.made(hub).values():
                await self.delete_if_empty(before.channel)
            if after.channel == hub:
                await self.create_for(hub, member)

    @commands.Cog.listener()
    async def on_ready(self):
        # people may have left while the bot was offline
        if hub := self.hub():
            async with self.lock:
                for channel in self.made(hub).values():
                    await self.delete_if_empty(channel)


async def setup(bot):
    await bot.add_cog(Voice(bot))
