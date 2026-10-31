"""The Pitboss control panel: log in with Discord (needs Manage Server) and change the bot's settings. Run: python dash.py

The bot reads every setting from the shared database when it uses it, so changes apply without a restart."""
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from cogs.welcome import DEFAULT as WELCOME_DEFAULT, PLACEHOLDERS
from core import db

PORT = int(os.environ.get("DASH_PORT", 8643))
DISCORD = "https://discord.com/api/v10"
SESSION_TTL = 12 * 3600
ADMINISTRATOR, MANAGE_GUILD = 1 << 3, 1 << 5
TEXT, VOICE, FORUM = (0, 5), (2,), (15,)  # Discord channel types; 5 is an announcement channel
# (setting key, label, allowed channel types). The scrim log stays in /setup: picking it changes channel permissions.
CHANNELS = [("recap_forum_id", "Recap forum", FORUM), ("patch_notes_id", "Patch notes", TEXT),
            ("bot_updates_id", "Bot updates", TEXT), ("voice_hub_id", "Voice hub", VOICE),
            ("welcome_channel_id", "Welcome channel", TEXT)]


def sign(data, key):
    payload = base64.urlsafe_b64encode(json.dumps(data).encode()).decode()
    return payload + "." + hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()


def unsign(token, key):
    """The signed data, or None if the token is missing, forged or expired."""
    payload, _, sig = (token or "").partition(".")
    if not hmac.compare_digest(sig, hmac.new(key.encode(), payload.encode(), hashlib.sha256).hexdigest()):
        return None
    data = json.loads(base64.urlsafe_b64decode(payload))
    return data if data.get("exp", 0) > time.time() else None


def can_manage(guilds, guild_id):
    """Whether the user's /users/@me/guilds entry for our server has Manage Server, Administrator or ownership."""
    g = next((g for g in guilds if g["id"] == str(guild_id)), None)
    return bool(g) and (g.get("owner") or int(g.get("permissions", 0)) & (ADMINISTRATOR | MANAGE_GUILD) != 0)


def changes(form, channels):
    """{setting: value} to save from the submitted form. Channel ids must be a channel of the right type, or "" for none."""
    out = {}
    for key, _, types in CHANNELS:
        value = form.get(key, "")
        if value and not any(c["id"] == value and c["type"] in types for c in channels):
            raise web.HTTPBadRequest(text=f"Unknown channel for {key}")
        out[key] = value
    out["welcome_message"] = form.get("welcome_message", "").strip()[:2000]  # Discord's message limit
    return out


async def discord_get(app, path, auth):
    async with app["http"].get(DISCORD + path, headers={"Authorization": auth}) as r:
        if r.status != 200:
            raise web.HTTPBadGateway(text=f"Discord said {r.status} for {path}")
        return await r.json()


