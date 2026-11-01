"""Transcripts recorded by another bot, as .md files, turned into calls on the Voice tab. A call's
recording can be added on its page afterwards (one file for the whole call, see voice_audio_upload in dash.py).

The format: a header with "**Date**: October 29, 2026 at 03:25:41 AM GMT" and "**Channel**: D&D", then a message per
"**Speaker** - 03:25:57 AM" line with its text on the lines below. Lines in *italics* (joins, leaves) are skipped."""
import re
import zlib
from datetime import datetime, timezone

DATE = re.compile(r"\*\*Date\*\*:\s*(.+?\d{4}) at (\d{1,2}:\d\d(?::\d\d)?(?: ?[AP]M)?)\s*(?:(?:GMT|UTC)([+-]\d{1,2})?(?::?(\d\d))?)?\s*$",
                  re.M | re.I)  # message times use the same zone as this line
CHANNEL = re.compile(r"\*\*Channel\*\*:\s*(.+?)\s*$", re.M)
MESSAGE = re.compile(r"\*\*(.+?)\*\*\s*[-–]\s*(\d{1,2}:\d\d(?::\d\d)?(?: ?[AP]M)?)\s*$", re.I)
END = re.compile(r"\*.* ended the recording\s*[-–]\s*(\d{1,2}:\d\d(?::\d\d)?(?: ?[AP]M)?)\*\s*$", re.I)
LONGEST = 30_000  # a line lasts until the next one starts, but no longer than this


def seconds(clock):
    """Seconds since midnight from "03:25:57 AM", "3:25 PM" or "15:25:57"."""
    t = clock.upper().replace(" ", "")
    pm, am = t.endswith("PM"), t.endswith("AM")
    h, m, *s = (int(x) for x in t.rstrip("APM").split(":"))
    h = h % 12 + 12 * pm if pm or am else h
    return h * 3600 + m * 60 + (s[0] if s else 0)


def member_id(name):
    """A stand-in id per speaker name; negative so it never matches a real Discord account."""
    return -(zlib.crc32(name.encode()) + 1)


def parse(text):
    """{"channel", "started_at", "ended_at", "lines": [(member id, name, start_ms, duration_ms, text)]}. ValueError if it isn't one."""
    date, channel = DATE.search(text), CHANNEL.search(text)
    if not date:
        raise ValueError("no **Date** line")
    day = datetime.strptime(date[1].strip(), "%B %d, %Y").replace(tzinfo=timezone.utc)
    zone = int(date[3] or 0) * 3600 + (int(date[4] or 0) * 60 if date[3] else 0) * (-1 if (date[3] or "").startswith("-") else 1)
    start = seconds(date[2])
    lines, end, last, days = [], None, start, 0  # lines: [name, ms, [text lines]]
    for row in text.split("## Transcript", 1)[-1].splitlines():
        msg, ended = MESSAGE.match(row.strip()), END.match(row.strip())
        if msg or ended:
            at = seconds((msg or ended).groups()[-1]) + days
            if at < last - 3600:  # the clock went back: past midnight
                days, at = days + 86400, at + 86400
            last = at
        if msg:
            lines.append([msg[1].strip(), (at - start) * 1000, []])
        elif ended:
            end = at
        elif lines and row.strip() and not row.startswith("*"):
            lines[-1][2].append(row.strip())
    lines = [ln for ln in lines if ln[2]]
    if not lines:
        raise ValueError("no messages found")
    out = []
    for i, (name, ms, words) in enumerate(lines):
        nxt = lines[i + 1][1] if i + 1 < len(lines) else ms + 5000
        out.append((member_id(name), name, max(ms, 0), max(1000, min(nxt - ms, LONGEST)), " ".join(words)))
    started_at = int(day.timestamp()) + start - zone
    ended_at = started_at + max(end - start if end else 0, (out[-1][2] + out[-1][3]) // 1000)
    return {"channel": channel[1] if channel else "Imported", "started_at": started_at, "ended_at": ended_at, "lines": out}
