"""Role menus: messages members click to get or drop roles. Admins build them in the control panel (dash.py),
which posts them through Discord's API; the bot (cogs/rolemenus.py) answers the clicks.

Shared here: which roles are safe to hand out, how a menu becomes Discord components, and what a click changes."""
import re

MODES = {"buttons": "Buttons", "dropdown": "Dropdown", "reactions": "Emoji reactions"}
MAX_OPTIONS = {"buttons": 25, "dropdown": 25, "reactions": 20}  # Discord's limits per message
BUTTON_STYLES = {"2": "Grey", "1": "Blurple", "3": "Green", "4": "Red"}
CUSTOM_EMOJI_RE = re.compile(r"^<(a?):(\w{2,32}):(\d{15,25})>$")
# Administrator, kick, ban, every Manage permission, mention @everyone and timeout: never handed out by a click
DANGEROUS = (1 << 3 | 1 << 1 | 1 << 2 | 1 << 4 | 1 << 5 | 1 << 13 | 1 << 17 | 1 << 27 | 1 << 28 | 1 << 29 | 1 << 30
             | 1 << 33 | 1 << 34 | 1 << 40)


def safe(role, guild_id, bot_top):
    """Whether a role (Discord API dict) can go in a menu: below the bot's highest role, not @everyone,
    not managed by a bot or integration, and without moderator powers."""
    return (str(role["id"]) != str(guild_id) and not role.get("managed") and role["position"] < bot_top
            and not int(role["permissions"]) & DANGEROUS)


def parse_emoji(text):
    """Discord's emoji object for a unicode emoji or <:name:id>, or None when empty."""
    text = (text or "").strip()
    if not text:
        return None
    if m := CUSTOM_EMOJI_RE.match(text):
        return {"name": m[2], "id": m[3], "animated": bool(m[1])}
    return {"name": text}


def emoji_key(emoji):
    """The same key for an emoji however it arrives: a custom emoji's id, or the unicode without variation selectors."""
    if isinstance(emoji, dict):
        return emoji.get("id") or emoji["name"].replace("️", "")
    if getattr(emoji, "id", None):
        return str(emoji.id)
    return str(getattr(emoji, "name", emoji) or "").replace("️", "")


def reaction_path(emoji):
    """How an emoji goes in a reaction URL: the unicode itself, or name:id."""
    return f"{emoji['name']}:{emoji['id']}" if emoji.get("id") else emoji["name"]


def clean(form, roles, channels):
    """(menu fields, options) from the panel's form. roles: the safe roles {id: name}; channels: text channel ids.
    Raises ValueError with a message for the admin."""
    channel = form.get("channel", "")
    if channel not in channels:
        raise ValueError("Pick a text channel to post the menu in.")
    mode = form.get("mode", "buttons")
    if mode not in MODES:
        raise ValueError("Pick how members choose: buttons, dropdown or emoji reactions.")
    max_picks = form.get("max_picks", "0")
    max_picks = int(max_picks) if max_picks.isdigit() else 0
    required = form.get("required_role", "")
    options, seen = [], set()
    for role, emoji, label, desc in zip(form.getall("opt_role", []), form.getall("opt_emoji", []),
                                        form.getall("opt_label", []), form.getall("opt_desc", [])):
        if not role:
            continue
        if role not in roles:
            raise ValueError("One of the roles can't be handed out (it's above the bot's role or has moderator powers).")
        if role in seen:
            raise ValueError(f"{roles[role]} is in the menu twice.")
        seen.add(role)
        if mode == "reactions" and not emoji.strip():
            raise ValueError(f"Give {roles[role]} an emoji: reaction menus need one for every role.")
        keys = {emoji_key(parse_emoji(o["emoji"])) for o in options if o["emoji"]}
        if emoji.strip() and emoji_key(parse_emoji(emoji)) in keys and mode == "reactions":
            raise ValueError(f"Two roles use the emoji {emoji.strip()}.")
        options.append({"role_id": int(role), "emoji": emoji.strip()[:64], "label": (label.strip() or roles[role])[:80],
                        "description": desc.strip()[:100]})
    if not options:
        raise ValueError("Add at least one role.")
    if len(options) > MAX_OPTIONS[mode]:
        raise ValueError(f"{MODES[mode]} can have at most {MAX_OPTIONS[mode]} roles.")
    menu = {"channel_id": int(channel), "mode": mode, "max_picks": min(max_picks, len(options)),
            "required_role_id": int(required) if required.isdigit() else None,
            "button_style": form.get("button_style") if form.get("button_style") in BUTTON_STYLES else "2",
            "placeholder": (form.get("placeholder") or "").strip()[:150]}
    return menu, options


def components(menu, options):
    """Discord message components for a buttons or dropdown menu; none for emoji reactions."""
    mid = menu["id"]
    if menu["mode"] == "buttons":
        buttons = [{"type": 2, "style": int(menu.get("button_style") or 2), "label": o["label"],
                    "custom_id": f"rolemenu:{mid}:{o['role_id']}", **({"emoji": e} if (e := parse_emoji(o["emoji"])) else {})}
                   for o in options]
        return [{"type": 1, "components": buttons[i:i + 5]} for i in range(0, len(buttons), 5)]
    if menu["mode"] == "dropdown":
        choices = [{"label": o["label"], "value": str(o["role_id"]), **({"description": o["description"]} if o["description"] else {}),
                    **({"emoji": e} if (e := parse_emoji(o["emoji"])) else {})} for o in options]
        return [{"type": 1, "components": [{"type": 3, "custom_id": f"rolemenu:{mid}:select",
                                            "placeholder": menu.get("placeholder") or "Pick your roles",
                                            "min_values": 0, "max_values": menu["max_picks"] or len(options), "options": choices}]}]
    return []


def click(have, menu_roles, role, max_picks):
    """What a button click (or emoji reaction) does: (add, remove), or None when it would go over the limit.
    Clicking a role you have drops it; with "pick one" a new pick replaces the old one."""
    if role in have:
        return set(), {role}
    mine = have & menu_roles
    if max_picks == 1:
        return {role}, mine
    if max_picks and len(mine) >= max_picks:
        return None
    return {role}, set()


def choose(have, menu_roles, picked):
    """What a dropdown choice does: the menu's roles become exactly the picked ones. (add, remove)"""
    return picked - have, (menu_roles - picked) & have
