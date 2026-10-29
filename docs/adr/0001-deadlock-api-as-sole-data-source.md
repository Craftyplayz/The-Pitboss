# deadlock-api.com is the sole stats source

Valve publishes no public API for Deadlock match or player data, and the other stat sites (Statlocker, Tracklock) offer no public API. All stats therefore come from the community API at api.deadlock-api.com, which is free, open source and not endorsed by Valve. We start without an API key, and the code must allow one to be added later as configuration only, because a key raises rate limits and the speed of fresh match history.

## Consequences

- If deadlock-api.com goes down or changes, every feature of the bot is affected.
- Players who opted out of deadlock-api.com cannot be linked.
- Some Players' recent Matches only appear after a delay, unless the Player friends one of the API's bot accounts.
