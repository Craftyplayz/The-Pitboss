# Feature ideas

Ideas for new bot features, in the order to build them. Tick one off when it ships.

Order rules: safety first, then the cheap features members see on day one, then the moderation stack while the server is small, then features that reuse earlier ones (a scheduler, the leveling data, image cards, voice playback), and the heavy or fragile ones last.

## Phase 0: safety (do first)

| Done | # | Feature | Time | Notes |
|---|---|---|---|---|
| [x] | 0 | Skip broken cogs | ~10 min | Wrap the cog loading loop in bot.py so one broken cog is skipped instead of stopping the whole bot. |
| [x] | 0b | Control panel | ~3 hrs | dash.py: Discord login, edit channels and the welcome message. Add each new feature's settings here as it ships. |

If a dashboard ever writes to the database, set a busy timeout in core/db.py first; the bot and web containers share one SQLite file.

## Phase 1: new members

| Done | # | Feature | Time | Notes |
|---|---|---|---|---|
| [x] | 1 | Welcome messages | ~1 hr | No risk. Members intent is already on (bot.py). |
| [x] | 2 | Role menus (reaction roles) | ~6 hrs | Full plan below. |
| [ ] | 3 | Rank roles | ~2 hrs | Give roles from each linked player's Deadlock rank. Reuses the button-role code. |

## Phase 2: moderation

| Done | # | Feature | Time | Notes |
|---|---|---|---|---|
| [x] | 4 | Logging (joins, leaves, deletes, edits, role changes) | ~2–3 hrs | Turns on the Message Content intent, which leveling, starboard and translation need later. Sets up the private mod log channel. |
| [ ] | 5 | Moderation system | ~1–2 days | Full plan below. Posts to the mod log channel from #4. |
| [ ] | 6 | Automod | ~1–2 hrs | Use Discord's built-in AutoMod for bad words, spam and invite links. Its hits feed the warnings from #5. |
| [ ] | 7 | Tickets | ~2–3 hrs | Private help threads between a member and the mods. |

## Phase 3: utility and scheduling

| Done | # | Feature | Time | Notes |
|---|---|---|---|---|
| [ ] | 8 | Sticky message | ~1 hr | Keeps one message at the bottom of a busy channel by re-posting it after new messages. |
| [ ] | 9 | Timezone tool | ~1–2 hrs | `/timezone set`, then `/time @user` shows their local time. Handy for planning games. |
| [ ] | 10 | Event signups | ~2–3 hrs | `/event` posts an event with Going / Maybe buttons and pings everyone who signed up before it starts. Builds the reminder code #11, #12 and #14 reuse. |
| [ ] | 11 | Scrim reminders | ~1–2 hrs | Scrims have no start time yet (core/db.py). Add an optional one, then reuse the reminders from #10. |
| [ ] | 12 | Birthday roles | ~1–2 hrs | `/birthday set`. On the day: a special role for 24 hours and a shoutout. Uses the scheduler from #10. |
| [ ] | 13 | LFG button | ~2 hrs | `/lfg` posts "2 spots open" with a Join button and pings when full. Pairs with the voice hub. |

## Phase 4: leveling and community

