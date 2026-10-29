import unittest

from cogs.scrims import TEAM_SIZE, result_embed, scoreboard_png, signup
from core.dashboard import match_detail
from tests.test_recap_embed import ITEMS, META

PLAYERS = [(m, m % 2) for m in range(2 * TEAM_SIZE)]


class ScrimEmbeds(unittest.IsolatedAsyncioTestCase):  # discord.ui.View needs a running loop
    async def test_signup_every_state(self):
        for state in ("open", "picking", "creating", "lobby", "live", "done", "failed", "cancelled"):
            scrim = {"id": 3, "state": state, "creator_id": 1, "party_code": "ABC12", "match_id": 9}
            embed, _ = signup(scrim, PLAYERS + [(99, None)])
            self.assertTrue(embed.author.name.startswith("Scrim · "), state)
            self.assertTrue(all(len(f.value) <= 1024 for f in embed.fields), state)
        self.assertIn("```", embed.fields[-1].value if state == "lobby" else "```")
        embed, _ = signup({**scrim, "state": "lobby"}, PLAYERS)
        self.assertIn("ABC12", embed.fields[-1].value)
        self.assertIn("🟧 Amber (6/6)", embed.fields[0].name)

    def test_result_embed(self):
        detail = match_detail(META, ITEMS, {1: "<b>x</b>"})
        e = result_embed(5, detail, {}, {2: 555}, {p["hero"]: "<:h:1>" for p in detail["pl"]})
        win = detail["win"]
        self.assertEqual(e.color.value, (0xE67E22, 0x3498DB)[win])
        self.assertEqual(e.author.name, "Scrim #5 · finished")
        self.assertEqual(e.title, ("Amber", "Sapphire")[win] + " wins")
        self.assertEqual(e.image.url, "attachment://scoreboard.png")
        self.assertIn("🏆", e.fields[win].name)
        self.assertNotIn("🏆", e.fields[1 - win].name)
        self.assertIn("kills", e.fields[0].name)
        self.assertIn("<:h:1> **Hero**", e.fields[0].value + e.fields[1].value)
        self.assertIn("MVP (most damage)", e.description)

    def test_missing_emoji_has_no_gap(self):
        detail = match_detail(META, ITEMS, {})
        e = result_embed(5, detail, {}, {})
        for line in (e.fields[0].value + "\n" + e.fields[1].value).split("\n"):
            self.assertTrue(line.startswith("**"), line)

    def test_scoreboard_png(self):
        self.assertGreater(len(scoreboard_png(match_detail(META, ITEMS, {}), {}).read()), 100)


class LogThreads(unittest.IsolatedAsyncioTestCase):
    async def test_thread_name(self):
        from cogs.scrims import thread_name
        self.assertEqual(thread_name(7, {"win": 1}), "Scrim #7 · Sapphire wins")

    async def test_open_discussion(self):
        from unittest.mock import AsyncMock
        from cogs.scrims import open_discussion
        msg = AsyncMock()
        await open_discussion(msg, "x" * 150)
        msg.create_thread.assert_awaited_once_with(name="x" * 100, auto_archive_duration=10080)

    async def test_open_discussion_failure_is_swallowed(self):
        from unittest.mock import AsyncMock, MagicMock
        import discord
        from cogs.scrims import open_discussion
        msg = AsyncMock()
        msg.create_thread.side_effect = discord.Forbidden(MagicMock(status=403), "no")
        self.assertIsNone(await open_discussion(msg, "Scrim #1"))

    async def test_lock_log_channel(self):
        from unittest.mock import AsyncMock, MagicMock
        import discord
        from cogs.scrims import lock_log_channel
        channel = MagicMock()
        channel.overwrites_for.side_effect = lambda target: discord.PermissionOverwrite(view_channel=True)
        channel.set_permissions = AsyncMock()
        everyone, me = object(), object()
        await lock_log_channel(channel, everyone, me)
        (t1, k1), (t2, k2) = [(c.args[0], c.kwargs["overwrite"]) for c in channel.set_permissions.await_args_list]
        self.assertIs(t1, everyone)
        self.assertEqual((k1.send_messages, k1.send_messages_in_threads, k1.create_public_threads), (False, True, False))
        self.assertTrue(k1.view_channel)  # existing overwrites are kept
        self.assertIs(t2, me)
        self.assertEqual((k2.send_messages, k2.create_public_threads), (True, True))


if __name__ == "__main__":
    unittest.main()
