import json
import unittest
from types import SimpleNamespace
from unittest import mock

from core import db, review

FINAL = "large-v3-turbo"


def fake_client(*replies):
    """An Anthropic client whose streamed messages return `replies` in order (dicts are sent back as JSON)."""
    client = mock.MagicMock()
    messages = [SimpleNamespace(stop_reason="end_turn", content=[SimpleNamespace(type="text", text=r if isinstance(r, str) else json.dumps(r))],
                                usage=SimpleNamespace(input_tokens=10, cache_read_input_tokens=0, output_tokens=5)) for r in replies]
    client.beta.messages.stream.return_value.__enter__.return_value.get_final_message.side_effect = messages
    return client


def sent(client, n=-1):
    """The keyword arguments of the n-th request."""
    return client.beta.messages.stream.call_args_list[n].kwargs


SUMMARY = {"overview": "They planned the raid.", "topics": ["The rat king [0:05]"], "decisions": ["Free the bandit [0:10]"],
           "people": [{"name": "Bob", "points": ["Found Veyra [0:00]"]}]}


class Review(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.addCleanup(self.conn.close)
        db.set_setting(self.conn, "voice_model", FINAL)
        self.call = db.start_call(self.conn, 99, SimpleNamespace(id=10, name="Deadlock 1"), 5, 1000)
        for i in range(25):  # enough lines to be worth reviewing; the first three mishear the same name
            db.add_clip(self.conn, self.call, 7, "Bob (@bob)", i * 1000, 800, f"{i}.ogg")
            db.save_transcript(self.conn, i + 1, text=["We met Vera.", "Bayra helped.", "Vyra's sword"][i] if i < 3 else f"line {i}", model=FINAL)
        db.end_call(self.conn, self.call, 1100)
        patcher = mock.patch("builtins.print")
        patcher.start()
        self.addCleanup(patcher.stop)

    def status(self):
        return db.get_call(self.conn, self.call)["review_status"]

    def test_ready_only_once_every_clip_is_final(self):
        db.save_transcript(self.conn, 1, text="We met Vera.", model="small.en")  # still waits for the final model
        self.assertFalse(db.call_ready(self.conn, self.call, FINAL))
        self.assertFalse(review.step(self.conn, fake_client()))  # nothing sent to Claude
        db.save_transcript(self.conn, 1, text="We met Vera.", error="boom", model="small.en")  # a failed rewrite is final
        db.save_transcript(self.conn, 2, text="", model="small.en")  # so is noise
        self.assertTrue(db.call_ready(self.conn, self.call, FINAL))
        db.update_call(self.conn, self.call, status="recording")
        self.assertFalse(db.call_ready(self.conn, self.call, FINAL))

    def test_old_calls_wait_for_the_button(self):
        db.update_call(self.conn, self.call, review_status="old")
        self.assertFalse(review.step(self.conn, fake_client()))

    def test_short_calls_are_skipped(self):
        with self.conn:
            self.conn.execute("DELETE FROM voice_clips WHERE id > 5")
        client = fake_client()
        review.step(self.conn, client)
        self.assertEqual(self.status(), "short")
        client.beta.messages.stream.assert_not_called()

    def test_questions_answers_and_follow_up_rounds(self):
        question = {"variants": [{"text": "Vera", "clips": [1, 999]}, {"text": "Bayra", "clips": [2]}, {"text": "Vyra", "clips": [3]}],
                    "guess": "Veyra", "confidence": "high", "question": "Are Vera, Bayra and Vyra all Veyra?"}
        client = fake_client({"questions": [question]}, {"questions": []}, SUMMARY)
        review.step(self.conn, client)
        self.assertIn("#1 [0:00] Bob: We met Vera.", sent(client)["messages"][0]["content"][0]["text"])  # names, times and clip ids
        self.assertEqual(sent(client)["model"], "claude-opus-5-5")
        self.assertEqual(self.status(), "questions")
        q = db.call_questions(self.conn, self.call)[0]
        self.assertEqual(json.loads(q["variants"])[0]["clips"], [1])  # a clip id from outside the call is dropped
        self.assertFalse(review.step(self.conn, client))  # waits for the answer

        db.answer_question(self.conn, q["id"], "Veyra")
        db.update_call(self.conn, self.call, review_status=None)  # what the panel does once all are answered
        review.step(self.conn, client)  # round 2: corrected text, and the answer so Claude doesn't ask again
        text = "".join(b["text"] for b in sent(client)["messages"][0]["content"])
        self.assertIn("We met Veyra.", text)
        self.assertIn("Veyra's sword", text)
        self.assertIn("Answer: Veyra", text)
        self.assertEqual(self.status(), "summarise")

        review.step(self.conn, client)
        call = db.get_call(self.conn, self.call)
        self.assertEqual((call["review_status"], json.loads(call["summary"])), ("done", SUMMARY))

    def test_fixes_whole_words_only(self):
        fixes = review.fixes([{"answer": "Veyra", "variants": json.dumps([{"text": "Vera", "clips": []}, {"text": "Veyra", "clips": []}])},
                              {"answer": "", "variants": json.dumps([{"text": "bandit", "clips": []}])}])
        self.assertEqual(fixes, [("Vera", "Veyra")])  # "leave as is" and the right spelling change nothing
        self.assertEqual(review.fix_text("vera met Veranda, then Vera.", fixes), "Veyra met Veranda, then Veyra.")

    def test_glossary(self):
        review.add_to_glossary(self.conn, "Veyra", ["Vera", "Veyra", "Bayra"])
        review.add_to_glossary(self.conn, "veyra", ["Vyra"])  # already there
        self.assertEqual(db.get_setting(self.conn, "voice_glossary"), "Veyra (heard as Vera, Bayra)")
        client = fake_client({"questions": []})
        review.step(self.conn, client)
        self.assertIn("<glossary>\nVeyra (heard as Vera, Bayra)\n</glossary>", sent(client)["messages"][0]["content"][0]["text"])

    def test_failures_are_kept(self):
        client = fake_client()
        client.beta.messages.stream.side_effect = RuntimeError("overloaded")
        review.step(self.conn, client)
        call = db.get_call(self.conn, self.call)
        self.assertEqual((call["review_status"], call["review_error"]), ("failed", "overloaded"))
        self.assertFalse(review.step(self.conn, client))  # not retried by itself

    def test_refusal_fails_the_call(self):
        client = fake_client({"questions": []})
        client.beta.messages.stream.return_value.__enter__.return_value.get_final_message.side_effect = [
            SimpleNamespace(stop_reason="refusal", content=[], usage=SimpleNamespace(input_tokens=1, cache_read_input_tokens=0, output_tokens=0))]
        review.step(self.conn, client)
        self.assertEqual(db.get_call(self.conn, self.call)["review_error"], "Claude declined to answer")

    def test_ask(self):
        db.update_call(self.conn, self.call, review_status="done", summary=json.dumps(SUMMARY))
        other = db.start_call(self.conn, 99, SimpleNamespace(id=10, name="Deadlock 1"), 5, 500)
        db.update_call(self.conn, other, status="done", review_status="done", summary=json.dumps(SUMMARY | {"overview": "Last week."}))
        db.add_ask(self.conn, self.call, "Who found Veyra?", [other, 12345], 1200)
        db.add_ask(self.conn, self.call, "Second?", [], 1300)
        self.assertEqual([a["question"] for a in db.call_asks(self.conn, self.call)], ["Second?", "Who found Veyra?"])  # newest first
        client = fake_client("Bob did [0:00].", "Nothing about that in the transcript.")
        review.step(self.conn, client)
        first, rest = sent(client)["messages"][0]["content"]
        self.assertEqual(first["cache_control"], {"type": "ephemeral", "ttl": "1h"})  # transcript and summary are cached
        self.assertIn("<summary>\nThey planned the raid.", first["text"])
        self.assertIn("Last week.", rest["text"])  # the other call's summary goes after the cached part
        self.assertIn("<question>Who found Veyra?</question>", rest["text"])
        review.step(self.conn, client)
        self.assertEqual(sent(client, 0)["messages"][0]["content"][0], sent(client, 1)["messages"][0]["content"][0])  # same prefix
        self.assertEqual([a["answer"] for a in db.call_asks(self.conn, self.call)],
                         ["Nothing about that in the transcript.", "Bob did [0:00]."])

    def test_failed_ask_keeps_the_error(self):
        db.update_call(self.conn, self.call, review_status="done", summary=json.dumps(SUMMARY))
        db.add_ask(self.conn, self.call, "Who?", [], 1200)
        client = fake_client()
        client.beta.messages.stream.side_effect = RuntimeError("rate limited")
        review.step(self.conn, client)
        self.assertEqual(db.call_asks(self.conn, self.call)[0]["error"], "rate limited")
        self.assertFalse(review.step(self.conn, client))

    def test_rerun_review_keeps_answers(self):
        db.add_questions(self.conn, self.call, 1, [{"variants": [{"text": "Vera", "clips": [1]}], "guess": "Veyra", "confidence": "low",
                                                   "question": f"Q{i}"} for i in range(2)])
        db.answer_question(self.conn, 1, "Veyra")
        db.rerun_review(self.conn, self.call)
        self.assertEqual([q["question"] for q in db.call_questions(self.conn, self.call)], ["Q0"])
        self.assertIsNone(self.status())


class OldDatabases(unittest.TestCase):
    def test_existing_calls_are_marked_old(self):
        import os
        import sqlite3
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "old.db")
            conn = sqlite3.connect(path)
            conn.execute("CREATE TABLE voice_calls (id INTEGER PRIMARY KEY AUTOINCREMENT, recorder_id INTEGER NOT NULL, channel_id INTEGER NOT NULL, "
                         "channel_name TEXT NOT NULL, started_by INTEGER, started_at INTEGER NOT NULL, ended_at INTEGER, status TEXT NOT NULL)")
            conn.execute("INSERT INTO voice_calls (recorder_id, channel_id, channel_name, started_at, status) VALUES (1, 2, 'x', 3, 'done')")
            conn.commit()
            conn.close()
            conn = db.connect(path)
            self.assertEqual(db.get_call(conn, 1)["review_status"], "old")
            conn.close()
