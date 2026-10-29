import asyncio
import sys
import types
import unittest
from unittest.mock import MagicMock

try:
    import core.insights  # noqa: F401
except ImportError:  # written by another agent; stub so this module imports
    sys.modules["core.insights"] = types.SimpleNamespace(match_insights=lambda m, h, n: ["insight"])

import discord

from cogs.recaps import MAX_AGE, add_site_links, build_embed, due_matches
from core.shared import SITE_URL

NOW = 1_800_000_000
LINKED = NOW - 3 * 86400


def m(match_id, ended_ago, duration=1800, **kw):
    return {"match_id": match_id, "start_time": NOW - ended_ago - duration, "match_duration_s": duration, **kw}


def ids(recap):
    return [x["match_id"] for x in recap]


class DueMatches(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(due_matches([], LINKED, None, NOW), ([], None))

    def test_oldest_first(self):
        recap, skip = due_matches([m(3, 100), m(1, 3000), m(2, 2000)], LINKED, None, NOW)
        self.assertEqual(ids(recap), [1, 2, 3])
        self.assertIsNone(skip)

    def test_backfill_includes_matches_before_link(self):
        linked = NOW - 1000
        recap, skip = due_matches([m(1, 2000), m(2, 500), m(3, 1000)], linked, None, NOW)
        self.assertEqual(ids(recap), [1, 2, 3])
        self.assertIsNone(skip)

    def test_backfill_ignores_max_age_but_not_window(self):
        linked = NOW - 86400
        history = [m(1, 40 * 86400), m(2, 20 * 86400), m(3, 60)]
        self.assertEqual(ids(due_matches(history, linked, None, NOW)[0]), [2, 3])

    def test_no_skip_while_backfill_pending(self):
        linked = NOW - 5 * 86400
        history = [m(1, 10 * 86400), m(2, 3 * 86400)]  # 1 is backfill, 2 is after the link but too old
        recap, skip = due_matches(history, linked, None, NOW)
        self.assertEqual((ids(recap), skip), ([1], None))

    def test_started_before_link_but_ended_after(self):
        linked = NOW - 1000
        self.assertEqual(ids(due_matches([m(1, 500, duration=1800)], linked, None, NOW)[0]), [1])

    def test_only_newer_than_last(self):
        recap, _ = due_matches([m(1, 300), m(2, 200), m(3, 100)], LINKED, 2, NOW)
        self.assertEqual(ids(recap), [3])

    def test_nothing_new(self):
        self.assertEqual(due_matches([m(1, 300), m(2, 200)], LINKED, 2, NOW), ([], None))

    def test_too_old_skipped_but_advances(self):
        linked = NOW - 5 * 86400
        history = [m(1, 3 * 86400), m(2, 2 * 86400), m(3, MAX_AGE - 1), m(4, 60)]
        recap, skip = due_matches(history, linked, None, NOW)
        self.assertEqual(ids(recap), [3, 4])
        self.assertEqual(skip, 2)

    def test_all_too_old(self):
        linked = NOW - 5 * 86400
        recap, skip = due_matches([m(1, 3 * 86400), m(2, 2 * 86400)], linked, None, NOW)
        self.assertEqual((recap, skip), ([], 2))

    def test_too_old_below_last_not_reported(self):
        linked = NOW - 5 * 86400
        self.assertEqual(due_matches([m(1, 2 * 86400)], linked, 1, NOW), ([], None))

    def test_before_backfill_window_does_not_advance(self):
        self.assertEqual(due_matches([m(1, 34 * 86400)], LINKED, None, NOW), ([], None))

    def test_exactly_max_age_still_posted(self):
        self.assertEqual(ids(due_matches([m(1, MAX_AGE)], LINKED, None, NOW)[0]), [1])


class Embed(unittest.TestCase):
    def test_fields(self):
        match = m(9, 60, duration=1500, hero_id=1, player_team=0, match_result=0, player_kills=5,
                  player_deaths=2, player_assists=7, net_worth=30000, ranked_delta=-300)
        member = MagicMock(display_name="Bob")
        member.display_avatar.url = "https://example.com/a.png"
        e = build_embed(match, [match], {1: "Infernus"}, member)
        self.assertEqual(e.title, "Infernus - Win")
        fields = {f.name: f.value for f in e.fields}
        self.assertEqual(fields["K/D/A"], "5/2/7")
        self.assertEqual(fields["Souls"], "30,000")
        self.assertEqual(fields["Souls/min"], "1,200")
        self.assertEqual(fields["Duration"], "25:00")
        self.assertEqual(fields["Rank change"], "-300")

    def test_no_rank_change_when_zero(self):
        match = m(9, 60, hero_id=99, player_team=1, match_result=0, player_kills=0, player_deaths=0,
                  player_assists=0, net_worth=0, ranked_delta=0)
        member = MagicMock(display_name="Bob")
        member.display_avatar.url = "https://example.com/a.png"
        e = build_embed(match, [match], {}, member)
        self.assertEqual(e.title, "Hero 99 - Loss")
        self.assertNotIn("Rank change", [f.name for f in e.fields])


class SiteLinks(unittest.IsolatedAsyncioTestCase):  # discord.ui.View needs a running event loop
    async def test_author_and_buttons_link_to_the_site(self):
        for post in ({"embed": discord.Embed()}, {"embeds": [discord.Embed(), discord.Embed()]}):
            embed = post.get("embed") or post["embeds"][0]
            embed.set_author(name="craft", icon_url="https://x/a.png")
            add_site_links(post, {"match_id": 7, "hero_id": 3}, 55, "Celeste")
            self.assertEqual(embed.author.url, f"{SITE_URL}/#players/55")
            self.assertEqual(embed.author.icon_url, "https://x/a.png")
            self.assertEqual(embed.url, f"{SITE_URL}/#matches/7/55")
            buttons = [(b.label, b.url) for b in post["view"].children]
            self.assertEqual(buttons, [("The Pitboss", f"{SITE_URL}/"), ("Leaderboards", f"{SITE_URL}/#leaderboards"),
                                       ("Celeste stats", f"{SITE_URL}/#heroes/3")])


class CheckMember(unittest.IsolatedAsyncioTestCase):
    """The loop and recap_now (run on /link) must never check one Member at once, or a recap posts twice."""

    def cog(self):
        from cogs.recaps import Recaps
        from core import db
        bot = MagicMock()
        bot.db = db.connect(":memory:")
        db.set_link(bot.db, 1, 111, 0)
        cog = Recaps(bot)
        self.seen, self.running = [], 0

        async def fake_recap(forum, member, link, assets):
            self.running += 1
            self.assertEqual(self.running, 1, "two checks overlapped")
            self.seen.append(link["last_match_id"])
            await asyncio.sleep(0.01)
            db.update_link(bot.db, 1, last_match_id=(link["last_match_id"] or 0) + 1)  # "posted" a recap
            self.running -= 1
        cog.recap_member = fake_recap
        return cog

    async def test_serialized_and_rereads_link(self):
        cog = self.cog()
        forum = MagicMock()
        await asyncio.gather(cog.check_member(forum, 1, ()), cog.check_member(forum, 1, ()))
        self.assertEqual(self.seen, [None, 1])  # the second check saw the first one's progress

    async def test_unlinked_member_skipped(self):
        cog = self.cog()
        await cog.check_member(MagicMock(), 2, ())
        self.assertEqual(self.seen, [])

    async def test_recap_now_runs_in_background(self):
        cog = self.cog()
        forum = MagicMock()

        async def ctx():
            return forum, ()
        cog.context = ctx
        cog.recap_now(1)
        self.assertEqual(len(cog.tasks), 1)
        await asyncio.gather(*cog.tasks)
        self.assertEqual(self.seen, [None])
        self.assertEqual(cog.tasks, set())


if __name__ == "__main__":
    unittest.main()
