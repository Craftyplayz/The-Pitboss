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
CREATE TABLE IF NOT EXISTS role_menus (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id       INTEGER NOT NULL,
    message_id       INTEGER,           -- NULL until posted
    mode             TEXT NOT NULL,     -- core.rolemenus.MODES
    max_picks        INTEGER NOT NULL,  -- 0 no limit, 1 pick only one
    required_role_id INTEGER,           -- only members with this role can use it
    button_style     TEXT,
    placeholder      TEXT,              -- dropdown's empty text
    embed            TEXT NOT NULL,     -- core.embeds config (JSON)
    updated_at       INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS role_menu_options (
    menu_id     INTEGER NOT NULL,
    position    INTEGER NOT NULL,
    role_id     INTEGER NOT NULL,
    emoji       TEXT,
    label       TEXT NOT NULL,
    description TEXT,
    PRIMARY KEY (menu_id, position)
);
CREATE TABLE IF NOT EXISTS voice_calls (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    recorder_id  INTEGER NOT NULL,  -- the bot account recording it, so more recorder bots can share the table later
    channel_id   INTEGER NOT NULL,
    channel_name TEXT NOT NULL,
    started_by   INTEGER,           -- member who ran /record start; NULL when auto-joined
    started_at   INTEGER NOT NULL,  -- unix seconds
    ended_at     INTEGER,
    status       TEXT NOT NULL,     -- recording, done, interrupted (bot restarted mid-call)
    -- Claude's review, the step it waits for: NULL (review a round once the transcript is final), questions (waiting
    -- for answers), summarise, done, failed, old (recorded before reviews existed) or short (too little said)
    review_status TEXT,
    review_error  TEXT,
    summary       TEXT,             -- JSON from core/review.py
    audio         TEXT              -- imported calls: the whole call's recording, relative to the voice folder
);
CREATE TABLE IF NOT EXISTS voice_clips (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id     INTEGER NOT NULL,
    member_id   INTEGER NOT NULL,
    member_name TEXT NOT NULL,
    start_ms    INTEGER NOT NULL,  -- from the start of the call
    duration_ms INTEGER NOT NULL,
    file        TEXT NOT NULL,     -- relative to the voice folder
    text        TEXT,              -- NULL until transcribed
    error       TEXT,
    model       TEXT               -- speech-to-text model that wrote `text`; NULL before this was tracked
);
CREATE INDEX IF NOT EXISTS voice_clips_call ON voice_clips (call_id, start_ms);
CREATE TABLE IF NOT EXISTS voice_questions (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id    INTEGER NOT NULL,
    round      INTEGER NOT NULL,  -- answering every question of a round lets Claude ask follow-ups in the next
    question   TEXT NOT NULL,
    variants   TEXT NOT NULL,     -- JSON [{"text": "Vera", "clips": [clip ids]}]
    guess      TEXT NOT NULL,
    confidence TEXT NOT NULL,     -- high, medium, low
    answer     TEXT               -- NULL until answered; "" means leave as is
);
CREATE TABLE IF NOT EXISTS voice_asks (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id  INTEGER NOT NULL,
    question TEXT NOT NULL,
    include  TEXT NOT NULL,       -- JSON ids of other calls whose summaries go along
    asked_at INTEGER NOT NULL,
    answer   TEXT,                -- NULL while Claude thinks
    error    TEXT
);
CREATE TABLE IF NOT EXISTS dnd_runs (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id  INTEGER NOT NULL,
    campaign TEXT NOT NULL,       -- folder in data/sessions/
    status   TEXT NOT NULL,       -- claude (its turn), you (waiting for a reply), done (file saved) or failed
    messages TEXT NOT NULL,       -- JSON chat history sent to Claude, starting with the transcript
    sent     TEXT,                -- what the first message held: characters, parts, last timestamp
    memory   TEXT,                -- the session file it started from, NULL on the first session
    filename TEXT,                -- the session file it saves
    summary  TEXT,
    error    TEXT
);
"""


def connect(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    # databases made before these columns existed
    for table, column in (("voice_clips", "model"), ("voice_calls", "review_status"), ("voice_calls", "review_error"),
                          ("voice_calls", "summary"), ("voice_calls", "audio")):
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")
        except sqlite3.OperationalError:
            continue  # already there (the bot, panel and transcriber all run this at startup)
        if column == "review_status":
            with conn:  # calls recorded before reviews existed only get one from the call page's button
                conn.execute("UPDATE voice_calls SET review_status = 'old'")
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


MENU_FIELDS = ("channel_id", "message_id", "mode", "max_picks", "required_role_id", "button_style", "placeholder", "embed", "updated_at")


def save_menu(conn, menu_id, options, **fields):
    """Create (menu_id None) or update a role menu and replace its options. Returns the menu id."""
    with conn:
        if menu_id is None:
            cols = [k for k in MENU_FIELDS if k in fields]
            menu_id = conn.execute(f"INSERT INTO role_menus ({', '.join(cols)}) VALUES ({', '.join('?' * len(cols))})",
                                   [fields[k] for k in cols]).lastrowid
        else:
            cols = [k for k in MENU_FIELDS if k in fields]
            conn.execute(f"UPDATE role_menus SET {', '.join(f'{k} = ?' for k in cols)} WHERE id = ?", [*(fields[k] for k in cols), menu_id])
        if options is not None:
            conn.execute("DELETE FROM role_menu_options WHERE menu_id = ?", (menu_id,))
            conn.executemany("INSERT INTO role_menu_options (menu_id, position, role_id, emoji, label, description) VALUES (?, ?, ?, ?, ?, ?)",
                             [(menu_id, i, o["role_id"], o["emoji"], o["label"], o["description"]) for i, o in enumerate(options)])
    return menu_id


def get_menu(conn, menu_id):
    return conn.execute("SELECT * FROM role_menus WHERE id = ?", (menu_id,)).fetchone()


def menu_for_message(conn, message_id):
    return conn.execute("SELECT * FROM role_menus WHERE message_id = ?", (message_id,)).fetchone()


def role_menus(conn):
    return conn.execute("SELECT * FROM role_menus ORDER BY id").fetchall()


def menu_options(conn, menu_id):
    return [dict(r) for r in conn.execute("SELECT * FROM role_menu_options WHERE menu_id = ? ORDER BY position", (menu_id,))]


def start_call(conn, recorder_id, channel, started_by, at):
    with conn:
        return conn.execute("INSERT INTO voice_calls (recorder_id, channel_id, channel_name, started_by, started_at, status) "
                            "VALUES (?, ?, ?, ?, ?, 'recording')", (recorder_id, channel.id, channel.name, started_by, at)).lastrowid


def end_call(conn, call_id, at, status="done"):
    with conn:
        conn.execute("UPDATE voice_calls SET ended_at = ?, status = ? WHERE id = ?", (at, status, call_id))


def interrupt_calls(conn, recorder_id, at):
    """Calls this recorder left as `recording` when it stopped; their clips so far are kept. Returns their channel ids."""
    channels = [r["channel_id"] for r in conn.execute(
        "SELECT channel_id FROM voice_calls WHERE recorder_id = ? AND status = 'recording'", (recorder_id,))]
    with conn:
        conn.execute("UPDATE voice_calls SET ended_at = ?, status = 'interrupted' WHERE recorder_id = ? AND status = 'recording'",
                     (at, recorder_id))
    return channels


def recording_in(conn, channel_id):
    """The call in progress in this channel, by any recorder bot."""
    return conn.execute("SELECT * FROM voice_calls WHERE channel_id = ? AND status = 'recording'", (channel_id,)).fetchone()


def add_clip(conn, call_id, member_id, member_name, start_ms, duration_ms, file):
    with conn:
        conn.execute("INSERT INTO voice_clips (call_id, member_id, member_name, start_ms, duration_ms, file) VALUES (?, ?, ?, ?, ?, ?)",
                     (call_id, member_id, member_name, start_ms, duration_ms, file))


# a clip still waiting for the final model (`?`): no text yet, or a line another model wrote. Noise, failed clips
# and lines from before models were tracked never get rewritten, so they count as final.
NOT_FINAL = "v.error IS NULL AND (v.text IS NULL OR (v.text != '' AND v.model IS NOT NULL AND v.model != ?))"


def voice_calls(conn, final_model, limit=100):
    """Newest calls first, each with its speakers, how many clips still wait for text or for the final model,
    and how many review questions wait for an answer."""
    return conn.execute(
        "SELECT c.*, GROUP_CONCAT(DISTINCT v.member_name) AS speakers, "
        f"SUM(v.text IS NULL AND v.error IS NULL) AS pending, SUM({NOT_FINAL}) AS unfinal, "
        "(SELECT COUNT(*) FROM voice_questions q WHERE q.call_id = c.id AND q.answer IS NULL) AS open FROM voice_calls c "
        "LEFT JOIN voice_clips v ON v.call_id = c.id GROUP BY c.id ORDER BY c.id DESC LIMIT ?", (final_model, limit)).fetchall()


def get_call(conn, call_id):
    return conn.execute("SELECT * FROM voice_calls WHERE id = ?", (call_id,)).fetchone()


def call_clips(conn, call_id):
    return conn.execute("SELECT * FROM voice_clips WHERE call_id = ? ORDER BY start_ms", (call_id,)).fetchall()


def call_joins(conn, call):
    """[(at, user_id, user name, joined)] from the Server Log: who came and went during the call."""
    out = []
    for r in conn.execute("SELECT at, user_id, user_name, data FROM events WHERE kind = 'voice_updated' AND at BETWEEN ? AND ? ORDER BY id",
                          (call["started_at"], call["ended_at"] or 2 ** 62)):
        before, after = json.loads(r["data"] or "{}").get("changes", {}).get("channel", [None, None])
        if call["channel_name"] in (before, after) and before != after and r["user_id"] != call["recorder_id"]:
            out.append((r["at"], r["user_id"], r["user_name"], after == call["channel_name"]))
    return out


def import_call(conn, call):
    """Store a parsed transcript (core/importer.py) as a done call with no audio. None if it's already there."""
    if conn.execute("SELECT 1 FROM voice_calls WHERE channel_name = ? AND started_at = ?", (call["channel"], call["started_at"])).fetchone():
        return None
    with conn:
        # recorder 0: no bot recorded it. 'old': Claude only reviews it from the call page's button
        call_id = conn.execute("INSERT INTO voice_calls (recorder_id, channel_id, channel_name, started_at, ended_at, status, review_status) "
                               "VALUES (0, 0, ?, ?, ?, 'done', 'old')", (call["channel"], call["started_at"], call["ended_at"])).lastrowid
        conn.executemany("INSERT INTO voice_clips (call_id, member_id, member_name, start_ms, duration_ms, file, text) VALUES (?, ?, ?, ?, ?, '', ?)",
                         [(call_id, member_id, name, ms, dur, text) for member_id, name, ms, dur, text in call["lines"]])
    return call_id


