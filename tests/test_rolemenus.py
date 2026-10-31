import asyncio
import unittest
from types import SimpleNamespace as NS

import discord
from multidict import MultiDict

from cogs import rolemenus as cog
from core import db
from core.rolemenus import DANGEROUS, choose, clean, click, components, emoji_key, parse_emoji, reaction_path, safe

ROLES = {"10": "Red", "11": "Blue", "12": "Green"}


def role(id_, position, perms=0, managed=False):
    return {"id": str(id_), "position": position, "permissions": str(perms), "managed": managed}


def form(**fields):
    opts = fields.pop("opts", [("10", "", "", "")])
    md = MultiDict({"channel": "7", "mode": "buttons", "max_picks": "0", **fields})
    for r, e, l, d in opts:
        md.add("opt_role", r)
        md.add("opt_emoji", e)
        md.add("opt_label", l)
        md.add("opt_desc", d)
    return md


class Safe(unittest.TestCase):
    def test_rules(self):
        self.assertTrue(safe(role(10, 2), 5, bot_top=5))
        self.assertFalse(safe(role(5, 0), 5, bot_top=5))  # @everyone
        self.assertFalse(safe(role(10, 5), 5, bot_top=5))  # level with the bot
        self.assertFalse(safe(role(10, 2, managed=True), 5, bot_top=5))
        self.assertFalse(safe(role(10, 2, perms=1 << 3), 5, bot_top=5))  # Administrator
        self.assertFalse(safe(role(10, 2, perms=1 << 28), 5, bot_top=5))  # Manage Roles
        self.assertTrue(safe(role(10, 2, perms=1 << 10 | 1 << 11), 5, bot_top=5))  # view and send messages

    def test_dangerous_covers_moderation(self):
        for bit in (1, 2, 3, 4, 5, 13, 28, 40):
            self.assertTrue(DANGEROUS & 1 << bit, bit)


class Emoji(unittest.TestCase):
    def test_parse_and_keys(self):
        self.assertIsNone(parse_emoji("  "))
        self.assertEqual(parse_emoji("🔥"), {"name": "🔥"})
        custom = parse_emoji("<a:party:123456789012345678>")
        self.assertEqual(custom, {"name": "party", "id": "123456789012345678", "animated": True})
        self.assertEqual(reaction_path(custom), "party:123456789012345678")
        self.assertEqual(emoji_key(custom), emoji_key(discord.PartialEmoji(name="party", id=123456789012345678)))
        self.assertEqual(emoji_key(parse_emoji("❤️")), emoji_key(discord.PartialEmoji(name="❤")))  # variation selector


class Clean(unittest.TestCase):
    def test_valid(self):
        menu, options = clean(form(max_picks="1", opts=[("10", "🔥", "", ""), ("11", "", "Blue team", "desc")]), ROLES, {"7"})
        self.assertEqual((menu["channel_id"], menu["mode"], menu["max_picks"]), (7, "buttons", 1))
        self.assertEqual([o["label"] for o in options], ["Red", "Blue team"])  # empty label: role name

    def test_errors(self):
        cases = [(form(channel="8"), "channel"), (form(mode="x"), "how members choose"),
                 (form(opts=[("99", "", "", "")]), "can't be handed out"), (form(opts=[("10", "", "", ""), ("10", "", "", "")]), "twice"),
                 (form(opts=[]), "at least one"), (form(mode="reactions"), "emoji"),
                 (form(mode="reactions", opts=[("10", "🔥", "", ""), ("11", "🔥", "", "")]), "Two roles")]
        for f, words in cases:
            with self.assertRaises(ValueError) as e:
                clean(f, ROLES, {"7"})
            self.assertIn(words, str(e.exception))

    def test_empty_rows_skipped_and_limit_capped(self):
        menu, options = clean(form(max_picks="9", opts=[("", "", "", ""), ("10", "", "", "")]), ROLES, {"7"})
        self.assertEqual((len(options), menu["max_picks"]), (1, 1))


