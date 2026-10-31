import json
import unittest

from cogs.welcome import DEFAULT, DEFAULT_TEXT, load
from core import db
from core.embeds import clean, fill, render

VALUES = {"user": "<@1>", "name": "Crafty", "server": "The Back Room", "count": 42}


class Fill(unittest.TestCase):
    def test_every_placeholder_twice(self):
        self.assertEqual(fill("{user} {user} {name} {server} {count}", VALUES), "<@1> <@1> Crafty The Back Room 42")

    def test_stray_braces_are_kept(self):
        self.assertEqual(fill("hi {nope} {", VALUES), "hi {nope} {")


class Render(unittest.TestCase):
    def test_default(self):
        content, embed = render(DEFAULT, VALUES, "https://cdn/a.png", "2026-10-31T00:00:00+00:00")
        self.assertEqual(content, "<@1>")
        self.assertEqual(embed["title"], "Welcome to The Back Room!")
        self.assertEqual(embed["description"], "Hey <@1>, glad you're here! You're member **#42**.")
        self.assertEqual(embed["color"], 0xF0C35A)
        self.assertEqual(embed["thumbnail"], {"url": "https://cdn/a.png"})
        self.assertEqual(embed["timestamp"], "2026-10-31T00:00:00+00:00")
        self.assertNotIn("author", embed)

    def test_author_image_footer(self):
        cfg = {**DEFAULT, "show_author": True, "author": "", "image": "https://x/big.png", "footer": "#{count}", "thumbnail": False}
        _, embed = render(cfg, VALUES, "https://cdn/a.png")
        self.assertEqual(embed["author"], {"name": "Crafty", "icon_url": "https://cdn/a.png"})  # empty author line: their name
        self.assertEqual(embed["image"], {"url": "https://x/big.png"})
        self.assertEqual(embed["footer"], {"text": "#42"})
        self.assertNotIn("thumbnail", embed)
        self.assertNotIn("timestamp", embed)  # no time given

    def test_empty_embed_still_valid(self):
        _, embed = render({"color": "#000000"}, VALUES)
        self.assertEqual(embed["description"], "​")


class Clean(unittest.TestCase):
    def test_limits_and_bad_values(self):
        cfg = clean({"embed_title": "x" * 300, "embed_color": "red", "embed_image": "javascript:alert(1)",
                     "embed_thumbnail": "1", "embed_description": "  hi  "})
        self.assertEqual(len(cfg["title"]), 256)
        self.assertEqual(cfg["color"], "#F0C35A")
        self.assertEqual(cfg["image"], "")
        self.assertEqual(cfg["description"], "hi")
        self.assertTrue(cfg["thumbnail"])
        self.assertFalse(cfg["timestamp"])  # unticked boxes aren't sent

    def test_good_values_kept(self):
        cfg = clean({"embed_color": "#12abEF", "embed_image": "https://x/y.png"})
        self.assertEqual((cfg["color"], cfg["image"]), ("#12abEF", "https://x/y.png"))


class Load(unittest.TestCase):
    def test_fallbacks(self):
        conn = db.connect(":memory:")
        self.assertEqual(load(conn)["description"], DEFAULT_TEXT)
        db.set_setting(conn, "welcome_message", "Old text {user}")  # saved before embeds existed
        self.assertEqual(load(conn)["description"], "Old text {user}")
        db.set_setting(conn, "welcome_embed", json.dumps({"title": "New"}))
        self.assertEqual((load(conn)["title"], load(conn)["description"]), ("New", DEFAULT_TEXT))
