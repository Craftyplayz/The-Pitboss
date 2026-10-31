"""The Pitstop: The Pitboss's control panel. Log in with Discord (needs Manage Server) and change the bot's settings.
Run: python dash.py

The bot reads every setting from the shared database when it uses it, so changes apply without a restart."""
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from cogs.welcome import DEFAULT as WELCOME_DEFAULT, PLACEHOLDERS
from core import db

PORT = int(os.environ.get("DASH_PORT", 8643))
DISCORD = "https://discord.com/api/v10"
SESSION_TTL = 12 * 3600
VOICE_TTL = 3600  # the voice tab locks again after an hour
ADMINISTRATOR, MANAGE_GUILD = 1 << 3, 1 << 5
TEXT, VOICE, FORUM = (0, 5), (2,), (15,)  # Discord channel types; 5 is an announcement channel
# (setting key, label, allowed channel types). The scrim log stays in /setup: picking it changes channel permissions.
CHANNELS = [("recap_forum_id", "Recap forum", FORUM), ("patch_notes_id", "Patch notes", TEXT),
            ("bot_updates_id", "Bot updates", TEXT), ("voice_hub_id", "Voice hub", VOICE),
            ("welcome_channel_id", "Welcome channel", TEXT)]
LABELS = {key: label for key, label, _ in CHANNELS} | {"welcome_message": "Welcome message"}


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
    """{setting: value} for the fields this form sent. Channel ids must be a channel of the right type, or "" for none."""
    out = {}
    for key, _, types in CHANNELS:
        if key not in form:
            continue  # each tab only sends its own fields
        value = form[key]
        if value and not any(c["id"] == value and c["type"] in types for c in channels):
            raise web.HTTPBadRequest(text=f"Unknown channel for {key}")
        out[key] = value
    if "welcome_message" in form:
        out["welcome_message"] = form["welcome_message"].strip()[:2000]  # Discord's message limit
    return out


async def discord_get(app, path, auth):
    async with app["http"].get(DISCORD + path, headers={"Authorization": auth}) as r:
        if r.status != 200:
            raise web.HTTPBadGateway(text=f"Discord said {r.status} for {path}")
        return await r.json()


async def guild_channels(app):
    channels = await discord_get(app, f"/guilds/{app['guild_id']}/channels", f"Bot {app['token']}")
    return sorted(channels, key=lambda c: c.get("position", 0))


def session(request):
    return unsign(request.cookies.get("session"), request.app["secret"])


# ---- page pieces ----

def card(title, body):
    return f'<div class="card"><h2>{title}</h2>{body}</div>'


def soon(*features):
    """A placeholder card for features that haven't shipped yet."""
    return card("Coming soon", "<ul>" + "".join(f"<li>{f}</li>" for f in features) + "</ul>"
                "<p><small>Settings for these show up here as each one ships.</small></p>")


def channel_select(app, channels, key):
    _, label, types = next(c for c in CHANNELS if c[0] == key)
    current = db.get_setting(app["db"], key) or ""
    options = '<option value="">Not set</option>' + "".join(
        f'<option value="{c["id"]}"{" selected" if c["id"] == current else ""}>'
        f'{"🔊 " if c["type"] in VOICE else "#"}{html.escape(c["name"])}</option>'
        for c in channels if c["type"] in types)
    return f'<label for="{key}">{label}</label><select id="{key}" name="{key}">{options}</select>'


def form(tab, body):
    return (f'<form method="post" action="/save"><input type="hidden" name="tab" value="{tab}">{body}'
            '<button class="btn" type="submit">Save</button></form>')


# ---- tabs ----

async def welcome_tab(request):
    app = request.app
    message = html.escape(db.get_setting(app["db"], "welcome_message") or "")
    return form("welcome", card("Welcome message", channel_select(app, await guild_channels(app), "welcome_channel_id") +
        f'<label for="welcome_message">Message (empty uses the default)</label>'
        f'<textarea id="welcome_message" name="welcome_message" maxlength="2000" placeholder="{html.escape(WELCOME_DEFAULT)}">{message}</textarea>'
        f'<p><small>{html.escape(PLACEHOLDERS).replace("`", "")}</small></p>')) + soon("Role menus: members pick roles with buttons", "Rank roles from linked Deadlock accounts")


async def utility_tab(request):
    return soon("Timezone converter", "Sticky messages", "Birthdays", "Looking for game (LFG)", "Event signups and reminders")


async def leveling_tab(request):
    return soon("XP for chatting and time in voice", "Level-up cards", "Role rewards at set levels", "Leaderboard")


async def games_tab(request):
    return soon("Daily Wordle", "Marriages", "Giveaways")


