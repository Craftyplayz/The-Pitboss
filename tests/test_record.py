import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from core import db
from core.voicerec import BYTES_PER_MS, GAP_MS, MAX_MS, Clipper, clip_path, encode_ogg, recordable


def member(mid=1, bot=False, pending=False):
    return SimpleNamespace(id=mid, bot=bot, pending=pending)


class Clock:
    """Counts whole milliseconds so float sums don't round 400 ms down to 399."""

    def __init__(self):
        self.ms = 100_000

    def __call__(self):
        return self.ms / 1000


def pcm(ms):
    return b"\x01\x00" * 2 * 48 * ms  # stereo 16-bit, 48 samples per ms


class Recordable(unittest.TestCase):
    def test_people_only(self):
        self.assertTrue(recordable(member()))
        self.assertFalse(recordable(member(bot=True)))
        self.assertFalse(recordable(member(pending=True)))  # hasn't agreed to the rules yet
        self.assertFalse(recordable(None))


class Clips(unittest.TestCase):
    def setUp(self):
        self.clock = Clock()
        self.c = Clipper(self.clock)

    def talk(self, m, ms):
        for _ in range(ms // 20):
            self.c.write(m, pcm(20))
            self.clock.ms += 20

    def test_clip_ends_after_a_pause(self):
        self.clock.ms += 1000
        self.talk(member(1), 1000)
        self.assertEqual(self.c.finished(), [])  # still talking
        self.clock.ms += GAP_MS
        [(m, start, data)] = self.c.finished()
        self.assertEqual((m.id, start, len(data)), (1, 980, 1000 * BYTES_PER_MS))
        self.assertEqual(self.c.finished(), [])

    def test_speakers_are_separate(self):
        self.talk(member(1), 400)
        self.talk(member(2), 400)
        self.clock.ms += GAP_MS
        clips = sorted(self.c.finished(), key=lambda c: c[0].id)
        self.assertEqual([(m.id, s) for m, s, _ in clips], [(1, 0), (2, 380)])

    def test_long_monologue_is_cut(self):
        self.talk(member(1), MAX_MS)
        self.assertEqual(len(self.c.finished()), 1)

    def test_clicks_dropped_and_flush_takes_the_rest(self):
        self.talk(member(1), 100)
        self.talk(member(2), 400)
        self.assertEqual([m.id for m, _, _ in self.c.finished(flush=True)], [2])
        self.assertEqual(self.c.open, {})


class Files(unittest.TestCase):
    def test_path(self):
        self.assertEqual(clip_path("data/voice", 3, 42, 1500), Path("data/voice/3/42/1500.ogg"))

    def test_encode(self):
        import av
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "a" / "b.ogg"
            encode_ogg(pcm(1000), path)
            with av.open(str(path)) as f:
                self.assertEqual(f.streams.audio[0].codec_context.name, "opus")
                self.assertAlmostEqual(f.duration / 1e6, 1.0, delta=0.1)


class Calls(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.channel = SimpleNamespace(id=9, name="Deadlock 1")

    def test_restart_interrupts_only_this_bots_calls(self):
        mine = db.start_call(self.conn, 100, self.channel, None, 1)
        other = db.start_call(self.conn, 200, SimpleNamespace(id=8, name="x"), 5, 1)
        self.assertEqual(db.recording_in(self.conn, 9)["id"], mine)
        self.assertEqual(db.interrupt_calls(self.conn, 100, 50), [9])
        status = dict(self.conn.execute("SELECT id, status FROM voice_calls").fetchall())
        self.assertEqual(status, {mine: "interrupted", other: "recording"})
        self.assertIsNone(db.recording_in(self.conn, 9))

    def test_autojoin_setting(self):
        self.assertEqual(db.autojoin_channels(self.conn), set())
        db.set_setting(self.conn, "voice_autojoin", "[1, 2]")
        self.assertEqual(db.autojoin_channels(self.conn), {1, 2})


class LiveTranscript(unittest.TestCase):
    def clip(self, member_id, name, start_ms, text):
        return {"member_id": member_id, "member_name": name, "start_ms": start_ms, "text": text}

    def test_runs_of_one_speaker_are_grouped(self):
        from cogs.record import live_text
        clips = [self.clip(1, "Raygun (@craftyplayz)", 2000, "Oh my god, it's a cat."), self.clip(1, "Raygun (@craftyplayz)", 4000, "Hi *Mr* Fluffins."),
                 self.clip(2, "Huski (@huski)", 5000, ""), self.clip(2, "Huski (@huski)", 6000, None), self.clip(2, "Huski (@huski)", 65000, "Roll for it.")]
        self.assertEqual(live_text(clips), "**Raygun** `0:02`\nOh my god, it's a cat.\nHi \\*Mr\\* Fluffins.\n\n**Huski** `1:05`\nRoll for it.")

    def test_only_the_newest_lines_fit(self):
        from cogs.record import live_text
        clips = [self.clip(i % 2, f"P{i % 2}", i * 1000, "x" * 50) for i in range(200)]
        text = live_text(clips)
        self.assertLessEqual(len(text), 4000)
        self.assertTrue(text.startswith("…"))
        self.assertTrue(text.endswith("**P1** `3:19`\n" + "x" * 50))
        self.assertLessEqual(len(live_text([self.clip(1, "P", 0, "y" * 5000)])), 4000)  # one huge monologue
