<p align="center">
  <img src="static/pitboss-512.png" alt="The Pitboss" width="160">
</p>

<h1 align="center">The Pitboss</h1>

<p align="center">
  A Discord bot and website for a Deadlock community server.<br>
  Match recaps, profiles, leaderboards, game-wide meta, scrims and patch notes.
</p>

<p align="center">
  <a href="CHANGELOG.md"><b>📜 Changelog / patch notes</b></a> ·
  <a href="https://pitboss.craftyplayz.com">🌐 Website</a> ·
  <a href="#commands">⌨️ Commands</a>
</p>

---

## What's new?

Every update to The Pitboss is listed in **[CHANGELOG.md](CHANGELOG.md)**, newest first. The bot also posts the latest changes in the server's bot updates channel after each restart.

## Features

### 🎮 Match Recaps
Link your Deadlock account and the bot posts a recap after every match you play, in your own post in the recap forum. No command needed.

- K/D/A, souls, damage, healing, accuracy, crits and farm
- Where your souls came from, your final build and both teams' scoreboard
- A souls-over-time graph
- When you first link, every match from the last 30 days gets a recap too

Recaps can take 5 to 30 minutes to appear after a match.

### 📊 Profiles
`/profile` shows your last 30 days: record, KDA, souls and damage per minute, accuracy, time played, last 10 results, top heroes, best teammates, personal records and a trend graph.

The website profile covers your **whole** match history, with trophies, mates and rivals, hero breakdown, best and worst games and more.

### 🏆 Leaderboards
`/leaderboard` ranks the server's linked members by rank, win rate, KDA, matches played, souls per minute or Rank Climb. Rank a single hero or all of them. You need at least 10 matches in the last 30 days to appear (except for Rank).

### 📈 Meta
Game-wide stats for every Deadlock player over the last 7 days, not just this server:

- `/meta heroes`: every hero's win rate, pick rate and matches
- `/meta hero`: one hero's best items, matchups and teammates
- `/meta items`: items with the highest win rate
- `/build`: what players buy on a hero in each phase of the match

### ⚔️ Scrims
`/scrim` opens a sign-up channel and team voice channels. Players press Join, teams are split randomly or picked by players, and the bot makes a Deadlock custom lobby and posts the code. Once the match is over, everyone's stats are saved, posted to the scrim log and shown on the website.

### 📰 Patch Notes
New Deadlock patch notes are taken from Steam and posted in the patch notes channel. Picking the channel for the first time posts every past patch, oldest first.

