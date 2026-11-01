"""Voice recording: cut each speaker's audio into one clip per sentence, so the transcriber can work while people talk."""
import os
import threading
import time
from pathlib import Path

import av

# next to the database, on the volume the bot, transcriber and control panel share
VOICE_DIR = Path(os.environ.get("DB_PATH", "data/pitboss.db")).parent / "voice"
# speech-to-text models picked in The Pitstop's Voice settings, least to most accurate (and fastest to slowest);
# only these, since a model name is a download
MODELS = ("base.en", "small.en", "medium.en", "large-v3-turbo")
DEFAULT_MODEL = "small.en"
RATE = 48000
BYTES_PER_MS = RATE * 2 * 2 // 1000  # Discord gives 48 kHz, 16-bit, stereo PCM
GAP_MS = 800  # a pause this long ends a clip
MAX_MS = 30_000  # whisper reads 30 s at a time; longer monologues get cut here
MIN_MS = 200  # shorter clips are clicks and coughs


def clock(ms):
    """0:42, 12:05 or 1:02:05 into the call."""
    s = ms // 1000
    return f"{s // 3600}:{s // 60 % 60:02}:{s % 60:02}" if s >= 3600 else f"{s // 60}:{s % 60:02}"


def short_name(name):
    return name.split(" (@")[0]  # "Display (@username)" from the recorder


def recordable(user):
    """People only: no bots, and no one still pending membership screening (hasn't agreed to the rules)."""
    return user is not None and not user.bot and not getattr(user, "pending", False)


def clip_path(root, call_id, member_id, start_ms):
    return Path(root) / str(call_id) / str(member_id) / f"{start_ms}.ogg"


class Clipper:
    """Collects PCM per speaker from the voice thread; `finished()` hands back clips whose speaker paused."""

    def __init__(self, clock=time.monotonic):
        self.clock = clock
        self.started = clock()
        self.lock = threading.Lock()  # write() runs on voice_recv's thread, finished() on the event loop
        self.open = {}  # member id: [member, start_ms, last_ms, bytearray]

    def now_ms(self):
        return int((self.clock() - self.started) * 1000)

    def write(self, member, pcm):
        now = self.now_ms()
        with self.lock:
            clip = self.open.get(member.id)
            if clip is None:
                # the first packet arrives about 20 ms after the speaker started
                clip = self.open[member.id] = [member, max(0, now - 20), now, bytearray()]
            clip[2] = now
            clip[3] += pcm

    def finished(self, flush=False):
        """[(member, start_ms, pcm)] for clips that paused, hit MAX_MS, or all of them when flushing."""
        now, out = self.now_ms(), []
        with self.lock:
            for mid, (member, start, last, pcm) in list(self.open.items()):
                if flush or now - last >= GAP_MS or len(pcm) >= MAX_MS * BYTES_PER_MS:
                    del self.open[mid]
                    if len(pcm) >= MIN_MS * BYTES_PER_MS:
                        out.append((member, start, bytes(pcm)))
        return out


def encode_ogg(pcm, path):
    """Stereo 48 kHz PCM to a mono Opus .ogg (about 0.25 MB per minute). Runs in a thread: it's CPU work."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with av.open(str(path), "w", format="ogg") as out:
        stream = out.add_stream("libopus", rate=RATE, layout="mono")
        stream.bit_rate = 32000
        samples = len(pcm) // 4
        frame = av.AudioFrame(format="s16", layout="stereo", samples=samples)
        frame.planes[0].update(pcm[:samples * 4])
        frame.sample_rate = RATE
        for packet in [*stream.encode(frame), *stream.encode(None)]:
            out.mux(packet)
