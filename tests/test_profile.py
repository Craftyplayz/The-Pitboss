import unittest
from unittest.mock import MagicMock

from cogs._profile_embed import build_profile_embed, form, hero_table, mates_text, streaks, trend, weighted


def m(i, win, k=5, d=2, a=3, nw=20000, hero=1, dur=1800, delta=None):
    return {"match_id": i, "start_time": 1_790_000_000 + i * 3600, "match_duration_s": dur, "player_team": 0,
            "match_result": 0 if win else 1, "player_kills": k, "player_deaths": d, "player_assists": a,
            "net_worth": nw, "last_hits": 100, "hero_id": hero, "ranked_delta": delta}


HS = [{"hero_id": 1, "matches_played": 3, "wins": 2, "kills": 15, "deaths": 6, "assists": 9, "networth_per_min": 1000,
       "accuracy": 0.5, "crit_shot_rate": 0.1, "damage_per_min": 600, "obj_damage_per_min": 100},
      {"hero_id": 2, "matches_played": 1, "wins": 0, "kills": 1, "deaths": 4, "assists": 2, "networth_per_min": 800,
       "accuracy": 0.3, "crit_shot_rate": None, "damage_per_min": 400, "obj_damage_per_min": 50}]
HEROES = {1: {"name": "Drifter", "images": {"icon_image_small": "https://x/drifter.png"}}, 2: {"name": "Wraith"}}


def member():
    mem = MagicMock()
    mem.mention = "<@42>"
    return mem


class Profile(unittest.TestCase):
    def test_form_oldest_to_newest(self):
        self.assertEqual(form([m(2, False), m(1, True), m(3, True)]), "🟩🟥🟩  2W 1L")

    def test_streaks(self):
        self.assertEqual(streaks([m(1, True), m(2, True), m(3, False), m(4, True), m(5, True), m(6, True)]), (3, True, 3))
        self.assertEqual(streaks([m(1, True), m(2, False), m(3, False)]), (2, False, 1))
        self.assertEqual(streaks([]), (0, False, 0))

    def test_weighted_skips_missing(self):
        self.assertAlmostEqual(weighted(HS, "accuracy"), (0.5 * 3 + 0.3) / 4)
        self.assertAlmostEqual(weighted(HS, "crit_shot_rate"), 0.1)
        self.assertIsNone(weighted([], "accuracy"))

    def test_hero_table_sorted_by_matches(self):
        rows = hero_table(HS, {1: "Drifter", 2: "Wraith"}).splitlines()
        self.assertEqual(rows[0], "**Drifter** · 3 Matches · 67% · 4.00 KDA · 1,000 souls/min · 50% acc")
        self.assertTrue(rows[1].startswith("**Wraith**"))

    def test_mates_mention_linked(self):
        mates = [{"mate_id": 7, "matches_played": 5, "wins": 3}, {"mate_id": 8, "matches_played": 9, "wins": 3}]
        text = mates_text(mates, {7: "Huski", 8: "Kit"}, {7: 99})
        self.assertEqual(text.splitlines(), ["**Kit** · 9 together · 33%", "<@99> · 5 together · 60%"])

    def test_trend_win_rate_starts_at_full_window(self):
        ms = [m(i, i % 2 == 0) for i in range(1, 13)]
        points, title, kw = trend(ms, ranked=False)
        self.assertEqual([p[0] for p in points], [10, 11, 12])
        self.assertEqual(points[0][1], 50)
        self.assertEqual(kw["y_range"], (0, 100))
        self.assertIsNone(trend(ms[:9], ranked=False))

    def test_trend_rank_is_cumulative(self):
        ms = [m(1, True, delta=300), m(2, False, delta=-300), m(3, True, delta=430), m(4, True)]
        points, title, _ = trend(ms, ranked=True)
        self.assertEqual(points, [(1, 300), (2, 0), (3, 430)])
        self.assertIn("Rank progress", title)

    def test_embed(self):
        hist = [m(i, i % 3 != 0) for i in range(1, 13)]
        steam = {"personaname": "Ravenye", "profileurl": "https://s/r", "countrycode": "AU", "avatarmedium": "https://a"}
        e = build_profile_embed(member(), steam, "Unranked", None, hist, HS, [], {}, {}, HEROES)
        self.assertEqual(e.title, "Ravenye's Profile")
        self.assertEqual(e.thumbnail.url, "https://x/drifter.png")
        names = [f.name for f in e.fields]
        self.assertIn("Top heroes", names)
        self.assertIn("Records", names)
        self.assertTrue(all(len(f.value) <= 1024 for f in e.fields))
        self.assertLessEqual(len(e), 6000)

    def test_embed_no_matches(self):
        e = build_profile_embed(member(), None, "Ascendant 1", "https://r", [], [], [], {}, {}, HEROES)
        self.assertIn("No Matches", e.description)
        self.assertEqual(e.thumbnail.url, "https://r")
        self.assertEqual(e.fields, [])


if __name__ == "__main__":
    unittest.main()
