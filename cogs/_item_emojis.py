"""Item and hero icons as Discord application emojis, uploaded the first time each one is shown."""
import asyncio

import aiohttp
import discord

from core.shared import item_icon


class ItemEmojis:
    # shared by every instance (recaps, meta), so two cogs never upload the same emoji
    by_name = None  # emoji name -> "<:name:id>"
    lock = asyncio.Lock()

    def __init__(self, bot):
        self.bot = bot

    async def get(self, item):
        """Inline emoji text for an item asset dict, or "" if it can't be made."""
        return await self.image(f"i{item['id']}", item_icon(item))

    async def hero(self, hero):
        """Inline emoji text for a hero asset dict, or ""."""
        return await self.image(f"h{hero['id']}", (hero.get("images") or {}).get("icon_image_small"))

    async def image(self, name, url):
        async with ItemEmojis.lock:
            if ItemEmojis.by_name is None:
                ItemEmojis.by_name = {e.name: str(e) for e in await self.bot.fetch_application_emojis()}
            if name in ItemEmojis.by_name:
                return ItemEmojis.by_name[name]
            if not url:
                return ""
            try:
                async with aiohttp.ClientSession() as s, s.get(url) as resp:
                    resp.raise_for_status()
                    image = await resp.read()
                emoji = await self.bot.create_application_emoji(name=name, image=image)
            except (aiohttp.ClientError, discord.HTTPException) as e:
                print(f"emoji {name} failed: {e}")
                return ""
            ItemEmojis.by_name[name] = str(emoji)
            return ItemEmojis.by_name[name]
