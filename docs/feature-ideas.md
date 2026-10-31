# Feature ideas

Ideas for new bot features, easiest first. Tick one off when it ships.

## Planned

| Done | Feature | Time | Notes |
|---|---|---|---|
| [ ] | Welcome messages | ~1 hr | No risk. Members intent is already on (bot.py). |
| [ ] | Autoroles / reaction roles | ~1–2 hrs | Use buttons, not emoji reactions. The bot's role must sit above the roles it gives. |
| [ ] | Rank roles | ~2 hrs | Give roles from each linked player's Deadlock rank. Shares code with autoroles. |
| [ ] | Logging (joins, leaves, deletes, edits, role changes) | ~2–3 hrs | Logging message text needs the Message Content intent. Keep logs in a private mod channel. |
| [ ] | Automod | ~1–2 hrs | Use Discord's built-in AutoMod for bad words, spam and invite links. Only build what it can't do, like "3 warnings, then timeout". |
| [ ] | Music player | ~1 day + regular fixes | Needs ffmpeg and yt-dlp in Docker. YouTube breaks yt-dlp often and bans bot playback in its rules. |
| [ ] | Voice transcription | 2–3 days | Hardest. discord.py can't receive voice without an extra library, Whisper is heavy on CPU, and everyone recorded must consent. Probably skip. |

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
4. Discord AutoMod, plus a bot-side warn system if still needed
5. Music, only if regular fixes are OK
