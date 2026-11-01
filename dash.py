"""The Pitstop: The Pitboss's control panel. Log in with Discord (needs Manage Server) and change the bot's settings.
Run: python dash.py

The bot reads every setting from the shared database when it uses it, so changes apply without a restart."""
import asyncio
import base64
import csv
import hashlib
import hmac
import html
import io
import json
import os
import secrets
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlencode

import aiohttp
from aiohttp import web

from cogs.welcome import load as load_welcome
from core import rolemenus
from core.embeds import GOLD, LIMITS, clean as clean_embed, render as render_embed
from core import db
from core.events import CATEGORIES, default_categories
from core.voicerec import DEFAULT_MODEL, MODELS, VOICE_DIR, clock, short_name

PORT = int(os.environ.get("DASH_PORT", 8643))
DISCORD = "https://discord.com/api/v10"
SESSION_TTL = 12 * 3600
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
CALL_STATUS = {"recording": '<span class="ok">● Recording</span>', "done": "Done", "interrupted": '<span class="bad">Cut short</span> (bot restarted)'}
SPEAKER_COLOURS = ["#5ab0f0", "#F0C35A", "#4fc98a", "#c792ea", "#f09a5a", "#5ad1c9", "#f05aa8", "#b0c45a"]
# <time data-t> in the viewer's own time zone
LOCAL_TIMES = "document.querySelectorAll('time[data-t]').forEach(t=>{t.textContent=new Date(t.dataset.t*1000).toLocaleString([], {dateStyle:'medium',timeStyle:'medium'})});"
# The call player: CLIPS is [[clip id, start ms, length ms]]. Each clip is fetched and started at its place in the
# call (Web Audio), 15 s ahead of the playhead, so overlapping speakers play together. `gen` drops clips that finish
# loading after a pause or seek. While live, the page reloads unless something is playing or being searched.
CALL_JS = """let ctx,gain,playing=false,pos=0,anchor=0,gen=0,srcs=[],queued=new Set(),dragging=false,lit=null;
const cache=new Map(),$=id=>document.getElementById(id),lines=[...document.querySelectorAll('.ln')];
const fmt=ms=>{let s=Math.max(0,Math.floor(ms/1000)),h=Math.floor(s/3600),m=Math.floor(s/60)%60;s%=60;return(h?h+':'+String(m).padStart(2,'0'):m)+':'+String(s).padStart(2,'0')};
const now=()=>playing?pos+(ctx.currentTime-anchor)*1000:pos;
function load(id){if(!cache.has(id))cache.set(id,fetch('/voice/clip/'+id+'.ogg').then(r=>r.arrayBuffer()).then(b=>ctx.decodeAudioData(b)));return cache.get(id)}
function queue(){const t=now(),g=gen;for(const[id,s,d]of CLIPS){
 if(s+d<t-5000)cache.delete(id);
 if(queued.has(id)||s+d<=t||s>t+15000)continue;queued.add(id);
 load(id).then(buf=>{if(g!==gen)return;const src=ctx.createBufferSource(),at=anchor+(s-pos)/1000;src.buffer=buf;src.connect(gain);
  src.start(Math.max(at,ctx.currentTime),Math.max(0,ctx.currentTime-at));srcs.push(src)}).catch(()=>{})}}
function play(){if(!ctx){ctx=new AudioContext();gain=ctx.createGain();gain.connect(ctx.destination)}ctx.resume();
 if(pos>=LEN)pos=0;anchor=ctx.currentTime;playing=true;queue();ui()}
function pause(){pos=now();playing=false;gen++;srcs.forEach(s=>{try{s.stop()}catch(e){}});srcs=[];queued.clear();ui()}
function seek(ms){const p=playing;if(p)pause();pos=Math.min(Math.max(0,ms),LEN);if(p)play();ui()}
function ui(){const t=now();$('cur').textContent=fmt(t);$('left').textContent='-'+fmt(LEN-t);if(!dragging)$('bar').value=t;
 $('pp').textContent=playing?'❚❚':'▶';
 const on=lines.filter(l=>+l.dataset.s<=t&&t<+l.dataset.e+500);
 lines.forEach(l=>l.classList.toggle('on',on.includes(l)));
 const newest=on.at(-1)||null;  // people talking over each other all light up; follow the one who started last
 if(newest!==lit){lit=newest;if(newest&&playing&&$('follow').checked)newest.scrollIntoView({block:'center',behavior:'smooth'})}}
setInterval(()=>{if(playing){if(now()>=LEN){pause();pos=LEN}else queue()}ui()},250);
$('pp').onclick=()=>playing?pause():play();$('back').onclick=()=>seek(now()-15000);$('fwd').onclick=()=>seek(now()+15000);
$('bar').oninput=()=>{dragging=true;$('cur').textContent=fmt(+$('bar').value)};$('bar').onchange=()=>{dragging=false;seek(+$('bar').value)};
const jump=ms=>{seek(ms);if(!playing)play()};
document.querySelectorAll('[data-seek]').forEach(b=>b.onclick=()=>jump(+b.dataset.seek));lines.forEach(l=>l.onclick=()=>jump(+l.dataset.s));
document.querySelectorAll('time[data-tt]').forEach(t=>{t.textContent=new Date(t.dataset.tt*1000).toLocaleTimeString()});
$('find').oninput=()=>{const q=$('find').value.toLowerCase();lines.forEach(l=>l.hidden=!!q&&!l.textContent.toLowerCase().includes(q));
 document.querySelectorAll('.msg').forEach(m=>m.hidden=![...m.querySelectorAll('.ln')].some(l=>!l.hidden));
 document.querySelectorAll('.jl').forEach(j=>j.hidden=!!q)};
if(LIVE)setInterval(()=>{if(!playing&&!$('find').value)location.reload()},5000);"""


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


async def discord_send(app, method, path, payload=None):
    """A bot call that changes something: (status, JSON body or None). Waits out rate limits a few times."""
    for _ in range(4):
        async with app["http"].request(method, DISCORD + path, json=payload, headers={"Authorization": f"Bot {app['token']}"}) as r:
            body = await r.json() if r.content_type == "application/json" else None
            if r.status != 429:
                return r.status, body
            await asyncio.sleep(min(float((body or {}).get("retry_after", 1)), 10))
    return r.status, body


