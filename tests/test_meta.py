import unittest

from cogs.meta import fit_table, fmt_table, rank_by_wr, win_rate


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

    def test_table_alignment(self):
        t = fmt_table(("Hero", "Win"), [("Abrams", "51.0%"), ("Ivy", "9.5%")])
        self.assertEqual(t.split("\n")[2], "Abrams  51.0%")
        self.assertEqual(t.split("\n")[3], "Ivy      9.5%")

    def test_fit_table_truncates(self):
        rows = [("x" * 50, "1") for _ in range(200)]
        self.assertLessEqual(len(fit_table(("a", "b"), rows)), 4000)


if __name__ == "__main__":
    unittest.main()
