"""The Pitstop: The Pitboss's control panel. Log in with Discord (needs Manage Server) and change the bot's settings.
Run: python dash.py

The bot reads every setting from the shared database when it uses it, so changes apply without a restart."""
import base64
import csv
import hashlib
import hmac
import html
import io
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import aiohttp
from aiohttp import web

from cogs.welcome import load as load_welcome
from core.embeds import LIMITS, clean as clean_embed
from core import db
from core.events import CATEGORIES, default_categories

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
LABELS = {key: label for key, label, _ in CHANNELS} | {"welcome_embed": "Welcome message"}
BOT_AVATAR = "https://pitboss.craftyplayz.com/static/pitboss-512.png"
DEFAULT_AVATAR = "https://cdn.discordapp.com/embed/avatars/0.png"
LOG_PAGE = 100  # events per page in the Logs tab
EXPORT_MAX = 50000  # rows in one CSV download
IMAGE_EXT = (".png", ".jpg", ".jpeg", ".gif", ".webp")
SAFE_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp",
              ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime", ".mp3": "audio/mpeg",
              ".ogg": "audio/ogg", ".wav": "audio/wav"}


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
    if form.get("embed") == "welcome":
        out["welcome_embed"] = json.dumps(clean_embed(form), ensure_ascii=False)
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

def embed_editor(name, cfg, sample, prefix="embed_"):
    """Form fields for an embed (core.embeds), next to a live preview of how Discord will show it.
    sample fills the placeholders in the preview: name, server, count and avatar."""
    e = html.escape

    def text(key, label, rows=0, hint=""):
        attrs = f'id="{prefix}{key}" name="{prefix}{key}" maxlength="{LIMITS[key]}" placeholder="{e(hint)}"'
        field = f'<textarea {attrs} rows="{rows}">{e(cfg.get(key, ""))}</textarea>' if rows else f'<input {attrs} value="{e(cfg.get(key, ""))}">'
        return f'<label for="{prefix}{key}">{label}</label>{field}'

    def check(key, label):
        return f'<label class="check"><input type="checkbox" name="{prefix}{key}" value="1"{" checked" if cfg.get(key) else ""}>{label}</label>'

    inserts = "".join(f'<button type="button" class="ins" data-ins="{{{p}}}">{{{p}}}</button>' for p in ("user", "name", "server", "count"))
    controls = (f'<input type="hidden" name="embed" value="{name}">'
                + text("content", "Message text (above the embed; put {user} here to ping them)")
                + check("show_author", "Show their name and picture at the top") + text("author", "Author line", hint="{name}")
                + text("title", "Title") + text("description", "Description", rows=6)
                + f'<label for="{prefix}color">Colour</label><input type="color" id="{prefix}color" name="{prefix}color" value="{e(cfg.get("color", "#F0C35A"))}">'
                + check("thumbnail", "Show their profile picture on the right")
                + f'<label for="{prefix}image">Big image (https link)</label><input id="{prefix}image" name="{prefix}image" type="url" maxlength="2000" value="{e(cfg.get("image", ""))}" placeholder="https://...">'
                + text("footer", "Footer") + check("timestamp", "Show the time in the footer")
                + f'<p class="phs">Insert where you typed: {inserts}</p>'
                + "<p><small>{user} pings them in the message text (inside the embed it shows but doesn't ping). "
                  "Formatting works like Discord: **bold**, *italic*, __underline__, ~~strike~~, `code`, # Heading, &gt; quote, [link](https://...).</small></p>")
    preview = f"""<div class="dc"><div class="dc-msg"><img class="dc-av" src="{BOT_AVATAR}" alt="">
<div class="dc-body"><div><span class="dc-name">The Pitboss</span><span class="dc-bot">APP</span><span class="dc-time">Today at <span class="pv-now"></span></span></div>
<div class="dc-content pv-content"></div><div class="dc-embed pv-embed"><div class="dc-emain">
<div class="dc-author pv-author"><img src="{e(sample["avatar"])}" alt=""><span class="pv-author-name"></span></div>
<div class="dc-title pv-title"></div><div class="dc-desc pv-desc"></div><img class="dc-image pv-image" alt=""><div class="dc-footer pv-footer"></div></div>
<img class="dc-thumb pv-thumb" src="{e(sample["avatar"])}" alt=""></div></div></div></div>"""
    return (f'<div class="ed embed-editor" data-p="{prefix}" data-sample="{e(json.dumps(sample))}"><div>{controls}</div>'
            f'<div class="pv"><label>Preview (how it looks in Discord)</label>{preview}</div></div>')


