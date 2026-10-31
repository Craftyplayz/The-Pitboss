import json
import sqlite3
from pathlib import Path

# shortcut: sync sqlite3 blocks the event loop briefly per query, fine for one server; move to aiosqlite if queries get slow
SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS links (
    member_id     INTEGER PRIMARY KEY,
    account_id    INTEGER NOT NULL UNIQUE,  -- Deadlock 32-bit account id
    linked_at     INTEGER NOT NULL,         -- unix seconds
    thread_id     INTEGER,                  -- Recap Thread, created on first recap
    last_match_id INTEGER                   -- newest Match already recapped
);
CREATE TABLE IF NOT EXISTS scrims (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    creator_id INTEGER NOT NULL,
    state      TEXT NOT NULL,  -- open, picking, creating, lobby, live, done, cancelled, failed
    created_at INTEGER NOT NULL,
    channel_id INTEGER,
    message_id INTEGER,        -- the sign-up message with the buttons
    party_id   TEXT,           -- deadlock-api custom lobby
    party_code TEXT,
    lobby_at   INTEGER,        -- when the current lobby code was made
    match_id   INTEGER,
    detail     TEXT            -- JSON scoreboard (core.dashboard.match_detail) once the Match is over
);
CREATE TABLE IF NOT EXISTS match_stats (
    account_id INTEGER NOT NULL,
    match_id   INTEGER NOT NULL,
    start_time INTEGER NOT NULL,
    stats      TEXT,           -- JSON from core.trophies.match_stats; NULL when the API never had metadata
    PRIMARY KEY (account_id, match_id)
);
CREATE TABLE IF NOT EXISTS scrim_players (
    scrim_id  INTEGER NOT NULL,
    member_id INTEGER NOT NULL,
    team      INTEGER,         -- 0 Amber, 1 Sapphire; NULL until teams are made
    joined_at INTEGER NOT NULL,
    PRIMARY KEY (scrim_id, member_id)
);
CREATE TABLE IF NOT EXISTS events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    at           INTEGER NOT NULL,  -- unix seconds
    kind         TEXT NOT NULL,     -- core.events.KINDS, e.g. message_deleted
    category     TEXT NOT NULL,     -- core.events.CATEGORIES
    user_id      INTEGER,           -- who it happened to or who did it
    user_name    TEXT,              -- "Display (@username)" at the time
    channel_id   INTEGER,
    channel_name TEXT,
    message_id   INTEGER,
    summary      TEXT NOT NULL,     -- one readable line
    data         TEXT               -- JSON details: content, before/after, saved files
);
CREATE INDEX IF NOT EXISTS events_at ON events (at);
CREATE INDEX IF NOT EXISTS events_message ON events (message_id);
"""


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get_setting(conn, key):
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_setting(conn, key, value):
    with conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )


def get_link(conn, member_id):
    return conn.execute("SELECT * FROM links WHERE member_id = ?", (member_id,)).fetchone()


def get_link_by_account(conn, account_id):
    return conn.execute("SELECT * FROM links WHERE account_id = ?", (account_id,)).fetchone()


def all_links(conn):
    return conn.execute("SELECT * FROM links").fetchall()


def set_link(conn, member_id, account_id, linked_at):
    """Create or replace a Member's Link. Recap state resets with it."""
    with conn:
        conn.execute("DELETE FROM links WHERE member_id = ?", (member_id,))
        conn.execute(
            "INSERT INTO links (member_id, account_id, linked_at) VALUES (?, ?, ?)",
            (member_id, account_id, linked_at),
        )


def delete_link(conn, member_id):
    with conn:
        conn.execute("DELETE FROM links WHERE member_id = ?", (member_id,))


def update_link(conn, member_id, **fields):
    cols = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(f"UPDATE links SET {cols} WHERE member_id = ?", (*fields.values(), member_id))


def save_match_stats(conn, account_id, match_id, start_time, stats):
    """stats: dict, or None to mark a Match whose metadata never showed up. The first save wins."""
    with conn:
        conn.execute("INSERT OR IGNORE INTO match_stats (account_id, match_id, start_time, stats) VALUES (?, ?, ?, ?)",
                     (account_id, match_id, start_time, None if stats is None else json.dumps(stats)))


def saved_match_ids(conn, account_id):
    return {r[0] for r in conn.execute("SELECT match_id FROM match_stats WHERE account_id = ?", (account_id,))}


