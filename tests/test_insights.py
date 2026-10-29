import unittest

from cogs._insights import match_insights, profile_insights


def entry(i, hero=1, win=True, k=5, d=5, a=5, nw=10000, dur=1200):
    return {"match_id": i, "hero_id": hero, "player_team": 0, "match_result": 0 if win else 1,
            "player_kills": k, "player_deaths": d, "player_assists": a,
            "net_worth": nw, "match_duration_s": dur}


NAMES = {1: "Abrams", 2: "Haze"}


class Insights(unittest.TestCase):
    def test_too_little_data(self):
        h = [entry(i) for i in range(5)]
        self.assertEqual(profile_insights(h, NAMES), [])
        self.assertEqual(match_insights(h[0], h, NAMES), [])

    def test_best_hero_and_streak(self):
        # 6 Haze wins (newest) then 6 Abrams losses
        h = [entry(i, hero=2, win=True) for i in range(6)] + [entry(10 + i, hero=1, win=False) for i in range(6)]
        out = profile_insights(h, NAMES)
        self.assertTrue(any("Best hero: Haze" in s for s in out))
        self.assertTrue(any("Worst hero: Abrams" in s for s in out))
        self.assertTrue(any("6-match win streak" in s for s in out))

    def test_one_win_is_not_best(self):
        h = [entry(i, hero=1, win=i % 2 == 0) for i in range(12)] + [entry(99, hero=2, win=True)]
        self.assertFalse(any("Haze" in s for s in profile_insights(h, NAMES)))

    def test_match_kda_and_souls(self):
        m = entry(100, k=15, d=1, a=10, nw=40000)
        out = match_insights(m, [m] + [entry(i, win=i % 2 == 0) for i in range(12)], NAMES)
        self.assertTrue(any(s.startswith("KDA") and "above" in s for s in out))
        self.assertTrue(any("souls/min" in s and "above" in s for s in out))
        self.assertLessEqual(len(out), 3)


if __name__ == "__main__":
    unittest.main()
