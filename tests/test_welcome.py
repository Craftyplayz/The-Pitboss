import unittest
from types import SimpleNamespace

from cogs.welcome import DEFAULT, fill

MEMBER = SimpleNamespace(mention="<@1>", display_name="Crafty", guild=SimpleNamespace(name="The Back Room", member_count=42))


class Fill(unittest.TestCase):
    def test_default(self):
        self.assertEqual(fill(DEFAULT, MEMBER), "Welcome to **The Back Room**, <@1>! You're member #42.")

    def test_every_placeholder_twice(self):
        self.assertEqual(fill("{user} {user} {name} {server} {count}", MEMBER), "<@1> <@1> Crafty The Back Room 42")

    def test_stray_braces_are_kept(self):
        self.assertEqual(fill("hi {nope} {", MEMBER), "hi {nope} {")
