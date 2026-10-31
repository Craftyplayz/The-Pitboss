# Feature ideas

Ideas for new bot features, easiest first. Tick one off when it ships.

## Planned

| Done | Feature | Time | Notes |
|---|---|---|---|
| [ ] | Welcome messages | ~1 hr | No risk. Members intent is already on (bot.py). |
| [ ] | Autoroles / reaction roles | ~1–2 hrs | Use buttons, not emoji reactions. The bot's role must sit above the roles it gives. |
| [ ] | Rank roles | ~2 hrs | Give roles from each linked player's Deadlock rank. Shares code with autoroles. |
| [ ] | Logging (joins, leaves, deletes, edits, role changes) | ~2–3 hrs | Logging message text needs the Message Content intent. Keep logs in a private mod channel. |
| [ ] | Automod | ~1–2 hrs | Use Discord's built-in AutoMod for bad words, spam and invite links. Its hits feed the moderation system's warnings. |
| [ ] | Moderation system | ~1–2 days | Full plan below. |
| [ ] | Timezone tool | ~1–2 hrs | `/timezone set`, then `/time @user` shows their local time. Handy for planning games. |
| [ ] | Sticky message | ~1 hr | Keeps one message at the bottom of a busy channel by re-posting it after new messages. |
| [ ] | Music player | ~1 day + regular fixes | Needs ffmpeg and yt-dlp in Docker. YouTube breaks yt-dlp often and bans bot playback in its rules. |
| [ ] | Voice transcription | 2–3 days | Hardest. discord.py can't receive voice without an extra library, Whisper is heavy on CPU, and everyone recorded must consent. Probably skip. |

## Moderation system

Every action gets a case number, is saved in the database and is posted to a private mod log channel.

- **Warnings**: `/warn`, `/warnings @user`, `/clearwarn`. Auto-timeout after a set number of warnings in 30 days.
- **Punishments**: `/timeout`, `/kick`, `/ban`, `/tempban` (unbans itself), `/unban`. The member gets a DM with the reason.
- **Channel tools**: `/purge` (bulk delete, optionally by user), `/slowmode`, `/lock` and `/unlock`.
- **Mod notes**: private notes about a member that only mods can see.
- **History**: `/case <number>` and `/history @user` show everything on record, and a reason can be edited later.
- **Appeals**: banned members get a link or DM button to appeal, which posts to a mod channel.

## More ideas

- **LFG button**: `/lfg` posts "2 spots open" with a Join button and pings when full. Pairs with the voice hub.
- **Hero of the week**: every Monday, post the server's most-played or best win-rate hero.
- **Scrim reminders**: ping signed-up players 30 min before a scrim (check cogs/scrims.py first; it may already exist).
- **Starboard**: messages with 5 ⭐ get copied to a highlights channel.
- **Others**: tickets (private help threads), birthdays, giveaways, XP/levels. Skip polls and events; Discord has them built in.

## Before adding any of these

- Wrap the cog loading loop in bot.py so one broken cog is skipped instead of stopping the whole bot.
- If a dashboard ever writes to the database, set a busy timeout in core/db.py; the bot and web containers share one SQLite file.

## Suggested order

1. Welcome messages
2. Button roles + rank roles
3. Logging
4. Moderation system, then Discord AutoMod feeding its warnings
5. Timezone tool and sticky message
6. Music, only if regular fixes are OK
