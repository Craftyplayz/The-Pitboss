"""Match Recaps: post each Linked Member's finished Matches to their Recap Thread."""
import asyncio
import time
from datetime import datetime, timezone

import discord
from discord.ext import commands, tasks

from core import db
from core.api import APIError
from core.insights import match_insights
from cogs._item_emojis import ItemEmojis
from cogs._recap_embed import build_full_embed
from core.match import final_build, find_player, scoreboard, souls_sources, souls_timeline
from core.recap_images import scoreboard_image, souls_image
from core.shared import site_links, won
from core.trophies import match_stats

MAX_AGE = 24 * 3600  # a Match after the Link missed for longer than this gets no recap
BACKFILL = 30 * 86400  # on link, Matches from this long before it get recaps too
RECAPS_PER_RUN = 10  # per Member per loop run, so a backfill drips out instead of flooding Discord
POST_DELAY = 2  # seconds between posts
META_WAIT = 30 * 60  # how long a new Match waits for full metadata before getting the simple recap
STATS_PER_RUN = 5  # trophy-stat metadata fetches per Member per loop run, so a backfill drips in
NO_META_AFTER = 2 * 86400  # a Match still without metadata this long after it ended is saved as having none


def match_end(match):
    return match["start_time"] + match["match_duration_s"]


def due_matches(history, linked_at, last_match_id, now):
    """Return (Matches to recap oldest first, match_id to advance past without posting, or None).

    Backfill Matches (ended up to BACKFILL before the Link) always get a recap. Matches after the
    Link only do within MAX_AGE; the skip id is the newest one older than that.
    """
    fresh = sorted(
        (m for m in history
         if match_end(m) > linked_at - BACKFILL and (last_match_id is None or m["match_id"] > last_match_id)),
        key=lambda m: m["match_id"],
    )
    backfill = [m for m in fresh if match_end(m) <= linked_at]
    after = [m for m in fresh if match_end(m) > linked_at]
    recap = backfill + [m for m in after if now - match_end(m) <= MAX_AGE]
    recap.sort(key=lambda m: m["match_id"])
    # advancing past a skipped Match while backfill is pending could jump over unposted backfill
    skip_to = None if backfill else max(
        (m["match_id"] for m in after if now - match_end(m) > MAX_AGE), default=None)
    return recap, skip_to


def build_embed(match, history, heroes, member):
    """Fallback recap from the match-history entry alone, styled like the full recap."""
    win = won(match)
    hero_names = {i: h["name"] for i, h in heroes.items()}
    hero = heroes.get(match["hero_id"], {})
    duration = match["match_duration_s"]
    minutes = max(duration / 60, 1)
    lines = match_insights(match, history, hero_names) + ["-# Full stats weren't available for this Match."]
    embed = discord.Embed(
        title=f"{hero.get('name', 'Hero ' + str(match['hero_id']))} · {'Win' if win else 'Loss'} · {duration // 60}:{duration % 60:02d}",
        description="\n".join(lines),
        color=discord.Color.green() if win else discord.Color.red(),
        timestamp=datetime.fromtimestamp(match_end(match), timezone.utc),
    )
    if icon := (hero.get("images") or {}).get("icon_image_small"):
        embed.set_thumbnail(url=icon)
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    kda = (match["player_kills"] + match["player_assists"]) / max(match["player_deaths"], 1)
    add = embed.add_field
    add(name="K / D / A", value=f"{match['player_kills']} / {match['player_deaths']} / {match['player_assists']} · KDA {kda:.1f}")
    add(name="Souls", value=f"{match['net_worth']:,} · {match['net_worth'] / minutes:,.0f}/min")
    add(name="Level", value=str(match["hero_level"]))
    add(name="Farm", value=f"{match['last_hits']} LH · {match['denies']} DN")
    if match.get("ranked_delta"):
        add(name="Rank change", value=f"{match['ranked_delta']:+d}")
    embed.set_footer(text=f"Match {match['match_id']}")
    return embed


