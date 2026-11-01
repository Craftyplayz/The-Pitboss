"""Claude summarises a D&D session from its transcript: it asks questions in a chat on the call page, then writes a
summary and saves a cumulative memory file in data/sessions/<campaign>/ that the next session's summary starts from.

Runs in the transcriber's review thread like the rest of core/review.py: the panel stores the chat in `dnd_runs` and
sets status 'claude', and `turn` answers it. `py -m core.dnd <transcript file> <campaign>` runs the same chat in a
terminal, for testing on a transcript file."""
import json
import re
import sys
from datetime import date
from pathlib import Path

from core import db
from core.review import BETAS, MODEL, call_text, day
from core.voicerec import VOICE_DIR

SESSIONS = VOICE_DIR.parent / "sessions"
CAMPAIGN = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")
FILE = re.compile(r"session-(\d+)-\d{4}-\d\d-\d\d\.md")
PART = 150_000  # characters per transcript part; the whole transcript still goes in one request (1M token context)
CACHE = {"type": "ephemeral", "ttl": "1h"}  # the transcript is resent every turn and answers come minutes apart
STAMP = re.compile(r"\d+:\d\d(?::\d\d)?(?: ?[AP]M)?")

PROMPT = """You summarise D&D sessions from Discord speech-to-text transcripts. Expect transcription errors, especially in names, places, spells and invented fantasy words.

## Memory
You may be given the latest file from the sessions/ folder. It is cumulative: cast, shared-account notes, name glossary, NPCs, places, plot threads and the user's preferences.
- Treat everything marked confirmed as settled. Use it and do not ask about it again.
- Only ask about new things, unconfirmed things, or places where the transcript contradicts memory. For contradictions, quote both.
- Follow the stored preferences, for example sections to leave out or topics to keep private.
If there is no memory file, this is the first session, so also ask the setup questions in Phase 3.

## Phase 1: Read and identify speakers
- Read the whole transcript before drawing any conclusions.
- Speaker labels are Discord usernames, not character names. Work out who the DM is and which player plays which character.
- Shared accounts: up to 5 people may talk through one Discord account (the memory file lists which accounts are shared; on the first run, ask). Never assume one label means one person. Split the lines using clues: DM narration and NPC voices, "I attack…" lines, rolls, people addressing each other by name, and possessions or backstory ("a costume from your caravan" points to the character who owns a caravan).
- Echo: online players' speech is often picked up again by the in-person microphone, so the same words appear under two labels a few seconds apart. Credit it to the original speaker and ignore the duplicate.
- Separate in-character talk, out-of-character chat and DM narration.
- Characters sometimes get NPC names wrong on purpose as a running joke. Don't "correct" those. Note them as jokes.

## Phase 2: Fix names
Group every name that was transcribed in more than one way. Make a table: Most likely spelling | Variants seen | Who/what (PC, NPC, place, item, faction, spell) | Confidence (High/Medium/Low).
Use the High-confidence ones from here on. Turn Medium and Low into questions. Names already confirmed in memory count as High.

## Phase 3: Questions
- Show the Phase 1 speaker list and the Phase 2 table, then ask your questions.
- Ask as many questions as you need, in batches of up to 10. Number each one, put the most important first, give a short quote with its timestamp, and give your best guess so I can just reply "4: yes".
- Ask about:
  - unclear names
  - who said or did something important on a shared account
  - confusing events
  - jokes vs. real in-game events
  - mechanics or results that were never said aloud
  - audio gaps
  - pronouns of any new character (never infer them from a name or from one speaker's usage)
  - whether any private or secret player threads should be left out
- Setup questions on the first run only: which accounts are shared, players' names and handles, the DM's name, and whether to include a "Previously" section.
- If I skip a question or leave it blank, ask it again in the next batch. If I answer only part of it, follow up on the rest.
- If an answer contradicts an earlier assumption (for example a place name), check what else depended on that assumption and ask about it.
- Keep going until I say "done with questions" or you have nothing left to ask.

## Phase 4: Summary
Start with one line naming the audience ("Written for: …"). Use the corrected names everywhere.
1. Session overview (2-3 sentences)
2. Cast: player → character (race/class if known), plus the NPCs met this session
3. Story recap in past tense and readable narrative style, with a heading for each scene or location. Include key dialogue, decisions and their outcomes.
4. Combat: who fought what, notable moments (crits, near-deaths, clever plays), and how each fight ended
5. Loot and rewards: items, gold, XP, information gained
6. Character moments
7. Plot threads: open mysteries, hooks, promises, enemies still around
8. Quotes: 3 to 5 of the best or funniest lines
9. Next session: where the party is and what they plan to do
Rules:
- Never invent events. Anything still unclear is marked [unclear].
- Never credit a shared-account line to a specific character unless the context or my answer makes it clear. Otherwise write "someone at the table".
- Leave out out-of-character chat unless it changed the game (a ruling or a retcon).
- End with one line listing any spellings that were never confirmed.

## Phase 5: Save the memory file
After the summary, save one markdown file for future runs. It must be cumulative: copy forward everything from the previous memory file, update it, and add this session. That way the newest file is always enough on its own. Use this structure:

---
session: <NN>
date: <YYYY-MM-DD>
title: <short title>
previous_file: <filename or none>
---
## Preferences
(sections to leave out, private topics never to mention, formatting choices)
## Players
| Player name/handle | Discord account | Character | Pronouns | Race/Class | Status (confirmed/unconfirmed) |
## Shared accounts
(which accounts are shared, who uses them, and clues for telling the speakers apart)
## Glossary
| Canonical spelling | Transcription variants seen | Type | Notes | confirmed? |
## NPCs
| Name | Role | Status (alive/dead/unknown) | Attitude to party | First/last seen (session) |
## Places and factions
## Party resources
(gold, notable items, mounts, contacts; what was gained or lost this session)
## Plot threads
| Thread | Status (open/resolved) | Opened in session | Latest development |
## Session log
### Session <NN>
(short bullet timeline of this session's events)
## Unconfirmed
(things to check next time instead of asking from scratch)

Keep private or secret topics out of the file, apart from a note in Preferences that they exist and must be left out."""
# how questions reach the user on the call page; this overrides how Phase 3 says to lay them out
ASKING = """

## How to ask on this page
I answer in a form, not a chat box. Whenever you have questions (Phase 3 and every follow-up batch), call ask_questions instead \
of writing them as text, and write nothing else in that reply:
- cast: Phase 1 as a short markdown summary of who is in the campaign: each Discord account, who uses it and their \
character, plus a line on how you split shared accounts. A few lines or a small table, without the evidence.
- names: one entry per name from the Phase 2 table that memory hasn't confirmed, High confidence included. Its options are \
possible spellings, most likely first.
- questions: the Phase 3 questions, up to 10 per batch. Each has a short quote and its options: your best guess first, then \
any other likely answers. The form always adds an "Other" box, so never add one. When a question is about something that \
happened, give the time of the line exactly as the transcript writes it, like 1:08:14, so I can jump there and listen.
In any text you write, put transcript times in square brackets, like [1:08:14]: the page turns them into links to that moment.
My answers come back as the tool result. Ask follow-ups the same way, or go on to Phase 4 and 5 when nothing is left."""
SYSTEM = PROMPT + ASKING

