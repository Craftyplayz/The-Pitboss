import json
import time

import aiohttp

BASE_URL = "https://api.deadlock-api.com"


class APIError(Exception):
    """deadlock-api.com failed or rate-limited us. The message is safe to show to Members."""


class DeadlockAPI:
    def __init__(self, key=None, log_path=None):
        self.key = key
        self.log_path = log_path
        self.session = None
        self._heroes = None
        self._items = None
        self._ranks = None

    async def start(self):
        headers = {"X-API-KEY": self.key} if self.key else {}
        self.session = aiohttp.ClientSession(
            BASE_URL, headers=headers, timeout=aiohttp.ClientTimeout(total=30)
        )

    async def close(self):
        if self.session:
            await self.session.close()

    def log(self, url, params, status, started, size):
        """Append one API call to the log file as a JSON line. Never raises: logging must not break a request."""
        if not self.log_path:
            return
        line = json.dumps({"t": round(time.time()), "url": url, "params": params, "status": status,
                           "ms": round((time.monotonic() - started) * 1000), "bytes": size}, separators=(",", ":"))
        try:
            with open(self.log_path, "a", encoding="utf8") as f:
                f.write(line + "\n")
        except OSError as e:
            print(f"api log: {e}")

    async def get(self, path, **params):
        """GET a path like "/v1/players/123/rank" and return parsed JSON. Returns None on 404."""
        return await self.request("GET", path, params)

    async def post(self, path, payload=None):
        """POST a JSON body and return parsed JSON. Returns None on 404 or an empty reply."""
        return await self.request("POST", path, {}, payload)

    async def request(self, method, path, params, payload=None):
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items() if v is not None}
        started, status, size = time.monotonic(), "error", 0
        try:
            async with self.session.request(method, path, params=params, json=payload) as resp:
                status = resp.status
                body = await resp.read()
                size = len(body)
                if resp.status == 404:
                    return None
                if resp.status in (429, 503, 504):
                    raise APIError("The Deadlock stats API is busy. Try again in a minute.")
                if resp.status >= 400:
                    raise APIError(f"The Deadlock stats API returned an error ({resp.status}).")
                return json.loads(body) if body else None
        except (aiohttp.ClientError, TimeoutError) as e:
            raise APIError("Couldn't reach the Deadlock stats API.") from e
        finally:
            self.log(path, params, status, started, size)

    async def heroes(self):
        """{hero_id: hero asset dict} for selectable heroes. Cached until restart."""
        # shortcut: never refreshed, so a hero added by a patch shows up after a bot restart
        if self._heroes is None:
            data = await self.get("/v1/assets/heroes", only_active=True)
            self._heroes = {h["id"]: h for h in data if h.get("player_selectable")}
        return self._heroes

    async def items(self):
        """{item_id: item asset dict}. Cached until restart."""
        if self._items is None:
            self._items = {i["id"]: i for i in await self.get("/v1/assets/items")}
        return self._items

    async def ranks(self):
        """{tier: rank asset dict}. Cached until restart."""
        if self._ranks is None:
            self._ranks = {r["tier"]: r for r in await self.get("/v1/assets/ranks")}
        return self._ranks

    async def hero_name(self, hero_id):
        hero = (await self.heroes()).get(hero_id)
        return hero["name"] if hero else f"Hero {hero_id}"
