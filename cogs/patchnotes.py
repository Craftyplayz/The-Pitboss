"""Patch Notes: post each new Deadlock update from Steam's news feed to the patch notes channel."""
import asyncio
import re
import time
from datetime import datetime, timezone

import aiohttp
import discord
from discord.ext import commands, tasks

from core import db

APP_ID = 1422450
NEWS_URL = "https://api.steampowered.com/ISteamNews/GetNewsForApp/v2/"
STEAM_IMAGES = "https://clan.akamai.steamstatic.com/images"
CHUNK = 4000  # embed descriptions max out at 4096
MAX_CHUNKS = 30  # the biggest patch so far (03-06-2026, 92k characters) is 23
HISTORY = 100  # Steam holds every announcement since 10-24-2024: 46 in total, 25 of them patches
POST_DELAY = 2  # seconds between patches while backfilling

IMG_RE = re.compile(r'\[img(?:\s+src="([^"]*)")?\](.*?)\[/img\]', re.S | re.I)
URL_RE = re.compile(r'\[url=?"?([^\]"]*)"?\](.*?)\[/url\]', re.S | re.I)
HEADING_RE = re.compile(r"\[h[1-6]\](.*?)\[/h[1-6]\]", re.S | re.I)
SECTION_RE = re.compile(r"^[*_]*\[ (.+?) \][*_]*$", re.M)  # Valve's "[ General ]" section lines
# only Steam's own tags, so link text like "[forum](...)" survives
TAG_RE = re.compile(r"\[/?(?:list|olist|quote|code|table|tr|td|th|spoiler|noparse|hr|strike|previewyoutube|"
                    r"video|carousel|url|img|h[1-6]|[bius]|p)(?:[= ][^\]]*)?\]", re.I)
SIMPLE_TAGS = {"[b]": "**", "[/b]": "**", "[i]": "*", "[/i]": "*", "[u]": "__", "[/u]": "__",
               "[s]": "~~", "[/s]": "~~", "[*]": "- ", "[p]": "", "[/p]": "\n"}


def is_patch(item):
    """Valve titles every patch "... Update ..."; hero teasers and lore posts never are."""
    return "update" in item["title"].lower()


def news_page(item):
    return f"https://store.steampowered.com/news/app/{APP_ID}/view/{item['gid']}"


def to_markdown(bbcode):
    """Steam announcement BBCode -> (Discord markdown, first image URL or None)."""
    text = bbcode.replace("{STEAM_CLAN_LOC_IMAGE}", STEAM_IMAGES).replace("{STEAM_CLAN_IMAGE}", STEAM_IMAGES)
    images = [m.group(1) or m.group(2).strip() for m in IMG_RE.finditer(text)]
    text = IMG_RE.sub("", text)  # embeds can't show images inline; the first becomes the embed image
    text = URL_RE.sub(lambda m: f"[{m.group(2)}]({m.group(1)})" if m.group(1) else m.group(2), text)
    text = HEADING_RE.sub(lambda m: f"\n### {m.group(1).strip()}\n", text)
    for tag, md in SIMPLE_TAGS.items():
        text = re.sub(re.escape(tag), md, text, flags=re.I)
    text = TAG_RE.sub("", text).replace("\\[", "[")
    text = SECTION_RE.sub(lambda m: f"### {m.group(1)}", text)
    text = re.sub(r"\n{3,}", "\n\n", re.sub(r"[ \t]+\n", "\n", text))
    return text.strip(), images[0] if images else None


def chunks(text, size=CHUNK):
    """Split on line breaks into pieces of at most `size` characters."""
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > size:  # one huge line: hard-split it
            out += [cur, line[:size]]
            cur, line = "", line[size:]
        if len(cur) + len(line) + 1 > size:
            out.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    return [c for c in out + [cur] if c.strip()] or [""]


def new_patches(items, last_date):
    """Patches newer than `last_date`, oldest first."""
    return sorted((i for i in items if is_patch(i) and i["date"] > last_date), key=lambda i: i["date"])