async def welcome_tab(request):
    app, user = request.app, session(request)
    guild = await discord_get(app, f"/guilds/{app['guild_id']}?with_counts=true", f"Bot {app['token']}")
    sample = {"name": user["name"], "server": guild["name"], "count": guild.get("approximate_member_count", 0),
              "avatar": user.get("avatar") or DEFAULT_AVATAR}
    return form("welcome", card("Welcome channel", channel_select(app, await guild_channels(app), "welcome_channel_id"))
                + card("Welcome message", embed_editor("welcome", load_welcome(app["db"]), sample))) \
        + soon("Role menus: members pick roles with buttons", "Rank roles from linked Deadlock accounts") + EDITOR_JS


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


def log_filters(query):
    """The Logs tab's filters from the URL. No filter submitted yet means the default categories."""
    picked = [c for c in query.getall("c", []) if c in CATEGORIES] if "f" in query else default_categories()
    tz = int(query.get("tz", "0")) if query.get("tz", "0").lstrip("-").isdigit() else 0

    def stamp(name):
        # datetime-local is the viewer's own time; tz is their offset from JS getTimezoneOffset (minutes behind UTC)
        try:
            return int(datetime.strptime(query.get(name, ""), "%Y-%m-%dT%H:%M").replace(tzinfo=timezone.utc).timestamp()) + tz * 60
        except ValueError:
            return None
    return {"categories": picked, "user": query.get("user", "").strip(), "channel": query.get("channel", "").strip(),
            "text": query.get("q", "").strip(), "since": stamp("from"), "until": stamp("to")}


def show_file(f):
    if not f.get("file"):
        link = f' <a href="{html.escape(f["url"])}" rel="noreferrer" target="_blank">Discord link</a> (may have expired)' if f.get("url") else ""
        return f'<li>{html.escape(f.get("name", "file"))} (not saved{", too big" if f.get("size", 0) > 25 << 20 else ""}){link}</li>'
    src = "/logs/file/" + html.escape(f["file"])
    image = f'<a href="{src}" target="_blank"><img src="{src}" alt="" loading="lazy"></a>' if f["file"].lower().endswith(IMAGE_EXT) else ""
    return f'<li>{image}<a href="{src}" target="_blank">{html.escape(f.get("name") or f["file"])}</a></li>'