def get_clip(conn, clip_id):
    return conn.execute("SELECT * FROM voice_clips WHERE id = ?", (clip_id,)).fetchone()


def delete_call(conn, call_id):
    with conn:
        conn.execute("DELETE FROM voice_questions WHERE call_id = ?", (call_id,))
        conn.execute("DELETE FROM voice_asks WHERE call_id = ?", (call_id,))
        conn.execute("DELETE FROM dnd_runs WHERE call_id = ?", (call_id,))
        conn.execute("DELETE FROM voice_clips WHERE call_id = ?", (call_id,))
        conn.execute("DELETE FROM voice_calls WHERE id = ?", (call_id,))


def untranscribed_clips(conn, limit=20):
    """Clips waiting for text, oldest first, each with `ready_at`: the unix time its sentence ended."""
    return conn.execute("SELECT v.*, c.started_at + (v.start_ms + v.duration_ms) / 1000.0 AS ready_at FROM voice_clips v "
                        "JOIN voice_calls c ON c.id = v.call_id WHERE v.text IS NULL AND v.error IS NULL ORDER BY v.id LIMIT ?",
                        (limit,)).fetchall()


def clip_to_upgrade(conn, model):
    """The oldest line another model wrote, to rewrite with `model`, live calls included. Noise-only clips stay empty
    with any model, and a clip whose rewrite failed keeps its error instead of being retried."""
    return conn.execute("SELECT * FROM voice_clips WHERE text != '' AND error IS NULL AND model IS NOT NULL AND model != ? "
                        "ORDER BY id LIMIT 1", (model,)).fetchone()


