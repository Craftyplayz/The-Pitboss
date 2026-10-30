import unittest

from cogs.voice import NAME_RE, lowest_free


class LowestFree(unittest.TestCase):
    def test_empty(self):
        self.assertEqual(lowest_free({}), 1)

    def test_next_up(self):
        self.assertEqual(lowest_free({1, 2}), 3)

    def test_fills_gap(self):
        self.assertEqual(lowest_free({2, 3}), 1)
        self.assertEqual(lowest_free({1, 3}), 2)

    def test_name(self):
        self.assertEqual(NAME_RE.match("Deadlock 12").group(1), "12")
        self.assertIsNone(NAME_RE.match("Deadlock lobby"))
