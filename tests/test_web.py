import json
import unittest

from core.dashboard import (GRAPH, PAGE, hero_analytics, hero_items, history_page, item_info, match_detail, player_entry,
                            server_matches)
from tests.test_recap_embed import ITEMS, META
from core.shared import item_icon
from web import hero_items_api, player_matches_api, render_page

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
        p = player_entry(1, profile, 103, [hist(1, 100), hist(2, 50, win=False, hero=2)], NOW - 1000, HERO_STATS, mates, [],
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
        self.assertIsNone(player_entry(1, profile, 0, [], 0, [], [], [], set(), {}))

    def test_player_entry_all_time_vs_window(self):
        old = [hist(i, 90 * 86400 + i, win=i % 2 == 0, k=i) for i in range(1, 61)]  # 60 old Matches, 1 newest
        p = player_entry(1, {}, 0, [hist(100, 50, win=False, hero=2), *old], NOW - 30 * 86400, [], [], [], set(), {})
        self.assertEqual((p["n"], p["w"], p["g"][0][0], p["form"]), (1, 0, 100, [0]))  # window: one Match
        a = p["al"]
        self.assertEqual((a["n"], a["w"], a["k"]), (61, 30, 5 + sum(range(1, 61))))
        self.assertEqual(a["sk"], [0, 2])  # the newest loss plus old Match 1, a loss
        self.assertEqual([r[0] for r in a["hero"]], [1, 2])
        self.assertEqual(len(a["g"]), PAGE)
        self.assertEqual(a["g"][0][0], 100)  # newest first
        self.assertEqual(a["best"][0], 60)  # most kills, same deaths
        self.assertEqual((a["len"], a["nw"], a["lh"], a["spm"]), (1800, 30000, 100, 1000))
        self.assertEqual(len(a["sg"]), GRAPH)
        self.assertEqual(a["sg"][-1], [NOW - 50, 1000, 0])  # oldest -> newest

    def test_player_entry_without_recent_matches(self):
        p = player_entry(1, {}, 0, [hist(1, 90 * 86400)], NOW - 30 * 86400, [], [], [], set(), {})
        self.assertEqual((p["n"], p["g"], p["form"], p["spm"], p["al"]["n"]), (0, [], [], 0, 1))

    def test_history_page(self):
        games = [hist(i, i) for i in range(1, 66)]  # match 1 is newest
        self.assertEqual([r[0] for r in history_page(games, 0)], list(range(1, 31)))
        self.assertEqual([r[0] for r in history_page(games, 2)], list(range(61, 66)))
        self.assertEqual(history_page(games, 3), [])

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

    def test_item_info(self):
        item = {"description": {"desc": 'Apply a <span class="highlight">Stun</span><svg><path/></svg>.<br>Isn\'t <b>safe</b>'},
                "is_active_item": True,
                "tooltip_sections": [{"section_attributes": [{"properties": ["Health", "Zero", "Unlabelled"]},
                                                             {"elevated_properties": ["Range"]}]}],
                "properties": {"Health": {"value": "75", "label": "Bonus Health", "prefix": "{s:sign}"},
                               "Zero": {"value": "0", "label": "Nothing"},
                               "Unlabelled": {"value": "3"},
                               "Range": {"value": "45m", "label": "Cast Range", "postfix": "m"},
                               "AbilityCooldown": {"value": "-35", "label": "Cooldown", "prefix": "+", "postfix": "s"}}}
        self.assertEqual(item_info(item), ["Apply a Stun.\nIsn&#x27;t safe",
                                           [["Bonus Health", "+75"], ["Cast Range", "45m"], ["Cooldown", "-35s"]]])
        self.assertEqual(item_info({}), ["", []])

    def test_item_icon_falls_back_to_shop_image(self):
        self.assertEqual(item_icon({"image": "a.png", "shop_image": "b.png"}), "a.png")
        self.assertEqual(item_icon({"shop_image": "b.png"}), "b.png")  # e.g. Stalker
        self.assertEqual(item_icon({}), "")
        self.assertEqual(item_icon({"image": "parry.svg", "shop_image": "rebuttal.png"}), "rebuttal.png")

    def test_render_page_cannot_close_script(self):
        page = render_page("<script>const D=/*DATA*/null;</script>", {"n": "</script><script>alert(1)</script>"})
        self.assertEqual(page.count("</script>"), 1)
        payload = page[len("<script>const D="):-len(";</script>")]
        self.assertEqual(json.loads(payload)["n"], "</script><script>alert(1)</script>")


class HeroItemsScope(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, query):
        calls = []

        class API:
            async def heroes(self):
                return {1: {}}

            async def items(self):
                return ITEMS

            async def get(self, path, **params):
                calls.append(params)
                return []

        class Links:
            def execute(self, *_):
                return self

            def fetchall(self):
                return [{"account_id": 55}, {"account_id": 66}]

        request = type("R", (), {"match_info": {"hero_id": "1"}, "query": query,
                                 "app": {"api": API(), "db": Links(), "cache": {}}})()
        await hero_items_api(request)
        return calls[0]

    async def test_server_is_default_and_filters_linked_players(self):
        self.assertEqual((await self.fetch({}))["account_ids"], "55,66")

    async def test_global_has_no_account_filter(self):
        self.assertNotIn("account_ids", await self.fetch({"scope": "global"}))


class PlayerMatches(unittest.IsolatedAsyncioTestCase):
    async def fetch(self, account_id, query):
        calls = []

        class API:
            async def get(self, path, **params):
                calls.append(path)
                return [hist(i, i) for i in range(1, 41)]

        class Links:
            def execute(self, *_):
                return self

            def fetchall(self):
                return [{"account_id": 55}]

        request = type("R", (), {"match_info": {"account_id": str(account_id)}, "query": query,
                                 "app": {"api": API(), "db": Links(), "cache": {}}})()
        resp = await player_matches_api(request)
        return json.loads(resp.text), calls, request

    async def test_pages_of_30_newest_first(self):
        rows, calls, _ = await self.fetch(55, {"page": "1"})
        self.assertEqual([r[0] for r in rows], list(range(31, 41)))
        self.assertEqual(calls, ["/v1/players/55/match-history"])
        self.assertEqual(len(rows[0]), 10)  # the page's row shape

    async def test_history_is_cached(self):
        _, calls, request = await self.fetch(55, {})
        await player_matches_api(request)
        self.assertEqual(len(calls), 1)

    async def test_unlinked_player_and_bad_page(self):
        from aiohttp import web
        with self.assertRaises(web.HTTPNotFound):
            await self.fetch(66, {})
        with self.assertRaises(web.HTTPBadRequest):
            await self.fetch(55, {"page": "-1"})


if __name__ == "__main__":
    unittest.main()
