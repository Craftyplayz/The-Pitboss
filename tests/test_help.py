import unittest

from cogs.help import PAGES, page_embed


class HelpPages(unittest.TestCase):
    def test_pages_fit_discord_limits(self):
        for i in range(len(PAGES)):
            e = page_embed(i)
            self.assertLessEqual(len(e), 6000)
            self.assertTrue(all(len(f.name) <= 256 and len(f.value) <= 1024 for f in e.fields))
            self.assertEqual(e.footer.text, f"Page {i + 1} of {len(PAGES)}")

    def test_no_admin_commands(self):
        text = " ".join(n + v for _, fs in PAGES for n, v in fs)
        self.assertNotIn("/setup", text)


if __name__ == "__main__":
    unittest.main()
