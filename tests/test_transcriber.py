import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import transcriber
from core import db
from core.voicerec import clip_path, encode_ogg


class FakeModel:
    def __init__(self, name):
        self.name = name

    def transcribe(self, audio, vad_filter):
        if len(audio) < 16000:
            raise RuntimeError("too short")
        return [SimpleNamespace(text=" Hello from "), SimpleNamespace(text=f"{self.name}. ")], None


class Settings(unittest.TestCase):
    def test_models_are_checked(self):
        self.assertEqual(transcriber.pick_model("medium.en"), "medium.en")
        self.assertEqual(transcriber.pick_model(None), "small.en")
        self.assertEqual(transcriber.pick_model("someone/evil-repo"), "small.en")  # a model name is a download
        self.assertEqual(transcriber.pick_fast(None, "large-v3-turbo"), "small.en")
        self.assertEqual(transcriber.pick_fast("", "large-v3-turbo"), "large-v3-turbo")  # never switch
        self.assertEqual(transcriber.pick_fast("someone/evil-repo", "medium.en"), "medium.en")


class PaceRule(unittest.TestCase):
    def test_switches_when_behind_and_back_only_after_a_calm_minute(self):
        p = transcriber.Pace()
        self.assertFalse(p.update(3, 0))  # keeping up
        self.assertTrue(p.update(transcriber.BEHIND_S, 1))
        self.assertTrue(p.update(2, 2))  # caught up a bit, still fast
        self.assertTrue(p.update(None, 3))  # empty, but not for long
        self.assertTrue(p.update(1, 30))  # a clip arrived: the calm minute starts over
        self.assertTrue(p.update(None, 31))
        self.assertTrue(p.update(None, 31 + transcriber.CALM_S - 1))
        self.assertFalse(p.update(None, 31 + transcriber.CALM_S))


class Steps(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)
        for patch in (mock.patch.object(transcriber, "VOICE_DIR", Path(self.dir.name)), mock.patch("builtins.print")):
            patch.start()
            self.addCleanup(patch.stop)
        self.conn = db.connect(":memory:")
        self.used = []

    def models(self, name):
        self.used.append(name)
        return FakeModel(name)

    def call(self, started_at, ended=True):
        call_id = db.start_call(self.conn, 1, SimpleNamespace(id=9, name="vc"), None, started_at)
        if ended:
            db.end_call(self.conn, call_id, started_at + 60)
        return call_id

    def clip(self, call_id, start_ms, ms=1000):
        path = clip_path(self.dir.name, call_id, 7, start_ms)
        encode_ogg(b"\x01\x00" * 2 * 48 * ms, path)
        db.add_clip(self.conn, call_id, 7, "Bob", start_ms, ms, path.relative_to(self.dir.name).as_posix())

    def rows(self):
        return [tuple(r) for r in self.conn.execute("SELECT start_ms, text, error, model FROM voice_clips ORDER BY id")]

    def test_waiting_clips_first_then_upgrades_then_idle(self):
        now = int(time.time())
        old, live = self.call(now - 600), self.call(now, ended=False)
        self.clip(old, 0)
        self.clip(live, 0)
        self.clip(live, 2000, ms=300)  # too short for the fake model: an error
        pace = transcriber.Pace()
        with self.conn:  # pretend the old call's first clip was done fast during the call
            self.conn.execute("UPDATE voice_clips SET text = 'hi', model = 'small.en' WHERE start_ms = 0 AND call_id = ?", (old,))
        for _ in range(2):
            self.assertTrue(transcriber.step(self.conn, self.models, pace, "large-v3-turbo", "small.en"))
        self.assertEqual(self.used, ["large-v3-turbo", "large-v3-turbo"])  # keeping up: the best model
        self.assertTrue(transcriber.step(self.conn, self.models, pace, "large-v3-turbo", "small.en"))  # the upgrade
        self.assertFalse(transcriber.step(self.conn, self.models, pace, "large-v3-turbo", "small.en"))
        self.assertEqual(self.rows(), [(0, "Hello from large-v3-turbo.", None, "large-v3-turbo"),  # upgraded
                                       (0, "Hello from large-v3-turbo.", None, "large-v3-turbo"),
                                       (2000, None, "RuntimeError('too short')", None)])

    def test_behind_uses_the_fast_model_and_skips_upgrades(self):
        call_id = self.call(int(time.time()) - 600)  # its clips ended ten minutes ago: far behind
        self.clip(call_id, 0)
        self.clip(call_id, 2000)
        pace = transcriber.Pace()
        while transcriber.step(self.conn, self.models, pace, "large-v3-turbo", "small.en"):
            pass
        self.assertEqual(self.used, ["small.en", "small.en"])  # no upgrade until a calm minute has passed
        self.assertEqual(db.clip_to_upgrade(self.conn, "large-v3-turbo")["start_ms"], 0)
        self.assertIsNone(db.clip_to_upgrade(self.conn, "small.en"))

    def test_calls_still_recording_and_noise_are_never_upgraded(self):
        live = self.call(int(time.time()), ended=False)
        self.clip(live, 0)
        done = self.call(int(time.time()) - 600)
        self.clip(done, 0)
        with self.conn:
            self.conn.execute("UPDATE voice_clips SET text = 'hi', model = 'small.en' WHERE call_id = ?", (live,))
            self.conn.execute("UPDATE voice_clips SET text = '', model = 'small.en' WHERE call_id = ?", (done,))
        self.assertIsNone(db.clip_to_upgrade(self.conn, "large-v3-turbo"))

    def test_a_failed_upgrade_keeps_the_old_text(self):
        call_id = self.call(int(time.time()) - 600)
        self.clip(call_id, 0, ms=300)
        with self.conn:
            self.conn.execute("UPDATE voice_clips SET text = 'hi', model = 'small.en'")
        transcriber.do_clip(self.conn, FakeModel("large-v3-turbo"), "large-v3-turbo", db.clip_to_upgrade(self.conn, "large-v3-turbo"), upgrade=True)
        self.assertEqual(self.rows(), [(0, "hi", None, "small.en")])


class Migration(unittest.TestCase):
    def test_model_column_is_added_to_old_databases(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "old.db"
            import sqlite3
            old = sqlite3.connect(path)
            old.execute("CREATE TABLE voice_clips (id INTEGER PRIMARY KEY, call_id INTEGER, member_id INTEGER, member_name TEXT, "
                        "start_ms INTEGER, duration_ms INTEGER, file TEXT, text TEXT, error TEXT)")
            old.close()
            conn = db.connect(path)
            self.assertIn("model", [r[1] for r in conn.execute("PRAGMA table_info(voice_clips)")])
            conn.close()
            db.connect(path).close()  # a second start finds it already there
