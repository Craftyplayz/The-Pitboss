import unittest

from core import db
from core.trophies import match_stats, player_trophies, rarity


def match(t, hero=1, win=True, k=2, d=1, a=3, souls=30000, dur=1800):
    return {"start_time": t, "hero_id": hero, "match_result": 0, "player_team": 0 if win else 1,
            "player_kills": k, "player_deaths": d, "player_assists": a, "net_worth": souls, "match_duration_s": dur}


DAY = 86400


class PlayerTrophies(unittest.TestCase):
    def setUp(self):
        # 3 days in a row, then a gap; matches given out of order
        self.ms = [match(2 * DAY, hero=2, win=False), match(0, k=10), match(DAY, d=0, k=6, a=5),
                   match(10 * DAY, dur=1000)]
        self.got, self.progress, self.won_with, _ = player_trophies(self.ms, [], hero_count=30, item_count=170)
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
        got, progress, won_with, _ = player_trophies([], [], hero_count=30, item_count=170)
        self.assertEqual((got, won_with), ([], []))
        self.assertIsNone(progress["kills"])


ITEMS = {10: {"type": "upgrade", "item_slot_type": "weapon"}, 11: {"type": "upgrade", "item_slot_type": "spirit"},
         99: {"type": "ability"}}


def meta(kill_times, mvp=None):
    me = {"account_id": 7, "player_slot": 1, "team": 0, "mvp_rank": mvp,
          "items": [{"item_id": 10}, {"item_id": 99}, {"item_id": 11}, {"item_id": 10}],
          "stats": [{"player_damage": 500, "player_damage_taken": 400, "player_healing": 300, "headshot_kills": 1,
                     "melee_kills": 0, "ability_kills": 2, "shots_hit": 140, "shots_missed": 60}],
          "death_details": [{"game_time_s": 5, "killer_player_slot": 9}]}
    enemy = {"account_id": 8, "player_slot": 9, "team": 1,
             "death_details": [{"game_time_s": t, "killer_player_slot": 1} for t in kill_times]}
    return {"match_info": {"players": [me, enemy]}}


class MatchStats(unittest.TestCase):
    def test_numbers(self):
        s = match_stats(meta([100, 108, 117, 200], mvp=1), 7, ITEMS)
        self.assertEqual((s["dmg"], s["taken"], s["heal"], s["head"], s["abil"], s["mvp"]), (500, 400, 300, 1, 2, 1))
        self.assertEqual(s["multi"], 3)  # 100, 108, 117: each within 10s of the last
        self.assertEqual((s["weapon"], s["vitality"], s["spirit"], s["items"]), (2, 0, 1, [10, 11]))
        self.assertEqual((s["hit"], s["shots"]), (140, 200))

    def test_not_in_match(self):
        self.assertIsNone(match_stats(meta([]), 1, ITEMS))

    def test_meta_families(self):
        rows = [{**match_stats(meta([1, 2, 3]), 7, ITEMS), "start_time": 50},
                {**match_stats(meta([], mvp=1), 7, ITEMS), "start_time": 10}]
        got, progress, _, items = player_trophies([], rows, hero_count=30, item_count=2)
        tiers = {(k, t): when for k, t, when in got}
        self.assertEqual(tiers[("multi", 0)], 50)
        self.assertEqual(tiers[("mvp", 0)], 10)
        self.assertEqual(tiers[("acc", 0)], 10)  # 70% of 200 shots
        self.assertEqual(progress["collector"], 2)
        self.assertEqual(progress["dmg"], 1000)
        self.assertEqual(items, [10, 11])


class SavedStats(unittest.TestCase):
    def test_round_trip(self):
        conn = db.connect(":memory:")
        db.save_match_stats(conn, 7, 1, 100, {"dmg": 5})
        db.save_match_stats(conn, 7, 1, 100, {"dmg": 9})  # first save wins
        db.save_match_stats(conn, 7, 2, 200, None)
        self.assertEqual(db.saved_match_ids(conn, 7), {1, 2})
        self.assertEqual(db.match_stats(conn, 7), [{"dmg": 5, "start_time": 100}])


class Rarity(unittest.TestCase):
    def test_share_of_players(self):
        self.assertEqual(rarity([[["kills", 0, 1]], [["kills", 0, 2], ["kills", 1, 3]], []]),
                         {"kills:0": 67, "kills:1": 33})


if __name__ == "__main__":
    unittest.main()