def discord_error(status, body):
    return f"Discord said {status}: {(body or {}).get('message', 'no details')}"


async def guild_info(app):
    return await discord_get(app, f"/guilds/{app['guild_id']}?with_counts=true", f"Bot {app['token']}")


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

def embed_editor(name, cfg, sample, prefix="embed_", for_member=True):
    """Form fields for an embed (core.embeds), next to a live preview of how Discord will show it.
    sample fills the placeholders in the preview: name, server, count and avatar. for_member: the message is about
    one member (a welcome), so {user} and {name} make sense."""
    e = html.escape

    def text(key, label, rows=0, hint=""):
        attrs = f'id="{prefix}{key}" name="{prefix}{key}" maxlength="{LIMITS[key]}" placeholder="{e(hint)}"'
        field = f'<textarea {attrs} rows="{rows}">{e(cfg.get(key, ""))}</textarea>' if rows else f'<input {attrs} value="{e(cfg.get(key, ""))}">'
        return f'<label for="{prefix}{key}">{label}</label>{field}'

    def check(key, label):
        return f'<label class="check"><input type="checkbox" name="{prefix}{key}" value="1"{" checked" if cfg.get(key) else ""}>{label}</label>'

    places = ("user", "name", "server", "count") if for_member else ("server", "count")
    link_channel = ('<select class="ins-ch" aria-label="Link a channel"><option value="">Link a channel…</option>'
                    + "".join(f'<option value="{i}">{e(n)}</option>' for i, n in sample.get("channels", {}).items()) + "</select>")
    inserts = "".join(f'<button type="button" class="ins" data-ins="{{{p}}}">{{{p}}}</button>' for p in places)
    controls = (f'<input type="hidden" name="embed" value="{name}">'
                + text("content", "Message text (above the embed; put {user} here to ping them)" if for_member else "Message text (above the embed)")
                + (check("show_author", "Show their name and picture at the top") + text("author", "Author line", hint="{name}") if for_member else "")
                + text("title", "Title") + text("description", "Description", rows=6)
                + f'<label for="{prefix}color">Colour</label><input type="color" id="{prefix}color" name="{prefix}color" value="{e(cfg.get("color", "#F0C35A"))}">'
                + (check("thumbnail", "Show their profile picture on the right") if for_member else "")
                + f'<label for="{prefix}image">Big image (https link)</label><input id="{prefix}image" name="{prefix}image" type="url" maxlength="2000" value="{e(cfg.get("image", ""))}" placeholder="https://...">'
                + text("footer", "Footer") + check("timestamp", "Show the time in the footer")
                + f'<p class="phs">Insert where you typed: {inserts} {link_channel}</p>'
                + ("<p><small>{user} pings them in the message text (inside the embed it shows but doesn't ping). " if for_member else "<p><small>")
                + ("Formatting works like Discord: **bold**, *italic*, __underline__, ~~strike~~, `code`, # Heading, &gt; quote, [link](https://...). Channel links are clickable in the message text and description.</small></p>"))
    preview = f"""<div class="dc"><div class="dc-msg"><img class="dc-av" src="{BOT_AVATAR}" alt="">
<div class="dc-body"><div><span class="dc-name">The Pitboss</span><span class="dc-bot">APP</span><span class="dc-time">Today at <span class="pv-now"></span></span></div>
<div class="dc-content pv-content"></div><div class="dc-embed pv-embed"><div class="dc-emain">
<div class="dc-author pv-author"><img src="{e(sample["avatar"])}" alt=""><span class="pv-author-name"></span></div>
<div class="dc-title pv-title"></div><div class="dc-desc pv-desc"></div><img class="dc-image pv-image" alt=""><div class="dc-footer pv-footer"></div></div>
<img class="dc-thumb pv-thumb" src="{e(sample["avatar"])}" alt=""></div><div class="pv-extra"></div></div></div></div>"""
    return (f'<div class="ed embed-editor" data-p="{prefix}" data-sample="{e(json.dumps(sample))}"><div>{controls}</div>'
            f'<div class="pv"><label>Preview (how it looks in Discord)</label>{preview}</div></div>')


async def preview_sample(app, user):
    guild = await guild_info(app)
    # channels a message can link to, as Discord shows them: #text or 🔊voice (categories can't be linked)
    channels = {c["id"]: ("🔊" if c["type"] in (2, 13) else "#") + c["name"] for c in await guild_channels(app) if c["type"] != 4}
    return {"name": user["name"], "server": guild["name"], "count": guild.get("approximate_member_count", 0),
            "avatar": user.get("avatar") or DEFAULT_AVATAR, "channels": channels}


def menus_card(app, channels):
    names = {c["id"]: c["name"] for c in channels}
    rows = "".join(
        f'<tr><td><a href="/rolemenu/{m["id"]}">{html.escape(json.loads(m["embed"]).get("title") or "Menu " + str(m["id"]))}</a></td>'
        f'<td>#{html.escape(names.get(str(m["channel_id"]), "deleted channel"))}</td><td>{rolemenus.MODES.get(m["mode"], m["mode"])}</td>'
        f'<td>{len(db.menu_options(app["db"], m["id"]))}</td><td>{"Posted" if m["message_id"] else "<span class=bad>Not posted</span>"}</td></tr>'
        for m in db.role_menus(app["db"]))
    table = (f'<table><tr><th>Menu</th><th>Channel</th><th>Style</th><th>Roles</th><th>Status</th></tr>{rows}</table>' if rows
             else "<p>No role menus yet. Make one and the bot posts it where you choose; members click to get or drop roles.</p>")
    return card("Role menus", table + '<a class="btn" href="/rolemenu/new">New role menu</a>')


async def welcome_tab(request):
    app, user = request.app, session(request)
    channels = await guild_channels(app)
    return form("welcome", card("Welcome channel", channel_select(app, channels, "welcome_channel_id"))
                + card("Welcome message", embed_editor("welcome", load_welcome(app["db"]), await preview_sample(app, user)))) \
        + menus_card(app, channels) + soon("Rank roles from linked Deadlock accounts") + EDITOR_JS


