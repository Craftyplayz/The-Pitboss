"""Transcriber: turns each recorded voice clip into text as soon as it's saved. Its own process so the CPU work never freezes the bot."""
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


def pick_model(setting):
    return setting if setting in MODELS else DEFAULT_MODEL


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


def work(conn, model):
    """Transcribe waiting clips, oldest first. Returns how many it did."""
    clips = db.untranscribed_clips(conn)
    for clip in clips:
        started = time.monotonic()
        try:
            text = transcribe(model, VOICE_DIR / clip["file"])
        except Exception as e:  # one broken clip shouldn't stop the rest; the panel shows the error
            db.save_transcript(conn, clip["id"], error=repr(e)[:500])
            print(f"transcriber: clip {clip['id']} failed: {e!r}")
            continue
        db.save_transcript(conn, clip["id"], text=text)
        took = time.monotonic() - started
        print(f"transcriber: clip {clip['id']} ({clip['duration_ms'] / 1000:.1f}s) in {took:.1f}s "
              f"({clip['duration_ms'] / 1000 / max(took, 0.01):.1f}x real time)")
    return len(clips)


def main():
    conn = db.connect(os.environ.get("DB_PATH", "data/pitboss.db"))
    name, model = None, None
    while True:
        wanted = pick_model(db.get_setting(conn, "voice_model"))
        if wanted != name:  # changed in The Pitstop's Voice settings
            print(f"transcriber: loading {wanted} on {THREADS} threads")
            model = WhisperModel(wanted, device="cpu", compute_type="int8", cpu_threads=THREADS, download_root=str(MODEL_DIR))
            name = wanted
        if not work(conn, model):
            time.sleep(1)


if __name__ == "__main__":
    main()