async def voice_tab(request):
    app, user = request.app, session(request)
    if not app["voice_password"]:
        return card("Locked", "<p>Set <code>VOICE_PASSWORD</code> on the dash container to turn this tab on.</p>")
    unlocked = unsign(request.cookies.get("voice"), app["secret"])
    if not unlocked or unlocked["id"] != user["id"]:
        wrong = '<p class="bad">Wrong password.</p>' if "wrong" in request.query else ""
        return card("Password needed", f'{wrong}<p>Voice transcripts and recordings need a second password.</p>'
                    '<form method="post" action="/voice/unlock"><label for="pw">Password</label>'
                    '<input id="pw" name="password" type="password" autocomplete="current-password" required>'
                    '<button class="btn" type="submit">Unlock</button></form>')
    return soon("Voice call transcripts", "Raw audio recordings of each call", "AI summaries of each call") + \
        '<p><small>Unlocked for an hour. <a href="/voice/lock">Lock now</a></small></p>'


async def translate_tab(request):
    return soon("Auto-translate messages that aren't in English", "Replies to a translation go back in the original language", "Pick which channels it runs in")


async def setup_tab(request):
    app = request.app
    channels = await guild_channels(app)
    return form("setup", card("Channels", "".join(channel_select(app, channels, k) for k in
                                                  ("recap_forum_id", "patch_notes_id", "bot_updates_id", "voice_hub_id")) +
                              "<p><small>Pick the scrim log with /setup in Discord: it also changes that channel's permissions.</small></p>"))


async def logs_tab(request):
    rows = db.dash_log(request.app["db"])
    if not rows:
        body = "<p>Nothing yet. Every change made here is listed, newest first.</p>"
    else:
        body = '<table><tr><th>When (UTC)</th><th>Who</th><th>What</th></tr>' + "".join(
            f'<tr><td>{datetime.fromtimestamp(r["at"], timezone.utc):%Y-%m-%d %H:%M}</td><td>{html.escape(r["user"])}</td>'
            f'<td>{html.escape(r["action"])}</td></tr>' for r in rows) + "</table>"
    return card("Control panel changes", body) + soon("Server logs: joins, leaves, deleted and edited messages, role changes")


ICONS = {
    "welcome": '<circle cx="9" cy="8" r="3.5"/><path d="M2 20c0-4 3-6 7-6s7 2 7 6M19 8v6M16 11h6"/>',
    "utility": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "leveling": '<path d="M4 20v-6M10 20V9M16 20V4M2 20h20"/>',
    "games": '<rect x="3" y="3" width="18" height="18" rx="4"/><circle cx="8.5" cy="8.5" r="1.2" fill="currentColor"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="15.5" cy="15.5" r="1.2" fill="currentColor"/>',
    "voice": '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4M8 22h8"/>',
    "translate": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3z"/>',
    "setup": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/>',
    "logs": '<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7"/>',
}
# Sidebar order, top to bottom: move a line to move its tab. (url slug, label, subtitle, page)
TABS = [
    ("welcome", "Welcome & Roles", "What new members see, and the roles they can pick", welcome_tab),
    ("utility", "Utility", "Handy everyday commands", utility_tab),
    ("leveling", "Leveling", "XP, levels and rewards", leveling_tab),
    ("games", "Games", "Fun stuff to play in the server", games_tab),
    ("voice", "Voice", "Transcripts and recordings of voice calls", voice_tab),
    ("translate", "Translate", "Automatic translation between languages", translate_tab),
]
# Always at the bottom of the sidebar, in this order.
PINNED = [
    ("setup", "Setup", "Which channels the bot uses", setup_tab),
    ("logs", "Logs", "Everything that changed, newest first", logs_tab),
]
BY_SLUG = {t[0]: t for t in TABS + PINNED}

