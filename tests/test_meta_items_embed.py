import unittest

from cogs._meta_items_embed import items_embed

ASSETS = {1: {"name": "Alpha", "item_slot_type": "weapon"}, 2: {"name": "Beta", "item_slot_type": "spirit"},
          3: {"name": "Gamma", "item_slot_type": "weapon"}}
HERO = {"name": "Abrams", "colors": {"ui": [1, 2, 3]}, "images": {"icon_image_small": "http://x/i.png"}}


def row(i, wins=60, matches=100):
    return {"item_id": i, "wins": wins, "matches": matches}


class ItemsEmbed(unittest.TestCase):
    def test_grouping_and_ranks(self):
        e = items_embed([row(1), row(2), row(3)], ASSETS, {1: "<:a:1>"}, None, 7, 5000)
        self.assertEqual([f.name for f in e.fields], ["Weapon", "Spirit"])
        self.assertEqual(e.fields[0].value.splitlines(), ["`1.` <:a:1> **Alpha** · 60.0% · 100 matches", "`3.` **Gamma** · 60.0% · 100 matches"])
        self.assertTrue(e.fields[1].value.startswith("`2.` **Beta**"))
        self.assertEqual(e.footer.text, "Last 7 days · at least 5,000 matches per item")

    def test_hero_vs_none(self):
        h = items_embed([row(1)], ASSETS, {}, HERO, 7, 200)
        self.assertEqual(h.title, "Best items for Abrams")
        self.assertEqual(h.color.to_rgb(), (1, 2, 3))
        self.assertEqual(h.thumbnail.url, "http://x/i.png")
        n = items_embed([row(1)], ASSETS, {}, None, 7, 200)
        self.assertEqual(n.title, "Best items")
        self.assertIsNone(n.thumbnail.url)
        self.assertNotEqual(n.color.to_rgb(), (1, 2, 3))

    def test_empty(self):
        self.assertEqual(items_embed([], ASSETS, {}, None, 7, 200).description, "No items with enough matches.")

    def test_limits(self):
        assets = {i: {"name": "N" * 40, "item_slot_type": "weapon"} for i in range(30)}
        e = items_embed([row(i, matches=1234567) for i in range(30)], assets, {i: "<:" + "e" * 26 + ":1>" for i in range(30)}, HERO, 7, 200)
        self.assertGreater(len(e.fields), 1)
        self.assertEqual(sum(f.value.count("\n") + 1 for f in e.fields), 20)
        self.assertTrue(all(len(f.value) <= 1024 for f in e.fields))
        self.assertLessEqual(len(e), 6000)


if __name__ == "__main__":
    unittest.main()
