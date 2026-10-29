import discord
from discord import app_commands
from discord.ext import commands

from core.shared import WINDOW_DAYS, WINDOW_MIN_MATCHES

# (title, [(field name, field value)]). Admin-only commands (/setup) are left out on purpose.
PAGES = [
    ("Getting started", [
        ("What The Pitboss does",
         "Shows Deadlock stats for this server: your Profile, Leaderboards between members, "
         "game-wide hero and item stats, and an automatic Match Recap after every game you play."),
        ("/link player:",
         "Link your Deadlock account. Start typing your Steam name and pick yourself from the list, "
         "or paste your Steam ID or steamcommunity.com profile URL. You'll see a card with the account's "
         "profile picture: press That's me to link it. Linking again replaces your old account."),
        ("/unlink", "Remove your Link. Your recaps stop and your recap post is archived."),
    ]),
    ("Match Recaps", [
        ("Automatic, no command needed",
         "Once you're linked, the bot checks for your finished Matches every 5 minutes and posts a recap "
         "in your own post in the recap forum. Recaps can take 5–30 minutes to appear after a Match."),
        ("What a recap shows",
         "K/D/A, souls, damage, healing, accuracy, crits, farm, where your souls came from, your final build, "
         "both teams' scoreboard and a souls-over-time graph."),
        ("Your past Matches",
         "When you first link, every Match from the last 30 days gets a recap too. They post a few at a time, "
         "so a busy month can take an hour or so to fill in."),
    ]),
    ("Your stats", [
        ("/profile member:",
         f"Your last {WINDOW_DAYS} days: record, KDA, souls and damage per minute, accuracy, time played, "
         "your last 10 results, top heroes, best teammates, personal records and a trend graph "
         "(rank progress if you play ranked, win rate if not). Pick a member to see their Profile instead."),
    ]),
    ("Leaderboards", [
        ("/leaderboard metric: hero:",
         "Ranks this server's linked members. You see the top 10, plus your own spot if you're lower."),
        ("Metrics",
         "**Rank**: in-game rank.\n**Win rate**, **KDA**, **Matches played**, **Souls per minute**.\n"
         "**Rank Climb**: rank progress gained."),
        ("Rules",
         f"Everything except Rank covers the last {WINDOW_DAYS} days, and you need at least "
         f"{WINDOW_MIN_MATCHES} Matches to appear. Add a hero to rank only games on that hero (not for Rank)."),
    ]),
    ("Meta", [
        ("Game-wide stats", "Covers every Deadlock player over the last 7 days, not just this server."),
        ("/meta heroes sort: rank:",
         "Every hero's win rate, pick rate and Matches. Optionally only games at or above a rank."),
        ("/meta hero hero:", "One hero: win rate, best items, best and worst matchups, and best teammates."),
        ("/meta items hero:", "The items with the highest win rate, for everyone or for one hero."),
        ("/build hero: rank:",
         "What players buy on a hero in each phase of the match (0–9, 9–20, 20–30 and 30+ minutes), "
         "with how often each item is bought and its win rate."),
    ]),
    ("Scrims", [
        ("/scrim",
         "Opens a scrim-<number> channel with a Join button. Everyone who wants to play presses Join, "
         "then the creator presses Start scrim and picks random teams or lets players pick their own."),
        ("The lobby",
         "The bot makes a Deadlock custom lobby and posts its code. Join it in game and take your team's side "
         "within 15 minutes; the creator can press New code if it runs out."),
        ("Results",
         "Once the Match is over, every player's stats are saved, posted to the scrim log channel and "
         "listed in the Scrims section of the website."),
    ]),
]


def page_embed(i):
    title, fields = PAGES[i]
    embed = discord.Embed(title=f"The Pitboss help · {title}", color=discord.Color.gold())
    for name, value in fields:
        embed.add_field(name=name, value=value, inline=False)
    embed.set_footer(text=f"Page {i + 1} of {len(PAGES)}")
    return embed


class HelpView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=300)
        self.page = 0
        self.sync()

    def sync(self):
        self.prev.disabled = self.page == 0
        self.next.disabled = self.page == len(PAGES) - 1

    async def show(self, interaction, page):
        self.page = page
        self.sync()
        await interaction.response.edit_message(embed=page_embed(page), view=self)

    @discord.ui.button(label="Back", style=discord.ButtonStyle.secondary)
    async def prev(self, interaction, button):
        await self.show(interaction, self.page - 1)

    @discord.ui.button(label="Next", style=discord.ButtonStyle.primary)
    async def next(self, interaction, button):
        await self.show(interaction, self.page + 1)


class Help(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(description="How to use The Pitboss")
    async def help(self, interaction: discord.Interaction):
        # ephemeral: only the asker sees it, so the buttons can't be pressed by anyone else
        await interaction.response.send_message(embed=page_embed(0), view=HelpView(), ephemeral=True)


async def setup(bot):
    await bot.add_cog(Help(bot))
