"""The Pitboss website: plain HTML pages of the stats the bot posts, for Linked Players only. Run: python web.py"""
import html
import os
from datetime import datetime, timezone
from pathlib import Path

from aiohttp import web

from core import db
from core.api import APIError, DeadlockAPI
from core.match import final_build, find_player, scoreboard, souls_sources
from core.shared import won

PORT = int(os.environ.get("WEB_PORT", 8642))


def _cell(c):
    """A table cell: (text, href) becomes a link, anything else is escaped text."""
    if isinstance(c, tuple):
        return f'<a href="{html.escape(c[1])}">{html.escape(str(c[0]))}</a>'
    return html.escape(str(c))


def table(headers, rows):
    head = "".join(f"<th>{html.escape(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{_cell(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table border=1 cellpadding=4><tr>{head}</tr>{body}</table>"


def page(title, body):
    return (f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width'>"
            f"<title>{html.escape(title)} · The Pitboss</title></head>"
            f"<body><p><a href='/'>The Pitboss</a></p><h1>{html.escape(title)}</h1>{body}</body></html>")


def _date(ts):
    return datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def _mmss(s):
    return f"{s // 60}:{s % 60:02d}"


def index_page(links, names):
    """links: db rows. names: {account_id: personaname}."""
    rows = [((names.get(l["account_id"], l["account_id"]), f"/player/{l['account_id']}"), l["account_id"], _date(l["linked_at"]))
            for l in links]
    return page("Linked Players", table(["Player", "Account ID", "Linked"], rows) if rows else "<p>No one is linked yet.</p>")


def player_page(account_id, name, rank_name, history, hero_names):
    rows = [(_date(m["start_time"]), hero_names.get(m["hero_id"], f"Hero {m['hero_id']}"), "Win" if won(m) else "Loss",
             f"{m['player_kills']}/{m['player_deaths']}/{m['player_assists']}", f"{m['net_worth']:,}",
             _mmss(m["match_duration_s"]), (m["match_id"], f"/match/{m['match_id']}/{account_id}"))
            for m in history]
    body = f"<p>Account ID {account_id} · Rank: {html.escape(rank_name or 'Unranked')}</p><h2>Recent matches</h2>"
    body += table(["Date", "Hero", "Result", "K/D/A", "Souls", "Duration", "Match"], rows) if rows else "<p>No matches.</p>"
    return page(name, body)


def match_page(meta, account_id, heroes, items):
    """None if the Player isn't in this Match."""
    info = meta["match_info"]
    me = find_player(meta, account_id)
    if me is None:
        return None
    hero_names = {i: h["name"] for i, h in heroes.items()}
    s = me["stats"][-1]
    win = info["winning_team"] == me["team"]
    minutes = max(info["duration_s"] / 60, 1)
    shots = s["shots_hit"] + s["shots_missed"]
    stats = [
        ("K / D / A", f"{me['kills']} / {me['deaths']} / {me['assists']}"),
        ("Souls", f"{me['net_worth']:,} ({me['net_worth'] / minutes:,.0f}/min)"),
        ("Level", me["level"]),
        ("Hero damage", f"{s['player_damage']:,}"),
        ("Healing", f"{s['player_healing']:,}"),
        ("Damage taken", f"{s['player_damage_taken']:,}"),
        ("Accuracy", f"{s['shots_hit'] / shots:.1%}" if shots else "-"),
        ("Last hits / denies", f"{me['last_hits']} / {me['denies']}"),
    ]
    body = f"<p>{_date(info['start_time'])} · {_mmss(info['duration_s'])} · Match {info['match_id']}</p>"
    body += "<h2>Stats</h2>" + table(["Stat", "Value"], stats)
    body += "<h2>Souls by source</h2>" + table(["Source", "Souls"], [(n, f"{v:,}") for n, v in souls_sources(s)])
    build = final_build(me, items)
    body += "<h2>Final build</h2>" + table(["Item", "Slot", "Cost"], [(i["name"], i.get("item_slot_type", ""), i.get("cost") or 0) for i in build])
    for label, team_won, total, rows in scoreboard(info["players"], me, hero_names, win):
        body += f"<h2>{label} · {'Win' if team_won else 'Loss'} · {total:,} souls</h2>"
        body += table(["Hero", "K/D/A", "Souls", "Damage", ""], [(h, kda, f"{so:,}", f"{d:,}", "you" if is_me else "")
                                                                 for h, kda, so, d, is_me in rows])
    return page(f"{heroes.get(me['hero_id'], {}).get('name', 'Hero')} · {'Win' if win else 'Loss'}", body)


def _html(text, status=200):
    return web.Response(text=text, status=status, content_type="text/html")


def _linked(request):
    """The account_id from the URL if it belongs to a Linked Player, else raise 404."""
    try:
        account_id = int(request.match_info["account_id"])
    except ValueError:
        raise web.HTTPNotFound()
    if not db.get_link_by_account(request.app["db"], account_id):
        raise web.HTTPNotFound(text="That Player isn't linked.")
    return account_id


async def index(request):
    links = db.all_links(request.app["db"])
    names = {}
    if links:
        found = await request.app["api"].get("/v1/players/steam", account_ids=",".join(str(l["account_id"]) for l in links))
        names = {p["account_id"]: p["personaname"] for p in found or []}
    return _html(index_page(links, names))


async def player(request):
    aid = _linked(request)
    api = request.app["api"]
    found = await api.get("/v1/players/steam", account_ids=aid)
    rank = await api.get(f"/v1/players/{aid}/rank")
    history = await api.get(f"/v1/players/{aid}/match-history") or []
    badge = (rank or {}).get("badge") or 0
    rank_asset = (await api.ranks()).get(badge // 10) if badge else None
    rank_name = f"{rank_asset['name']} {badge % 10}" if rank_asset else None
    hero_names = {i: h["name"] for i, h in (await api.heroes()).items()}
    name = found[0]["personaname"] if found else str(aid)
    return _html(player_page(aid, name, rank_name, history[:20], hero_names))


async def match(request):
    aid = _linked(request)
    api = request.app["api"]
    meta = await api.get(f"/v1/matches/{int(request.match_info['match_id'])}/metadata")
    text = match_page(meta, aid, await api.heroes(), await api.items()) if meta else None
    if text is None:
        raise web.HTTPNotFound(text="No data for that Player in that Match yet.")
    return _html(text)


async def mockups_index(request):
    raise web.HTTPFound("/mockups/index.html")


@web.middleware
async def api_errors(request, handler):
    try:
        return await handler(request)
    except APIError as e:
        return _html(page("Stats unavailable", f"<p>{html.escape(str(e))}</p>"), status=502)


def make_app():
    app = web.Application(middlewares=[api_errors])
    app["db"] = db.connect(os.environ.get("DB_PATH", "data/pitboss.db"))
    app["api"] = DeadlockAPI(os.environ.get("DEADLOCK_API_KEY") or None)

    async def start(app):
        await app["api"].start()

    async def stop(app):
        await app["api"].close()

    app.on_startup.append(start)
    app.on_cleanup.append(stop)
    app.add_routes([web.get("/", index), web.get("/player/{account_id}", player),
                    web.get("/match/{match_id:\\d+}/{account_id}", match),
                    web.get("/mockups", mockups_index),
                    web.static("/mockups", Path(__file__).parent / "mockups")])
    return app


if __name__ == "__main__":
    web.run_app(make_app(), port=PORT)
