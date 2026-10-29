"""Match Recaps: post each Linked Member's finished Matches to their Recap Thread."""
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

import db
from api import APIError
from cogs._insights import match_insights
from cogs._shared import won

MAX_AGE = 24 * 3600  # a Match missed for longer than this gets no recap


def match_end(match):
    return match["start_time"] + match["match_duration_s"]


def due_matches(history, linked_at, last_match_id, now):
    """Return (Matches to recap oldest first, match_id to advance past without posting, or None).

    The skip id is the newest qualifying Match that ended more than MAX_AGE ago.
    """
    fresh = sorted(
        (m for m in history
         if match_end(m) > linked_at and (last_match_id is None or m["match_id"] > last_match_id)),
        key=lambda m: m["match_id"],
    )
    recap = [m for m in fresh if now - match_end(m) <= MAX_AGE]
    skip_to = max((m["match_id"] for m in fresh if now - match_end(m) > MAX_AGE), default=None)
    return recap, skip_to


def build_embed(match, history, hero_names, member):
    win = won(match)
    hero = hero_names.get(match["hero_id"], f"Hero {match['hero_id']}")
    duration = match["match_duration_s"]
    embed = discord.Embed(
        title=f"{hero} - {'Win' if win else 'Loss'}",
        description="\n".join(match_insights(match, history, hero_names)) or None,
        color=discord.Color.green() if win else discord.Color.red(),
        timestamp=datetime.fromtimestamp(match_end(match), timezone.utc),
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    embed.add_field(name="K/D/A", value=f"{match['player_kills']}/{match['player_deaths']}/{match['player_assists']}")
    embed.add_field(name="Souls", value=f"{match['net_worth']:,}")
    embed.add_field(name="Souls/min", value=f"{match['net_worth'] / max(duration / 60, 1):,.0f}")
    embed.add_field(name="Duration", value=f"{duration // 60}:{duration % 60:02d}")
    if match.get("ranked_delta"):
        embed.add_field(name="Rank change", value=f"{match['ranked_delta']:+d}")
    embed.set_footer(text=f"Match {match['match_id']}")
    return embed


class Recaps(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.recap_loop.start()

    async def cog_unload(self):
        self.recap_loop.cancel()

    @tasks.loop(minutes=5)
    async def recap_loop(self):
        forum_id = db.get_setting(self.bot.db, "recap_forum_id")
        forum = self.bot.get_channel(int(forum_id)) if forum_id else None
        if not isinstance(forum, discord.ForumChannel):
            return
        try:
            hero_names = {i: h["name"] for i, h in (await self.bot.api.heroes()).items()}
        except APIError as e:
            print(f"recaps: hero list failed: {e}")
            return
        for link in db.all_links(self.bot.db):
            member = forum.guild.get_member(link["member_id"])
            if member is None:  # left the server; the link cog removes the Link
                continue
            try:
                await self.recap_member(forum, member, link, hero_names)
            except Exception as e:  # an unhandled error would stop the loop for good
                print(f"recaps: member {member.id} failed: {e}")

    @recap_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    async def recap_member(self, forum, member, link, hero_names):
        # shortcut: bot-friended accounts hit the live path (10 req/h per IP, shared by all of them), so
        # their checks may get rate-limited; add DEADLOCK_API_KEY (300 req/h) when that shows up in logs
        history = await self.bot.api.get(f"/v1/players/{link['account_id']}/match-history") or []
        recap, skip_to = due_matches(history, link["linked_at"], link["last_match_id"], time.time())
        if skip_to is not None:
            db.update_link(self.bot.db, member.id, last_match_id=skip_to)
        thread = await self.usable_thread(forum, link["thread_id"]) if recap else None
        for match in recap:
            embed = build_embed(match, history, hero_names, member)
            if thread:
                await thread.send(embed=embed)
            else:
                thread = (await forum.create_thread(name=member.display_name, embed=embed)).thread
                db.update_link(self.bot.db, member.id, thread_id=thread.id)
            # saved per post so a crash mid-batch doesn't double-post
            db.update_link(self.bot.db, member.id, last_match_id=match["match_id"])

    async def usable_thread(self, forum, thread_id):
        """The Recap Thread if it can still take posts; sending unarchives it unless it is locked."""
        if thread_id is None:
            return None
        try:
            thread = forum.guild.get_thread(thread_id) or await self.bot.fetch_channel(thread_id)
        except discord.NotFound:
            return None
        if not isinstance(thread, discord.Thread) or thread.locked or thread.parent_id != forum.id:
            return None
        return thread


async def setup(bot):
    await bot.add_cog(Recaps(bot))
