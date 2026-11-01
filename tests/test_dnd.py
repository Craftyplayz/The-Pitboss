import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from core import db, dnd, markdown, review


def block(**b):
    return SimpleNamespace(to_dict=lambda: b, **b)


def fake_client(*replies):
    """An Anthropic client whose streamed messages are `replies`: each a list of content blocks (dicts)."""
    client = mock.MagicMock()
    client.beta.messages.stream.return_value.__enter__.return_value.get_final_message.side_effect = [
        SimpleNamespace(stop_reason="tool_use" if any(b["type"] == "tool_use" for b in r) else "end_turn",
                        content=[block(**b) for b in r], usage=SimpleNamespace(input_tokens=1, cache_read_input_tokens=0, output_tokens=1))
        for r in replies]
    return client


def text(t):
    return [{"type": "thinking", "thinking": "", "signature": "s"}, {"type": "text", "text": t}]


def saving(filename, content="---\nsession: 01\n---\n## Players"):
    return [{"type": "text", "text": "Written for: the table\n# Overview\nThey won."},
            {"type": "tool_use", "id": "t1", "name": "save_session_file", "input": {"filename": filename, "content": content}}]


ASKED = {"cast": "**Raygun**: Glory, played by Tom.",
         "names": [{"spelling": "Valen", "variants": ["Velen"], "what": "PC", "confidence": "high", "options": ["Valen", "Velen"]}],
         "questions": [{"question": "Who threw the javelin?", "quote": "I throw it!", "time": "1:08:14", "options": ["Vera", "Leon"]},
                       {"question": "Was the duel real?", "quote": "", "time": "", "options": []}]}


