"""Item icons as Discord application emojis, uploaded the first time an item shows up in a recap."""
import aiohttp
import discord


class ItemEmojis:
    def __init__(self, bot):
        self.bot = bot
        self.by_name = None  # emoji name -> "<:name:id>"

    async def get(self, item):
        """Inline emoji text for an item asset dict, or "" if it can't be made."""
        if self.by_name is None:
            self.by_name = {e.name: str(e) for e in await self.bot.fetch_application_emojis()}
        name = f"i{item['id']}"
        if name not in self.by_name:
            url = item.get("shop_image_small") or item.get("image")
            if not url:
                return ""
            try:
                async with aiohttp.ClientSession() as s, s.get(url) as resp:
                    resp.raise_for_status()
                    image = await resp.read()
                emoji = await self.bot.create_application_emoji(name=name, image=image)
            except (aiohttp.ClientError, discord.HTTPException) as e:
                print(f"item emoji {name} failed: {e}")
                return ""
            self.by_name[name] = str(emoji)
        return self.by_name[name]