MENU_EMBED = {"content": "", "author": "", "title": "Pick your roles", "description": "Click a role to get it, and click it again to drop it.",
              "footer": "", "color": GOLD, "image": "", "show_author": False, "thumbnail": False, "timestamp": False}


async def menu_context(app):
    """What the role menu editor offers: (safe roles {id: name} highest first, every role {id: role}, text channels, custom emojis)."""
    bot, gid = f"Bot {app['token']}", app["guild_id"]
    if "bot_id" not in app["cache"]:
        app["cache"]["bot_id"] = (await discord_get(app, "/users/@me", bot))["id"]
    roles = await discord_get(app, f"/guilds/{gid}/roles", bot)
    me = await discord_get(app, f"/guilds/{gid}/members/{app['cache']['bot_id']}", bot)
    by_id = {r["id"]: r for r in sorted(roles, key=lambda r: -r["position"])}
    top = max((by_id[r]["position"] for r in me["roles"] if r in by_id), default=0)
    safe_roles = {i: r["name"] for i, r in by_id.items() if rolemenus.safe(r, gid, top)}
    channels = [c for c in await guild_channels(app) if c["type"] in TEXT]
    return safe_roles, by_id, channels, await discord_get(app, f"/guilds/{gid}/emojis", bot)


def option_row(o, safe_roles, roles):
    e = html.escape
    o = o or {"role_id": "", "emoji": "", "label": "", "description": ""}
    rid = str(o["role_id"])
    choices = "".join(f'<option value="{i}"{" selected" if i == rid else ""}>{e(n)}</option>' for i, n in safe_roles.items())
    if rid and rid not in safe_roles:  # saved earlier but no longer allowed: shown so the admin sees why saving fails
        choices += f'<option value="{e(rid)}" selected>{e(roles.get(rid, {}).get("name", "deleted role"))} (can\'t be given)</option>'
    return (f'<div class="opt"><select name="opt_role" aria-label="Role"><option value="">Pick a role</option>{choices}</select>'
            f'<input name="opt_emoji" list="emojis" maxlength="64" placeholder="Emoji" aria-label="Emoji" value="{e(o["emoji"] or "")}">'
            f'<input name="opt_label" maxlength="80" placeholder="Label (role name if empty)" aria-label="Label" value="{e(o["label"] or "")}">'
            f'<input name="opt_desc" class="m-dropdown" maxlength="100" placeholder="Description" aria-label="Description" value="{e(o["description"] or "")}">'
            '<span class="optb"><button type="button" class="ib" data-mv="-1" title="Move up">↑</button>'
            '<button type="button" class="ib" data-mv="1" title="Move down">↓</button><button type="button" class="ib" data-rm title="Remove">✕</button></span></div>')


async def rolemenu_page(request, menu_id=None, menu=None, options=None, cfg=None, message=""):
    """The role menu editor: from the database, or (after a failed save) from what the admin sent."""
    app, user = request.app, session(request)
    if not user:
        raise web.HTTPFound("/welcome")
    mid = menu_id or request.match_info["id"]
    if menu is None:
        if mid == "new":
            menu, options, cfg = {"mode": "buttons", "max_picks": 0, "button_style": "2"}, [None], MENU_EMBED
        else:
            row = db.get_menu(app["db"], int(mid))
            if not row:
                raise web.HTTPNotFound()
            menu, options, cfg = dict(row), db.menu_options(app["db"], int(mid)), {**MENU_EMBED, **json.loads(row["embed"])}
    safe_roles, roles, channels, emojis = await menu_context(app)
    e, mode = html.escape, menu.get("mode", "buttons")
    channel_opts = "".join(f'<option value="{c["id"]}"{" selected" if c["id"] == str(menu.get("channel_id", "")) else ""}>#{e(c["name"])}</option>' for c in channels)
    modes = "".join(f'<label class="check"><input type="radio" name="mode" value="{k}"{" checked" if k == mode else ""}>{v}</label>'
                    for k, v in (("buttons", "Buttons: one per role, click to get it and again to drop it"),
                                 ("dropdown", "Dropdown: one list, good for lots of roles"),
                                 ("reactions", "Emoji reactions: the classic style (clicks while the bot is offline are missed)")))
    need = "".join(f'<option value="{i}"{" selected" if i == str(menu.get("required_role_id") or "") else ""}>{e(r["name"])}</option>'
                   for i, r in roles.items() if i != str(app["guild_id"]) and not r.get("managed"))
    styles = "".join(f'<option value="{k}"{" selected" if k == str(menu.get("button_style") or "2") else ""}>{v}</option>' for k, v in rolemenus.BUTTON_STYLES.items())
    emoji_list = "".join(f'<option value="&lt;{"a" if x.get("animated") else ""}:{e(x["name"])}:{x["id"]}&gt;">:{e(x["name"])}:</option>' for x in emojis)
    setup_card = card("Where and how", f"""<label for="channel">Post in</label><select id="channel" name="channel"><option value="">Pick a channel</option>{channel_opts}</select>
<label>How members pick</label>{modes}
<label for="max_picks">How many roles each member can have from this menu</label>
<input id="max_picks" name="max_picks" type="number" min="0" max="25" value="{int(menu.get('max_picks') or 0)}">
<p><small>0 means no limit. 1 means pick only one: picking another swaps it.</small></p>
<label for="required_role">Who can use it</label><select id="required_role" name="required_role"><option value="">Everyone</option>{need}</select>
<div class="m-buttons"><label for="button_style">Button colour</label><select id="button_style" name="button_style">{styles}</select></div>
<div class="m-dropdown"><label for="placeholder">Dropdown text before picking</label><input id="placeholder" name="placeholder" maxlength="150" placeholder="Pick your roles" value="{e(menu.get('placeholder') or '')}"></div>""")
    roles_card = card("Roles", f"""<div id="opts">{''.join(option_row(o, safe_roles, roles) for o in options or [None])}</div>
<template id="opt-tpl">{option_row(None, safe_roles, roles)}</template><datalist id="emojis">{emoji_list}</datalist>
<button type="button" class="btn ghost" id="add-opt">Add a role</button>
<p><small>Only roles below the bot's highest role and without moderator powers are listed. Emoji: paste one, or pick a server emoji from the list.</small></p>""")
    delete = (f'<form method="post" action="/rolemenu/{mid}/delete" onsubmit="return confirm(\'Delete this menu and its message in Discord?\')">'
              '<button class="btn danger" type="submit">Delete menu</button></form>') if mid != "new" else ""
    body = (message + f'<form method="post" action="/rolemenu/{mid}" id="menu-form" data-mode="{mode}">{setup_card}{roles_card}'
            + card("Message", embed_editor("menu", cfg, await preview_sample(app, user), for_member=False))
            + '<button class="btn" type="submit">Save and post</button> <a class="btn ghost" href="/welcome">Back</a></form>'
            + delete + EDITOR_JS + MENU_JS)
    return layout("welcome", user, body, "New role menu" if mid == "new" else "Edit role menu",
                  "Members click to get or drop roles. Saving posts it, or updates it where it already is.")


