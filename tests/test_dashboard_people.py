import unittest

from core.dashboard import PEOPLE_SHOWN, top_people


class TopPeople(unittest.TestCase):
    def test_most_games_first_without_linked(self):
        rows = [{"mate_id": i, "matches_played": i} for i in range(1, 20)]
        top = top_people(rows, "mate_id", linked={19})
        self.assertEqual([r["mate_id"] for r in top], [18, 17, 16, 15, 14, 13][:PEOPLE_SHOWN])

    def test_short_list(self):
        self.assertEqual(top_people([{"enemy_id": 5, "matches_played": 2}], "enemy_id", linked=set()),
                         [{"enemy_id": 5, "matches_played": 2}])


if __name__ == "__main__":
    unittest.main()
