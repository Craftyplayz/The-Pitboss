import aiohttp

BASE_URL = "https://api.deadlock-api.com"


class APIError(Exception):
    """deadlock-api.com failed or rate-limited us. The message is safe to show to Members."""


class DeadlockAPI:
    def __init__(self, key=None):
        self.key = key
        self.session = None
        self._heroes = None

    async def start(self):
        headers = {"X-API-KEY": self.key} if self.key else {}
        self.session = aiohttp.ClientSession(
            BASE_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
        )

    async def close(self):
        if self.session:
            await self.session.close()

    async def get(self, path, **params):
        """GET a path like "/v1/players/123/rank" and return parsed JSON. Returns None on 404."""
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items() if v is not None}
        try:
            async with self.session.get(path, params=params) as resp:
                if resp.status == 404:
                    return None
                if resp.status in (429, 503, 504):
                    raise APIError("The Deadlock stats API is busy. Try again in a minute.")
                if resp.status >= 400:
                    raise APIError(f"The Deadlock stats API returned an error ({resp.status}).")
                return await resp.json()
        except (aiohttp.ClientError, TimeoutError) as e:
            raise APIError("Couldn't reach the Deadlock stats API.") from e

    async def heroes(self):
        """{hero_id: hero asset dict} for selectable heroes. Cached until restart."""
        # shortcut: never refreshed, so a hero added by a patch shows up after a bot restart
        if self._heroes is None:
            data = await self.get("/v1/assets/heroes", only_active=True)
            self._heroes = {h["id"]: h for h in data if h.get("player_selectable")}
        return self._heroes

    async def hero_name(self, hero_id):
        hero = (await self.heroes()).get(hero_id)
        return hero["name"] if hero else f"Hero {hero_id}"
