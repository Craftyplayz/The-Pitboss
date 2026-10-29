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


if __name__ == "__main__":
    unittest.main()