def event_row(r):
    label, colour, _ = CATEGORIES.get(r["category"], (r["category"], "#8190a3", True))
    data = json.loads(r["data"] or "{}")
    e = html.escape
    bits = []
    if r["user_name"] or r["user_id"]:
        bits.append(f'<b>User</b> {e(r["user_name"] or "")} <code>{r["user_id"] or ""}</code>')
    if r["channel_name"] or r["channel_id"]:
        bits.append(f'<b>Channel</b> #{e(r["channel_name"] or "")} <code>{r["channel_id"] or ""}</code>')
    if r["message_id"]:
        jump = f' <a href="{e(data["jump"])}" target="_blank">open in Discord</a>' if data.get("jump") else ""
        bits.append(f'<b>Message</b> <code>{r["message_id"]}</code>{jump}')
    detail = f'<p class="meta">{" · ".join(bits)}</p>' if bits else ""
    if "before" in data:
        detail += f'<div class="ba"><div><b>Before</b><pre>{e(str(data["before"] or "(empty)"))}</pre></div><div><b>After</b><pre>{e(data.get("content") or "(empty)")}</pre></div></div>'
    elif data.get("content"):
        detail += f'<b>Content</b><pre>{e(data["content"])}</pre>'
    if data.get("changes"):
        detail += '<table><tr><th>What</th><th>Before</th><th>After</th></tr>' + "".join(
            f'<tr><td>{e(k.replace("_", " "))}</td><td>{e(str(a))}</td><td>{e(str(b))}</td></tr>' for k, (a, b) in data["changes"].items()) + "</table>"
    pics = [(n, data[k]) for n, k in (("Before", "before_file"), ("After", "after_file"), ("Avatar", "avatar")) if data.get(k)]
    if pics:
        detail += '<div class="pics">' + "".join(f'<figure><img src="/logs/file/{e(f)}" alt=""><figcaption>{n}</figcaption></figure>' for n, f in pics) + "</div>"
    if data.get("files"):
        detail += '<b>Files</b><ul class="files">' + "".join(show_file(f) for f in data["files"]) + "</ul>"
    for m in data.get("messages", []):
        detail += f'<pre>{e(str(m.get("author") or "unknown"))}: {e(m.get("content") or "(sent before logging started)")}</pre>'
    detail += f'<details class="raw"><summary>Raw data</summary><pre>{e(json.dumps(dict(r) | {"data": data}, indent=2, ensure_ascii=False))}</pre></details>'
    return (f'<details class="ev"><summary><time data-t="{r["at"]}">{datetime.fromtimestamp(r["at"], timezone.utc):%Y-%m-%d %H:%M} UTC</time>'
            f'<span class="badge" style="--c:{colour}">{e(label)}</span><span class="sm">{e(r["summary"])}</span></summary>'
            f'<div class="det">{detail}</div></details>')


async def logs_tab(request):
    app, query = request.app, request.query
    filters = log_filters(query)
    before = query.get("before", "")
    rows, total = db.find_events(app["db"], filters["categories"], filters["user"], filters["channel"], filters["text"],
                                 filters["since"], filters["until"], int(before) if before.isdigit() else None, LOG_PAGE)
    chips = "".join(f'<label class="chip" style="--c:{colour}"><input type="checkbox" name="c" value="{key}"'
                    f'{" checked" if key in filters["categories"] else ""}><span>{label}</span></label>'
                    for key, (label, colour, _) in CATEGORIES.items())
    v = lambda name: html.escape(query.get(name, ""))  # noqa: E731
    kept = [(k, val) for k, val in query.items() if k not in ("before", "format")]
    older = (f'<a class="btn ghost" href="/logs?{urlencode(kept + [("before", rows[-1]["id"])])}">Older →</a>'
             if len(rows) == LOG_PAGE else "")
    newest = f'<a class="btn ghost" href="/logs?{urlencode(kept)}">← Newest</a>' if before else ""
    filters_card = f"""<form method="get" action="/logs" id="lf" class="card"><input type="hidden" name="f" value="1"><input type="hidden" name="tz" id="tz">
<div class="chips">{chips}</div>
<div class="chiprow"><button type="button" class="link" data-all="1">Select all</button> · <button type="button" class="link" data-all="0">Select none</button></div>
<div class="fgrid"><div><label for="q">Search text</label><input id="q" name="q" value="{v('q')}" placeholder="Words in the event or message"></div>
<div><label for="user">User</label><input id="user" name="user" value="{v('user')}" placeholder="Name or ID"></div>
<div><label for="channel">Channel</label><input id="channel" name="channel" value="{v('channel')}" placeholder="Name or ID"></div>
<div><label for="from">From</label><input id="from" name="from" type="datetime-local" value="{v('from')}"></div>
<div><label for="to">To</label><input id="to" name="to" type="datetime-local" value="{v('to')}"></div></div>
<button class="btn" type="submit">Apply filters</button> <a class="btn ghost" href="/logs">Reset</a>
<a class="btn ghost" href="/logs/export?{urlencode(kept)}">Download CSV</a>
<label class="auto"><input type="checkbox" id="auto"> Auto-refresh every 15 s</label></form>"""
    script = """<script>
document.querySelectorAll('time[data-t]').forEach(t=>{t.textContent=new Date(t.dataset.t*1000).toLocaleString([], {dateStyle:'medium',timeStyle:'medium'})});
tz.value=new Date().getTimezoneOffset();
document.querySelectorAll('[data-all]').forEach(b=>b.onclick=()=>document.querySelectorAll('.chip input').forEach(i=>i.checked=b.dataset.all==='1'));
let A=false;try{A=localStorage.getItem('pitstop-auto')==='1'}catch(e){}auto.checked=A;
auto.onchange=()=>{try{localStorage.setItem('pitstop-auto',auto.checked?'1':'0')}catch(e){}location.reload()};
if(A&&!location.search.includes('before='))setTimeout(()=>location.reload(),15000);
</script>"""
    events = "".join(event_row(r) for r in rows) or '<p class="empty">No events match these filters.</p>'
    return (filters_card + f'<p class="count">{total:,} matching event{"s" if total != 1 else ""}. Click one for the details.</p>'
            + f'<div class="evs">{events}</div><div class="pager">{newest}{older}</div>' + script)


