import unittest

from PIL import Image

from cogs.meta import buy_path, hero_embed, place, rank_by_wr, trend_points, week_change, win_rate
from core.recap_images import buy_path_image


class MetaHelpers(unittest.TestCase):
    def test_win_rate(self):
        self.assertEqual(win_rate(1, 4), 25.0)
        self.assertEqual(win_rate(0, 0), 0.0)

    def test_rank_by_wr_min_matches_and_order(self):
        rows = [
            {"w": 9, "m": 10},  # 90% but too few matches
            {"w": 60, "m": 100},
            {"w": 55, "m": 100},
        ]
        out = rank_by_wr(rows, "w", "m", 100)
        self.assertEqual([r["w"] for r in out], [60, 55])


class HeroEmbed(unittest.TestCase):
    STATS = [{"hero_id": 1, "wins": 60, "matches": 100}, {"hero_id": 2, "wins": 45, "matches": 300},
             {"hero_id": 3, "wins": 50, "matches": 200}]

    def test_place(self):
        win = lambda r: win_rate(r["wins"], r["matches"])
        self.assertEqual(place(self.STATS, win, 3), (2, 3))
        self.assertEqual(place(self.STATS, lambda r: r["matches"], 2), (1, 3))

    def test_trend_skips_today_and_empty_days(self):
        now = 10 * 86400 + 500
        daily = [{"bucket": 9 * 86400, "wins": 1, "matches": 2}, {"bucket": 8 * 86400, "wins": 3, "matches": 4},
                 {"bucket": 10 * 86400, "wins": 1, "matches": 1}, {"bucket": 7 * 86400, "wins": 0, "matches": 0}]
        self.assertEqual(trend_points(daily, now), [(8 * 86400, 75.0), (9 * 86400, 50.0)])

    def test_week_change(self):
        self.assertIsNone(week_change([(i, 50) for i in range(13)]))
        self.assertAlmostEqual(week_change([(i, 50) for i in range(7)] + [(i, 52) for i in range(7)]), 2)

    def test_embed(self):
        hero = {"id": 2, "name": "The Doorman", "colors": {"ui": [156, 205, 236]}, "images": {"icon_image_small": "https://x/d.png"}}
        row = dict(self.STATS[1], total_kills=600, total_deaths=900, total_assists=1500, total_net_worth=9_000_000,
                   total_shots_hit=300, total_shots_missed=700)
        heroes = {1: {"name": "Mina"}, 3: {"name": "Rat King"}}
        items = [{"item_id": 9, "wins": 57, "matches": 100}]
        counters = [{"enemy_hero_id": 1, "wins": 52, "matches_played": 100}, {"enemy_hero_id": 3, "wins": 38, "matches_played": 100}]
        e = hero_embed(hero, row, self.STATS, items, {9: {"name": "Magic Carpet"}}, {9: "<:i9:1>"}, counters,
                       [{"hero_id": 3, "wins": 54, "matches_played": 100}], heroes, {1: "<:h1:2>"}, -1.2)
        self.assertEqual(e.thumbnail.url, "https://x/d.png")
        self.assertIn("#3 of 3 heroes", e.description)
        self.assertIn("Down 1.2 points", e.description)
        f = {x.name: x.value for x in e.fields}
        self.assertEqual(f["Pick rate"], "50.0% · #1")
        self.assertEqual(f["Avg K / D / A"], "2.0 / 3.0 / 5.0")
        self.assertEqual(f["Accuracy"], "30.0%")
        self.assertEqual(f["Top items · win rate · matches"], "<:i9:1> **Magic Carpet** · 57.0% · 100")
        self.assertEqual(f["Best matchups"].splitlines()[0], "<:h1:2> **Mina** · 52.0%")
        self.assertEqual(f["Worst matchups"].splitlines()[0], "**Rat King** · 38.0%")

    def test_embed_no_row(self):
        e = hero_embed({"id": 5, "name": "X"}, None, [], [], {}, {}, [], [], {}, {}, None)
        self.assertEqual(e.description, "No matches in this window.")


class BuyPath(unittest.TestCase):
    FLOW = {"summary": {"wins": 50, "matches": 100}, "nodes": [
        {"column": 0, "item_id": 1, "wins": 30, "matches": 60},
        {"column": 0, "item_id": 2, "wins": 50, "matches": 80},
        {"column": 0, "item_id": 9, "wins": 99, "matches": 99},  # not an upgrade: left out
        {"column": 2, "item_id": 3, "wins": 0, "matches": 0},  # no matches: left out, so the column is dropped
        {"column": 1, "item_id": 3, "wins": 5, "matches": 10},
    ]}
    ITEMS = {1: {"name": "A"}, 2: {"name": "B"}, 3: {"name": "Some very long item name indeed"}}

    def test_columns_most_bought_first(self):
        cols = buy_path(self.FLOW, self.ITEMS)
        self.assertEqual(cols, [("0–9 min", [(2, 0.8, 0.625), (1, 0.6, 0.5)]), ("9–20 min", [(3, 0.1, 0.5)])])
        self.assertEqual(len(buy_path(self.FLOW, self.ITEMS, per=1)[0][1]), 1)

    def test_no_matches(self):
        self.assertEqual(buy_path({}, self.ITEMS), [])
        self.assertEqual(buy_path({"summary": {"matches": 0}, "nodes": []}, self.ITEMS), [])

    def test_image(self):
        cols = [(label, [(self.ITEMS[i]["name"], b"not a png" if i == 3 else None, buy, win) for i, buy, win in rows])
                for label, rows in buy_path(self.FLOW, self.ITEMS)]
        img = Image.open(buy_path_image(cols, 0.5))
        self.assertEqual(img.format, "PNG")
        self.assertEqual(img.width, 800)


if __name__ == "__main__":
    unittest.main()