### 🌐 Website
A dashboard at [pitboss.craftyplayz.com](https://pitboss.craftyplayz.com) with Overview, Leaderboards, Matches, Heroes and Scrims tabs, plus a full profile and trophies page for every linked player.

## Commands

| Command | What it does |
|---|---|
| `/help` | How to use The Pitboss |
| `/link player:` | Link your Deadlock account (Steam name, Steam ID or profile URL) |
| `/unlink` | Remove your link. Recaps stop and your recap post is archived |
| `/profile member:` | Your Profile, or another member's |
| `/leaderboard metric: hero:` | Rank linked members by a stat |
| `/meta heroes sort: rank:` | Win rate and pick rate of every hero |
| `/meta hero hero:` | Items, matchups and teammates for one hero |
| `/meta items hero:` | Best items by win rate |
| `/build hero: rank:` | What to buy on a hero in each phase of the match |
| `/scrim` | Start a scrim with sign-up and team voice channels |

**Admin only** (needs Manage Server):

| Command | What it does |
|---|---|
| `/setup` | Pick the recap forum, scrim log, patch notes, bot updates and welcome channels, and the voice hub. Leave all options empty to see the current setup |
| `/welcome message:` | Change the welcome embed's main text (design the whole embed in the control panel). Leave it empty to see a preview |
| `/rebuild-recaps` | Delete every Recap Thread and post all recaps again |

## Self-hosting

The Pitboss is built for one Discord server. It runs as four services that share one SQLite database: the **bot** (`bot.py`), the **website** (`web.py`), the **control panel**, The Pitstop (`dash.py`), where admins log in with Discord and change the bot's settings, and the **transcriber** (`transcriber.py`), which turns recorded voice calls into text.

### Requirements
- Docker and Docker Compose, **or** Python 3.12
- A Discord bot token with the **Server Members**, **Message Content** and **Presence** privileged intents turned on in the Developer Portal (Bot page)
- For the Server Log's audit entries (who kicked, banned or deleted what), give the bot the **View Audit Log** permission
- For voice recording (`/record`), give the bot **Connect** and **Set Voice Channel Status**. The transcriber runs speech to text on the CPU; a 6-core CPU keeps up with live calls on the default model
- For role menus, give the bot **Manage Roles** and put its role above the roles it hands out (plus **Manage Messages** so emoji menus can tidy reactions)

### 1. Configure
Copy `.env.example` to `.env` and fill it in:

| Variable | Needed | What it is |
|---|---|---|
| `DISCORD_TOKEN` | Yes | Your bot's token |
| `GUILD_ID` | Yes | Your server's ID (right-click the server > Copy Server ID, needs Developer Mode) |
| `DEADLOCK_API_KEY` | No | Raises [deadlock-api.com](https://deadlock-api.com) rate limits |
| `SITE_URL` | No | The website's public address. Recaps link here |
| `ADMIN_PASSWORD` | No | Password for `/admin`, the API call log viewer. Leave empty to turn it off |
| `DISCORD_CLIENT_ID` | For the control panel | Developer Portal > your app > OAuth2 > Client ID |
| `DISCORD_CLIENT_SECRET` | For the control panel | Developer Portal > your app > OAuth2 > Client Secret |
| `DASH_URL` | No | The control panel's public address (default `https://pitstop.craftyplayz.com`). Add `<DASH_URL>/callback` as a redirect in Developer Portal > OAuth2 |

### 2. Run with Docker (recommended)
```sh
docker compose up -d --build
```
The website listens on port `8642` and the control panel on `8643`. Put a reverse proxy with HTTPS in front of both. Data is kept in the `pitboss-data` volume.

### 2b. Or run with Python
```sh
pip install -r requirements.txt
python bot.py
python web.py
python dash.py
python transcriber.py
```
The database is stored at `data/pitboss.db` (change it with `DB_PATH`). Files the Server Log saves (attachments, avatars) go in `data/logfiles/`, voice recordings in `data/voice/` and speech-to-text models in `data/whisper/`.

### 3. Set up the channels
In Discord, run `/setup` and pick the recap forum, scrim log, patch notes, bot updates and welcome channels, and the voice hub. Change the welcome message with `/welcome`.

## Running the tests
```sh
python -m unittest
```

## Project layout

| Path | What's in it |
|---|---|
| `bot.py` | Starts the Discord bot |
| `web.py`, `admin.py` | The website and the `/admin` page |
| `dash.py` | The control panel: Discord login and bot settings |
| `transcriber.py` | Turns recorded voice clips into text |
| `cogs/` | Bot commands and background tasks (recaps, scrims, patch notes, bot updates, the Server Log, role menus) |
| `core/` | Shared code: Deadlock API client, database, stats, graphs, trophies |
| `pages/`, `static/` | Website page and images |
| `tests/` | Unit tests |
| `docs/` | Design decisions (ADRs) and plans |
| [`GLOSSARY.md`](GLOSSARY.md) | What words like Link, Match Recap and Rank Climb mean |
| [`CHANGELOG.md`](CHANGELOG.md) | Every version and what changed |

## Data sources
- Match and player stats: [deadlock-api.com](https://deadlock-api.com)
- Patch notes: Steam's news feed for Deadlock

The Pitboss is a fan project and is not affiliated with Valve.
