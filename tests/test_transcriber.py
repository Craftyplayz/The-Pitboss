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
        pick = transcriber.pick_models
        self.assertEqual(pick("large-v3-turbo", None), ("small.en", "large-v3-turbo"))  # live unset: small.en
        self.assertEqual(pick("large-v3-turbo", "base.en"), ("base.en", "large-v3-turbo"))
        self.assertEqual(pick("large-v3-turbo", ""), ("large-v3-turbo", "large-v3-turbo"))  # the final model does everything
        self.assertEqual(pick(None, None), ("small.en", "small.en"))
        self.assertEqual(pick("someone/evil-repo", "evil/too"), ("small.en", "small.en"))  # a model name is a download


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

    def test_live_writes_new_clips_and_final_rewrites_them(self):
        call_id = self.call(int(time.time()), ended=False)  # still recording: rewrites don't wait for the call to end
        self.clip(call_id, 0)
        self.clip(call_id, 2000)
        self.assertFalse(transcriber.final_step(self.conn, self.models, "large-v3-turbo"))  # nothing written yet
        self.assertTrue(transcriber.live_step(self.conn, self.models, "small.en"))
        self.assertFalse(transcriber.final_step(self.conn, self.models, "large-v3-turbo"))  # a clip still waits: live first
        self.assertTrue(transcriber.live_step(self.conn, self.models, "small.en"))
        self.assertFalse(transcriber.live_step(self.conn, self.models, "small.en"))
        while transcriber.final_step(self.conn, self.models, "large-v3-turbo"):
            pass
        self.assertEqual(self.used, ["small.en", "small.en", "large-v3-turbo", "large-v3-turbo"])
        self.assertEqual(self.rows(), [(0, "Hello from large-v3-turbo.", None, "large-v3-turbo"),
                                       (2000, "Hello from large-v3-turbo.", None, "large-v3-turbo")])

    def test_noise_old_and_failed_lines_are_not_rewritten(self):
        call_id = self.call(int(time.time()) - 600)
        for start in (0, 2000, 4000):
            self.clip(call_id, start)
        self.clip(call_id, 6000, ms=300)  # too short for the fake model
        with self.conn:
            self.conn.execute("UPDATE voice_clips SET text = '', model = 'small.en' WHERE start_ms = 0")  # only noise
            self.conn.execute("UPDATE voice_clips SET text = 'old', model = NULL WHERE start_ms = 2000")  # before models were tracked
            self.conn.execute("UPDATE voice_clips SET text = 'done', model = 'large-v3-turbo' WHERE start_ms = 4000")
            self.conn.execute("UPDATE voice_clips SET text = 'hi', model = 'small.en' WHERE start_ms = 6000")
        self.assertTrue(transcriber.final_step(self.conn, self.models, "large-v3-turbo"))  # the short clip fails
        self.assertFalse(transcriber.final_step(self.conn, self.models, "large-v3-turbo"))  # and isn't retried
        self.assertEqual(self.rows()[3], (6000, "hi", "RuntimeError('too short')", "small.en"))  # keeps the live text
        self.assertEqual(self.used, ["large-v3-turbo"])

    def test_a_failed_live_clip_shows_its_error(self):
        self.clip(self.call(int(time.time())), 0, ms=300)
        transcriber.live_step(self.conn, self.models, "small.en")
        self.assertEqual(self.rows(), [(0, None, "RuntimeError('too short')", None)])
        self.assertEqual(db.untranscribed_clips(self.conn), [])


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