async def logs_export(request):
    if not session(request):
        raise web.HTTPForbidden()
    filters = log_filters(request.query)
    rows, _ = db.find_events(request.app["db"], filters["categories"], filters["user"], filters["channel"], filters["text"],
                             filters["since"], filters["until"], limit=EXPORT_MAX)
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["time_utc", "category", "kind", "user", "user_id", "channel", "channel_id", "message_id", "summary", "data"])
    for r in rows:
        w.writerow([datetime.fromtimestamp(r["at"], timezone.utc).isoformat(), r["category"], r["kind"], r["user_name"], r["user_id"],
                    r["channel_name"], r["channel_id"], r["message_id"], r["summary"], r["data"]])
    return web.Response(text=out.getvalue(), content_type="text/csv",
                        headers={"Content-Disposition": f'attachment; filename="pitstop-logs-{time.strftime("%Y%m%d-%H%M")}.csv"'})


async def log_file(request):
    """A file the Server Log saved. Only images, video and audio open in the browser; anything else downloads,
    and the sandbox header stops an uploaded page from running as this site."""
    if not session(request):
        raise web.HTTPForbidden()
    base = request.app["files"].resolve()
    path = (base / request.match_info["name"]).resolve()
    if path.parent != base or not path.is_file():
        raise web.HTTPNotFound()
    kind = SAFE_TYPES.get(path.suffix.lower())
    headers = {"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox", "Content-Type": kind or "application/octet-stream"}
    if not kind:
        headers["Content-Disposition"] = f'attachment; filename="{path.name}"'
    return web.FileResponse(path, headers=headers)


def panel_log(app, user, action):
    db.add_event(app["db"], int(time.time()), "panel_change", "panel", f"{user['name']} {action}",
                 user_id=int(user["id"]), user_name=user["name"])


ICONS = {
    "welcome": '<circle cx="9" cy="8" r="3.5"/><path d="M2 20c0-4 3-6 7-6s7 2 7 6M19 8v6M16 11h6"/>',
    "utility": '<rect x="3" y="3" width="7" height="7" rx="1.5"/><rect x="14" y="3" width="7" height="7" rx="1.5"/><rect x="3" y="14" width="7" height="7" rx="1.5"/><rect x="14" y="14" width="7" height="7" rx="1.5"/>',
    "leveling": '<path d="M4 20v-6M10 20V9M16 20V4M2 20h20"/>',
    "games": '<rect x="3" y="3" width="18" height="18" rx="4"/><circle cx="8.5" cy="8.5" r="1.2" fill="currentColor"/><circle cx="12" cy="12" r="1.2" fill="currentColor"/><circle cx="15.5" cy="15.5" r="1.2" fill="currentColor"/>',
    "voice": '<rect x="9" y="2" width="6" height="12" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v4M8 22h8"/>',
    "translate": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 3.8 5.5 3.8 9s-1.3 6.5-3.8 9c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3z"/>',
    "setup": '<circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M4.9 4.9 7 7M17 17l2.1 2.1M4.9 19.1 7 17M17 7l2.1-2.1"/>',
    "logs": '<path d="M6 3h9l4 4v14H6zM14 3v5h5M9 12h7M9 16h7"/>',
    "admin": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
}