class Files(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def test_numbering(self):
        self.assertEqual(dnd.next_file(self.dir, "2026-10-29"), (None, "session-01-2026-10-29.md"))
        for name in ("session-09-2026-01-01.md", "session-100-2026-02-01.md", "session-99-2026-01-15.md", "notes.md"):
            (self.dir / name).write_text("x")
        memory, name = dnd.next_file(self.dir, "2026-10-29")
        self.assertEqual((memory.name, name), ("session-100-2026-02-01.md", "session-101-2026-10-29.md"))

    def test_save_checks_name_and_never_overwrites(self):
        name = "session-01-2026-10-29.md"
        self.assertIsNone(dnd.save(self.dir, name, {"filename": "../x.md", "content": "hi"})[0])
        self.assertIsNone(dnd.save(self.dir, name, {"filename": name, "content": " "})[0])
        self.assertEqual(dnd.save(self.dir, name, {"filename": name, "content": "hi"})[0], self.dir / name)
        self.assertIsNone(dnd.save(self.dir, name, {"filename": name, "content": "new"})[0])
        self.assertEqual((self.dir / name).read_text(), "hi")


class Opening(unittest.TestCase):
    def test_whole_transcript_in_parts(self):
        lines = "".join(f"[{i // 60}:{i % 60:02}] Bob: {'word ' * 20}\n" for i in range(3000))
        with mock.patch.object(dnd, "PART", 50_000):
            blocks, sent = dnd.opening(lines, None, "session-01-2026-10-29.md")
        parts = [b["text"] for b in blocks if b["text"].startswith("<transcript")]
        self.assertGreater(len(parts), 1)
        self.assertEqual("".join(p.split("\n", 1)[1].rsplit("\n</transcript>", 1)[0] for p in parts), lines)
        self.assertIn(f"in {len(parts)} parts", blocks[0]["text"])
        self.assertIn("first session", blocks[0]["text"])
        self.assertIn(f"part {len(parts)} of {len(parts)}", blocks[-1]["text"])
        self.assertEqual(sent, f"{len(lines):,} characters in {len(parts)} parts, last timestamp 49:59")

    def test_memory_goes_first(self):
        memory = Path(tempfile.mkdtemp()) / "session-03-2026-10-01.md"
        memory.write_text("## Glossary\nVeyra", encoding="utf-8")
        blocks, sent = dnd.opening("**Raygun** - 08:16:12 AM\nbye\n", memory, "session-04-2026-10-29.md")
        self.assertTrue(blocks[0]["text"].startswith('<memory file="session-03-2026-10-01.md">\n## Glossary\nVeyra'))
        self.assertTrue(sent.endswith("in 1 part, last timestamp 08:16:12 AM"))


class Turns(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        self.call = db.start_call(self.conn, 99, SimpleNamespace(id=10, name="D&D"), 5, 1_761_708_341)  # 2025-10-29
        db.add_clip(self.conn, self.call, 7, "Raygun (@ray)", 0, 800, "0.ogg")
        db.save_transcript(self.conn, 1, text="I attack the bandit.")
        db.end_call(self.conn, self.call, 1_761_708_400)
        db.update_call(self.conn, self.call, review_status="done")
        self.dir = Path(tempfile.mkdtemp())
        for patcher in (mock.patch.object(dnd, "SESSIONS", self.dir), mock.patch("builtins.print")):
            patcher.start()
            self.addCleanup(patcher.stop)
        db.start_dnd(self.conn, self.call, "curse")

    def run_(self):
        return db.call_dnd(self.conn, self.call)

    def test_questions_then_summary_and_file(self):
        client = fake_client(text("1. Who is the DM?"))
        self.assertTrue(review.step(self.conn, client))
        run = self.run_()
        self.assertEqual((run["status"], run["filename"], run["memory"]), ("you", "session-01-2025-10-29.md", None))
        self.assertEqual(run["sent"], "35 characters in 1 part, last timestamp 0:00")
        sent = client.beta.messages.stream.call_args.kwargs
        self.assertEqual((sent["system"], sent["tools"], sent["cache_control"]["ttl"]), (dnd.SYSTEM, [dnd.TOOL, dnd.ASK], "1h"))
        self.assertTrue(dnd.SYSTEM.startswith("You summarise D&D sessions") and "## How to ask on this page" in dnd.SYSTEM)
        self.assertIn("I attack the bandit.", json.dumps(sent["messages"][0]))
        self.assertFalse(review.step(self.conn, client))  # waits for the admin

        msgs = json.loads(run["messages"]) + [{"role": "user", "content": "1: Huski"}]
        db.update_dnd(self.conn, run["id"], status="claude", messages=json.dumps(msgs))
        client = fake_client(saving("wrong.md"), saving("session-01-2025-10-29.md"), text("Saved."))
        review.step(self.conn, client)
        run = self.run_()
        self.assertEqual(run["status"], "done")
        self.assertEqual(run["summary"], "Written for: the table\n# Overview\nThey won.")
        self.assertTrue((self.dir / "curse" / "session-01-2025-10-29.md").read_text().startswith("---\nsession: 01"))
        msgs = json.loads(run["messages"])
        self.assertEqual(msgs[1]["content"][0]["type"], "thinking")  # replayed unchanged
        self.assertTrue(msgs[4]["content"][0]["is_error"])  # the wrong filename was refused
        self.assertEqual(client.beta.messages.stream.call_count, 3)

        db.start_dnd(self.conn, self.call, "curse")  # the next session starts from that file
        review.step(self.conn, fake_client(text("Anything new?")))
        run = self.run_()
        self.assertEqual((run["memory"], run["filename"]), ("session-01-2025-10-29.md", "session-02-2025-10-29.md"))
        self.assertIn('<memory file="session-01-2025-10-29.md">', json.loads(run["messages"])[0]["content"][0]["text"])

    def test_questions_wait_for_the_form(self):
        ask = {"type": "tool_use", "id": "a1", "name": "ask_questions", "input": ASKED}
        client = fake_client([ask])
        review.step(self.conn, client)
        run = self.run_()
        self.assertEqual((run["status"], client.beta.messages.stream.call_count), ("you", 1))  # not answered by itself
        self.assertEqual(dnd.pending(json.loads(run["messages"]))["input"], ASKED)
        self.assertIn("N1. Valen (PC, high; heard as Velen): Valen / Velen", dnd.questions_text(ask))

    def test_failure_keeps_the_chat(self):
        client = mock.MagicMock()
        client.beta.messages.stream.side_effect = RuntimeError("overloaded")
        review.step(self.conn, client)
        run = self.run_()
        self.assertEqual((run["status"], run["error"], run["messages"]), ("failed", "overloaded", "[]"))


class Markdown(unittest.TestCase):
    def test_render(self):
        out = markdown.render("# Recap\n\nThe **party** won <b>.\n\n| A | B |\n|---|---|\n| 1 | 2 |\n\n- one\n- two\n\n3. three\n#5 not a heading")
        self.assertIn("<h2>Recap</h2>", out)
        self.assertIn("<p>The <b>party</b> won &lt;b&gt;.</p>", out)
        self.assertIn("<tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr>", out)
        self.assertIn("<ul><li>one</li><li>two</li></ul>", out)
        self.assertIn('<ol start="3"><li>three</li></ol><p>#5 not a heading</p>', out)
