import unittest

from core.trophies import player_trophies, rarity


def match(t, hero=1, win=True, k=2, d=1, a=3, souls=30000, dur=1800):
    return {"start_time": t, "hero_id": hero, "match_result": 0, "player_team": 0 if win else 1,
            "player_kills": k, "player_deaths": d, "player_assists": a, "net_worth": souls, "match_duration_s": dur}


DAY = 86400


class PlayerTrophies(unittest.TestCase):
    def setUp(self):
        # 3 days in a row, then a gap; matches given out of order
        self.ms = [match(2 * DAY, hero=2, win=False), match(0, k=10), match(DAY, d=0, k=6, a=5),
                   match(10 * DAY, dur=1000)]
        self.got, self.progress, self.won_with = player_trophies(self.ms, hero_count=30)
        self.tiers = {}
        for key, tier, when in self.got:
            self.tiers.setdefault(key, []).append((tier, when))

    def test_tier_dated_by_the_match_that_reached_it(self):
        self.assertEqual(self.tiers["kills"], [(0, DAY)])  # 10 + 6 = 16 >= 15 on day 1
        self.assertEqual(self.tiers["matches"], [(0, 2 * DAY)])  # 3rd match

    def test_streaks_and_days(self):
        self.assertEqual(self.progress["winstreak"], 2)
        self.assertEqual(self.progress["losestreak"], 1)
        self.assertEqual(self.progress["grind"], 3)
        self.assertEqual(self.tiers["grind"], [(0, DAY)])

    def test_single_match_and_lower_is_better(self):
        self.assertEqual(self.tiers["untouchable"], [(0, DAY), (1, DAY)])  # 0 deaths, K+A 11
        self.assertEqual(self.progress["stomp"], 16.7)
        self.assertEqual([t for t, _ in self.tiers["stomp"]], [0, 1, 2, 3])  # 16.7 min: under 25, 22, 20, 17

    def test_heroes(self):
        self.assertEqual(self.won_with, [1])
        self.assertEqual(self.progress["h1"], 3)
        self.assertEqual(self.tiers["h1"], [(0, 10 * DAY)])
        self.assertNotIn("jack", self.tiers)

    def test_no_matches(self):
        got, progress, won_with = player_trophies([], hero_count=30)
        self.assertEqual((got, won_with), ([], []))
        self.assertIsNone(progress["kills"])


class Rarity(unittest.TestCase):
    def test_share_of_players(self):
        self.assertEqual(rarity([[["kills", 0, 1]], [["kills", 0, 2], ["kills", 1, 3]], []]),
                         {"kills:0": 67, "kills:1": 33})


if __name__ == "__main__":
    unittest.main()
