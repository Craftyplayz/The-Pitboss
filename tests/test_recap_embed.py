import unittest
from unittest.mock import MagicMock

from cogs._recap_embed import FIELD_MAX, build_field, build_full_embed, final_build, place, rank_lines

STATS = dict(player_damage=0, player_healing=0, net_worth=0, player_damage_taken=900, damage_absorbed=10,
             shots_hit=60, shots_missed=40, hero_bullets_hit=20, hero_bullets_hit_crit=5, creep_kills=40,
             possible_creeps=50, gold_lane_creep=5000, gold_neutral_creep=3000, gold_player=2000, gold_boss=500,
             gold_treasure=100, gold_death_loss=700)


def player(acc, team, dmg, nw, items=()):
    stats = dict(STATS, player_damage=dmg, net_worth=nw, time_stamp_s=1800)
    return {"account_id": acc, "team": team, "hero_id": 1, "kills": 5, "deaths": 2, "assists": 3, "net_worth": nw,
            "level": 20, "ability_points": 15, "last_hits": 100, "denies": 4, "stats": [stats],
            "items": [{"item_id": i, "sold_time_s": s} for i, s in items],
            "player_rank_data": {"initial_display_rank": 101, "desired_progress_change": 120,
                                 "initial_flat_progress": 63000, "final_flat_progress": 63120}}


ITEMS = {10: {"id": 10, "name": "Mystic Shot", "type": "upgrade", "item_slot_type": "weapon", "cost": 1600},
         11: {"id": 11, "name": "Extra Spirit", "type": "upgrade", "item_slot_type": "spirit", "cost": 800},
         12: {"id": 12, "name": "Ability", "type": "ability"}}
META = {"match_info": {"match_id": 7, "duration_s": 1800, "start_time": 1_700_000_000, "winning_team": 0, "players": [
    player(1, 0, 30000, 25000, [(10, 0), (11, 0), (12, 0), (10, 0)]),
    player(2, 0, 40000, 20000),
    player(3, 1, 10000, 15000, [(11, 600)]),
]}}
HEROES = {1: {"name": "Violet", "images": {"icon_image_small": "https://x/violet.png"}}}
RANKS = {10: {"name": "Ascendant", "images": {"small_subrank1": "https://x/r.png"}}}


def member():
    m = MagicMock()
    m.display_name = "craft"
    m.display_avatar.url = "https://x/a.png"
    return m


class RecapEmbed(unittest.TestCase):
    def test_place(self):
        ps = META["match_info"]["players"]
        self.assertEqual(place(ps, ps[0], "player_damage"), 2)
        self.assertEqual(place(ps, ps[1], "player_damage"), 1)

    def test_final_build_skips_sold_abilities_and_dupes(self):
        ps = META["match_info"]["players"]
        self.assertEqual([i["id"] for i in final_build(ps[0], ITEMS)], [10, 11])
        self.assertEqual(final_build(ps[2], ITEMS), [])

    def test_build_field_falls_back_to_icons_when_too_long(self):
        build = [dict(ITEMS[10], id=n, name="X" * 60) for n in range(20)]
        emojis = {n: f"<:i{n}:123456789012345678>" for n in range(20)}
        text = build_field(build, emojis)
        self.assertLessEqual(len(text), FIELD_MAX)
        self.assertNotIn("XXXX", text)

    def test_full_embed(self):
        e = build_full_embed({"match_id": 7, "hero_id": 1}, META, 1, [], HEROES, ITEMS, RANKS, {10: "<:i10:1>"}, member())
        self.assertEqual(e.title, "Violet · Win · 30:00")
        self.assertIn("Most souls in the Match", e.description)
        self.assertIn("Gained 120 rank progress.", e.description)
        names = [f.name for f in e.fields]
        self.assertIn("Final build · 2 items · 2,400 souls", names)
        self.assertTrue(all(len(f.value) <= FIELD_MAX for f in e.fields))
        self.assertEqual(e.footer.text, "Ascendant 1 · Match 7")
        self.assertEqual(e.thumbnail.url, "https://x/violet.png")
        score = e.fields[-1].value
        self.assertIn("YOUR TEAM · WIN", score)
        self.assertIn("ENEMY TEAM · LOSS", score)

    def test_rank_lines(self):
        # real Match: protection kicked in at the Ascendant 1 boundary
        protected = {"initial_flat_progress": 63060, "final_flat_progress": 63000, "desired_progress_change": -300,
                     "consumed_demotion_protection": True, "initial_demotion_protection_games": 5}
        self.assertEqual(rank_lines(protected), ["**Rank loss protection saved you:** lost 60 instead of 300. 4 protected losses left."])
        self.assertIn("1 protected loss left.", rank_lines(dict(protected, initial_demotion_protection_games=2))[0])
        self.assertEqual(rank_lines({"initial_flat_progress": 63300, "final_flat_progress": 63000,
                                     "desired_progress_change": -300}), ["Lost 300 rank progress."])
        self.assertEqual(rank_lines({"initial_flat_progress": 5, "final_flat_progress": 5}), [])
        self.assertEqual(rank_lines(None), [])

    def test_player_missing(self):
        self.assertIsNone(build_full_embed({}, META, 99, [], HEROES, ITEMS, RANKS, {}, member()))


if __name__ == "__main__":
    unittest.main()
