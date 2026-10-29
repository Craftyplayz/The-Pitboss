import unittest

from tests.test_recap_embed import HEROES, ITEMS, META
from web import index_page, match_page, player_page


class Pages(unittest.TestCase):
    def test_index_escapes_names(self):
        text = index_page([{"account_id": 5, "linked_at": 1_700_000_000}], {5: "<script>x</script>"})
        self.assertIn("&lt;script&gt;", text)
        self.assertNotIn("<script>x", text)
        self.assertIn('href="/player/5"', text)
        self.assertIn("No one is linked", index_page([], {}))

    def test_player(self):
        m = {"match_id": 9, "hero_id": 1, "start_time": 1_700_000_000, "match_result": 0, "player_team": 0,
             "player_kills": 1, "player_deaths": 2, "player_assists": 3, "net_worth": 12345, "match_duration_s": 1805}
        text = player_page(5, "craft", None, [m], {1: "Violet"})
        for s in ("Violet", "Win", "1/2/3", "12,345", "30:05", 'href="/match/9/5"', "Unranked"):
            self.assertIn(s, text)

    def test_match(self):
        text = match_page(META, 1, HEROES, ITEMS)
        for s in ("Violet · Win", "Mystic Shot", "Lost on death", "YOUR TEAM · Win", "ENEMY TEAM · Loss", "you"):
            self.assertIn(s, text)
        self.assertIsNone(match_page(META, 999, HEROES, ITEMS))


if __name__ == "__main__":
    unittest.main()
