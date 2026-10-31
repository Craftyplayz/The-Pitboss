import asyncio
import json
import os
import tempfile
import unittest
from types import SimpleNamespace as NS

import discord

os.environ["GUILD_ID"] = "5"
os.environ.setdefault("DB_PATH", os.path.join(tempfile.mkdtemp(), "p.db"))

from cogs.logs import Logs, activity_text, who  # noqa: E402
from core import db  # noqa: E402
from core.events import CATEGORIES, KINDS, default_categories, describe, diff, show  # noqa: E402

GUILD = NS(id=5, member_count=10)
CHANNEL = NS(id=7, name="general")
ALICE = NS(id=1, name="alice", display_name="Alice", bot=False)


class FakeBot:
    def __init__(self):
        self.db = db.connect(":memory:")

    def get_channel(self, cid):
        return CHANNEL if cid == 7 else None

    def get_user(self, uid):
        return ALICE if uid == 1 else None


def events(bot, kind=None):
    rows = bot.db.execute("SELECT * FROM events" + (" WHERE kind = ?" if kind else "") + " ORDER BY id", (kind,) if kind else ()).fetchall()
    return [dict(r) | {"data": json.loads(r["data"] or "{}")} for r in rows]


def message(content, mid=100):
    return NS(guild=GUILD, id=mid, author=ALICE, channel=CHANNEL, content=content, attachments=[], stickers=[], embeds=[],
              reference=None, jump_url="https://discord.com/x")


class Helpers(unittest.TestCase):
    def test_every_kind_has_a_category(self):
        self.assertTrue(set(KINDS.values()) <= set(CATEGORIES))
        self.assertNotIn("sent", default_categories())  # messages sent are hidden until picked

    def test_show_and_diff(self):
        self.assertEqual(show(None), "none")
        self.assertEqual(show([NS(name="b"), NS(name="a")]), "a, b")
        self.assertEqual(show(discord.Status.idle), "idle")
        before, after = NS(name="old", topic=None, nsfw=False), NS(name="new", topic="hi", nsfw=False)
        self.assertEqual(diff(before, after, ["name", "topic", "nsfw"]), {"name": ["old", "new"], "topic": ["none", "hi"]})
        self.assertEqual(describe({"name": ["old", "new"]}), "name: old → new")

    def test_who(self):
        self.assertEqual(who(ALICE), "Alice (@alice)")
        self.assertEqual(who(NS(name="bob", display_name="bob")), "@bob")
        self.assertIsNone(who(None))

    def test_activity_text(self):
        self.assertEqual(activity_text(discord.CustomActivity(name="busy")), "custom status: busy")
        self.assertEqual(activity_text(discord.Game(name="Deadlock")), "playing Deadlock")


class Listeners(unittest.TestCase):
    def setUp(self):
        self.bot = FakeBot()
        self.cog = Logs(self.bot)

    def run_(self, coro):
        return asyncio.run(coro)

    def test_message_edit_and_delete_use_the_logged_text(self):
        self.run_(self.cog.on_message(message("hello")))
        edit = NS(guild_id=5, message_id=100, channel_id=7, data={"content": "hello there"}, cached_message=None,
                  message=NS(author=ALICE, jump_url="https://discord.com/x"))
        self.run_(self.cog.on_raw_message_edit(edit))
        self.run_(self.cog.on_raw_message_edit(edit))  # same text again (a link preview loading): not logged
        self.run_(self.cog.on_raw_message_delete(NS(guild_id=5, message_id=100, channel_id=7, cached_message=None)))
        sent, = events(self.bot, "message_sent")
        self.assertEqual(sent["category"], "sent")
        edited, = events(self.bot, "message_edited")
        self.assertEqual((edited["data"]["before"], edited["data"]["content"]), ("hello", "hello there"))
        deleted, = events(self.bot, "message_deleted")
        self.assertEqual((deleted["data"]["content"], deleted["user_id"]), ("hello there", 1))
        self.assertIn("Alice (@alice)", deleted["summary"])

    def test_delete_of_a_message_never_seen(self):
        self.run_(self.cog.on_raw_message_delete(NS(guild_id=5, message_id=999, channel_id=7, cached_message=None)))
        deleted, = events(self.bot, "message_deleted")
        self.assertIn("sent before logging started", deleted["summary"])

    def test_other_servers_are_ignored(self):
        self.run_(self.cog.on_message(NS(**{**vars(message("hi")), "guild": NS(id=6)})))
        self.assertEqual(events(self.bot), [])

    def test_role_and_nickname_changes(self):
        mod, vip = NS(name="Mod", id=11), NS(name="VIP", id=12)
        everyone = NS(name="@everyone", id=5)
        before = NS(guild=GUILD, id=1, name="alice", display_name="Alice", nick=None, roles=[everyone, vip],
                    timed_out_until=None, premium_since=None, pending=False, guild_avatar=None)
        after = NS(**{**vars(before), "nick": "Ally", "display_name": "Ally", "roles": [everyone, mod]})
        self.run_(self.cog.on_member_update(before, after))
        ev, = events(self.bot, "member_updated")
        self.assertIn("got Mod", ev["summary"])
        self.assertIn("lost VIP", ev["summary"])
        self.assertIn("nick: none → Ally", ev["summary"])

    def test_presence_status_and_custom_status(self):
        base = dict(guild=GUILD, id=1, name="alice", display_name="Alice", desktop_status=discord.Status.online,
                    mobile_status=discord.Status.offline, web_status=discord.Status.offline)
        before = NS(**base, status=discord.Status.online, activities=[])
        after = NS(**{**base, "desktop_status": discord.Status.dnd}, status=discord.Status.dnd,
                   activities=[discord.CustomActivity(name="grinding")])
        self.run_(self.cog.on_presence_update(before, after))
        ev, = events(self.bot, "presence_updated")
        self.assertEqual(ev["data"]["changes"]["status"], ["online", "dnd"])
        self.assertEqual(ev["data"]["changes"]["activity"], ["none", "custom status: grinding"])


class FindEvents(unittest.TestCase):
    def test_filters(self):
        conn = db.connect(":memory:")
        db.add_event(conn, 100, "message_sent", "sent", "Alice in #general: hi", user_id=1, user_name="Alice (@alice)", channel_id=7, channel_name="general")
        db.add_event(conn, 200, "member_joined", "members", "Bob joined", user_id=2, user_name="@bob")
        db.add_event(conn, 300, "message_deleted", "messages", "deleted", user_id=1, user_name="Alice (@alice)", data={"content": "secret"})
        every = list(CATEGORIES)
        self.assertEqual(db.find_events(conn, every)[1], 3)
        self.assertEqual(db.find_events(conn, default_categories())[1], 2)  # the sent message is hidden
        self.assertEqual([r["at"] for r in db.find_events(conn, every, user="alice")[0]], [300, 100])
        self.assertEqual([r["at"] for r in db.find_events(conn, every, user="2")[0]], [200])
        self.assertEqual([r["at"] for r in db.find_events(conn, every, text="secret")[0]], [300])  # searches the details too
        self.assertEqual([r["at"] for r in db.find_events(conn, every, channel="gen")[0]], [100])
        self.assertEqual([r["at"] for r in db.find_events(conn, every, since=150, until=300)[0]], [200])
        newest, = db.find_events(conn, every, limit=1)[0]
        self.assertEqual([r["at"] for r in db.find_events(conn, every, before_id=newest["id"])[0]], [200, 100])