async def admin_tab(request):
    raise web.HTTPFound("https://www.youtube.com/watch?v=dQw4w9WgXcQ")  # easter egg: told you not to touch
# Sidebar order, top to bottom: move a line to move its tab. (url slug, label, subtitle, page)
TABS = [
    ("welcome", "Welcome & Roles", "What new members see, and the roles they can pick", welcome_tab),
    ("utility", "Utility", "Handy everyday commands", utility_tab),
    ("leveling", "Leveling", "XP, levels and rewards", leveling_tab),
    ("games", "Games", "Fun stuff to play in the server", games_tab),
    ("voice", "Voice", "Transcripts and recordings of voice calls", voice_tab),
    ("translate", "Translate", "Automatic translation between languages", translate_tab),
    ("admin", "Admin (do not touch)", "", admin_tab),
]
# Always at the bottom of the sidebar, in this order.
PINNED = [
    ("setup", "Setup", "Which channels the bot uses", setup_tab),
    ("logs", "Logs", "Everything that happens in the server, newest first", logs_tab),
]
BY_SLUG = {t[0]: t for t in TABS + PINNED}

EDITOR_JS = r"""<script>
document.querySelectorAll('.embed-editor').forEach(ed=>{
const P=ed.dataset.p,S=JSON.parse(ed.dataset.sample),f=ed.closest('form'),$=c=>ed.querySelector('.pv-'+c);
const esc=s=>s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const MENTION='<span class="mention">@'+esc(S.name)+'</span>';
// placeholders first (the user mention as a marker), then escape, then Discord's markdown
const fill=s=>esc(s.replace(/\{user\}/g,'\u0001').replace(/\{name\}/g,S.name).replace(/\{server\}/g,S.server).replace(/\{count\}/g,S.count));
const md=s=>fill(s).replace(/```(?:\w*\n)?([\s\S]*?)```/g,'<pre>$1</pre>').replace(/`([^`\n]+)`/g,'<code>$1</code>')
 .replace(/^### (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h2>$1</h2>').replace(/^# (.*)$/gm,'<h1>$1</h1>').replace(/^&gt; (.*)$/gm,'<blockquote>$1</blockquote>')
 .replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/__(.+?)__/g,'<u>$1</u>').replace(/\*(.+?)\*/g,'<i>$1</i>').replace(/~~(.+?)~~/g,'<s>$1</s>')
 .replace(/\|\|(.+?)\|\|/g,'<span class="spoiler">$1</span>').replace(/\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noreferrer">$1</a>')
 .replace(/\u0001/g,MENTION).replace(/\n/g,'<br>').replace(/(<\/h\d>|<\/blockquote>|<\/pre>)<br>/g,'$1');
const plain=s=>fill(s).replace(/\u0001/g,'@'+esc(S.name));
const v=k=>{const el=f.elements[P+k];return el.type==='checkbox'?el.checked:el.value};
const now=new Date().toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});$('now').textContent=now;
function upd(){
 const show=(c,html)=>{$(c).innerHTML=html;$(c).hidden=!html};
 show('content',md(v('content')));show('title',md(v('title')));show('desc',md(v('description')));
 $('embed').style.borderColor=v('color');$('author').hidden=!v('show_author');$('author-name').innerHTML=plain(v('author')||'{name}');
 $('thumb').hidden=!v('thumbnail');
 const im=v('image');$('image').hidden=!/^https:\/\/\S+$/.test(im);if(!$('image').hidden&&$('image').getAttribute('src')!==im)$('image').src=im;
 const ft=v('footer'),ts=v('timestamp');show('footer',(ft?plain(ft):'')+(ft&&ts?' • ':'')+(ts?'Today at '+now:''));
}
let last=null;ed.querySelectorAll('input:not([type]),textarea').forEach(el=>el.addEventListener('focus',()=>last=el));
ed.querySelectorAll('[data-ins]').forEach(b=>b.onclick=()=>{const el=last||f.elements[P+'description'],t=b.dataset.ins,s=el.selectionStart??el.value.length;
 el.value=el.value.slice(0,s)+t+el.value.slice(el.selectionEnd??s);el.focus();el.selectionStart=el.selectionEnd=s+t.length;upd()});
f.addEventListener('input',upd);f.addEventListener('change',upd);upd();
});
</script>"""

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
.btn.ghost{background:none;color:var(--tx);border:1px solid var(--line)} .link{background:none;border:0;color:var(--gold);cursor:pointer;font:inherit;padding:0}
.chips{display:flex;flex-wrap:wrap;gap:8px}.chip{margin:0;text-transform:none;letter-spacing:0}.chip input{display:none}.chiprow{margin:8px 0 4px;font-size:12px;color:var(--mu)}
.chip span{display:inline-block;padding:5px 11px;border-radius:99px;border:1px solid var(--line);color:var(--mu);cursor:pointer;font-size:13px;user-select:none}
.chip input:checked+span{border-color:var(--c);color:var(--c);background:color-mix(in srgb,var(--c) 12%,transparent)}
.chip input:focus-visible+span{outline:2px solid var(--gold)}
.fgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:0 12px}
.auto{display:inline-flex;align-items:center;gap:6px;margin:12px 0 0 8px;text-transform:none;letter-spacing:0;font-size:13px}.auto input{width:auto}
.count{color:var(--mu);margin:-4px 0 10px}.empty{color:var(--mu);padding:20px 0}
.evs{border:1px solid var(--line);border-radius:var(--r);overflow:hidden;background:var(--card)}
.ev{border-bottom:1px solid var(--line)}.ev:last-child{border-bottom:0}
.ev>summary{display:grid;grid-template-columns:150px 130px minmax(0,1fr);gap:10px;align-items:baseline;padding:9px 14px;cursor:pointer;list-style:none}
.ev>summary::-webkit-details-marker{display:none}.ev>summary:hover{background:#1a212c}.ev[open]>summary{background:#1c2430}
.ev time{color:var(--mu);font-size:12px;white-space:nowrap}.sm{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.ev[open] .sm{white-space:normal}
.badge{justify-self:start;font-size:11px;padding:2px 8px;border-radius:99px;color:var(--c);background:color-mix(in srgb,var(--c) 14%,transparent);white-space:nowrap}
.det{padding:4px 14px 14px;font-size:13px}.det b{color:var(--mu);font-weight:500}.meta{color:var(--mu);margin:6px 0 10px}
pre{white-space:pre-wrap;word-break:break-word;background:var(--bg);border:1px solid var(--line);border-radius:8px;padding:8px 10px;margin:4px 0 10px;font:12px/1.5 ui-monospace,Consolas,monospace}
.ba{display:grid;grid-template-columns:1fr 1fr;gap:10px}.det table{margin:4px 0 10px}
.pics{display:flex;gap:14px;margin:6px 0 10px}.pics img{width:96px;height:96px;border-radius:50%;object-fit:cover;border:1px solid var(--line)}
figcaption{text-align:center;color:var(--mu);font-size:12px}
.files{list-style:none;padding:0}.files li{margin:6px 0}.files img{display:block;max-width:320px;max-height:240px;border-radius:8px;margin-bottom:4px}
.raw summary{color:var(--mu);cursor:pointer;font-size:12px}.pager{display:flex;justify-content:space-between;margin:14px 0}
main.wide{max-width:none}
@media(max-width:820px){.ev>summary{grid-template-columns:1fr auto}.ev .sm{grid-column:1/-1}.ba{grid-template-columns:1fr}}
label.check{display:flex;align-items:center;gap:8px;text-transform:none;letter-spacing:0;font-size:13px;color:var(--tx);cursor:pointer}label.check input{width:auto}
input[type=color]{height:38px;padding:3px;cursor:pointer}.phs{margin:12px 0 4px;font-size:12px;color:var(--mu)}
.ins{background:var(--bg);border:1px solid var(--line);color:var(--gold);border-radius:6px;padding:2px 7px;margin:0 2px;cursor:pointer;font:12px ui-monospace,Consolas,monospace}
.ed{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:24px;align-items:start}.ed .pv{position:sticky;top:16px}
.dc{background:#313338;border-radius:8px;padding:16px 16px 20px 0;font:16px/1.375 "gg sans","Noto Sans",Inter,system-ui,sans-serif;color:#dbdee1}
.dc-msg{display:flex;gap:16px;padding-left:16px}.dc-av{width:40px;height:40px;border-radius:50%;flex:none}.dc-body{min-width:0;flex:1}
.dc-name{font-weight:500;color:#f2f3f5;margin-right:4px}.dc-bot{background:#5865f2;color:#fff;font-size:10px;font-weight:600;padding:1px 4px;border-radius:3px;vertical-align:2px;margin-right:6px}
.dc-time{font-size:12px;color:#949ba4}.dc-content{word-wrap:break-word}
.dc-embed{display:flex;gap:16px;max-width:432px;background:#2b2d31;border-left:4px solid;border-radius:4px;padding:8px 16px 16px 12px;margin-top:4px}
.dc-emain{min-width:0;flex:1}.dc-author{display:flex;align-items:center;gap:8px;margin-top:8px;font-size:14px;font-weight:600;color:#f2f3f5}.dc-author img{width:24px;height:24px;border-radius:50%}
.dc-title{margin-top:8px;font-size:16px;font-weight:600;color:#f2f3f5}.dc-desc{margin-top:8px;font-size:14px;word-wrap:break-word}
.dc-thumb{width:80px;height:80px;border-radius:4px;object-fit:cover;margin-top:8px;flex:none}.dc-image{display:block;max-width:100%;border-radius:4px;margin-top:16px}
.dc-footer{margin-top:8px;font-size:12px;color:#b5bac1}
.dc .mention{background:rgba(88,101,242,.3);color:#c9cdfb;border-radius:3px;padding:0 2px;font-weight:500}
.dc code{background:#1e1f22;border-radius:4px;padding:0 3px;font-size:85%}.dc pre{background:#1e1f22;border:1px solid #1e1f22;color:#dbdee1;margin:4px 0}
.dc h1,.dc h2,.dc h3{color:#f2f3f5;font-weight:700;margin:8px 0 4px;line-height:1.3}.dc h1{font-size:24px}.dc h2{font-size:20px}.dc h3{font-size:16px}
.dc blockquote{border-left:4px solid #4e5058;padding-left:12px}.dc a{color:#00a8fc;text-decoration:none}
.dc .spoiler{background:#1e1f22;color:transparent;border-radius:3px}.dc .spoiler:hover{color:inherit}
[hidden]{display:none!important}
@media(max-width:1100px){.ed{grid-template-columns:1fr}.ed .pv{position:static}}
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
<main{' class="wide"' if active in ("logs", "welcome") else ""}><h1>{label}</h1><p class="sub">{subtitle}</p>{body}</main>""")


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
        shown = f"#{names.get(value, value)}" if value else "not set"
        panel_log(app, user, f"set {LABELS[key]}: {shown}" if key != "welcome_embed" else "changed the welcome message")
    tab = posted.get("tab") if posted.get("tab") in BY_SLUG else TABS[0][0]
    raise web.HTTPFound(f"/{tab}?saved")


async def voice_unlock(request):
    app, user = request.app, check_post(request)
    password = (await request.post()).get("password", "")
    if not app["voice_password"] or not hmac.compare_digest(password.encode(), app["voice_password"].encode()):
        panel_log(app, user, "typed a wrong Voice tab password")
        raise web.HTTPFound("/voice?wrong")
    panel_log(app, user, "unlocked the Voice tab")
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
    avatar = f"https://cdn.discordapp.com/avatars/{me['id']}/{me['avatar']}.png" if me.get("avatar") else None
    token = sign({"id": me["id"], "name": me.get("global_name") or me["username"], "avatar": avatar,
                  "exp": time.time() + SESSION_TTL}, app["secret"])
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
    app["files"] = Path(os.environ.get("DB_PATH", "data/pitboss.db")).parent / "logfiles"  # saved by cogs/logs.py

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
                    web.get("/logs/export", logs_export), web.get("/logs/file/{name}", log_file),
                    web.get("/{tab}", tab_page)])
    return app


if __name__ == "__main__":
    web.run_app(make_app(), port=PORT)