def page(body, user=None):
    who = f'<span>{html.escape(user)} · <a href="/logout">Log out</a></span>' if user else ""
    return web.Response(content_type="text/html", text=f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Pitboss Control Panel</title>
<link rel="icon" href="https://pitboss.craftyplayz.com/static/favicon.svg" type="image/svg+xml">
<style>:root{{--bg:#0e1319;--card:#161c25;--line:#232c39;--tx:#dce3ec;--mu:#8190a3;--gold:#F0C35A;--win:#4fc98a}}
body{{margin:0;background:var(--bg);color:var(--tx);font:15px/1.5 system-ui,sans-serif}}
header{{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 16px;border-bottom:1px solid var(--line)}}
header b{{color:var(--gold)}} main{{max-width:640px;margin:0 auto;padding:20px 16px}} a{{color:var(--gold)}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:16px;margin-bottom:16px}}
h2{{font-size:16px;margin:0 0 12px}} label{{display:block;margin:12px 0 4px;color:var(--mu);font-size:13px}}
select,textarea{{width:100%;box-sizing:border-box;background:var(--bg);color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:8px;font:inherit}}
textarea{{min-height:90px}} small{{color:var(--mu)}} .ok{{color:var(--win)}}
.btn{{display:inline-block;background:var(--gold);color:#111;border:0;border-radius:8px;padding:10px 18px;font:600 15px system-ui;cursor:pointer;text-decoration:none}}
</style></head><body><header><b>The Pitboss · Control Panel</b>{who}</header><main>{body}</main></body></html>""")


def session(request):
    return unsign(request.cookies.get("session"), request.app["secret"])


async def index(request):
    app, user = request.app, session(request)
    if not user:
        return page('<div class="card"><h2>Log in</h2><p>You need Manage Server on the Discord server to change the bot\'s settings.</p>'
                    '<a class="btn" href="/login">Log in with Discord</a></div>')
    channels = sorted(await discord_get(app, f"/guilds/{app['guild_id']}/channels", f"Bot {app['token']}"),
                      key=lambda c: c.get("position", 0))
    rows = []
    for key, label, types in CHANNELS:
        current = db.get_setting(app["db"], key) or ""
        options = '<option value="">Not set</option>' + "".join(
            f'<option value="{c["id"]}"{" selected" if c["id"] == current else ""}>#{html.escape(c["name"])}</option>'
            for c in channels if c["type"] in types)
        rows.append(f'<label for="{key}">{label}</label><select id="{key}" name="{key}">{options}</select>')
    message = html.escape(db.get_setting(app["db"], "welcome_message") or "")
    saved = '<p class="ok">Saved. The bot uses the new settings straight away.</p>' if "saved" in request.query else ""
    return page(f"""{saved}<form method="post" action="/save">
<div class="card"><h2>Channels</h2>{''.join(rows)}
<p><small>Pick the scrim log with /setup in Discord: it also changes that channel's permissions.</small></p></div>
<div class="card"><h2>Welcome message</h2><label for="welcome_message">Message (empty uses the default)</label>
<textarea id="welcome_message" name="welcome_message" maxlength="2000" placeholder="{html.escape(WELCOME_DEFAULT)}">{message}</textarea>
<p><small>{html.escape(PLACEHOLDERS).replace("`", "")}</small></p></div>
<button class="btn" type="submit">Save</button></form>""", user["name"])


async def save(request):
    app, user = request.app, session(request)
    # SameSite=Lax already keeps the cookie off cross-site posts; this also blocks a post from another site we host
    if not user or request.headers.get("Origin") != app["url"]:
        raise web.HTTPForbidden()
    channels = await discord_get(app, f"/guilds/{app['guild_id']}/channels", f"Bot {app['token']}")
    new = changes(await request.post(), channels)
    if new["patch_notes_id"] and new["patch_notes_id"] != db.get_setting(app["db"], "patch_notes_id"):
        db.set_setting(app["db"], "patch_notes_last", 0)  # same backfill /setup does; the bot's 10-minute check posts it
    for key, value in new.items():
        db.set_setting(app["db"], key, value)
    print(f"dash: {user['name']} ({user['id']}) saved {new}")
    raise web.HTTPFound("/?saved")


async def login(request):
    app, state = request.app, secrets.token_urlsafe(16)
    query = {"client_id": app["client_id"], "redirect_uri": app["url"] + "/callback", "response_type": "code",
             "scope": "identify guilds", "state": state, "prompt": "none"}
    response = web.HTTPFound("https://discord.com/oauth2/authorize?" + urlencode(query))
    response.set_cookie("state", state, max_age=600, httponly=True, secure=app["secure"], samesite="Lax")
    raise response


async def callback(request):
    app = request.app
    state = request.query.get("state", "")
    if not state or not hmac.compare_digest(state, request.cookies.get("state", "")) or "code" not in request.query:
        raise web.HTTPFound("/")  # cancelled, expired or forged: start over
    async with app["http"].post(DISCORD + "/oauth2/token", data={
            "client_id": app["client_id"], "client_secret": app["secret"], "grant_type": "authorization_code",
            "code": request.query["code"], "redirect_uri": app["url"] + "/callback"}) as r:
        if r.status != 200:
            raise web.HTTPBadGateway(text=f"Discord login failed ({r.status}). Check DISCORD_CLIENT_SECRET and the redirect URL.")
        auth = "Bearer " + (await r.json())["access_token"]
    me = await discord_get(app, "/users/@me", auth)
    if not can_manage(await discord_get(app, "/users/@me/guilds", auth), app["guild_id"]):
        return page("<div class='card'><h2>No access</h2><p>You need Manage Server on the Discord server to use this.</p></div>")
    # shortcut: permission is checked at login only, so someone who loses Manage Server keeps access until the session ends (12 h)
    token = sign({"id": me["id"], "name": me.get("global_name") or me["username"], "exp": time.time() + SESSION_TTL}, app["secret"])
    response = web.HTTPFound("/")
    response.set_cookie("session", token, max_age=SESSION_TTL, httponly=True, secure=app["secure"], samesite="Lax")
    response.del_cookie("state")
    raise response


async def logout(request):
    response = web.HTTPFound("/")
    response.del_cookie("session")
    raise response


def make_app():
    app = web.Application()
    app["db"] = db.connect(os.environ.get("DB_PATH", "data/pitboss.db"))
    app["token"], app["guild_id"] = os.environ["DISCORD_TOKEN"], int(os.environ["GUILD_ID"])
    app["client_id"] = os.environ["DISCORD_CLIENT_ID"]
    app["secret"] = os.environ["DISCORD_CLIENT_SECRET"]  # also signs the session cookie
    app["url"] = os.environ.get("DASH_URL", "https://dash.pitboss.craftyplayz.com").rstrip("/")
    app["secure"] = app["url"].startswith("https://")

    async def start(app):
        app["http"] = aiohttp.ClientSession()

    async def stop(app):
        await app["http"].close()

    app.on_startup.append(start)
    app.on_cleanup.append(stop)
    app.add_routes([web.get("/", index), web.post("/save", save), web.get("/login", login),
                    web.get("/callback", callback), web.get("/logout", logout)])
    return app


if __name__ == "__main__":
    web.run_app(make_app(), port=PORT)
