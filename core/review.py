"""Claude reviews finished voice calls: it asks about words the speech-to-text likely misheard, writes a summary once
every question is answered, then answers questions about the call.

Runs as a thread in the transcriber process (see transcriber.py), never in the bot or a panel request: The Pitstop
only writes answers and questions into the database, and `step` picks them up. Only text is sent, never audio."""
import json
import re
import time
from datetime import datetime, timezone

from core import db
from core.voicerec import DEFAULT_MODEL, MODELS, clock, short_name

MODEL = "claude-opus-5-5"
# if Claude declines (safety classifiers), the API retries on a model it picks instead of failing the request
BETAS = ["server-side-fallback-2026-07-01"]
MIN_LINES = 20  # fewer spoken lines than this isn't worth a review
MAX_ROUNDS = 5  # follow-up rounds before it summarises anyway, so it can't keep asking forever
# answers usually come minutes apart: the 1 hour cache outlives the gaps, the 5 minute one wouldn't
CACHE = {"type": "ephemeral", "ttl": "1h"}
SYSTEM = ("You work with transcripts of voice calls on a Discord server. Speech-to-text (Whisper) wrote them, so words can be "
          "misheard, most often names of people, places and game characters. Speaker names come from Discord and are always "
          "right. Each line is [time into the call] Speaker: text.")
REVIEW = """Speech-to-text often mishears names and unusual words, and writes the same one differently in different lines: a \
character called "Veyra" might come out as "Vera", "Bayra" and "Vyra". Find those mistakes in the transcript. Each line \
starts with its clip id, like #123.

For each suspected mistake give:
- variants: every spelling you found, each with the clip ids of the lines that contain it (the right spelling too, if it appears)
- guess: your best guess at the correct spelling
- confidence: how sure you are of that guess
- question: one short question for the server admin, like "Are 'Vera', 'Bayra' and 'Vyra' all the character Veyra?"

The glossary holds confirmed spellings: use it to spot mistakes, and don't ask about a name it already covers unless it was \
misheard in a new way. Skip ordinary words that are only slightly off and don't change the meaning. Return an empty list \
when nothing is worth asking."""
SUMMARY = """Summarise this call for the server admin:
- overview: two to four sentences on what the call was about
- topics: what was talked about
- decisions: what was decided or agreed
- people: for each speaker who said something that matters, what they said
Use the spellings from the transcript and the glossary. End each topic, decision and point with the time of the line it \
comes from in square brackets, like [1:18:08]."""
ASK = """Answer the admin's question about this call. The summary is a guide; the transcript is the source, so check details \
there. Cite the time of each line you use in square brackets exactly as the transcript writes it, like [1:18:08]. If the \
transcript doesn't contain the answer, say so plainly instead of guessing. Summaries of other calls, when given, are \
background only: say which call (by date) anything from them comes from. Plain text in short paragraphs, no markdown."""
REVIEW_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["questions"],
    "properties": {"questions": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["variants", "guess", "confidence", "question"],
        "properties": {
            "variants": {"type": "array", "items": {
                "type": "object", "additionalProperties": False, "required": ["text", "clips"],
                "properties": {"text": {"type": "string"}, "clips": {"type": "array", "items": {"type": "integer"}}}}},
            "guess": {"type": "string"},
            "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
            "question": {"type": "string"}}}}}}
LIST = {"type": "array", "items": {"type": "string"}}
SUMMARY_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["overview", "topics", "decisions", "people"],
    "properties": {"overview": {"type": "string"}, "topics": LIST, "decisions": LIST, "people": {"type": "array", "items": {
        "type": "object", "additionalProperties": False, "required": ["name", "points"],
        "properties": {"name": {"type": "string"}, "points": LIST}}}}}


def final_model(conn):
    """The final speech-to-text model, as the transcriber picks it: a line is final once this model wrote it."""
    model = db.get_setting(conn, "voice_model")
    return model if model in MODELS else DEFAULT_MODEL


def fixes(questions):
    """[(misheard, correct)] from the answered questions, longest first so "Bayra's" goes before "Bay"."""
    out = [(v["text"], q["answer"]) for q in questions if q["answer"]
           for v in json.loads(q["variants"]) if v["text"].lower() != q["answer"].lower()]
    return sorted(out, key=lambda f: -len(f[0]))


def fix_text(text, fixes):
    """`text` with each misheard word replaced, whole words only. The stored text never changes."""
    for wrong, right in fixes:
        text = re.sub(rf"(?<!\w){re.escape(wrong)}(?!\w)", lambda _: right, text, flags=re.IGNORECASE)
    return text


def line(clip, fixes, ids=False):
    return f"{f'#{clip['id']} ' if ids else ''}[{clock(clip['start_ms'])}] {short_name(clip['member_name'])}: {fix_text(clip['text'], fixes)}"


def call_text(conn, call, ids=False):
    """The corrected transcript, one line per spoken clip; noise-only clips are left out."""
    found = fixes(db.call_questions(conn, call["id"]))
    return "\n".join(line(c, found, ids) for c in db.call_clips(conn, call["id"]) if c["text"])


def day(call):
    return f"{datetime.fromtimestamp(call['started_at'], timezone.utc):%Y-%m-%d}"


def context(conn, call, ids=False):
    """The glossary and the transcript: what every request about a call starts with."""
    glossary = db.get_setting(conn, "voice_glossary")
    return ((f"<glossary>\n{glossary}\n</glossary>\n\n" if glossary else "")
            + f'<transcript channel="{call["channel_name"]}" date="{day(call)}">\n{call_text(conn, call, ids)}\n</transcript>')