async def post_menu(app, menu_id, old, old_options):
    """Post the menu, or edit it where it already is. An error message for the admin, or None."""
    conn = app["db"]
    menu, options = dict(db.get_menu(conn, menu_id)), db.menu_options(conn, menu_id)
    guild = await guild_info(app)
    content, embed = render_embed(json.loads(menu["embed"]), {"server": guild["name"], "count": guild.get("approximate_member_count", 0),
                                                              "user": "", "name": ""})
    payload = {"content": content, "embeds": [embed], "components": rolemenus.components(menu, options), "allowed_mentions": {"parse": []}}
    channel, message_id, status = menu["channel_id"], old and old["message_id"], None
    if message_id and old["channel_id"] == channel:
        status, body = await discord_send(app, "PATCH", f"/channels/{channel}/messages/{message_id}", payload)
        if status >= 300 and status != 404:
            return discord_error(status, body)
    elif message_id:  # moved to another channel: take the old message down
        await discord_send(app, "DELETE", f"/channels/{old['channel_id']}/messages/{message_id}")
    if status in (None, 404):  # never posted, moved, or someone deleted the message
        status, body = await discord_send(app, "POST", f"/channels/{channel}/messages", payload)
        if status >= 300:
            db.save_menu(conn, menu_id, None, message_id=None)
            return discord_error(status, body)
        message_id = int(body["id"])
        db.save_menu(conn, menu_id, None, message_id=message_id)
        old_options = []  # a fresh message has no reactions yet
    reactions = f"/channels/{channel}/messages/{message_id}/reactions"
    if menu["mode"] != "reactions":
        if old and old["mode"] == "reactions" and status < 300:
            await discord_send(app, "DELETE", reactions)  # switched away from reactions: clear them (needs Manage Messages)
        return None
    wanted = {rolemenus.emoji_key(rolemenus.parse_emoji(o["emoji"])): rolemenus.parse_emoji(o["emoji"]) for o in options}
    for o in old_options:
        gone = rolemenus.parse_emoji(o["emoji"])
        if gone and rolemenus.emoji_key(gone) not in wanted:
            await discord_send(app, "DELETE", f"{reactions}/{quote(rolemenus.reaction_path(gone))}")
    for emoji in wanted.values():
        status, body = await discord_send(app, "PUT", f"{reactions}/{quote(rolemenus.reaction_path(emoji))}/@me")
        if status >= 300:
            return f"Posted, but adding the {emoji['name']} reaction failed. " + discord_error(status, body)
    return None


async def rolemenu_save(request):
    app, user = request.app, check_post(request)
    mid = request.match_info["id"]
    old = None if mid == "new" else db.get_menu(app["db"], int(mid))
    if mid != "new" and not old:
        raise web.HTTPNotFound()
    old_options = db.menu_options(app["db"], old["id"]) if old else []
    posted = await request.post()
    cfg = clean_embed(posted)
    safe_roles, _, channels, _ = await menu_context(app)
    try:
        fields, options = rolemenus.clean(posted, safe_roles, {c["id"] for c in channels})
    except ValueError as err:
        sent = [{"role_id": r, "emoji": em, "label": la, "description": de} for r, em, la, de in
                zip(posted.getall("opt_role", []), posted.getall("opt_emoji", []), posted.getall("opt_label", []), posted.getall("opt_desc", []))]
        menu = {"channel_id": posted.get("channel", ""), "mode": posted.get("mode", "buttons"), "max_picks": posted.get("max_picks", "0"),
                "required_role_id": posted.get("required_role", ""), "button_style": posted.get("button_style"), "placeholder": posted.get("placeholder")}
        return await rolemenu_page(request, mid, menu, sent, cfg, f'<p class="bad">Not saved: {html.escape(str(err))}</p>')
    menu_id = db.save_menu(app["db"], old["id"] if old else None, options, **fields, embed=json.dumps(cfg, ensure_ascii=False),
                           updated_at=int(time.time()))
    error = await post_menu(app, menu_id, old, old_options)
    panel_log(app, user, f"{'updated' if old else 'created'} role menu {menu_id} in #{next((c['name'] for c in channels if c['id'] == str(fields['channel_id'])), '?')}")
    if error:
        return await rolemenu_page(request, str(menu_id), message=f'<p class="bad">Saved, but not posted: {html.escape(error)}</p>')
    raise web.HTTPFound(f"/rolemenu/{menu_id}?saved")


async def rolemenu_delete(request):
    app, user = request.app, check_post(request)
    menu = db.get_menu(app["db"], int(request.match_info["id"]))
    if not menu:
        raise web.HTTPNotFound()
    if menu["message_id"]:
        await discord_send(app, "DELETE", f"/channels/{menu['channel_id']}/messages/{menu['message_id']}")  # already gone is fine
    db.delete_menu(app["db"], menu["id"])
    panel_log(app, user, f"deleted role menu {menu['id']}")
    raise web.HTTPFound("/welcome?saved")


async def rolemenu_get(request):
    saved = '<p class="ok">Saved and posted. Members can use it straight away.</p>' if "saved" in request.query else ""
    return await rolemenu_page(request, message=saved)


async def utility_tab(request):
    return soon("Timezone converter", "Sticky messages", "Birthdays", "Looking for game (LFG)", "Event signups and reminders")


async def leveling_tab(request):
    return soon("XP for chatting and time in voice", "Level-up cards", "Role rewards at set levels", "Leaderboard")


