"""Transcriber: turns each recorded voice clip into text as soon as it's saved. Its own process so the CPU work never freezes the bot.

It uses the best model while it keeps up, switches to the fast one when clips start waiting, and once nothing is
waiting it redoes finished calls' fast-model clips with the best model. A clip the best model wrote is never redone."""
import os
import time

import av
import numpy as np
from faster_whisper import WhisperModel

from core import db
from core.voicerec import DEFAULT_MODEL, MODELS, VOICE_DIR

# models download here once, on the shared volume, so restarts don't fetch them again
MODEL_DIR = VOICE_DIR.parent / "whisper"
# half the CPU threads: the bot, website and control panel share the machine
THREADS = max(1, (os.cpu_count() or 2) // 2)
BEHIND_S = 15  # a clip waiting this long switches to the fast model
CALM_S = 60  # the queue must stay empty this long before going back, so it doesn't flip back and forth


def pick_model(setting):
    return setting if setting in MODELS else DEFAULT_MODEL


def pick_fast(setting, best):
    """The fast model; the best one when it's set to never switch ("")."""
    if setting is None:
        return DEFAULT_MODEL
    return setting if setting in MODELS else best


class Pace:
    """Whether to use the fast model right now."""

    def __init__(self):
        self.fast = False
        self.empty_since = None

    def update(self, oldest_wait, now):
        """`oldest_wait`: seconds the oldest waiting clip has waited, None when nothing waits. `now`: a monotonic clock."""
        if oldest_wait is None:
            if self.empty_since is None:
                self.empty_since = now
            if now - self.empty_since >= CALM_S:
                self.fast = False
        else:
            self.empty_since = None
            if oldest_wait >= BEHIND_S:
                self.fast = True
        return self.fast


def load(path):
    """A clip as 16 kHz mono float samples, what whisper expects.
    Decoded here because faster-whisper 1.2.1's own loader passes an option PyAV 19 removed."""
    resampler = av.AudioResampler(format="s16", layout="mono", rate=16000)
    with av.open(str(path)) as f:
        frames = [out for frame in f.decode(audio=0) for out in resampler.resample(frame)] + resampler.resample(None)
    return np.concatenate([fr.to_ndarray().ravel() for fr in frames]).astype(np.float32) / 32768


def transcribe(model, path):
    """Text spoken in one clip; empty when it was only noise."""
    segments, _ = model.transcribe(load(path), vad_filter=True)
    return " ".join(s.text.strip() for s in segments).strip()


def do_clip(conn, model, name, clip, upgrade=False):
    started = time.monotonic()
    try:
        text = transcribe(model, VOICE_DIR / clip["file"])
    except Exception as e:  # one broken clip shouldn't stop the rest; the panel shows the error
        if not upgrade:  # a failed upgrade keeps the text it had
            db.save_transcript(conn, clip["id"], error=repr(e)[:500])
        print(f"transcriber: clip {clip['id']} failed: {e!r}")
        return
    db.save_transcript(conn, clip["id"], text=text, model=name)
    took = time.monotonic() - started
    print(f"transcriber: {'upgraded ' if upgrade else ''}clip {clip['id']} ({clip['duration_ms'] / 1000:.1f}s) with {name} "
          f"in {took:.1f}s ({clip['duration_ms'] / 1000 / max(took, 0.01):.1f}x real time)")


def step(conn, models, pace, best, fast):
    """Transcribe one clip: the oldest waiting one, else a finished call's clip to upgrade. Returns False when idle.
    `models(name)` gives a loaded model."""
    waiting = db.untranscribed_clips(conn, limit=1)
    wait = time.time() - waiting[0]["ready_at"] if waiting else None
    name = fast if pace.update(wait, time.monotonic()) else best
    if waiting:
        do_clip(conn, models(name), name, waiting[0])
        return True
    if not pace.fast and (clip := db.clip_to_upgrade(conn, best)):
        do_clip(conn, models(best), best, clip, upgrade=True)
        return True
    return False


def main():
    conn = db.connect(os.environ.get("DB_PATH", "data/pitboss.db"))
    loaded, pace = {}, Pace()

    def models(name):
        if name not in loaded:
            print(f"transcriber: loading {name} on {THREADS} threads")
            loaded[name] = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=THREADS, download_root=str(MODEL_DIR))
        return loaded[name]

    while True:
        # both read every step, so a change in The Pitstop's Voice settings applies to the next clip
        best = pick_model(db.get_setting(conn, "voice_model"))
        fast = pick_fast(db.get_setting(conn, "voice_fast_model"), best)
        for name in [n for n in loaded if n not in (best, fast)]:
            del loaded[name]  # a model nobody picked any more
        if not step(conn, models, pace, best, fast):
            time.sleep(1)


if __name__ == "__main__":
    main()
