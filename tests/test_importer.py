import unittest

from core import db, importer

SAMPLE = """# Late Session

## Recording Information

- **Date**: October 29, 2026 at 11:59:00 PM GMT
- **Channel**: D&D

## Summary

**Ignored** - 11:00:00 PM
not part of the transcript

## Transcript

*Raygun is present - 11:59:00 PM*

**Raygun** - 11:59:10 PM
I attack the bandit.
With my sword.

*Nigelll joined - 11:59:30 PM*

**Huski** - 11:59:50 PM
Roll for it.

**Huski** - 12:00:20 AM
Nat 20!

*Raygun ended the recording - 12:01:00 AM*
"""


class Parse(unittest.TestCase):
    def test_sample(self):
        call = importer.parse(SAMPLE)
        self.assertEqual((call["channel"], call["started_at"], call["ended_at"] - call["started_at"]), ("D&D", 1793318340, 120))
        ray, huski = importer.member_id("Raygun"), importer.member_id("Huski")
        self.assertEqual(call["lines"], [(ray, "Raygun", 10000, 30000, "I attack the bandit. With my sword."),
                                         (huski, "Huski", 50000, 30000, "Roll for it."),
                                         (huski, "Huski", 80000, 5000, "Nat 20!")])  # past midnight
        self.assertLess(ray, 0)

    def test_not_a_transcript(self):
        with self.assertRaises(ValueError):
            importer.parse("# Notes\nhello")
        with self.assertRaises(ValueError):
            importer.parse("**Date**: October 29, 2026 at 3:25 PM GMT\n## Transcript\nnothing said")

    def test_clocks(self):
        self.assertEqual([importer.seconds(t) for t in ("12:00:05 AM", "12:30 PM", "3:25:57 PM", "15:25:57")], [5, 45000, 55557, 55557])

    def test_import_once(self):
        conn = db.connect(":memory:")
        call_id = db.import_call(conn, importer.parse(SAMPLE))
        self.assertIsNone(db.import_call(conn, importer.parse(SAMPLE)))
        call = db.get_call(conn, call_id)
        self.assertEqual((call["status"], call["review_status"]), ("done", "old"))
        self.assertTrue(db.call_ready(conn, call_id, "large-v3-turbo"))  # so the D&D summary button shows
        self.assertEqual([c["text"] for c in db.call_clips(conn, call_id)], ["I attack the bandit. With my sword.", "Roll for it.", "Nat 20!"])
