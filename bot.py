import os
from pathlib import Path

import discord
from discord.ext import commands

from core import db
from core.api import DeadlockAPI
from core.shared import SITE_URL

GUILD = discord.Object(id=int(os.environ["GUILD_ID"]))

intents = discord.Intents.default()
intents.members = True  # needed for on_member_remove (privileged: enable in Developer Portal)

# the bot profile's About Me; links in it are clickable, unlike in the status line
ABOUT = f"Watching your Deadlock matches.\n\nFull stats: {SITE_URL}\nRun /help for a list of commands."


class Pitboss(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix=commands.when_mentioned, intents=intents,
                         activity=discord.CustomActivity(name="Always watching"))
        db_path = os.environ.get("DB_PATH", "data/pitboss.db")
        self.db = db.connect(db_path)
        # every API call, forever, one JSON line each; next to the database so it lives on the data volume
        self.api = DeadlockAPI(os.environ.get("DEADLOCK_API_KEY") or None, log_path=Path(db_path).parent / "api-bot.jsonl")

    async def setup_hook(self):
        await self.api.start()
        try:
            app = await self.application_info()
            if app.description != ABOUT:
                await app.edit(description=ABOUT)
        except discord.HTTPException as e:  # cosmetic; never block startup on it
            print(f"Couldn't set the About Me: {e}")
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