async def games_tab(request):
    return soon("Daily Wordle", "Marriages", "Giveaways")


def utc_time(at):
    return f'<time data-t="{at}">{datetime.fromtimestamp(at, timezone.utc):%Y-%m-%d %H:%M} UTC</time>'


def voice_settings_card(app, channels):
    picked = db.autojoin_channels(app["db"])
    boxes = "".join(f'<label class="check"><input type="checkbox" name="autojoin" value="{c["id"]}"'
                    f'{" checked" if int(c["id"]) in picked else ""}> 🔊 {html.escape(c["name"])}</label>'
                    for c in channels if c["type"] in VOICE)
    model = db.get_setting(app["db"], "voice_model") or DEFAULT_MODEL
    options = "".join(f'<option{" selected" if m == model else ""}>{m}</option>' for m in MODELS)
    live = db.get_setting(app["db"], "voice_live_channel") or ""
    live_options = "<option value=\"\">The voice channel's own chat</option>" + "".join(
        f'<option value="{c["id"]}"{" selected" if c["id"] == live else ""}>#{html.escape(c["name"])}</option>'
        for c in channels if c["type"] in TEXT)
    return (f'<form method="post" action="/voice/settings" class="card"><h2>Settings</h2>'
            f'<label>Join these channels by itself when someone is in them</label>{boxes or "<p>No voice channels.</p>"}'
            '<p><small>Admins can also record any channel with /record start in Discord. The bot records one channel at a time.</small></p>'
            f'<label for="live">Live transcript for calls it joins by itself</label><select id="live" name="live">{live_options}</select>'
            '<p><small>Everyone who can see that channel can read the live transcript. With /record start it posts where the command was run.</small></p>'
            f'<label for="model">Speech-to-text model</label><select id="model" name="model">{options}</select>'
            '<p><small>small.en keeps up with live calls on a 6-core CPU. medium.en is more accurate but about 3 times slower. '
            'A change applies to clips recorded after it.</small></p><button class="btn" type="submit">Save</button></form>')


def call_status(c):
    pending = f" · {c['pending']} transcribing" if c["pending"] else ""
    return CALL_STATUS.get(c["status"], c["status"]) + pending


def calls_card(app):
    e = html.escape
    rows = "".join(
        f'<tr><td><a href="/voice/call/{c["id"]}">{utc_time(c["started_at"])}</a></td><td>🔊{e(c["channel_name"])}</td>'
        f'<td>{clock(((c["ended_at"] or int(time.time())) - c["started_at"]) * 1000)}</td>'
        f'<td>{e(", ".join(short_name(n) for n in (c["speakers"] or "").split(",") if n))}</td>'
        f'<td>{call_status(c)}</td></tr>' for c in db.voice_calls(app["db"]))
    # shortcut: shows the newest 100 calls only; add paging when there are more
    return card("Calls", f'<table><tr><th>Started</th><th>Channel</th><th>Length</th><th>Speakers</th><th>Status</th></tr>{rows}</table>'
                if rows else "<p>No calls recorded yet.</p>")


async def voice_tab(request):
    app = request.app
    return (calls_card(app) + voice_settings_card(app, await guild_channels(app)) + soon("AI summaries of each call")
            + f"<script>{LOCAL_TIMES}</script>")


async def voice_settings(request):
    app, user = request.app, check_post(request)
    posted = await request.post()
    channels = await guild_channels(app)
    names = {c["id"]: c["name"] for c in channels if c["type"] in VOICE}
    texts = {c["id"]: c["name"] for c in channels if c["type"] in TEXT}
    picked = sorted(int(v) for v in posted.getall("autojoin", []) if v in names)
    model = posted.get("model")
    live = posted.get("live", "")
    if model not in MODELS or (live and live not in texts):
        raise web.HTTPBadRequest(text="Unknown model or channel")
    if live != (db.get_setting(app["db"], "voice_live_channel") or ""):
        db.set_setting(app["db"], "voice_live_channel", live)
        panel_log(app, user, "set the live transcript channel: " + (f"#{texts[live]}" if live else "the voice channel's own chat"))
    if set(picked) != db.autojoin_channels(app["db"]):
        db.set_setting(app["db"], "voice_autojoin", json.dumps(picked))
        panel_log(app, user, "set voice auto-join channels: " + (", ".join(f"🔊{names[str(c)]}" for c in picked) or "none"))
    if model != (db.get_setting(app["db"], "voice_model") or DEFAULT_MODEL):
        db.set_setting(app["db"], "voice_model", model)
        panel_log(app, user, f"set the speech-to-text model: {model}")
    raise web.HTTPFound("/voice?saved")


async def avatars(app, member_ids):
    """{member id: avatar url}, server avatar first. Cached: one Discord lookup per member per hour."""
    cache = app["cache"].setdefault("avatars", {})

    async def one(mid):
        if mid in cache and cache[mid][1] > time.time():
            return
        url = DEFAULT_AVATAR
        try:
            m = await discord_get(app, f"/guilds/{app['guild_id']}/members/{mid}", f"Bot {app['token']}")
            if m.get("avatar"):
                url = f"https://cdn.discordapp.com/guilds/{app['guild_id']}/users/{mid}/avatars/{m['avatar']}.png?size=64"
            elif m["user"].get("avatar"):
                url = f"https://cdn.discordapp.com/avatars/{mid}/{m['user']['avatar']}.png?size=64"
        except web.HTTPBadGateway:
            pass  # left the server: default avatar
        cache[mid] = (url, time.time() + 3600)

    await asyncio.gather(*(one(m) for m in member_ids))
    return {m: cache[m][0] for m in member_ids}


def clip_text(clip):
    e = html.escape
    if clip["text"] is not None:
        return e(clip["text"])
    if clip["error"]:
        return f'<i class="bad">Couldn\'t transcribe: {e(clip["error"])}</i>'
    return "<i class=wait>Transcribing…</i>"