TOOL = {"name": "save_session_file", "eager_input_streaming": True,
        "description": "Save the cumulative memory file (Phase 5) into the campaign's sessions folder. Call it once, right "
                       "after the summary, with the exact filename you were given.",
        "input_schema": {"type": "object", "additionalProperties": False, "required": ["filename", "content"],
                         "properties": {"filename": {"type": "string"}, "content": {"type": "string", "description": "The whole markdown file"}}}}


OPTIONS = {"type": "array", "items": {"type": "string"}}
ASK = {"name": "ask_questions", "strict": True,
       "description": "Show the user the cast and your questions as a form. Their answers come back as this tool's result.",
       "input_schema": {"type": "object", "additionalProperties": False, "required": ["cast", "names", "questions"], "properties": {
           "cast": {"type": "string", "description": "Short markdown summary of who is in the campaign (Phase 1)"},
           "names": {"type": "array", "items": {
               "type": "object", "additionalProperties": False, "required": ["spelling", "variants", "what", "confidence", "options"],
               "properties": {"spelling": {"type": "string", "description": "Most likely spelling"}, "variants": OPTIONS,
                              "what": {"type": "string", "description": "PC, NPC, place, item, faction or spell, and who or what it is"},
                              "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                              "options": {**OPTIONS, "description": "Spellings to pick from, most likely first"}}}},
           "questions": {"type": "array", "items": {
               "type": "object", "additionalProperties": False, "required": ["question", "quote", "time", "options"],
               "properties": {"question": {"type": "string"}, "quote": {"type": "string", "description": "Short quote, or empty"},
                              "time": {"type": "string", "description": "Transcript time like 1:08:14, or empty"},
                              "options": {**OPTIONS, "description": "Your best guess first, then other likely answers"}}}}}}}


def pending(messages):
    """The ask_questions call waiting for answers, or None."""
    last = messages[-1] if messages else None
    if last and last["role"] == "assistant":
        return next((b for b in last["content"] if b["type"] == "tool_use" and b["name"] == ASK["name"]), None)


def questions_text(ask):
    """An ask_questions call as plain text, for the terminal."""
    a = ask["input"]
    out = [a.get("cast", ""), "", "Names:"]
    out += [f"  N{i}. {n['spelling']} ({n['what']}, {n['confidence']}; heard as {', '.join(n['variants'])}): {' / '.join(n['options'])}"
            for i, n in enumerate(a.get("names", []), 1)]
    out += ["", "Questions:"] + [f"  {i}. {q['question']} [{q['time']}] \"{q['quote']}\" Options: {' / '.join(q['options'])}"
                                 for i, q in enumerate(a.get("questions", []), 1)]
    return "\n".join(out)


def campaigns():
    return sorted(p.name for p in SESSIONS.glob("*") if p.is_dir() and CAMPAIGN.fullmatch(p.name))


def files(folder):
    """Session files oldest first, by number (session-100 after session-99)."""
    found = [(int(m[1]), p) for p in Path(folder).glob("session-*.md") if (m := FILE.fullmatch(p.name))]
    return [p for _, p in sorted(found)]


def next_file(folder, day_):
    """(newest memory file or None, the name the next one gets)."""
    found = files(folder)
    n = int(FILE.fullmatch(found[-1].name)[1]) + 1 if found else 1
    return (found[-1] if found else None), f"session-{n:02}-{day_}.md"


def opening(transcript, memory, filename):
    """The first message: memory file, the whole transcript in parts, then the go. Also what was sent, for the page."""
    lines, parts, size = transcript.splitlines(keepends=True), [""], 0
    for ln in lines:  # parts break between lines, never inside one
        if parts[-1] and len(parts[-1]) + len(ln) > PART:
            parts.append("")
        parts[-1] += ln
    assert "".join(parts) == transcript  # nothing dropped
    n = len(parts)
    blocks = [{"type": "text", "text": (f'<memory file="{memory.name}">\n{memory.read_text(encoding="utf-8")}\n</memory>'
                                        if memory else "There is no memory file: this is the first session.")
               + f"\n\nThe transcript follows in {n} part{'s' * (n > 1)}. Don't start until you have part {n}."}]
    blocks += [{"type": "text", "text": f'<transcript part="{i}" of="{n}">\n{p}\n</transcript>'} for i, p in enumerate(parts, 1)]
    blocks.append({"type": "text", "text": f"That was part {n} of {n}, the whole transcript. Start with Phase 1. When you "
                                           f"reach Phase 5, save the file as {filename} with save_session_file."})
    stamps = STAMP.findall(transcript)
    sent = f"{len(transcript):,} characters in {n} part{'s' * (n > 1)}, last timestamp {stamps[-1] if stamps else 'none'}"
    return blocks, sent


def save(folder, filename, tool_input):
    """Run save_session_file. (saved path or None, tool result text)."""
    name, content = tool_input.get("filename"), tool_input.get("content")
    if not isinstance(content, str) or not content.strip():
        return None, "Error: content is empty or was cut off. Call save_session_file again with the whole file."
    if name != filename:
        return None, f"Error: the filename must be {filename}. Check the session number in the file too, then call again."
    path = Path(folder) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(path, "x", encoding="utf-8") as f:  # never overwrite an earlier session
            f.write(content)
    except FileExistsError:
        return None, f"Error: {filename} already exists."
    return path, f"Saved {filename}."


def text_of(content):
    return "\n\n".join(b["text"] for b in content if b["type"] == "text").strip()


def talk(client, messages, folder, filename):
    """Claude's next reply, tool calls included; appends to `messages`. (saved path or None, summary or None)."""
    saved = summary = None
    while True:
        with client.beta.messages.stream(model=MODEL, max_tokens=64000, system=SYSTEM, messages=messages, tools=[TOOL, ASK],
                                         output_config={"effort": "high"}, cache_control=CACHE, betas=BETAS,
                                         fallbacks="default") as stream:
            msg = stream.get_final_message()
        u = msg.usage
        print(f"dnd: {u.input_tokens} in, {u.cache_read_input_tokens or 0} cached, {u.output_tokens} out")
        if msg.stop_reason == "refusal":
            raise RuntimeError("Claude declined to answer")
        if msg.stop_reason == "max_tokens":
            raise RuntimeError("Claude's answer was cut off")
        content = [b.to_dict() for b in msg.content]  # every block goes back unchanged, thinking included
        messages.append({"role": "assistant", "content": content})
        uses = [b for b in content if b["type"] == "tool_use"]
        if not uses or pending(messages):  # questions wait for the user's answers
            return saved, summary
        results = []
        for b in uses:
            path, result = save(folder, filename, b["input"]) if b["name"] == TOOL["name"] else (None, "Error: unknown tool")
            if path:
                # the summary comes with the save, or in the reply just before it
                saved, summary = path, text_of(content) or next(
                    (text_of(m["content"]) for m in reversed(messages[:-1]) if m["role"] == "assistant" and text_of(m["content"])), "")
            results.append({"type": "tool_result", "tool_use_id": b["id"], "content": result, "is_error": not path})
        messages.append({"role": "user", "content": results})


def turn(conn, client, run):
    """Answer the chat on a call page: the opening on the first turn, the admin's latest reply after that."""
    folder = SESSIONS / run["campaign"]
    messages = json.loads(run["messages"])
    fields = {}
    if not messages:
        memory, filename = next_file(folder, day(db.get_call(conn, run["call_id"])))
        blocks, sent = opening(call_text(conn, db.get_call(conn, run["call_id"])), memory, filename)
        messages.append({"role": "user", "content": blocks})
        fields = {"filename": filename, "memory": memory.name if memory else None, "sent": sent}
    saved, summary = talk(client, messages, folder, run["filename"] or fields["filename"])
    db.update_dnd(conn, run["id"], messages=json.dumps(messages), status="done" if saved else "you", error=None,
                  **fields, **({"summary": summary} if saved else {}))


def main(path, campaign, day_=None):
    """Chat in the terminal about a transcript file. 'quit' stops without saving."""
    import anthropic

    if not CAMPAIGN.fullmatch(campaign):
        sys.exit("Campaign: lowercase letters, digits and dashes")
    day_ = day_ or (m[0] if (m := re.search(r"\d{4}-\d\d-\d\d", Path(path).name)) else f"{date.today()}")
    folder = SESSIONS / campaign
    memory, filename = next_file(folder, day_)
    blocks, sent = opening(Path(path).read_text(encoding="utf-8"), memory, filename)
    print(f"Memory: {memory or 'none (first session)'}\nSending: {sent}\n")
    client, messages = anthropic.Anthropic(), [{"role": "user", "content": blocks}]
    while True:
        saved, summary = talk(client, messages, folder, filename)
        if saved:
            print(f"{summary}\n\nSaved {saved}")
            return
        ask = pending(messages)
        print("\n" + (questions_text(ask) if ask else text_of(messages[-1]["content"])) + "\n")
        reply = input("You (blank line ends, 'quit' stops):\n")
        lines = [reply]
        while lines[-1]:
            lines.append(input())
        if reply.strip() == "quit":
            return
        reply = "\n".join(lines).strip()
        messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": ask["id"], "content": reply}] if ask else reply})


if __name__ == "__main__":
    main(*sys.argv[1:4])
