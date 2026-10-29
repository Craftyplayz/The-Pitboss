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
