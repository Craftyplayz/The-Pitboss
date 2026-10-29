import unittest

from cogs.link import VANITY_RE, parse_player

S = 76561197960265728


class ParsePlayer(unittest.TestCase):
    def test_forms(self):
        self.assertEqual(parse_player("12345"), 12345)
        self.assertEqual(parse_player(str(S + 12345)), 12345)
        for u in ("https://steamcommunity.com/profiles/%d/", "steamcommunity.com/profiles/%d",
                  "http://www.steamcommunity.com/profiles/%d"):
            self.assertEqual(parse_player(u % (S + 12345)), 12345)
        self.assertEqual(parse_player(f"  {S + 7}  "), 7)

    def test_rejects(self):
        for t in ("", "abc", "0", str(S), "https://steamcommunity.com/id/foo", "-5", str(S + 2**32)):
            self.assertIsNone(parse_player(t), t)


class Vanity(unittest.TestCase):
    def test_match(self):
        for u in ("https://steamcommunity.com/id/foo-bar_1/", "steamcommunity.com/id/foo-bar_1",
                  "http://www.steamcommunity.com/id/foo-bar_1"):
            self.assertEqual(VANITY_RE.match(u).group(1), "foo-bar_1")
        for t in ("foo", "steamcommunity.com/profiles/123", "evil.com/steamcommunity.com/id/foo"):
            self.assertIsNone(VANITY_RE.match(t), t)


if __name__ == "__main__":
    unittest.main()