def add_site_links(post, match, account_id, hero_name):
    """Point the recap at the website: the author name opens the profile, the title opens the match,
    link buttons open the home page, leaderboards and hero. Author names and buttons stay white; the title shows blue."""
    links = site_links(account_id, match["match_id"], match["hero_id"])
    embed = post["embeds"][0] if "embeds" in post else post["embed"]
    embed.set_author(name=embed.author.name, icon_url=embed.author.icon_url, url=links["player"])
    embed.url = links["match"]
    view = discord.ui.View(timeout=None)
    for label, key in (("The Pitboss", "home"), ("Leaderboards", "leaderboards"), (f"{hero_name} stats", "hero")):
        view.add_item(discord.ui.Button(label=label, url=links[key]))
    post["view"] = view
    return post


def post_title(post):
    embeds = post.get("embeds") or [post.get("embed")]
    return (embeds[0].title if embeds and embeds[0] else None) or "Match"


LATEST_LABEL = "Jump to latest recap"


def header_view(first, url):
    """The first message's existing link buttons, plus one jump button to the newest recap (replacing any old one)."""
    view = discord.ui.View.from_message(first, timeout=None)
    for item in [i for i in view.children if getattr(i, "label", None) == LATEST_LABEL]:
        view.remove_item(item)
    view.add_item(discord.ui.Button(label=LATEST_LABEL, url=url, emoji="⬇️"))
    return view


async def update_header(thread, latest, title):
    """Point the Recap Thread's first message at the newest recap: forum posts open at the top, not the bottom.
    Only its text line and buttons change (a white link button, no blue link); its embeds and images stay."""
    if latest.id == thread.id:  # the newest recap is the first message itself: nothing to jump to
        return
    try:
        first = await thread.fetch_message(thread.id)  # a forum post's first message shares the thread's id
        await first.edit(content=f"**Latest recap:** {title}", view=header_view(first, latest.jump_url))
    except discord.HTTPException as e:  # e.g. the first message was deleted
        print(f"recaps: header update in {thread.id} failed: {e}")


