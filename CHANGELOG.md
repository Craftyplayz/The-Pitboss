# Patch notes

Versions before 1.0 were built before The Pitboss moved to its new server. 1.0 is the first version on the new server. Each version has a git tag, `v<version>`. From 1.4.1 on every change gets its own version (see CLAUDE.md), and the bot posts the newest entries after it restarts.

## 1.4.1.1

- The first restart with bot updates posts what changed since 1.4.0 instead of nothing.

## 1.4.1

- After an update the bot posts which version it was on, which version it's on now, and what changed. Pick the channel with the new **bot_updates** option in /setup.

## 1.4.0

- New Recap Threads open with the member's Discord avatar, so the forum list shows the avatar and not the first recap's souls graph.
- New **/rebuild-recaps** command (needs Manage Server). It deletes every Recap Thread and posts all recaps again in new threads that open with the avatar. Older matches are not skipped as too old. A thread the bot can't delete stays as it is, so no recap is posted twice.

## 1.3.0

- Website profiles now cover the player's whole match history: record, win rate, KDA, averages, souls/min, hero breakdown, best and worst game, streak and main hero.
- The match list shows 30 matches at a time, with **← Newer** and **Older →** buttons.
- The souls/min graph shows the last 50 matches.
- Mates and Rivals count every match, not only the last 30 days.
- Linked players with no match in the last 30 days still get a profile.
- Match-data trophies fill in for the whole history.
- Long hero names no longer overlap in the hero breakdown.
- The Overview, Leaderboards, Matches and Heroes tabs still cover the last 30 days.

## 1.2.1

- Patch-note threads hide after a week with no activity.

## 1.2.0

- **Trophies** on website profiles: Recent and Rarest trophy cards, and a full trophies page with earned tiers, progress to the next tier, rarity, heroes not yet won with and heroes never played.
- Trophy families for damage, healing, items, kill style, MVP, multi-kills, accuracy and Collector, built from saved match data.
- Each trophy family has its own icon. Hero mastery badges show the hero's portrait.
- The trophy tier colours are labelled.

## 1.1.1

- Fixed: an item icon Discord can't upload stopped every member's recaps. It now skips that icon.
- Rebuttal and Counterspell use their shop image, since Discord can't take their SVG icon as an emoji.

## 1.1.0

- Website: Most-bought items switch between **Server** (linked players, the default) and **Global**.
- /meta heroes shows the share of matches each hero appears in, next to pick rate.
- The server win rate counts only players with 10 or more matches.

## 1.0.0 (new server)

The first version on the new server. Everything below 1.0 is included.

- The website address (SITE_URL) and the /admin password (ADMIN_PASSWORD) are set in the server's environment.

## 0.7.0

- Website: click an item for its description and stats. Click a hero icon to open that hero's page. Every hero has a page, even ones nobody on the server has played.
- **Patch notes**: /setup picks a channel for new Deadlock updates from Steam. Picking it first posts every past patch, oldest first. All /setup options are optional; leave them empty to see the current channels.
- **/build** posts a buy-path image for a hero and rank: the most-bought items in each phase of the match, with buy rate and win rate.
- /profile: top heroes are styled lines instead of a table. The name links to the player's website page.
- Website: match list rows are simpler.

## 0.6.0

- **Scrims**: /scrim opens its own category with a sign-up channel and a voice channel per team. Teams are random or picked, and the bot makes the custom lobby and posts its code. The final scoreboard is saved and posted to the scrim log, with a discussion thread on each result. The website has a Scrims tab.
- Members who haven't linked get a private guide on how to link before they can join a scrim.
- /setup picks the scrim log channel alongside the recap forum.
- /meta hero rework: hero colour and icon, stat grid with ranks, item and hero icons, and a 14-day win-rate graph.
- New designs for the leaderboard, /meta heroes, /meta items and the simple recap.
- The first message in a Recap Thread names the newest recap and has a button that jumps to it.
- Bot status: "Always watching".
- Website /admin page (password protected) lists every API call the bot and site make.
- Fixed: website match details stuck on "Loading".

## 0.5.0

- **Website dashboard** with live data: overview, leaderboards, players, matches and heroes for linked players over the last 30 days.
- Recaps link to the website: the author name opens the player's profile, the title opens the match, and buttons open the home page, leaderboards and hero.
- /link shows a confirmation card with the Steam avatar, and suggestions show country flags. Recaps post right after "That's me".
- New icon for the bot and website: the watcher (an eye in a diamond).
- Bot status and About Me link to the website.
- Website: every mate and rival shown has a name, and switching player in a match keeps your scroll position.
- Fixed: 15 items had no icon.

## 0.4.0

- Recaps show souls by source and the scoreboard as images.
- /profile rework.
- First version of the website.

## 0.3.0

- Full Match Recaps: damage, healing, accuracy, crits, farm, souls by source, final build, scoreboard and a souls-over-time graph. Rank changes show, and when rank loss protection saved one. If the full match data isn't ready after 30 minutes, the simple recap posts.
- /link searches Steam names and accepts steamcommunity.com/id/ links.
- **/help** with a paged command guide.

## 0.2.0

- /link, /profile, Match Recaps, /leaderboard and /meta.
- Linking posts recaps for the 30 days before the link, a few at a time.

## 0.1.0

- The bot starts up.