def timeline(call, clips, joins, faces, colours):
    """Messages grouped by speaker, like a chat, with join and leave markers between them."""
    e = html.escape
    items = [(c["start_ms"], 1, c) for c in clips if c["text"] != ""]  # "" was only noise
    items += [((at - call["started_at"]) * 1000, 0, (at, uid, name, joined)) for at, uid, name, joined in joins]
    groups = []  # a join/leave tuple, or [first clip, [clips]] for one speaker's run of lines
    for _, is_clip, item in sorted(items, key=lambda i: (i[0], i[1])):
        if is_clip and groups and isinstance(groups[-1], list) and groups[-1][0]["member_id"] == item["member_id"]:
            groups[-1][1].append(item)
        else:
            groups.append([item, [item]] if is_clip else item)
    out = []
    for g in groups:
        if isinstance(g, tuple):
            at, _, name, joined = g
            out.append(f'<div class="jl">{e(short_name(name or "Someone"))} {"joined" if joined else "left"} · <time data-tt="{at}"></time></div>')
            continue
        first, run = g
        lines = "".join(f'<p class="ln" data-s="{c["start_ms"]}" data-e="{c["start_ms"] + c["duration_ms"]}">{clip_text(c)}</p>' for c in run)
        out.append(f'<div class="msg"><img class="av" src="{e(faces[first["member_id"]])}" alt=""><div>'
                   f'<div class="mh"><b style="color:{colours[first["member_id"]]}">{e(short_name(first["member_name"]))}</b>'
                   f'<button type="button" class="tt" data-seek="{first["start_ms"]}">{clock(first["start_ms"])}</button></div>{lines}</div></div>')
    return "".join(out)


async def voice_call(request):
    app, user = request.app, session(request)
    if not user:
        raise web.HTTPFound("/voice")  # shows the login
    call = db.get_call(app["db"], int(request.match_info["id"]))
    if not call:
        raise web.HTTPNotFound()
    clips = db.call_clips(app["db"], call["id"])
    colours, names = {}, {}
    for c in clips:
        colours.setdefault(c["member_id"], SPEAKER_COLOURS[len(colours) % len(SPEAKER_COLOURS)])
        names[c["member_id"]] = short_name(c["member_name"])
    faces = await avatars(app, list(colours))
    length_ms = ((call["ended_at"] or int(time.time())) - call["started_at"]) * 1000
    live = call["status"] == "recording" or any(c["text"] is None and not c["error"] for c in clips)
    # the player schedules every clip at its place in the call, so people talking over each other play together
    player_clips = json.dumps([[c["id"], c["start_ms"], c["duration_ms"]] for c in clips if c["text"] != ""])
    delete = ("<small>Stop the recording before deleting this call.</small>" if call["status"] == "recording" else
              f'<form method="post" action="/voice/call/{call["id"]}/delete" style="display:inline" '
              'onsubmit="return confirm(\'Delete this call, its transcript and its audio for good?\')">'
              '<button class="btn danger" type="submit">Delete call</button></form>')
    faces_html = "".join(f'<img class="av mini" src="{html.escape(u)}" alt="{html.escape(names[m])}" title="{html.escape(names[m])}">'
                         for m, u in faces.items())
    subtitle = (f'{utc_time(call["started_at"])} · {clock(length_ms)} · {CALL_STATUS.get(call["status"], call["status"])}'
                f'<span class="faces">{faces_html}</span>')
    body = (f'<div class="callbar"><a href="/voice">← All calls</a><span><a class="btn ghost" href="/voice/call/{call["id"]}.txt">'
            f'Download transcript</a> {delete}</span></div>'
            f'<input id="find" type="search" placeholder="Search the transcript">'
            f'<div id="tls">{timeline(call, clips, db.call_joins(app["db"], call), faces, colours) or "<p class=empty>Nothing said yet.</p>"}</div>'
            '<div id="player"><button type="button" class="pb" id="back" aria-label="Back 15 seconds">↺15</button>'
            '<button type="button" class="pb play" id="pp" aria-label="Play">▶</button>'
            '<button type="button" class="pb" id="fwd" aria-label="Forward 15 seconds">15↻</button>'
            f'<span id="cur" class="tt">0:00</span><input id="bar" type="range" min="0" max="{length_ms}" value="0" aria-label="Position">'
            f'<span id="left" class="tt">-{clock(length_ms)}</span>'
            '<label class="check"><input type="checkbox" id="follow" checked> Follow along</label></div>'
            f"<script>const CLIPS={player_clips},LEN={length_ms},LIVE={'true' if live else 'false'};{LOCAL_TIMES}{CALL_JS}</script>")
    return layout("voice", user, body, label=f"🔊{html.escape(call['channel_name'])}", subtitle=subtitle)


async def voice_call_txt(request):
    if not session(request):
        raise web.HTTPForbidden()
    call = db.get_call(request.app["db"], int(request.match_info["id"]))
    if not call:
        raise web.HTTPNotFound()
    lines = [f"[{clock(c['start_ms'])}] {short_name(c['member_name'])}: {c['text']}"
             for c in db.call_clips(request.app["db"], call["id"]) if c["text"]]
    return web.Response(text="\n".join(lines) + "\n", content_type="text/plain", charset="utf-8",
                        headers={"Content-Disposition": f'attachment; filename="call-{call["id"]}.txt"'})


async def voice_call_delete(request):
    app, user = request.app, check_post(request)
    call = db.get_call(app["db"], int(request.match_info["id"]))
    if not call:
        raise web.HTTPNotFound()
    if call["status"] == "recording":
        raise web.HTTPConflict(text="Stop the recording first.")  # the bot would keep adding clips to it
    shutil.rmtree(app["voice_dir"] / str(call["id"]), ignore_errors=True)
    db.delete_call(app["db"], call["id"])
    panel_log(app, user, f"deleted voice call {call['id']} (🔊{call['channel_name']})")
    raise web.HTTPFound("/voice")