CSS = """:root{--bg:#0e1319;--side:#0a0e13;--card:#161c25;--line:#232c39;--tx:#dce3ec;--mu:#8190a3;--gold:#F0C35A;--win:#4fc98a;--loss:#e5636d;--r:12px}
*{box-sizing:border-box;margin:0}
body{background:var(--bg);color:var(--tx);font:14px/1.45 Inter,system-ui,sans-serif;min-height:100vh}
a{color:var(--gold)}
#side{position:fixed;inset:0 auto 0 0;width:232px;background:var(--side);border-right:1px solid var(--line);padding:22px 14px;display:flex;flex-direction:column;gap:2px;z-index:20;transition:transform .2s}
.logo{font:700 19px Cinzel,serif;color:var(--gold);letter-spacing:.06em;padding:0 10px 22px}
.nav{display:flex;align-items:center;gap:10px;color:var(--mu);font:500 14px Inter,system-ui,sans-serif;padding:10px;border-radius:8px;text-decoration:none}
.nav:hover{background:#121922;color:var(--tx)}
.nav.on{background:#1c2430;color:var(--gold)}
.nav svg{width:18px;height:18px;flex:none;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.pin{margin-top:auto;padding-top:12px;border-top:1px solid var(--line)}
.who{margin-top:12px;padding:12px;border:1px solid var(--line);border-radius:10px;font-size:12px;color:var(--mu)}
.who b{display:block;color:var(--tx);font-size:13px}
#top{display:none;position:sticky;top:0;z-index:15;background:var(--side);border-bottom:1px solid var(--line);padding:10px 16px;align-items:center;gap:12px}
#top button{background:none;border:1px solid var(--line);color:var(--tx);border-radius:8px;padding:6px 10px;font-size:18px;cursor:pointer}
main{margin-left:232px;padding:28px 32px;max-width:900px}
h1{font:600 22px Inter,system-ui,sans-serif}
.sub{color:var(--mu);margin:2px 0 20px}
h2{font:600 14px Inter,system-ui,sans-serif;margin-bottom:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:var(--r);padding:18px;margin-bottom:16px}
.card ul{padding-left:18px;color:var(--mu)}.card li{margin:4px 0}
label{display:block;margin:12px 0 4px;color:var(--mu);font-size:12px;text-transform:uppercase;letter-spacing:.08em}
select,textarea,input{width:100%;background:var(--bg);color:var(--tx);border:1px solid var(--line);border-radius:8px;padding:9px;font:inherit}
textarea{min-height:110px;resize:vertical}
small{color:var(--mu)} .ok{color:var(--win);margin-bottom:16px} .bad{color:var(--loss)}
code{background:var(--bg);padding:1px 5px;border-radius:4px}
table{width:100%;border-collapse:collapse;font-size:13px}th{text-align:left;color:var(--mu);font-weight:500}
th,td{padding:8px 6px;border-bottom:1px solid var(--line);vertical-align:top}
.btn{display:inline-block;margin-top:12px;background:var(--gold);color:#111;border:0;border-radius:8px;padding:10px 18px;font:600 14px Inter,system-ui,sans-serif;cursor:pointer;text-decoration:none}
.btn:hover{filter:brightness(1.08)} form{margin-bottom:24px}
.solo{max-width:420px;margin:12vh auto;padding:0 16px;text-align:center}.solo .logo{font-size:26px;padding:0 0 18px}
@media(max-width:820px){#top{display:flex}#side{transform:translateX(-100%)}#side.open{transform:none;box-shadow:0 0 0 100vmax #0009}main{margin:0;padding:20px 16px}}"""