def save_transcript(conn, clip_id, text=None, error=None, model=None):
    with conn:
        conn.execute("UPDATE voice_clips SET text = ?, error = ?, model = ? WHERE id = ?", (text, error, model, clip_id))


def call_ready(conn, call_id, final_model):
    """Whether Claude may read the call: it ended and every clip has its final text."""
    return conn.execute(f"SELECT status != 'recording' AND NOT EXISTS (SELECT 1 FROM voice_clips v WHERE v.call_id = c.id "
                        f"AND {NOT_FINAL}) FROM voice_calls c WHERE c.id = ?", (final_model, call_id)).fetchone()[0] == 1


def call_to_review(conn, final_model):
    return conn.execute(f"SELECT * FROM voice_calls c WHERE review_status IS NULL AND status != 'recording' AND NOT EXISTS "
                        f"(SELECT 1 FROM voice_clips v WHERE v.call_id = c.id AND {NOT_FINAL}) ORDER BY id LIMIT 1",
                        (final_model,)).fetchone()


def call_to_summarise(conn):
    return conn.execute("SELECT * FROM voice_calls WHERE review_status = 'summarise' ORDER BY id LIMIT 1").fetchone()


def update_call(conn, call_id, **fields):
    cols = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(f"UPDATE voice_calls SET {cols} WHERE id = ?", (*fields.values(), call_id))


