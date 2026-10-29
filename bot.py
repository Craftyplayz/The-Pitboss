import os
from pathlib import Path

import discord
from discord.ext import commands

from core import db
from core.api import DeadlockAPI

GUILD = discord.Object(id=int(os.environ["GUILD_ID"]))

intents = discord.Intents.default()
intents.members = True  # needed for on_member_remove (privileged: enable in Developer Portal)


class Pitboss(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.db = db.connect(os.environ.get("DB_PATH", "data/pitboss.db"))
        self.api = DeadlockAPI(os.environ.get("DEADLOCK_API_KEY") or None)

    async def setup_hook(self):
        await self.api.start()
        for path in sorted(Path(__file__).parent.joinpath("cogs").glob("*.py")):
            if not path.name.startswith("_"):
                await self.load_extension(f"cogs.{path.stem}")
        # one server: register commands to it so they appear instantly
        self.tree.copy_global_to(guild=GUILD)
        await self.tree.sync(guild=GUILD)

    async def close(self):
        await self.api.close()
        await super().close()

    async def on_ready(self):
        print(f"Logged in as {self.user} ({self.user.id})")


Pitboss().run(os.environ["DISCORD_TOKEN"])