def html_page(body):
    return web.Response(content_type="text/html", text=f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>The Pitstop</title>
<link rel="icon" href="https://pitboss.craftyplayz.com/static/favicon.svg" type="image/svg+xml">
<link rel="preconnect" href="https://fonts.googleapis.com"><link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=Cinzel:wght@600;700&display=swap" rel="stylesheet">
<style>{CSS}</style></head><body>{body}</body></html>""")


def nav_link(tab, active):
    slug, label = tab[0], tab[1]
    return f'<a class="nav{" on" if slug == active else ""}" href="/{slug}"><svg viewBox="0 0 24 24">{ICONS.get(slug, "")}</svg>{label}</a>'


def layout(active, user, body):
    slug, label, subtitle, _ = BY_SLUG[active]
    return html_page(f"""<div id="top"><button onclick="side.classList.toggle('open')" aria-label="Menu">☰</button><b style="font:700 16px Cinzel,serif;color:var(--gold)">THE PITSTOP</b></div>
<nav id="side"><div class="logo">THE PITSTOP</div>{''.join(nav_link(t, active) for t in TABS)}
<div class="pin">{''.join(nav_link(t, active) for t in PINNED)}</div>
<div class="who"><b>{html.escape(user["name"])}</b><a href="/logout">Log out</a></div></nav>
<main><h1>{label}</h1><p class="sub">{subtitle}</p>{body}</main>""")


# ---- routes ----

async def index(request):
    raise web.HTTPFound("/" + TABS[0][0])


async def tab_page(request):
    tab = BY_SLUG.get(request.match_info["tab"])
    if not tab:
        raise web.HTTPNotFound()
    user = session(request)
    if not user:
        return html_page('<div class="solo"><div class="logo">THE PITSTOP</div>'
                         + card("Log in", "<p>You need Manage Server on the Discord server to change the bot's settings.</p>"
                                '<a class="btn" href="/login">Log in with Discord</a>') + "</div>")
    saved = '<p class="ok">Saved. The bot uses the new settings straight away.</p>' if "saved" in request.query else ""
    return layout(tab[0], user, saved + await tab[3](request))


def check_post(request):
    """The logged-in user, for a form posted from this site."""
    user = session(request)
    # SameSite=Lax already keeps the cookie off cross-site posts; this also blocks a post from another site we host
    if not user or request.headers.get("Origin") != request.app["url"]:
        raise web.HTTPForbidden()
    return user


async def save(request):
    app, user = request.app, check_post(request)
    posted = await request.post()
    channels = await guild_channels(app)
    names = {c["id"]: c["name"] for c in channels}
    new = changes(posted, channels)
    if new.get("patch_notes_id") and new["patch_notes_id"] != db.get_setting(app["db"], "patch_notes_id"):
        db.set_setting(app["db"], "patch_notes_last", 0)  # same backfill /setup does; the bot's 10-minute check posts it
    for key, value in new.items():
        if value == (db.get_setting(app["db"], key) or ""):
            continue
        db.set_setting(app["db"], key, value)
        shown = "changed" if key == "welcome_message" else f"set to #{names.get(value, value)}" if value else "cleared"
        db.log_dash(app["db"], int(time.time()), user["name"], f"{LABELS[key]} {shown}")
    tab = posted.get("tab") if posted.get("tab") in BY_SLUG else TABS[0][0]
    raise web.HTTPFound(f"/{tab}?saved")


async def voice_unlock(request):
    app, user = request.app, check_post(request)
    password = (await request.post()).get("password", "")
    if not app["voice_password"] or not hmac.compare_digest(password.encode(), app["voice_password"].encode()):
        db.log_dash(app["db"], int(time.time()), user["name"], "Wrong voice tab password")
        raise web.HTTPFound("/voice?wrong")
    db.log_dash(app["db"], int(time.time()), user["name"], "Unlocked the voice tab")
    response = web.HTTPFound("/voice")
    response.set_cookie("voice", sign({"id": user["id"], "exp": time.time() + VOICE_TTL}, app["secret"]),
                        max_age=VOICE_TTL, httponly=True, secure=app["secure"], samesite="Lax")
    raise response


async def voice_lock(request):
    response = web.HTTPFound("/voice")
    response.del_cookie("voice")
    raise response


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
        return html_page('<div class="solo"><div class="logo">THE PITSTOP</div>'
                         + card("No access", "<p>You need Manage Server on the Discord server to use this.</p>") + "</div>")
    # shortcut: permission is checked at login only, so someone who loses Manage Server keeps access until the session ends (12 h)
    token = sign({"id": me["id"], "name": me.get("global_name") or me["username"], "exp": time.time() + SESSION_TTL}, app["secret"])
    response = web.HTTPFound("/")
    response.set_cookie("session", token, max_age=SESSION_TTL, httponly=True, secure=app["secure"], samesite="Lax")
    response.del_cookie("state")
    raise response


async def logout(request):
    response = web.HTTPFound("/")
    response.del_cookie("session")
    response.del_cookie("voice")
    raise response


def make_app():
    # docker compose passes an unset variable as "", and an empty secret would make session cookies forgeable
    if missing := [k for k in ("DISCORD_TOKEN", "GUILD_ID", "DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET") if not os.environ.get(k)]:
        raise SystemExit(f"dash: set {', '.join(missing)} (client ID and secret are in Developer Portal > your app > OAuth2)")
    app = web.Application()
    app["db"] = db.connect(os.environ.get("DB_PATH", "data/pitboss.db"))
    app["token"], app["guild_id"] = os.environ["DISCORD_TOKEN"], int(os.environ["GUILD_ID"])
    app["client_id"] = os.environ["DISCORD_CLIENT_ID"]
    app["secret"] = os.environ["DISCORD_CLIENT_SECRET"]  # also signs the session cookie
    app["voice_password"] = os.environ.get("VOICE_PASSWORD", "")  # empty keeps the voice tab locked for everyone
    app["url"] = os.environ.get("DASH_URL", "https://pitstop.craftyplayz.com").rstrip("/")
    app["secure"] = app["url"].startswith("https://")

    async def start(app):
        app["http"] = aiohttp.ClientSession()

    async def stop(app):
        await app["http"].close()

    app.on_startup.append(start)
    app.on_cleanup.append(stop)
    # fixed routes first: /{tab} would match them too
    app.add_routes([web.get("/", index), web.post("/save", save), web.get("/login", login),
                    web.get("/callback", callback), web.get("/logout", logout),
                    web.post("/voice/unlock", voice_unlock), web.get("/voice/lock", voice_lock),
                    web.get("/{tab}", tab_page)])
    return app


if __name__ == "__main__":
    web.run_app(make_app(), port=PORT)
