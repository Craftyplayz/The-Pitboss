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