class Recaps(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.emojis = ItemEmojis(bot)
        self.locks = {}  # member_id -> Lock, so the loop and recap_now never check one Member at once
        self.tasks = set()  # keeps recap_now tasks referenced until they finish

    async def cog_load(self):
        self.recap_loop.start()

    async def cog_unload(self):
        self.recap_loop.cancel()

    async def context(self):
        """(recap forum, (heroes, items, ranks)), or None when recaps can't run right now."""
        forum_id = db.get_setting(self.bot.db, "recap_forum_id")
        forum = self.bot.get_channel(int(forum_id)) if forum_id else None
        if not isinstance(forum, discord.ForumChannel):
            return None
        try:
            return forum, (await self.bot.api.heroes(), await self.bot.api.items(), await self.bot.api.ranks())
        except APIError as e:
            print(f"recaps: asset lists failed: {e}")
            return None

    async def check_member(self, forum, member_id, assets):
        async with self.locks.setdefault(member_id, asyncio.Lock()):
            # re-read inside the lock: the other path may have just posted and moved last_match_id
            link = db.get_link(self.bot.db, member_id)
            member = forum.guild.get_member(member_id)
            if link is None or member is None:  # unlinked, or left the server (the link cog removes the Link)
                return
            try:
                await self.recap_member(forum, member, link, assets)
            except Exception as e:  # an unhandled error would stop the loop for good
                print(f"recaps: member {member_id} failed: {e}")

    def recap_now(self, member_id):
        """Check one Member right away, e.g. just after they link, instead of waiting for the loop."""
        async def run():
            if ctx := await self.context():
                await self.check_member(ctx[0], member_id, ctx[1])
        task = asyncio.create_task(run())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    @tasks.loop(minutes=5)
    async def recap_loop(self):
        if not (ctx := await self.context()):
            return
        forum, assets = ctx
        for link in db.all_links(self.bot.db):
            await self.check_member(forum, link["member_id"], assets)

    @recap_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()

    async def recap_member(self, forum, member, link, assets):
        heroes = assets[0]
        hero_names = {i: h["name"] for i, h in heroes.items()}
        # shortcut: bot-friended accounts hit the live path (10 req/h per IP, shared by all of them), so
        # their checks may get rate-limited; add DEADLOCK_API_KEY (300 req/h) when that shows up in logs
        history = await self.bot.api.get(f"/v1/players/{link['account_id']}/match-history") or []
        recap, skip_to = due_matches(history, link["linked_at"], link["last_match_id"], time.time())
        if skip_to is not None:
            db.update_link(self.bot.db, member.id, last_match_id=skip_to)
        recap = recap[:RECAPS_PER_RUN]
        thread = await self.usable_thread(forum, link["thread_id"]) if recap else None
        latest = None  # (message, title) of the newest recap posted this run
        for match in recap:
            # insights compare against earlier Matches only, so backfilled recaps don't see the future
            earlier = [m for m in history if m["match_id"] < match["match_id"]]
            post = await self.full_post(match, link["account_id"], earlier, assets, member)
            if post is None:
                if time.time() - match_end(match) < META_WAIT:
                    break  # metadata not ready yet; retry next run so the recap gets the full layout
                post = {"embed": build_embed(match, earlier, heroes, member)}
            add_site_links(post, match, link["account_id"], hero_names.get(match["hero_id"], "Hero"))
            if thread:
                await asyncio.sleep(POST_DELAY)
                latest = await thread.send(**post), post_title(post)
            else:
                created = await forum.create_thread(name=member.display_name, **post)
                thread, latest = created.thread, (created.message, post_title(post))
                db.update_link(self.bot.db, member.id, thread_id=thread.id)
            # saved per post so a crash mid-batch doesn't double-post
            db.update_link(self.bot.db, member.id, last_match_id=match["match_id"])
        if latest:
            await update_header(thread, *latest)
        await self.save_stats(link, history, assets[1])

    async def save_stats(self, link, history, items):
        """Save trophy stats for Matches since the Link (and its Backfill) that recaps didn't already cover."""
        saved = db.saved_match_ids(self.bot.db, link["account_id"])
        todo = sorted((m for m in history if match_end(m) > link["linked_at"] - BACKFILL and m["match_id"] not in saved),
                      key=lambda m: -m["match_id"])
        for m in todo[:STATS_PER_RUN]:
            meta = await self.bot.api.get(f"/v1/matches/{m['match_id']}/metadata")
            stats = match_stats(meta, link["account_id"], items) if meta else None
            if stats is None and time.time() - match_end(m) < NO_META_AFTER:
                continue  # metadata can lag; try again next run
            db.save_match_stats(self.bot.db, link["account_id"], m["match_id"], m["start_time"], stats)

    async def full_post(self, match, account_id, earlier, assets, member):
        """Send kwargs for the full recap with souls graph, or None if the Match metadata isn't available."""
        heroes, items, ranks = assets
        try:
            meta = await self.bot.api.get(f"/v1/matches/{match['match_id']}/metadata")
        except APIError as e:
            print(f"recaps: metadata for {match['match_id']} failed: {e}")
            return None
        me = find_player(meta, account_id) if meta else None
        if me is None:
            return None
        db.save_match_stats(self.bot.db, account_id, match["match_id"], match["start_time"], match_stats(meta, account_id, items))
        emojis ={i["id"]: await self.emojis.get(i) for i in final_build(me, items)}
        embed = build_full_embed(match, meta, account_id, earlier, heroes, items, ranks, emojis, member)
        embed.set_image(url="attachment://souls.png")
        players, hero_names = meta["match_info"]["players"], {i: h["name"] for i, h in heroes.items()}
        # a second image-only embed, since one embed holds one image
        board = discord.Embed(color=embed.color).set_image(url="attachment://scoreboard.png")
        return {"embeds": [embed, board], "files": [
            discord.File(souls_image(souls_timeline(me), souls_sources(me["stats"][-1])), "souls.png"),
            discord.File(scoreboard_image(scoreboard(players, me, hero_names, won(match))), "scoreboard.png")]}

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
