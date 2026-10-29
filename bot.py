import os

import discord

client = discord.Client(intents=discord.Intents.default())


@client.event
async def on_ready():
    print(f"Logged in as {client.user} ({client.user.id})")


client.run(os.environ["DISCORD_TOKEN"])