def patch_embeds(item):
    """One embed per CHUNK of the notes; the first carries the title, link and image."""
    text, image = to_markdown(item["contents"])
    parts = chunks(text)
    if len(parts) > MAX_CHUNKS:
        parts = parts[:MAX_CHUNKS - 1] + [f"*Too long for Discord. [Read the rest on Steam]({news_page(item)}).*"]
    embeds = []
    for n, part in enumerate(parts):
        e = discord.Embed(description=part, color=discord.Color.gold())
        if n == 0:
            e.title, e.url = item["title"][:256], news_page(item)
            e.timestamp = datetime.fromtimestamp(item["date"], timezone.utc)
            e.set_author(name="Deadlock Patch Notes")
            if image:
                e.set_image(url=image)
        if len(parts) > 1:
            e.set_footer(text=f"Part {n + 1} of {len(parts)}")
        embeds.append(e)
    return embeds


def link_view(item):
    view = discord.ui.View()
    view.add_item(discord.ui.Button(label="Read on Steam", url=news_page(item)))
    return view


class PatchNotes(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.lock = asyncio.Lock()  # loop and backfill never post at once
        self.tasks = set()  # keeps backfill tasks referenced until they finish

    async def cog_load(self):
        self.patch_loop.start()

    async def cog_unload(self):
        self.patch_loop.cancel()

    async def fetch_news(self, count):
        """Valve's latest announcements, newest first. Logged through the API log like other outside calls."""
        params = {"appid": APP_ID, "count": count, "maxlength": 0, "feeds": "steam_community_announcements"}
        started, status, body = time.monotonic(), "error", b""
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20)) as s:
                async with s.get(NEWS_URL, params=params) as resp:
                    status, body = resp.status, await resp.read()
                    resp.raise_for_status()
                    return (await resp.json())["appnews"]["newsitems"]
        finally:
            self.bot.api.log(NEWS_URL, params, status, started, len(body), body)

    async def post(self, channel, item):
        embeds = patch_embeds(item)
        msg = await channel.send(embed=embeds[0], view=link_view(item))
        if len(embeds) == 1:
            return
        # the rest goes in a thread so a big patch doesn't bury the channel
        thread = await msg.create_thread(name=item["title"][:100])
        for e in embeds[1:]:
            await thread.send(embed=e)
        await thread.send(view=link_view(item))

    def backfill(self):
        """Post every patch Steam has, oldest first, e.g. into a newly picked channel."""
        db.set_setting(self.bot.db, "patch_notes_last", 0)
        task = asyncio.create_task(self.check())
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    @tasks.loop(minutes=10)
    async def patch_loop(self):
        await self.check()

    async def check(self):
        async with self.lock:
            await self.post_new()

    async def post_new(self):
        channel_id = db.get_setting(self.bot.db, "patch_notes_id")
        channel = self.bot.get_channel(int(channel_id)) if channel_id else None
        if not isinstance(channel, discord.TextChannel):
            return
        last = db.get_setting(self.bot.db, "patch_notes_last")
        try:
            # 0 means backfill, which needs the whole history, not just the latest few
            items = await self.fetch_news(HISTORY if last == "0" else 10)
        except (aiohttp.ClientError, TimeoutError, KeyError, ValueError) as e:
            print(f"patch notes: Steam news failed: {e}")
            return
        if last is None:  # first run: start from now instead of posting old patches
            db.set_setting(self.bot.db, "patch_notes_last", max((i["date"] for i in items), default=0))
            return
        for n, item in enumerate(new_patches(items, int(last))):
            if n:
                await asyncio.sleep(POST_DELAY)
            try:
                await self.post(channel, item)
            except discord.HTTPException as e:
                print(f"patch notes: posting {item['gid']} failed: {e}")
            # advanced even on failure: a half-posted patch retried every 10 minutes would repeat forever
            db.set_setting(self.bot.db, "patch_notes_last", item["date"])

    @patch_loop.before_loop
    async def before_loop(self):
        await self.bot.wait_until_ready()


async def setup(bot):
    await bot.add_cog(PatchNotes(bot))