def match_stats(conn, account_id):
    """[stats dict with "start_time"] for every saved Match that had metadata."""
    return [{**json.loads(r["stats"]), "start_time": r["start_time"]} for r in conn.execute(
        "SELECT start_time, stats FROM match_stats WHERE account_id = ? AND stats IS NOT NULL", (account_id,))]


def create_scrim(conn, creator_id, created_at):
    with conn:
        return conn.execute("INSERT INTO scrims (creator_id, state, created_at) VALUES (?, 'open', ?)",
                            (creator_id, created_at)).lastrowid


def get_scrim(conn, scrim_id):
    return conn.execute("SELECT * FROM scrims WHERE id = ?", (scrim_id,)).fetchone()


def update_scrim(conn, scrim_id, **fields):
    cols = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(f"UPDATE scrims SET {cols} WHERE id = ?", (*fields.values(), scrim_id))


def scrims_in(conn, *states):
    return conn.execute(f"SELECT * FROM scrims WHERE state IN ({','.join('?' * len(states))})", states).fetchall()


def scrim_players(conn, scrim_id):
    """[(member_id, team)] in join order."""
    return [tuple(r) for r in conn.execute(
        "SELECT member_id, team FROM scrim_players WHERE scrim_id = ? ORDER BY joined_at, rowid", (scrim_id,))]


def add_scrim_player(conn, scrim_id, member_id, joined_at, team=None):
    """Join, or move to `team` if already in."""
    with conn:
        conn.execute("INSERT INTO scrim_players (scrim_id, member_id, team, joined_at) VALUES (?, ?, ?, ?) "
                     "ON CONFLICT(scrim_id, member_id) DO UPDATE SET team = excluded.team",
                     (scrim_id, member_id, team, joined_at))


def remove_scrim_player(conn, scrim_id, member_id):
    with conn:
        conn.execute("DELETE FROM scrim_players WHERE scrim_id = ? AND member_id = ?", (scrim_id, member_id))


def set_scrim_teams(conn, scrim_id, teams):
    """teams: {member_id: team}"""
    with conn:
        conn.executemany("UPDATE scrim_players SET team = ? WHERE scrim_id = ? AND member_id = ?",
                         [(t, scrim_id, m) for m, t in teams.items()])



def add_event(conn, at, kind, category, summary, user_id=None, user_name=None, channel_id=None, channel_name=None,
              message_id=None, data=None):
    with conn:
        conn.execute("INSERT INTO events (at, kind, category, user_id, user_name, channel_id, channel_name, message_id, summary, data) "
                     "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (at, kind, category, user_id, user_name, channel_id, channel_name, message_id, summary,
                      json.dumps(data, ensure_ascii=False) if data else None))


def message_history(conn, message_id):
    """The logged sent and edited events of one message, oldest first; empty if the bot never saw it."""
    return conn.execute("SELECT * FROM events WHERE message_id = ? AND kind IN ('message_sent', 'message_edited') "
                        "ORDER BY id", (message_id,)).fetchall()


def _event_filter(categories, user, channel, text, since, until):
    where, args = [f"category IN ({','.join('?' * len(categories))})"], list(categories)
    for col, value in (("user", user), ("channel", channel)):
        if value and value.isdigit():
            where.append(f"{col}_id = ?")
            args.append(int(value))
        elif value:
            where.append(f"{col}_name LIKE ?")
            args.append(f"%{value}%")
    if text:
        where.append("(summary LIKE ? OR data LIKE ?)")
        args += [f"%{text}%"] * 2
    if since:
        where.append("at >= ?")
        args.append(since)
    if until:
        where.append("at < ?")
        args.append(until)
    return " AND ".join(where), args


def find_events(conn, categories, user=None, channel=None, text=None, since=None, until=None, before_id=None, limit=100):
    """(matching events newest first, total matching). before_id pages back from an event id."""
    where, args = _event_filter(categories, user, channel, text, since, until)
    total = conn.execute(f"SELECT COUNT(*) FROM events WHERE {where}", args).fetchone()[0]
    page = f" AND id < {int(before_id)}" if before_id else ""
    rows = conn.execute(f"SELECT * FROM events WHERE {where}{page} ORDER BY id DESC LIMIT ?", (*args, limit)).fetchall()
    return rows, total
