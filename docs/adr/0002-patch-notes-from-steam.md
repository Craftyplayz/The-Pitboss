# Patch Notes come from Steam's news API

ADR 0001 covers stats. Patch Notes are not stats, and deadlock-api.com's `/v1/patches` mirrors the official forum changelog, which lags: in October 2026 it was missing two minor updates that Steam already had. So Patch Notes come from Steam's public, keyless news API (`ISteamNews/GetNewsForApp`, app 1422450, feed `steam_community_announcements`). An announcement counts as a patch when its title contains "Update", which matched every patch from 2025 to 2026 and no hero or lore post.

## Consequences

- A patch Valve posts only on the forum, or titles without "Update", is not posted.
- Steam is a second outside service; if it is down, only Patch Notes are affected.
