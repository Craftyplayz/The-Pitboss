import unittest

from cogs.link import VANITY_RE, choice_name, confirm_embed, flag, parse_player

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


class Card(unittest.TestCase):
    def test_flag(self):
        self.assertEqual(flag("AU"), "🇦🇺")
        self.assertEqual(flag("au"), "🇦🇺")
        for bad in (None, "", "A", "AUS", "1A"):
            self.assertEqual(flag(bad), "", bad)

    def test_choice_name(self):
        self.assertEqual(choice_name({"personaname": "Ravenye", "countrycode": "AU", "account_id": 54718219}),
                         "Ravenye · 🇦🇺 · 54718219")
        self.assertEqual(choice_name({"personaname": "Raven", "account_id": 1}), "Raven · 1")
        self.assertEqual(len(choice_name({"personaname": "x" * 200, "account_id": 1})), 100)

    def test_confirm_embed(self):
        player = {"personaname": "Ravenye", "account_id": 54718219, "countrycode": "AU",
                  "profileurl": "https://steamcommunity.com/id/Ravenye/", "avatarfull": "https://a/full.jpg"}
        hist = [{"start_time": 100, "match_duration_s": 50}, {"start_time": 300, "match_duration_s": 60}]
        e = confirm_embed(player, hist)
        self.assertEqual(e.thumbnail.url, "https://a/full.jpg")
        self.assertEqual(e.url, "https://steamcommunity.com/id/Ravenye/")
        fields = {f.name: f.value for f in e.fields}
        self.assertEqual(fields["Deadlock Matches"], "2")
        self.assertEqual(fields["Last played"], "<t:360:R>")
        empty = confirm_embed({"personaname": "New", "account_id": 5}, [])
        self.assertEqual({f.name: f.value for f in empty.fields}, {"Deadlock Matches": "None found"})


if __name__ == "__main__":
    unittest.main()