def add_questions(conn, call_id, round_, questions):
    """Store one round of Claude's questions; the call then waits for answers."""
    with conn:
        conn.executemany("INSERT INTO voice_questions (call_id, round, question, variants, guess, confidence) VALUES (?, ?, ?, ?, ?, ?)",
                         [(call_id, round_, q["question"], json.dumps(q["variants"]), q["guess"], q["confidence"]) for q in questions])
        conn.execute("UPDATE voice_calls SET review_status = 'questions', review_error = NULL WHERE id = ?", (call_id,))


def call_questions(conn, call_id):
    return conn.execute("SELECT * FROM voice_questions WHERE call_id = ? ORDER BY id", (call_id,)).fetchall()


def answer_question(conn, question_id, answer):
    with conn:
        conn.execute("UPDATE voice_questions SET answer = ? WHERE id = ?", (answer, question_id))


def rerun_review(conn, call_id):
    """Review the call again: answers stay (and so do their corrections), unanswered questions and the summary go."""
    with conn:
        conn.execute("DELETE FROM voice_questions WHERE call_id = ? AND answer IS NULL", (call_id,))
        conn.execute("UPDATE voice_calls SET review_status = NULL, review_error = NULL, summary = NULL WHERE id = ?", (call_id,))


def add_ask(conn, call_id, question, include, at):
    with conn:
        conn.execute("INSERT INTO voice_asks (call_id, question, include, asked_at) VALUES (?, ?, ?, ?)",
                     (call_id, question, json.dumps(include), at))


def next_ask(conn):
    return conn.execute("SELECT * FROM voice_asks WHERE answer IS NULL AND error IS NULL ORDER BY id LIMIT 1").fetchone()


def save_ask(conn, ask_id, answer=None, error=None):
    with conn:
        conn.execute("UPDATE voice_asks SET answer = ?, error = ? WHERE id = ?", (answer, error, ask_id))


def call_asks(conn, call_id):
    """Newest first, like the call page shows them."""
    return conn.execute("SELECT * FROM voice_asks WHERE call_id = ? ORDER BY id DESC", (call_id,)).fetchall()


def start_dnd(conn, call_id, campaign):
    with conn:
        conn.execute("INSERT INTO dnd_runs (call_id, campaign, status, messages) VALUES (?, ?, 'claude', '[]')", (call_id, campaign))


def call_dnd(conn, call_id):
    """The call's newest D&D summary chat, or None."""
    return conn.execute("SELECT * FROM dnd_runs WHERE call_id = ? ORDER BY id DESC LIMIT 1", (call_id,)).fetchone()


def next_dnd(conn):
    return conn.execute("SELECT * FROM dnd_runs WHERE status = 'claude' ORDER BY id LIMIT 1").fetchone()


def update_dnd(conn, run_id, **fields):
    cols = ", ".join(f"{k} = ?" for k in fields)
    with conn:
        conn.execute(f"UPDATE dnd_runs SET {cols} WHERE id = ?", (*fields.values(), run_id))


def summarised_calls(conn, ids=None):
    """Calls with a summary, newest first; only `ids` when given."""
    where = f" AND id IN ({','.join('?' * len(ids))})" if ids is not None else ""
    return conn.execute(f"SELECT * FROM voice_calls WHERE summary IS NOT NULL{where} ORDER BY id DESC", tuple(ids or ())).fetchall()


def autojoin_channels(conn):
    """Voice channel ids the bot joins on its own, set in The Pitstop's Voice settings."""
    return set(json.loads(get_setting(conn, "voice_autojoin") or "[]"))


def delete_menu(conn, menu_id):
    with conn:
        conn.execute("DELETE FROM role_menu_options WHERE menu_id = ?", (menu_id,))
        conn.execute("DELETE FROM role_menus WHERE id = ?", (menu_id,))
