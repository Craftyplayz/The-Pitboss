import json
import unittest

from core.dashboard import hero_analytics, hero_items, match_detail, player_entry, server_matches
from tests.test_recap_embed import ITEMS, META
from web import render_page

NOW = 1_800_000_000


def hist(match_id, ago, win=True, hero=1, k=5):
    return {"match_id": match_id, "hero_id": hero, "start_time": NOW - ago, "player_kills": k, "player_deaths": 2,
            "player_assists": 3, "net_worth": 30000, "match_duration_s": 1800, "match_result": 0 if win else 1,
            "player_team": 0, "last_hits": 100}


HERO_STATS = [{"hero_id": 1, "matches_played": 10, "time_played": 18000, "damage_per_min": 800.0,
               "last_hits_per_min": 4.0, "accuracy": 0.42, "networth_per_min": 1000.0}]


class Dashboard(unittest.TestCase):
    def test_player_entry_escapes_steam_text(self):
        profile = {"personaname": '<img src=x onerror="alert(1)">', "avatarmedium": 'https://a/"x', "countrycode": None}
        mates = [{"mate_id": 9, "matches_played": 3, "wins": 2}, {"mate_id": 2, "matches_played": 9, "wins": 9}]
        p = player_entry(1, profile, 103, [hist(1, 100), hist(2, 50, win=False, hero=2)], HERO_STATS, mates, [],
                         {1, 2}, {9: {"personaname": "<b>"}})
        self.assertNotIn("<", p["name"])
        self.assertNotIn('"', p["av"])
        self.assertEqual((p["tier"], p["sub"]), (10, 3))
        self.assertEqual((p["n"], p["w"]), (2, 1))
        self.assertEqual(p["form"], [1, 0])  # oldest -> newest
        self.assertEqual(p["g"][0][0], 2)  # newest first
        self.assertEqual(p["spm"], 1000)
        self.assertEqual([m[0] for m in p["mate"]], [9])  # Linked Player 2 is excluded
        self.assertEqual(p["mate"][0][1], "&lt;b&gt;")
        self.assertEqual((p["dpm"], p["acc"], p["at"]), (800, 42, 10))
        self.assertIsNone(player_entry(1, profile, 0, [], [], [], [], set(), {}))

    def test_server_matches_merges_linked_players(self):
        h = {1: [hist(7, 3600)], 2: [hist(7, 3600, win=False), hist(8, 40 * 86400)]}
        sm, days = server_matches([{"id": 1}, {"id": 2}], h, NOW)
        self.assertEqual([m["id"] for m in sm], [7, 8])
        self.assertEqual(len(sm[0]["pl"]), 2)
        self.assertEqual(days[0], 1)
        self.assertEqual(sum(days), 1)  # the 40-day-old match is outside the 30 bars

    def test_hero_analytics(self):
        rows = [{"hero_id": 1, "wins": 60, "matches": 100, "total_kills": 500, "total_deaths": 400, "total_assists": 700,
                 "total_net_worth": 3_000_000},
                {"hero_id": 2, "wins": 50, "matches": 100, "total_kills": 0, "total_deaths": 0, "total_assists": 0,
                 "total_net_worth": 0}]
        a = hero_analytics(rows)
        self.assertEqual(a[1][:3], [60.0, 600.0, 5.0])
        self.assertEqual(a[1][5], 30000)

    def test_match_detail(self):
        d = match_detail(META, ITEMS, {1: "<script>"})
        me = d["pl"][0]
        self.assertEqual(me["nm"], "&lt;script&gt;")
        self.assertEqual(me["items"], [10, 11])
        self.assertEqual(me["acc"], 60)
        self.assertEqual(len(me["src"]), 6)
        self.assertEqual(d["tc"][0], [45000])  # team 0 = players 1 and 2

    def test_hero_items(self):
        rows = [{"item_id": 10, "matches": 5, "wins": 4}, {"item_id": 11, "matches": 9, "wins": 3},
                {"item_id": 12, "matches": 99, "wins": 50}]
        self.assertEqual(hero_items(rows, ITEMS), [[11, 9, 33.3], [10, 5, 80.0]])

    def test_render_page_cannot_close_script(self):
        page = render_page("<script>const D=/*DATA*/null;</script>", {"n": "</script><script>alert(1)</script>"})
        self.assertEqual(page.count("</script>"), 1)
        payload = page[len("<script>const D="):-len(";</script>")]
        self.assertEqual(json.loads(payload)["n"], "</script><script>alert(1)</script>")


if __name__ == "__main__":
    unittest.main()
