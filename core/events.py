"""Server Log: the kinds of Discord events the bot records (cogs/logs.py) and the control panel shows (dash.py)."""

# category: (label, badge colour, shown when no filter is picked)
CATEGORIES = {
    "messages": ("Edits & deletes", "#F0C35A", True),
    "sent": ("Messages sent", "#8190a3", False),  # every message: too noisy to show by default
    "reactions": ("Reactions & polls", "#c792ea", True),
    "members": ("Joins & leaves", "#4fc98a", True),
    "member_changes": ("Member changes", "#5ab0f0", True),
    "profile": ("Profile changes", "#5ad1c9", True),
    "presence": ("Status & activity", "#7f8cf0", True),
    "voice": ("Voice", "#f09a5a", True),
    "channels": ("Channels & threads", "#b0c45a", True),
    "roles": ("Roles", "#f05aa8", True),
    "server": ("Server", "#d6b88a", True),
    "audit": ("Audit log", "#e5636d", True),
    "panel": ("Control panel", "#F0C35A", True),
}

KINDS = {
    "message_sent": "sent",
    **dict.fromkeys(["message_edited", "message_deleted", "messages_bulk_deleted", "pins_changed"], "messages"),
    **dict.fromkeys(["reaction_added", "reaction_removed", "reactions_cleared", "poll_vote_added", "poll_vote_removed"], "reactions"),
    **dict.fromkeys(["member_joined", "member_left", "member_banned", "member_unbanned"], "members"),
    "member_updated": "member_changes",
    "user_updated": "profile",
    "presence_updated": "presence",
    "voice_updated": "voice",
    **dict.fromkeys(["channel_created", "channel_deleted", "channel_updated",
                     "thread_created", "thread_deleted", "thread_updated"], "channels"),
    **dict.fromkeys(["role_created", "role_deleted", "role_updated"], "roles"),
    **dict.fromkeys(["server_updated", "emojis_updated", "stickers_updated", "invite_created", "invite_deleted",
                     "webhooks_updated", "scheduled_event", "automod_action", "automod_rule", "stage", "soundboard"], "server"),
    "audit_entry": "audit",
    "panel_change": "panel",
}


def default_categories():
    return [c for c, (_, _, shown) in CATEGORIES.items() if shown]


def show(value):
    """A before/after value as short readable text."""
    if value is None or (isinstance(value, (str, list, tuple, set, frozenset)) and not value):
        return "none"
    if hasattr(value, "name") and not isinstance(value, str):
        return str(value.name)  # channels, roles, members and enums: their name, not the repr (enums are tuples, so first)
    if isinstance(value, (list, tuple, set, frozenset)):
        return ", ".join(sorted(show(v) for v in value))
    return str(value)


def diff(before, after, attrs):
    """{attr: [old, new]} for each attribute that changed, as readable text."""
    out = {}
    for attr in attrs:
        old, new = getattr(before, attr, None), getattr(after, attr, None)
        if old != new:
            out[attr] = [show(old), show(new)]
    return out


def describe(changes):
    """'name: a → b; topic: none → hi' for a summary line."""
    return "; ".join(f"{k.replace('_', ' ')}: {a} → {b}" for k, (a, b) in changes.items())
