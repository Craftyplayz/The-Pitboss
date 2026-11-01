"""Transcriber: turns each recorded voice clip into text as soon as it's saved. Its own process so the CPU work never freezes the bot.

It uses the best model while it keeps up and steps down one model at a time (to the lowest one picked) when clips start
waiting, and back up when it's quiet. Once nothing is waiting it redoes finished calls' clips that a lower model wrote,
with the best model. A clip the best model wrote is never redone."""
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
BEHIND_S = 15  # a clip waiting this long steps down a model; still behind 15 s later, another step
CALM_S = 60  # the queue must stay empty this long for each step back up, so it doesn't flip back and forth


def pick_model(setting):
    return setting if setting in MODELS else DEFAULT_MODEL


def ladder(best, lowest_setting):
    """Models to step through, best first: every model from the best down to the lowest picked.
    Unset means down to small.en; "" means never switch."""
    lowest = DEFAULT_MODEL if lowest_setting is None else lowest_setting
    if lowest not in MODELS or MODELS.index(lowest) >= MODELS.index(best):
        return [best]
    return list(reversed(MODELS[MODELS.index(lowest):MODELS.index(best) + 1]))


class Pace:
    """How many steps down the ladder to be right now; 0 is the best model."""

    def __init__(self):
        self.level = 0
        self.changed = None
        self.empty_since = None

    def update(self, oldest_wait, now, steps):
        """`oldest_wait`: seconds the oldest waiting clip has waited, None when nothing waits. `now`: a monotonic clock.
        `steps`: how many models the ladder has."""
        if oldest_wait is None:
            if self.empty_since is None:
                self.empty_since = now
            if self.level and now - self.empty_since >= CALM_S:
                self.level -= 1
                self.empty_since = now  # the next step up needs another quiet minute
        else:
            self.empty_since = None
            settled = self.changed is None or now - self.changed >= BEHIND_S  # give the new model a chance first
            if oldest_wait >= BEHIND_S and settled and self.level < steps - 1:
                self.level += 1
                self.changed = now
        self.level = min(self.level, steps - 1)  # the ladder got shorter in settings
        return self.level


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


def step(conn, models, pace, steps):
    """Transcribe one clip: the oldest waiting one, else a finished call's clip to upgrade. Returns False when idle.
    `models(name)` gives a loaded model; `steps` is the ladder, best model first."""
    waiting = db.untranscribed_clips(conn, limit=1)
    wait = time.time() - waiting[0]["ready_at"] if waiting else None
    name, best = steps[pace.update(wait, time.monotonic(), len(steps))], steps[0]
    if waiting:
        do_clip(conn, models(name), name, waiting[0])
        return True
    if pace.level == 0 and (clip := db.clip_to_upgrade(conn, best)):
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
        steps = ladder(pick_model(db.get_setting(conn, "voice_model")), db.get_setting(conn, "voice_fast_model"))
        for name in [n for n in loaded if n not in steps]:
            del loaded[name]  # a model nobody picked any more
        if not step(conn, models, pace, steps):
            time.sleep(1)


if __name__ == "__main__":
    main()
