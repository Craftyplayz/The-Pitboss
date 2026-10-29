import unittest

from cogs.updates import LIMIT, changes_since, sections

LOG = """# Patch notes

Intro text.

## 1.5.0

- Big thing.

## 1.4.1.1

- Typo fixed.

## 1.4.1

- Small addition.

## 1.0.0 (new server)

- Moved.
"""


class Changes(unittest.TestCase):
    def test_sections_newest_first(self):
        self.assertEqual([v for v, _ in sections(LOG)], ["1.5.0", "1.4.1.1", "1.4.1", "1.0.0"])

    def test_every_version_since_the_last_start(self):
        self.assertEqual(changes_since(LOG, "1.4.1"), ("1.5.0", "- Big thing.\n- Typo fixed."))

    def test_same_version_posts_nothing(self):
        self.assertIsNone(changes_since(LOG, "1.5.0"))

    def test_unknown_old_version_posts_only_the_newest(self):
        self.assertEqual(changes_since(LOG, "0.9"), ("1.5.0", "- Big thing."))

    def test_long_changes_are_cut_to_fit_an_embed(self):
        new, body = changes_since(LOG.replace("Big thing.", "x" * 5000), "1.4.1")
        self.assertEqual(len(body), LIMIT)

    def test_real_changelog_parses(self):
        from cogs.updates import CHANGELOG
        secs = sections(CHANGELOG.read_text(encoding="utf8"))
        self.assertTrue(secs and all(b for _, b in secs))


if __name__ == "__main__":
    unittest.main()
