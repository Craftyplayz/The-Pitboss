import random
import unittest

from unittest.mock import AsyncMock, MagicMock

from cogs.scrims import Scrims as ScrimsCog
from cogs.scrims import TEAM_SIZE, link_guide, random_teams, result_embed, signup
from core import db
from core.dashboard import match_detail
from tests.test_recap_embed import ITEMS, META


def row(conn, sid):
    return db.get_scrim(conn, sid)


class Scrims(unittest.IsolatedAsyncioTestCase):  # discord.ui.View needs a running event loop
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.sid = db.create_scrim(self.conn, 1, 100)

    def test_random_teams_are_balanced(self):
        teams = random_teams(range(7), random.Random(3))
        self.assertEqual(sorted(teams), list(range(7)))
        self.assertEqual(sorted(teams.values()).count(0), 4)

    def test_players_join_move_and_leave(self):
        for m in (1, 2, 3):
            db.add_scrim_player(self.conn, self.sid, m, 100 + m)
        db.add_scrim_player(self.conn, self.sid, 2, 999, team=1)  # picking a team keeps the join order
        db.remove_scrim_player(self.conn, self.sid, 3)
        self.assertEqual(db.scrim_players(self.conn, self.sid), [(1, None), (2, 1)])
        db.set_scrim_teams(self.conn, self.sid, {1: 0})
        self.assertEqual(db.scrim_players(self.conn, self.sid), [(1, 0), (2, 1)])

    async def test_signup_buttons_follow_state(self):
        ids = lambda view: [i.custom_id.split(":")[1] for i in view.children if not i.disabled]
        db.add_scrim_player(self.conn, self.sid, 1, 100)
        _, view = signup(row(self.conn, self.sid), db.scrim_players(self.conn, self.sid))
        self.assertEqual(ids(view), ["join", "leave", "cancel"])  # one player can't start
        db.add_scrim_player(self.conn, self.sid, 2, 101, team=0)
        db.update_scrim(self.conn, self.sid, state="picking")
        _, view = signup(row(self.conn, self.sid), db.scrim_players(self.conn, self.sid))
        self.assertNotIn("lobby", ids(view))  # player 1 hasn't picked and Sapphire is empty
        db.set_scrim_teams(self.conn, self.sid, {1: 1})
        _, view = signup(row(self.conn, self.sid), db.scrim_players(self.conn, self.sid))
        self.assertIn("lobby", ids(view))
        db.update_scrim(self.conn, self.sid, state="lobby", party_code="ABC12")
        embed, view = signup(row(self.conn, self.sid), db.scrim_players(self.conn, self.sid))
        self.assertIn("ABC12", embed.fields[-1].value)
        self.assertEqual(ids(view), ["lobby", "cancel"])
        db.update_scrim(self.conn, self.sid, state="done")
        self.assertEqual(ids(signup(row(self.conn, self.sid), [])[1]), [])

    async def test_full_scrim_disables_join(self):
        players = [(m, None) for m in range(2 * TEAM_SIZE)]
        _, view = signup(row(self.conn, self.sid), players)
        self.assertTrue(view.children[0].disabled)

    def interaction(self, user_id):
        it = MagicMock()
        it.user.id = user_id
        it.response.send_message = AsyncMock()
        it.response.defer = AsyncMock()
        return it

    async def test_unlinked_members_get_the_link_guide_and_are_not_added(self):
        cog = ScrimsCog.__new__(ScrimsCog)  # skip __init__: no loops or emoji uploads in a unit test
        cog.bot = MagicMock(db=self.conn)
        cog.refresh = AsyncMock()
        db.set_link(self.conn, 7, 12345, 0)
        db.update_scrim(self.conn, self.sid, state="picking")
        for handler in (cog.do_join, cog.do_team0):
            db.update_scrim(self.conn, self.sid, state="open" if handler == cog.do_join else "picking")
            it = self.interaction(8)  # not linked
            await handler(it, row(self.conn, self.sid))
            kw = it.response.send_message.call_args.kwargs
            self.assertTrue(kw["ephemeral"])
            self.assertEqual(kw["embed"].title, link_guide().title)
            self.assertNotIn(8, [m for m, _ in db.scrim_players(self.conn, self.sid)])
        it = self.interaction(8)
        await ScrimsCog.scrim.callback(cog, it)  # /scrim by an unlinked member makes no scrim
        it.response.defer.assert_not_called()
        self.assertEqual(len(db.scrims_in(self.conn, "open")) + len(db.scrims_in(self.conn, "picking")), 1)
        db.update_scrim(self.conn, self.sid, state="open")
        it = self.interaction(7)  # linked
        await cog.do_join(it, row(self.conn, self.sid))
        self.assertIn(7, [m for m, _ in db.scrim_players(self.conn, self.sid)])

    def test_link_guide_explains_the_steps(self):
        text = " ".join(f.name + f.value for f in link_guide().fields)
        for step in ("/link", "That's me", "Join"):
            self.assertIn(step, text)

    def test_result_embed(self):
        detail = match_detail(META, ITEMS, {1: "<b>*x*</b>"})
        e = result_embed(self.sid, detail, {}, {2: 555})
        text = "".join(f.value for f in e.fields)
        self.assertIn("<@555>", text)  # Linked players are mentioned
        self.assertIn("<b>\\*x\\*</b>", text)  # Steam names are unescaped from HTML, escaped for Discord
        self.assertTrue(e.url.endswith(f"/#scrims/{self.sid}"))
        self.assertEqual(len(db.scrims_in(self.conn, "open")), 1)


if __name__ == "__main__":
    unittest.main()