async def voice_clip(request):
    """One recorded sentence."""
    if not session(request):
        raise web.HTTPForbidden()
    clip = db.get_clip(request.app["db"], int(request.match_info["id"]))
    base = request.app["voice_dir"].resolve()
    path = (base / clip["file"]).resolve() if clip else None
    if not path or not path.is_relative_to(base) or not path.is_file():
        raise web.HTTPNotFound()
    return web.FileResponse(path, headers={"X-Content-Type-Options": "nosniff", "Content-Security-Policy": "sandbox",
                                           "Content-Type": "audio/ogg"})


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
    script = "<script>" + LOCAL_TIMES + """
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
const CH=S.channels||{};
// links: Discord only makes channel links clickable in the message text and description
const md=(s,links)=>fill(s).replace(/&lt;#(\d+)&gt;/g,(m,id)=>links?'<span class="mention">'+esc(CH[id]||'#unknown')+'</span>':m).replace(/```(?:\w*\n)?([\s\S]*?)```/g,'<pre>$1</pre>').replace(/`([^`\n]+)`/g,'<code>$1</code>')
 .replace(/^### (.*)$/gm,'<h3>$1</h3>').replace(/^## (.*)$/gm,'<h2>$1</h2>').replace(/^# (.*)$/gm,'<h1>$1</h1>').replace(/^&gt; (.*)$/gm,'<blockquote>$1</blockquote>')
 .replace(/\*\*(.+?)\*\*/g,'<b>$1</b>').replace(/__(.+?)__/g,'<u>$1</u>').replace(/\*(.+?)\*/g,'<i>$1</i>').replace(/~~(.+?)~~/g,'<s>$1</s>')
 .replace(/\|\|(.+?)\|\|/g,'<span class="spoiler">$1</span>').replace(/\[([^\]]+)\]\((https:\/\/[^)\s]+)\)/g,'<a href="$2" target="_blank" rel="noreferrer">$1</a>')
 .replace(/\u0001/g,MENTION).replace(/\n/g,'<br>').replace(/(<\/h\d>|<\/blockquote>|<\/pre>)<br>/g,'$1');
const plain=s=>fill(s).replace(/\u0001/g,'@'+esc(S.name));
const v=k=>{const el=f.elements[P+k];return !el?'':el.type==='checkbox'?el.checked:el.value};
const now=new Date().toLocaleTimeString([],{hour:'numeric',minute:'2-digit'});$('now').textContent=now;
function upd(){
 const show=(c,html)=>{$(c).innerHTML=html;$(c).hidden=!html};
 show('content',md(v('content'),1));show('title',md(v('title')));show('desc',md(v('description'),1));
 $('embed').style.borderColor=v('color');$('author').hidden=!v('show_author');$('author-name').innerHTML=plain(v('author')||'{name}');
 $('thumb').hidden=!v('thumbnail');
 const im=v('image');$('image').hidden=!/^https:\/\/\S+$/.test(im);if(!$('image').hidden&&$('image').getAttribute('src')!==im)$('image').src=im;
 const ft=v('footer'),ts=v('timestamp');show('footer',(ft?plain(ft):'')+(ft&&ts?' • ':'')+(ts?'Today at '+now:''));
}
let last=null;ed.querySelectorAll('input:not([type]),textarea').forEach(el=>el.addEventListener('focus',()=>last=el));
const put=t=>{const el=last||f.elements[P+'description'],s=el.selectionStart??el.value.length;
 el.value=el.value.slice(0,s)+t+el.value.slice(el.selectionEnd??s);el.focus();el.selectionStart=el.selectionEnd=s+t.length;upd()};
ed.querySelectorAll('[data-ins]').forEach(b=>b.onclick=()=>put(b.dataset.ins));
ed.querySelectorAll('.ins-ch').forEach(c=>c.onchange=()=>{if(c.value)put('<#'+c.value+'>');c.value=''});
f.addEventListener('input',upd);f.addEventListener('change',upd);upd();
});
</script>"""

