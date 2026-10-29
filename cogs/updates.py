"""Bot Updates: after a restart onto a new version, post what changed since the last one, from CHANGELOG.md."""
import re
from pathlib import Path

import discord
from discord.ext import commands

from core import db

CHANGELOG = Path(__file__).parent.parent / "CHANGELOG.md"
LIMIT = 4000  # embed descriptions max out at 4096
SECTION_RE = re.compile(r"^## (\S+).*$", re.M)


def sections(text):
    """[(version, bullet text)], newest first, as CHANGELOG.md lists them."""
    heads = list(SECTION_RE.finditer(text))
    return [(h.group(1), text[h.end():heads[n + 1].start() if n + 1 < len(heads) else len(text)].strip())
            for n, h in enumerate(heads)]


def changes_since(text, last):
    """(current version, changes newer than `last` joined) or None when nothing is new."""
    secs = sections(text)
    if not secs or secs[0][0] == last:
        return None
    versions = [v for v, _ in secs]
    new = secs[:versions.index(last)] if last in versions else secs[:1]  # unknown old version: just the newest
    body = "\n".join(b for _, b in new)
    return secs[0][0], body if len(body) <= LIMIT else body[:LIMIT - 1] + "…"


def update_embed(old, new, body):
    return discord.Embed(title=f"The Pitboss updated: v{old} → v{new}", description=body, color=discord.Color.gold())


class Updates(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.done = False  # on_ready fires again on every reconnect; post once per start

    @commands.Cog.listener()
    async def on_ready(self):
        if self.done:
            return
        self.done = True
        text = CHANGELOG.read_text(encoding="utf8")
        last = db.get_setting(self.bot.db, "bot_version")
        if last is None:  # first start with this feature: nothing to compare with
            db.set_setting(self.bot.db, "bot_version", sections(text)[0][0])
            return
        if not (found := changes_since(text, last)):
            return
        channel_id = db.get_setting(self.bot.db, "bot_updates_id")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return  # version kept, so these changes post once a channel is set and the bot restarts
        try:
            await channel.send(embed=update_embed(last, *found))
        except discord.HTTPException as e:
            print(f"updates: posting failed: {e}")
            return
        db.set_setting(self.bot.db, "bot_version", found[0])


async def setup(bot):
    await bot.add_cog(Updates(bot))
