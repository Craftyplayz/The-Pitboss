import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import transcriber
from core import db
from core.voicerec import clip_path, encode_ogg


class FakeModel:
    def transcribe(self, audio, vad_filter):
        if len(audio) < 16000:
            raise RuntimeError("too short")
        return [SimpleNamespace(text=" Hello "), SimpleNamespace(text="there. ")], None


class Work(unittest.TestCase):
    def test_model_setting_is_checked(self):
        self.assertEqual(transcriber.pick_model("medium.en"), "medium.en")
        self.assertEqual(transcriber.pick_model(None), "small.en")
        self.assertEqual(transcriber.pick_model("someone/evil-repo"), "small.en")  # a model name is a download

    def test_clips_get_text_or_an_error(self):
        with tempfile.TemporaryDirectory() as d, mock.patch.object(transcriber, "VOICE_DIR", Path(d)):
            conn = db.connect(":memory:")
            for start, ms in ((0, 1000), (2000, 300)):
                path = clip_path(d, 1, 7, start)
                encode_ogg(b"\x01\x00" * 2 * 48 * ms, path)
                db.add_clip(conn, 1, 7, "Bob", start, ms, path.relative_to(d).as_posix())
            with mock.patch("builtins.print"):
                self.assertEqual(transcriber.work(conn, FakeModel()), 2)
            rows = [tuple(r) for r in conn.execute("SELECT start_ms, text, error FROM voice_clips ORDER BY start_ms")]
            self.assertEqual(rows, [(0, "Hello there.", None), (2000, None, "RuntimeError('too short')")])
            self.assertEqual(db.untranscribed_clips(conn), [])  # failed clips aren't retried forever
