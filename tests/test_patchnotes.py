import unittest

from cogs.patchnotes import chunks, new_patches, patch_embeds, to_markdown

# trimmed from real Steam announcements
MINOR = "[p]- Baba: Threadsap - Cooldown increased from 26s to 28s[/p][p][/p][p]- Radiant Regeneration: Spirit scaling reduced[/p]"
BIG = ('[p][b][u]\\[ General ][/u][/b][/p][p][/p][p]- Can now jump during slide[/p]'
       '[p][img src="{STEAM_CLAN_LOC_IMAGE}/45164767/c98e.png"][/img][/p]'
       '[p][url=https://example.com]forum[/url] and [i]more[/i][/p]')


def item(title, date, contents=MINOR, gid="1"):
    return {"title": title, "date": date, "contents": contents, "gid": gid}


class Markdown(unittest.TestCase):
    def test_minor_update(self):
        text, image = to_markdown(MINOR)
        self.assertEqual(text, "- Baba: Threadsap - Cooldown increased from 26s to 28s\n\n"
                               "- Radiant Regeneration: Spirit scaling reduced")
        self.assertIsNone(image)

    def test_sections_images_links(self):
        text, image = to_markdown(BIG)
        self.assertTrue(text.startswith("### General\n\n- Can now jump during slide"))
        self.assertIn("[forum](https://example.com) and *more*", text)
        self.assertNotIn("[img", text)
        self.assertEqual(image, "https://clan.akamai.steamstatic.com/images/45164767/c98e.png")


class Splitting(unittest.TestCase):
    def test_chunks_fit_and_keep_everything(self):
        text = "\n".join(f"- change number {n}" for n in range(2000)) + "\n" + "x" * 9000
        parts = chunks(text)
        self.assertTrue(all(0 < len(p) <= 4000 for p in parts))
        self.assertEqual("".join(parts).replace("\n", ""), text.replace("\n", ""))

    def test_big_patch_embeds(self):
        embeds = patch_embeds(item("Gameplay Update", 100, "[p]- line[/p]" * 20000))
        self.assertTrue(all(len(e) <= 6000 for e in embeds))
        self.assertEqual(embeds[0].title, "Gameplay Update")
        self.assertIn("store.steampowered.com/news/app/1422450/view/1", embeds[0].url)
        self.assertEqual(embeds[-1].footer.text, f"Part {len(embeds)} of {len(embeds)}")


class Selection(unittest.TestCase):
    def test_only_new_patches_oldest_first(self):
        items = [item("Paint the Town", 50), item("Minor Update - 2", 40), item("Minor Update - 1", 30),
                 item("Gameplay Update - 0", 10)]
        self.assertEqual([i["title"] for i in new_patches(items, 20)], ["Minor Update - 1", "Minor Update - 2"])


if __name__ == "__main__":
    unittest.main()
