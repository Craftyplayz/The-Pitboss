import unittest

import discord

from core.leaderboard_math import from_hero_stats, from_history, rank_board, rank_by_badge

from cogs.leaderboard import board_embed


def m(hero=1, k=5, d=0, a=5, t=1000, res=1, team=1, delta=10, dur=600, nw=6000):
    return dict(hero_id=hero, player_kills=k, player_deaths=d, player_assists=a, start_time=t,
                match_result=res, player_team=team, ranked_delta=delta, match_duration_s=dur, net_worth=nw)


def agg(n, w):
    return dict(matches=n, wins=w, kills=0, deaths=0, assists=0, seconds=0, souls=0, delta=0)


class T(unittest.TestCase):
    def test_history_window_hero_and_math(self):
        h = [m(), m(hero=2, res=0), m(t=5)]  # last is outside the window
        a = from_history(h, since=100)
        self.assertEqual((a["matches"], a["wins"], a["kills"], a["deaths"], a["delta"]), (2, 1, 10, 0, 20))
        self.assertEqual(from_history(h, 100, hero_id=2)["matches"], 1)
        self.assertEqual(rank_board({"x": a}, "KDA", minimum=1), [("x", 20.0)])  # deaths floor at 1
        self.assertEqual(rank_board({"x": a}, "Souls per minute", minimum=1), [("x", 600.0)])

    def test_hero_stats(self):
        rows = [dict(hero_id=1, matches_played=10, wins=6, kills=1, deaths=2, assists=3, time_played=600, networth_per_min=100),
                dict(hero_id=2, matches_played=5, wins=1, kills=1, deaths=1, assists=1, time_played=300, networth_per_min=200)]
        self.assertEqual(from_hero_stats(rows)["matches"], 15)
        a = from_hero_stats(rows, hero_id=2)
        self.assertEqual((a["matches"], a["souls"]), (5, 1000))

    def test_minimum_and_ties(self):
        board = rank_board({"a": agg(9, 9), "b": agg(10, 5), "c": agg(20, 10), "d": agg(10, 8)}, "Win rate")
        self.assertEqual([k for k, _ in board], ["d", "c", "b"])  # a under 10; c beats b on matches at 0.5
        self.assertEqual(rank_board({"a": agg(9, 9)}, "Win rate"), [])

    def test_badge(self):
        self.assertEqual(rank_by_badge({"a": 101, "b": 0, "c": 111, "d": None}), [("c", 111), ("a", 101)])

    def test_board_embed(self):
        rows = [(i, f"{i}.0", f"{i} matches") for i in range(1, 31)]
        e = board_embed(rows, "KDA", 15, "foot", ("Haze", [1, 2, 3]), "http://x/i.png")
        lines = e.description.split("\n")
        self.assertTrue(lines[0].startswith("🥇") and lines[2].startswith("🥉") and lines[3].startswith("**4.**"))
        self.assertEqual(lines[-2:], ["…", "▶ **15.** <@15> · **15.0** · 15 matches"])
        self.assertEqual((e.title, e.author.name, e.thumbnail.url), ("KDA · Haze", "Leaderboard · KDA · Haze", "http://x/i.png"))
        self.assertEqual(e.color.to_rgb(), (1, 2, 3))
        self.assertLessEqual(len(e.description), 1024)
        self.assertLessEqual(len(e), 6000)
        e = board_embed(rows[:3], "Rank", 2, "f")
        self.assertIn("▶ 🥈", e.description)
        self.assertEqual(e.color, discord.Color.gold())


if __name__ == "__main__":
    unittest.main()