def summary_text(summary):
    """A stored summary as plain text, for prompts."""
    s = json.loads(summary)
    return "\n".join([s["overview"], "Topics:", *(f"- {t}" for t in s["topics"]), "Decisions:", *(f"- {d}" for d in s["decisions"]),
                      *(f"{p['name']}:\n" + "\n".join(f"- {x}" for x in p["points"]) for p in s["people"])])


def add_to_glossary(conn, answer, variants):
    """Remember a confirmed spelling for every later call, unless the glossary already has it."""
    glossary = db.get_setting(conn, "voice_glossary") or ""
    if any(row.split(" (")[0].strip().lower() == answer.lower() for row in glossary.splitlines()):
        return
    heard = [v for v in variants if v.lower() != answer.lower()]
    db.set_setting(conn, "voice_glossary", (glossary.rstrip() + "\n" if glossary.strip() else "")
                   + answer + (f" (heard as {', '.join(heard)})" if heard else ""))


def ask_claude(client, what, content, effort, schema=None):
    """Claude's reply as text, or parsed JSON when `schema` is given. Streamed, so a long transcript can't time out."""
    output = {"effort": effort} | ({"format": {"type": "json_schema", "schema": schema}} if schema else {})
    with client.beta.messages.stream(model=MODEL, max_tokens=32000, system=SYSTEM, output_config=output, betas=BETAS,
                                     fallbacks="default", messages=[{"role": "user", "content": content}]) as stream:
        msg = stream.get_final_message()
    u = msg.usage
    print(f"review: {what}: {u.input_tokens} in, {u.cache_read_input_tokens or 0} cached, {u.output_tokens} out")
    if msg.stop_reason == "refusal":
        raise RuntimeError("Claude declined to answer")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Claude's answer was cut off")
    text = "".join(b.text for b in msg.content if b.type == "text")
    return json.loads(text) if schema else text


def answered(questions):
    if not any(q["answer"] is not None for q in questions):
        return ""
    return ("\n\nThe admin already answered these. Don't ask them again, but you may ask follow-ups they raise:\n"
            + "\n".join(f'- {q["question"]} Answer: {q["answer"] or "leave as is, those words are right"}'
                        for q in questions if q["answer"] is not None))


def review(conn, client, call):
    """One round of questions, or straight on to the summary when Claude has none left."""
    clips = [c for c in db.call_clips(conn, call["id"]) if c["text"]]
    if len(clips) < MIN_LINES:
        return db.update_call(conn, call["id"], review_status="short")
    questions = db.call_questions(conn, call["id"])
    round_ = max((q["round"] for q in questions), default=0) + 1
    if round_ > MAX_ROUNDS:
        return db.update_call(conn, call["id"], review_status="summarise")
    found = ask_claude(client, f"review round {round_} of call {call['id']}",
                       [{"type": "text", "text": context(conn, call, ids=True)}, {"type": "text", "text": REVIEW + answered(questions)}],
                       "high", REVIEW_SCHEMA)["questions"]
    ids = {c["id"] for c in clips}
    for q in found:  # keep only clip ids from this call; the page links them to the player
        q["variants"] = [v | {"clips": [i for i in v["clips"] if i in ids]} for v in q["variants"]]
    found = [q for q in found if q["variants"]]
    if found:
        db.add_questions(conn, call["id"], round_, found)
    else:
        db.update_call(conn, call["id"], review_status="summarise", review_error=None)


def summarise(conn, client, call):
    summary = ask_claude(client, f"summary of call {call['id']}",
                         [{"type": "text", "text": context(conn, call)}, {"type": "text", "text": SUMMARY}], "high", SUMMARY_SCHEMA)
    db.update_call(conn, call["id"], review_status="done", summary=json.dumps(summary))


def answer(conn, client, ask):
    """The transcript and its summary go first and are cached, so the next question about the call costs a fraction."""
    call = db.get_call(conn, ask["call_id"])
    others = db.summarised_calls(conn, [i for i in json.loads(ask["include"]) if i != call["id"]])
    background = "".join(f'<other_call channel="{o["channel_name"]}" date="{day(o)}">\n{summary_text(o["summary"])}\n</other_call>\n\n'
                         for o in others)
    reply = ask_claude(client, f"question {ask['id']} on call {call['id']}", [
        {"type": "text", "text": context(conn, call) + f"\n\n<summary>\n{summary_text(call['summary'])}\n</summary>", "cache_control": CACHE},
        {"type": "text", "text": f"{background}<question>{ask['question']}</question>\n\n{ASK}"}], "medium")
    db.save_ask(conn, ask["id"], answer=reply.strip())


def step(conn, client):
    """Do one piece of work, questions first since someone is waiting on the page. False when there's nothing to do."""
    if ask := db.next_ask(conn):
        try:
            answer(conn, client, ask)
        except Exception as e:  # shortcut: a failed request isn't retried; the admin asks again
            db.save_ask(conn, ask["id"], error=str(e)[:500])
            print(f"review: question {ask['id']} failed: {e!r}")
        return True
    call = db.call_to_summarise(conn)
    work = summarise
    if not call:
        call, work = db.call_to_review(conn, final_model(conn)), review
    if not call:
        return False
    try:
        work(conn, client, call)
    except Exception as e:  # shortcut: no automatic retry (an API outage fails the call); the call page has re-run buttons
        db.update_call(conn, call["id"], review_status="failed", review_error=str(e)[:500])
        print(f"review: call {call['id']} failed: {e!r}")
    return True


def worker(db_path, idle=5):
    import anthropic  # here, so the panel and the tests never need the package

    conn, client = db.connect(db_path), anthropic.Anthropic()  # reads ANTHROPIC_API_KEY
    while True:
        if not step(conn, client):
            time.sleep(idle)