# role menu editor: add, move and remove role rows, and show the buttons, dropdown or reactions under the preview
MENU_JS = r"""<script>
(()=>{const f=document.getElementById('menu-form'),opts=document.getElementById('opts'),tpl=document.getElementById('opt-tpl'),extra=f.querySelector('.pv-extra');
const esc=s=>s.replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const emo=t=>{t=(t||'').trim();const m=t.match(/^<(a?):(\w+):(\d+)>$/);return !t?'':m?`<img class="dc-emoji" src="https://cdn.discordapp.com/emojis/${m[3]}.${m[1]?'gif':'webp'}?size=44" alt="">`:`<span>${esc(t)}</span>`};
const rows=()=>[...opts.querySelectorAll('.opt')].map(r=>{const s=r.querySelector('select');return {role:s.value,name:s.value?s.selectedOptions[0].textContent:'',
 emoji:r.querySelector('[name=opt_emoji]').value,label:r.querySelector('[name=opt_label]').value}}).filter(o=>o.role);
function draw(){const mode=f.elements.mode.value;f.dataset.mode=mode;const o=rows();
 if(mode==='buttons')extra.innerHTML='<div class="dc-btns">'+o.map(x=>`<span class="dc-btn b${f.elements.button_style.value}">${emo(x.emoji)}${esc(x.label||x.name)}</span>`).join('')+'</div>';
 else if(mode==='dropdown')extra.innerHTML=`<div class="dc-select"><span>${esc(f.elements.placeholder.value||'Pick your roles')}</span><span>&#8964;</span></div>`;
 else extra.innerHTML='<div class="dc-reacts">'+o.filter(x=>x.emoji).map(x=>`<span class="dc-react">${emo(x.emoji)} 1</span>`).join('')+'</div>';}
document.getElementById('add-opt').onclick=()=>{opts.appendChild(tpl.content.cloneNode(true));draw()};
opts.addEventListener('click',e=>{const b=e.target.closest('button');if(!b)return;const r=b.closest('.opt');
 if('rm' in b.dataset)r.remove();else if(b.dataset.mv==='-1'&&r.previousElementSibling)opts.insertBefore(r,r.previousElementSibling);
 else if(b.dataset.mv==='1'&&r.nextElementSibling)opts.insertBefore(r.nextElementSibling,r);draw()});
f.addEventListener('input',draw);f.addEventListener('change',draw);draw();})();
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
.callbar{display:flex;justify-content:space-between;align-items:center;gap:8px;flex-wrap:wrap}.callbar span{display:flex;gap:8px;align-items:center}
.callbar form{margin:0}.callbar .btn{margin:0}#find{margin-bottom:8px}
.msg{display:grid;grid-template-columns:40px 1fr;gap:14px;padding:14px 0;border-bottom:1px solid var(--line)}
.av{width:40px;height:40px;border-radius:50%;object-fit:cover;background:var(--card)}
.av.mini{width:26px;height:26px;margin-left:-7px;border:2px solid var(--bg);vertical-align:middle}.faces{margin-left:14px;padding-left:7px}
.mh{display:flex;gap:8px;align-items:baseline}.mh b{font-size:15px}
.tt{color:var(--mu);font-size:12px;font-variant-numeric:tabular-nums;background:none;border:0;padding:0}button.tt{cursor:pointer}button.tt:hover{color:var(--tx)}
.msg>div{min-width:0}.ln{margin:4px 0 0 -8px;padding:3px 8px;border-radius:6px;cursor:pointer;line-height:1.55;overflow-wrap:anywhere}.ln:hover{background:var(--card)}
.ln.on{background:rgba(240,195,90,.15)}.ln .wait{color:var(--mu)}
.jl{font-size:12px;font-style:italic;color:var(--mu);padding:8px 0 8px 54px;border-bottom:1px solid var(--line)}
#player{position:sticky;bottom:12px;margin-top:16px;display:flex;align-items:center;gap:10px;background:var(--card);border:1px solid var(--line);
border-radius:var(--r);padding:10px 16px;box-shadow:0 8px 28px rgba(0,0,0,.45)}#player #bar{flex:1;width:auto;min-width:60px;accent-color:var(--gold)}
.pb{background:none;border:1px solid var(--line);color:var(--tx);border-radius:50%;width:38px;height:38px;cursor:pointer;font-size:11px;flex:none}
.pb.play{width:46px;height:46px;background:var(--gold);color:#111;border:0;font-size:16px}#player .check{white-space:nowrap;margin:0}
@media(max-width:820px){#player{flex-wrap:wrap}#player #bar{order:5;flex-basis:100%}}
@media(max-width:820px){.ev>summary{grid-template-columns:1fr auto}.ev .sm{grid-column:1/-1}.ba{grid-template-columns:1fr}}
label.check{display:flex;align-items:center;gap:8px;text-transform:none;letter-spacing:0;font-size:13px;color:var(--tx);cursor:pointer}label.check input{width:auto}
input[type=color]{height:38px;padding:3px;cursor:pointer}.phs{margin:12px 0 4px;font-size:12px;color:var(--mu)}
.ins-ch{width:auto;display:inline-block;padding:2px 6px;margin-left:4px;font-size:12px;color:var(--gold)}
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
.btn.danger{background:none;border:1px solid var(--loss);color:var(--loss)}
.opt{display:grid;grid-template-columns:minmax(0,1.3fr) 130px minmax(0,1fr) minmax(0,1.2fr) auto;gap:8px;margin-bottom:8px;align-items:center}
#menu-form:not([data-mode=dropdown]) .opt{grid-template-columns:minmax(0,1.3fr) 130px minmax(0,1fr) auto}
#menu-form:not([data-mode=dropdown]) .m-dropdown,#menu-form:not([data-mode=buttons]) .m-buttons{display:none}
.optb{display:flex;gap:4px}.ib{background:var(--bg);border:1px solid var(--line);color:var(--mu);border-radius:6px;width:30px;height:34px;cursor:pointer}.ib:hover{color:var(--tx)}
.dc-btns{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px;max-width:440px}
.dc-btn{display:inline-flex;align-items:center;gap:6px;height:32px;padding:0 16px;border-radius:8px;font-size:14px;font-weight:500;color:#fff}
.b1{background:#5865f2}.b2{background:#4e5058}.b3{background:#248046}.b4{background:#da373c}
.dc-emoji{width:20px;height:20px;object-fit:contain}.dc-react .dc-emoji{width:16px;height:16px}
.dc-select{display:flex;justify-content:space-between;max-width:400px;margin-top:8px;background:#1e1f22;border-radius:8px;padding:10px 12px;color:#949ba4;font-size:14px}
.dc-reacts{display:flex;flex-wrap:wrap;gap:4px;margin-top:6px}.dc-react{display:inline-flex;align-items:center;gap:6px;background:#2b2d31;border-radius:8px;padding:2px 8px;font-size:14px;color:#dbdee1}
@media(max-width:820px){.opt,#menu-form:not([data-mode=dropdown]) .opt{grid-template-columns:1fr 1fr}}
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


def layout(active, user, body, label=None, subtitle=None):
    _, tab_label, tab_subtitle, _ = BY_SLUG[active]
    label, subtitle = label or tab_label, subtitle or tab_subtitle
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
    app["url"] = os.environ.get("DASH_URL", "https://pitstop.craftyplayz.com").rstrip("/")
    app["secure"] = app["url"].startswith("https://")
    app["cache"] = {}  # looked up once: the bot's user id
    app["files"] = Path(os.environ.get("DB_PATH", "data/pitboss.db")).parent / "logfiles"  # saved by cogs/logs.py
    app["voice_dir"] = VOICE_DIR  # clips saved by cogs/record.py

    async def start(app):
        app["http"] = aiohttp.ClientSession()

    async def stop(app):
        await app["http"].close()

    app.on_startup.append(start)
    app.on_cleanup.append(stop)
    # fixed routes first: /{tab} would match them too
    app.add_routes([web.get("/", index), web.post("/save", save), web.get("/login", login),
                    web.get("/callback", callback), web.get("/logout", logout),
                    web.post("/voice/settings", voice_settings), web.get(r"/voice/call/{id:\d+}", voice_call),
                    web.get(r"/voice/call/{id:\d+}.txt", voice_call_txt), web.post(r"/voice/call/{id:\d+}/delete", voice_call_delete),
                    web.get(r"/voice/clip/{id:\d+}.ogg", voice_clip),
                    web.get("/logs/export", logs_export), web.get("/logs/file/{name}", log_file),
                    web.get(r"/rolemenu/{id:new|\d+}", rolemenu_get), web.post(r"/rolemenu/{id:new|\d+}", rolemenu_save),
                    web.post(r"/rolemenu/{id:\d+}/delete", rolemenu_delete),
                    web.get("/{tab}", tab_page)])
    return app


if __name__ == "__main__":
    web.run_app(make_app(), port=PORT)
