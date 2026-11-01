"""Transcriber: turns each recorded voice clip into text. Its own process so the CPU work never freezes the bot.

Two workers run side by side. The live worker writes every new clip with the fast live model straight away, so the
transcript keeps up with the conversation. The final worker rewrites each of those lines with the accurate final model,
oldest first, but only starts a clip while nothing waits for the live worker: in a busy call it falls behind, and in
quiet moments and after the call it catches up. A line the final model wrote is never redone.

With ANTHROPIC_API_KEY set, a third thread has Claude review each call once its transcript is final (core/review.py)."""
import os
import threading
import time

import av
import numpy as np
from faster_whisper import WhisperModel

from core import db, review
from core.voicerec import DEFAULT_MODEL, MODELS, VOICE_DIR

# models download here once, on the shared volume, so restarts don't fetch them again
MODEL_DIR = VOICE_DIR.parent / "whisper"
# half the CPU threads per model: the bot, website and control panel share the machine
THREADS = max(1, (os.cpu_count() or 2) // 2)


def pick_models(final_setting, live_setting):
    """(live model, final model). Unset live means small.en; "" means the final model does everything."""
    final = final_setting if final_setting in MODELS else DEFAULT_MODEL
    live = DEFAULT_MODEL if live_setting is None else live_setting
    return (live if live in MODELS else final), final


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
        # a failed rewrite keeps the live text; the error stops it being retried forever
        db.save_transcript(conn, clip["id"], text=clip["text"] if upgrade else None, error=repr(e)[:500],
                           model=clip["model"] if upgrade else None)
        print(f"transcriber: clip {clip['id']} failed: {e!r}")
        return
    db.save_transcript(conn, clip["id"], text=text, model=name)
    took = time.monotonic() - started
    print(f"transcriber: {'rewrote' if upgrade else 'wrote'} clip {clip['id']} ({clip['duration_ms'] / 1000:.1f}s) with {name} "
          f"in {took:.1f}s ({clip['duration_ms'] / 1000 / max(took, 0.01):.1f}x real time)")


def live_step(conn, models, live):
    """Write the oldest new clip. Returns False when none wait. `models(name)` gives a loaded model."""
    waiting = db.untranscribed_clips(conn, limit=1)
    if waiting:
        do_clip(conn, models(live), live, waiting[0])
    return bool(waiting)


def final_step(conn, models, final):
    """Rewrite the oldest line another model wrote, but only while the live worker has nothing waiting."""
    if db.untranscribed_clips(conn, limit=1):
        return False
    clip = db.clip_to_upgrade(conn, final)
    if clip:
        do_clip(conn, models(final), final, clip, upgrade=True)
    return bool(clip)


def worker(db_path, models, pick, step, idle):
    conn = db.connect(db_path)  # one connection per thread: sqlite3 connections can't be shared between threads
    while True:
        # read every turn, so a change in The Pitstop's Voice settings applies to the next clip
        live, final = pick_models(db.get_setting(conn, "voice_model"), db.get_setting(conn, "voice_fast_model"))
        if not step(conn, models, pick(live, final)):
            time.sleep(idle)


def main():
    if hasattr(os, "nice"):  # Linux, like the Docker image; Windows has no nice
        os.nice(10)  # low CPU priority: the bot and anything else on the server go first
    db_path = os.environ.get("DB_PATH", "data/pitboss.db")
    loaded, lock = {}, threading.Lock()

    def models(name):
        with lock:  # both workers may ask for a model the first time at once
            if name not in loaded:
                print(f"transcriber: loading {name} on {THREADS} threads")
                loaded[name] = WhisperModel(name, device="cpu", compute_type="int8", cpu_threads=THREADS,
                                            download_root=str(MODEL_DIR))
            return loaded[name]

    claude = bool(os.environ.get("ANTHROPIC_API_KEY"))
    db.set_setting(db.connect(db_path), "voice_claude", "1" if claude else "")  # the call page says when reviews are off
    if claude:  # waits on the network, not the CPU, so it never slows transcription
        threading.Thread(target=review.worker, args=(db_path,), daemon=True).start()
    threading.Thread(target=worker, args=(db_path, models, lambda live, final: final, final_step, 1), daemon=True).start()
    worker(db_path, models, lambda live, final: live, live_step, 0.25)


if __name__ == "__main__":
    main()