| Done | # | Feature | Time | Notes |
|---|---|---|---|---|
| [ ] | 14 | Leveling | ~3–4 hrs | XP for chatting (with a cooldown so spam doesn't count), `/rank` card, leaderboard, role rewards at set levels. |
| [ ] | 15 | Voice XP | ~1 hr | Time in voice earns XP, but not when alone or muted. |
| [ ] | 16 | Level-up cards | ~2 hrs | Image card with the member's avatar and new level. Reuse the image code in core/recap_images.py. |
| [ ] | 17 | Activity heatmap | ~3 hrs | Website page showing which hours and days the server is most active. Uses the message data leveling collects. |
| [ ] | 18 | Starboard | ~1–2 hrs | Messages with 5 ⭐ get copied to a highlights channel. |
| [ ] | 19 | Hero of the week | ~1–2 hrs | Every Monday, post the server's most-played or best win-rate hero. Uses stats the bot already pulls. |
| [ ] | 20 | Marriage / friends | ~2 hrs | `/marry @user` (they accept with a button), `/divorce`, partner shown on a profile card (reuses #16's card code). |

## Phase 5: games and extras

| Done | # | Feature | Time | Notes |
|---|---|---|---|---|
| [ ] | 21 | Wordle clone | ~3 hrs | One daily word for the whole server, guesses with coloured squares, results shared without spoilers. |
| [ ] | 22 | Giveaways | ~2 hrs | Enter with a button, a random winner is picked when the timer ends. |
| [ ] | 23 | Auto-translation | ~3–4 hrs | Full plan below. Needs a translation service account. |

## Phase 6: voice (heavy, do last)

| Done | # | Feature | Time | Notes |
|---|---|---|---|---|
| [ ] | 24 | Music player | ~1 day + regular fixes | Needs ffmpeg and yt-dlp in Docker. YouTube breaks yt-dlp often and bans bot playback in its rules. Builds the voice setup #25 reuses. |
| [ ] | 25 | Voice transcription | 2–3 days | Hardest. discord.py can't receive voice without an extra library (discord-ext-voice-recv), Whisper is heavy on CPU, and everyone recorded must consent (announce it when recording starts). |
| [ ] | 26 | Voice summaries | ~2 hrs | After a call, post a short AI summary of the transcript. Needs #25. |

## Role menus (reaction roles)

Admins build a role menu in the Welcome & Roles tab and post it; members click to get or drop roles.

**Already in place:** the embed for each menu reuses `core/embeds.py` and the panel's `embed_editor()` (the same editor and live preview as the welcome message; give each menu its own field prefix).

**How members pick** (chosen per menu):
- **Buttons** (default): one button per role, click to toggle. Works for everyone, needs no extra permissions, and the bot replies privately with what changed.
- **Dropdown**: one list, good for 6+ roles (up to 25).
- **Emoji reactions**: the classic style. Least reliable (reactions made while the bot is offline are missed), so offered but not the default.

**Options per menu:** pick many, pick only one (e.g. main hero), or a maximum (a minimum was left out: nobody asked for it); optionally only usable by members who already have a role (e.g. Verified).

**Storage** (core/db.py):
- `role_menus`: id, channel_id, message_id, mode, min_picks, max_picks, required_role_id, embed (JSON), updated_at
- `role_menu_options`: menu_id, role_id, label, emoji, description, position

**Panel** (Welcome & Roles tab): a list of menus, then an edit page with the channel, the embed editor, the role list (pick roles from a dropdown, add emoji, label and description, reorder) and the mode. Save posts the message, or edits it if it's already posted.

**How the panel and bot work together, with no link between them:** the panel posts and edits the menu message itself through Discord's API using the bot token, with buttons whose ids look like `rolemenu:<menu>:<role>`. The bot answers those clicks with a discord.py `DynamicItem`, which keeps working after restarts without re-registering anything. Emoji mode: the panel adds the reactions and the bot listens to reaction add and remove.

**Safety:** the panel only lists roles below the bot's highest role, never @everyone or bot-managed roles, and blocks roles with Administrator or any Manage permission. Role changes already show in the Server Log; menu edits show as Control panel entries.

**Build order:** database and shared code (~1 h), bot click handling (~1–2 h), panel list and editor (~2–3 h), emoji mode (~1 h), tests. Rank roles (#3) reuse the role-giving code afterwards.

## Moderation system

Every action gets a case number, is saved in the database and is posted to a private mod log channel.

- **Warnings**: `/warn`, `/warnings @user`, `/clearwarn`. Auto-timeout after a set number of warnings in 30 days.
- **Punishments**: `/timeout`, `/kick`, `/ban`, `/tempban` (unbans itself), `/unban`. The member gets a DM with the reason.
- **Channel tools**: `/purge` (bulk delete, optionally by user), `/slowmode`, `/lock` and `/unlock`.
- **Mod notes**: private notes about a member that only mods can see.
- **History**: `/case <number>` and `/history @user` show everything on record, and a reason can be edited later.
- **Appeals**: banned members get a link or DM button to appeal, which posts to a mod channel.

## Auto-translation

- The bot detects the language of every message. If it isn't English, it replies with the English translation.
- If someone replies to that translation, the bot translates their reply into the original message's language and posts it, so both people can talk in their own language.
- Needs the Message Content intent and a translation service: DeepL (free up to 500k characters a month) or a self-hosted LibreTranslate container (free, lower quality).
- Skip very short messages, links, emoji-only messages and code blocks, so the bot doesn't spam translations of "lol".
- Let admins choose which channels it runs in.
