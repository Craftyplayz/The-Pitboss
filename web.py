"""The Pitboss website: a dashboard of Linked Players' stats from deadlock-api.com. Run: python web.py"""
import asyncio
import json
import os
import time
from pathlib import Path

from aiohttp import web

from core import dashboard as dash
from core import db
from core.api import APIError, DeadlockAPI
from core.shared import window_start

PORT = int(os.environ.get("WEB_PORT", 8642))
ROOT = Path(__file__).parent
DASHBOARD_TTL = 300  # seconds before the dashboard data is rebuilt from the API
MATCH_TTL = 86400  # finished matches don't change
ITEMS_TTL = 6 * 3600


def render_page(template, data):
    """Inject the dashboard data into the page. `</` is escaped so no string can close the <script>."""
    payload = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/").replace("<!--", "<\\!--")
    return template.replace("/*DATA*/null", payload, 1)


def empty_page(message):
    return (f"<!doctype html><meta charset=utf-8><title>The Pitboss</title>"
            f"<body style='font:16px system-ui;background:#0f141b;color:#dbdee1;padding:24px'><p>{message}</p></body>")


async def cached(app, key, ttl, make):
    # shortcut: unbounded dict and no request coalescing, fine for one server's traffic; use an LRU if it grows
    hit = app["cache"].get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    value = await make()
    app["cache"][key] = (time.monotonic() + ttl, value)
    return value


async def _safe(coro, default):
    """An optional API call: log failures and fall back so one bad endpoint doesn't blank the page."""
    try:
        return await coro or default
    except APIError as e:
        print(f"web: {e}")
        return default


async def build_dashboard(app):
    api = app["api"]
    ids = [l["account_id"] for l in db.all_links(app["db"])]
    if not ids:
        return None
    now, since = int(time.time()), window_start()
    joined = ",".join(map(str, ids))
    n = len(ids)
    results = await asyncio.gather(
        _safe(api.get("/v1/players/steam", account_ids=joined), []),
        _safe(api.get("/v1/players/rank", account_ids=joined), []),
        _safe(api.get("/v1/players/hero-stats", account_ids=joined), []),
        _safe(api.get("/v1/analytics/hero-stats", min_unix_timestamp=since), []),
        *[_safe(api.get(f"/v1/players/{a}/match-history"), []) for a in ids],
        *[_safe(api.get(f"/v1/players/{a}/mate-stats", min_unix_timestamp=since), []) for a in ids],
        *[_safe(api.get(f"/v1/players/{a}/enemy-stats", min_unix_timestamp=since), []) for a in ids],
    )
    steam, rank_rows, hero_stats, hero_rows = results[:4]
    histories = {a: [m for m in h if m["start_time"] >= since] for a, h in zip(ids, results[4:4 + n])}
    mates, enemies = dict(zip(ids, results[4 + n:4 + 2 * n])), dict(zip(ids, results[4 + 2 * n:]))

    linked = set(ids)
    others = {r.get("mate_id") or r.get("enemy_id") for rows in (*mates.values(), *enemies.values()) for r in rows} - linked
    other_steam = await _safe(api.get("/v1/players/steam", account_ids=",".join(map(str, list(others)[:200]))), []) if others else []
    profiles = {p["account_id"]: p for p in [*steam, *other_steam]}
    badges = {r["account_id"]: r.get("badge") or 0 for r in rank_rows}

    players = [dash.player_entry(a, profiles.get(a), badges.get(a, 0), histories[a],
                                 [r for r in hero_stats if r["account_id"] == a], mates[a], enemies[a], linked, profiles)
               for a in ids]
    players = [p for p in players if p]  # shortcut: Linked Players with no match in 30 days are left off the page
    names = {i: p["personaname"] for i, p in profiles.items() if i not in linked}
    return dash.dashboard(now, players, histories, await api.heroes(), await api.items(), await api.ranks(), hero_rows, names)


async def dashboard_data(app):
    return await cached(app, "dashboard", DASHBOARD_TTL, lambda: build_dashboard(app))


async def index(request):
    data = await dashboard_data(request.app)
    if not data or not data["P"]:
        return web.Response(text=empty_page("No Linked Players have played in the last 30 days."), content_type="text/html")
    return web.Response(text=render_page(request.app["template"], data), content_type="text/html")


async def match_api(request):
    match_id = int(request.match_info["match_id"])
    app = request.app
    data = await dashboard_data(app)
    # only matches with a Linked Player, so the site can't be used as an open proxy to the API
    if not data or match_id not in {m["id"] for m in data["SM"]}:
        raise web.HTTPNotFound()

    async def make():
        meta = await app["api"].get(f"/v1/matches/{match_id}/metadata")
        if not meta:
            return None
        ids = ",".join(str(p["account_id"]) for p in meta["match_info"]["players"])
        names = {p["account_id"]: p["personaname"] for p in await _safe(app["api"].get("/v1/players/steam", account_ids=ids), [])}
        return dash.match_detail(meta, await app["api"].items(), names)

    detail = await cached(app, f"match:{match_id}", MATCH_TTL, make)
    if detail is None:
        app["cache"].pop(f"match:{match_id}", None)  # not processed yet; try again next time
        raise web.HTTPNotFound()
    return web.json_response(detail)


async def hero_items_api(request):
    hero_id = int(request.match_info["hero_id"])
    api = request.app["api"]
    if hero_id not in await api.heroes():
        raise web.HTTPNotFound()

    async def make():
        rows = await api.get("/v1/analytics/item-stats", hero_id=hero_id, min_unix_timestamp=int(time.time()) - 14 * 86400)
        return dash.hero_items(rows or [], await api.items())

    return web.json_response(await cached(request.app, f"items:{hero_id}", ITEMS_TTL, make))


async def mockups_index(request):
    raise web.HTTPFound("/mockups/index.html")


@web.middleware
async def api_errors(request, handler):
    try:
        return await handler(request)
    except APIError as e:
        return web.Response(text=empty_page(f"Stats unavailable: {e}"), status=502, content_type="text/html")


def make_app():
    app = web.Application(middlewares=[api_errors])
    db_path = os.environ.get("DB_PATH", "data/pitboss.db")
    app["db"] = db.connect(db_path)
    # every API call, forever, one JSON line each; next to the database so it lives on the data volume
    app["api"] = DeadlockAPI(os.environ.get("DEADLOCK_API_KEY") or None, log_path=Path(db_path).parent / "api-web.jsonl")
    app["template"] = (ROOT / "pages" / "dashboard.html").read_text(encoding="utf8")
    app["cache"] = {}

    async def start(app):
        await app["api"].start()

    async def stop(app):
        await app["api"].close()

    app.on_startup.append(start)
    app.on_cleanup.append(stop)
    app.add_routes([web.get("/", index),
                    web.get("/api/match/{match_id:\\d+}", match_api),
                    web.get("/api/hero-items/{hero_id:\\d+}", hero_items_api),
                    web.get("/mockups", mockups_index),
                    web.static("/mockups", ROOT / "mockups")])
    return app


if __name__ == "__main__":
    web.run_app(make_app(), port=PORT)