class Components(unittest.TestCase):
    def test_buttons_in_rows_of_five(self):
        options = [{"role_id": i, "emoji": "", "label": f"R{i}", "description": ""} for i in range(7)]
        rows = components({"id": 3, "mode": "buttons", "button_style": "1", "max_picks": 0}, options)
        self.assertEqual([len(r["components"]) for r in rows], [5, 2])
        self.assertEqual(rows[0]["components"][0], {"type": 2, "style": 1, "label": "R0", "custom_id": "rolemenu:3:0"})

    def test_dropdown(self):
        options = [{"role_id": 10, "emoji": "🔥", "label": "Red", "description": "hot"}]
        menu = components({"id": 3, "mode": "dropdown", "max_picks": 0, "placeholder": ""}, options)[0]["components"][0]
        self.assertEqual((menu["custom_id"], menu["min_values"], menu["max_values"], menu["placeholder"]), ("rolemenu:3:select", 0, 1, "Pick your roles"))
        self.assertEqual(menu["options"][0], {"label": "Red", "value": "10", "description": "hot", "emoji": {"name": "🔥"}})
        self.assertEqual(components({"id": 3, "mode": "reactions", "max_picks": 0}, options), [])


class Picking(unittest.TestCase):
    MENU = {10, 11, 12}

    def test_click(self):
        self.assertEqual(click({1}, self.MENU, 10, 0), ({10}, set()))
        self.assertEqual(click({1, 10}, self.MENU, 10, 0), (set(), {10}))  # again: drop it
        self.assertEqual(click({1, 11}, self.MENU, 10, 1), ({10}, {11}))  # pick one: swap
        self.assertIsNone(click({10, 11}, self.MENU, 12, 2))  # over the limit
        self.assertEqual(click({10, 11}, self.MENU, 11, 2), (set(), {11}))  # dropping is always fine

    def test_choose(self):
        self.assertEqual(choose({1, 10, 11}, self.MENU, {11, 12}), ({12}, {10}))


class FakeRole:
    def __init__(self, id_, guild, position=1, perms=0):
        self.id, self.guild, self.position, self.managed = id_, guild, position, False
        self.permissions = discord.Permissions(perms)
        self.mention = f"<@&{id_}>"

    def __lt__(self, other):
        return self.position < other.position

    def is_default(self):
        return False


class FakeMember:
    def __init__(self, guild, roles):
        self.guild, self.roles, self.bot = guild, roles, False

    def get_role(self, rid):
        return next((r for r in self.roles if r.id == rid), None)

    async def add_roles(self, *roles, reason=None):
        self.roles += list(roles)

    async def remove_roles(self, *roles, reason=None):
        self.roles = [r for r in self.roles if r not in roles]


class Clicks(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.guild = NS()
        top = FakeRole(99, self.guild, position=50)
        self.guild.me = NS(top_role=top)
        self.roles = {i: FakeRole(i, self.guild) for i in (10, 11)}
        self.roles[12] = FakeRole(12, self.guild, position=60)  # above the bot
        self.guild.get_role = self.roles.get
        self.menu_id = db.save_menu(self.conn, None, [{"role_id": i, "emoji": "", "label": "x", "description": ""} for i in (10, 11, 12)],
                                    channel_id=7, mode="buttons", max_picks=1, embed="{}", updated_at=1)
        self.sent = []

    def press(self, member, role_id, monkey_member_type=True):
        async def defer(**kw):
            pass

        async def send(text, **kw):
            self.sent.append(text)
        interaction = NS(client=NS(db=self.conn), user=member, response=NS(defer=defer, send_message=send), followup=NS(send=send))
        original = cog.discord.Member
        cog.discord.Member = FakeMember  # handle() checks the clicker is a server member
        try:
            asyncio.run(cog.RoleButton(self.menu_id, role_id).callback(interaction))
        finally:
            cog.discord.Member = original

    def test_pick_one_swaps(self):
        member = FakeMember(self.guild, [self.roles[11]])
        self.press(member, 10)
        self.assertEqual({r.id for r in member.roles}, {10})
        self.assertEqual(self.sent[-1], "Added <@&10>. Removed <@&11>.")

    def test_role_above_the_bot_is_skipped(self):
        member = FakeMember(self.guild, [])
        self.press(member, 12)
        self.assertEqual(member.roles, [])
        self.assertIn("I can't change <@&12>", self.sent[-1])

    def test_required_role(self):
        db.save_menu(self.conn, self.menu_id, None, required_role_id=77)
        member = FakeMember(self.guild, [])
        self.press(member, 10)
        self.assertEqual(member.roles, [])
        self.assertIn("You need <@&77>", self.sent[-1])

    def test_removed_option(self):
        member = FakeMember(self.guild, [])
        self.press(member, 55)
        self.assertIn("taken out of this menu", self.sent[-1])
