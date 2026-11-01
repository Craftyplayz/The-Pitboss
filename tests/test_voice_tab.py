import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from aiohttp.test_utils import TestClient, TestServer

import dash
from core import db

ENV = {"DISCORD_TOKEN": "t", "GUILD_ID": "1", "DISCORD_CLIENT_ID": "2", "DISCORD_CLIENT_SECRET": "secret",
       "DASH_URL": "http://pitstop.test", "DB_PATH": ":memory:"}
CHANNELS = [{"id": "10", "name": "Deadlock 1", "type": 2}, {"id": "11", "name": "general", "type": 0}]
USER = {"id": "5", "name": "Crafty"}


class VoiceCall(unittest.IsolatedAsyncioTestCase):
    """A done call with fake rows, shared by the tests below."""

    async def asyncSetUp(self):
        self.dir = tempfile.TemporaryDirectory()
        with mock.patch.dict(os.environ, ENV):
            app = dash.make_app()
        app["voice_dir"] = Path(self.dir.name)
        self.db = app["db"]
        for name, fake in (("guild_channels", mock.AsyncMock(return_value=CHANNELS)), ("discord_get", mock.AsyncMock(side_effect=self.member))):
            patcher = mock.patch.object(dash, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.client = TestClient(TestServer(app))
        await self.client.start_server()
        # a done call with two speakers, one noise-only clip and one still transcribing
        self.call = db.start_call(self.db, 99, SimpleNamespace(id=10, name="Deadlock 1"), 5, 1000)
        db.end_call(self.db, self.call, 1090)
        for i, (member, name, start, text) in enumerate([(7, "Bob <b> (@bob)", 0, "hello there"), (8, "Ann (@ann)", 1500, ""),
                                                         (8, "Ann (@ann)", 3000, "hi bob"), (7, "Bob <b> (@bob)", 5000, None)]):
            rel = f"{self.call}/{member}/{start}.ogg"
            (Path(self.dir.name) / rel).parent.mkdir(parents=True, exist_ok=True)
            (Path(self.dir.name) / rel).write_bytes(b"OggS")
            db.add_clip(self.db, self.call, member, name, start, 1000, rel)
            if text is not None:
                db.save_transcript(self.db, i + 1, text=text)

    async def member(self, app, path, auth):
        if path.endswith("/members/7"):
            return {"avatar": None, "user": {"avatar": "abc"}}
        raise dash.web.HTTPBadGateway()  # Ann left the server

    async def asyncTearDown(self):
        await self.client.close()
        self.dir.cleanup()

    def cookies(self):
        self.client.session.cookie_jar.update_cookies({"session": dash.sign(USER | {"exp": time.time() + 600}, "secret")})


class VoiceTab(VoiceCall):
    async def test_needs_a_login(self):
        page = await (await self.client.get("/voice")).text()
        self.assertIn("Log in with Discord", page)
        self.assertNotIn("Deadlock 1", page)
        self.assertEqual((await self.client.get("/voice/clip/1.ogg")).status, 403)
        self.assertEqual((await self.client.get(f"/voice/call/{self.call}.txt")).status, 403)

    async def test_call_list_and_page(self):
        self.cookies()
        page = await (await self.client.get("/voice")).text()
        self.assertIn("🔊Deadlock 1", page)
        self.assertIn("1:30", page)  # length
        self.assertIn("1 transcribing", page)
        page = await (await self.client.get(f"/voice/call/{self.call}")).text()
        self.assertIn("hello there", page)
        self.assertIn("Bob &lt;b&gt;", page)  # names are escaped
        self.assertIn("Transcribing…", page)
        self.assertEqual(page.count('class="ln"'), 3)  # the noise-only clip is hidden
        self.assertEqual(page.count('class="msg"'), 3)  # Bob, Ann, Bob: a new group each time the speaker changes
        self.assertIn("https://cdn.discordapp.com/avatars/7/abc.png", page)
        self.assertIn(dash.DEFAULT_AVATAR, page)

    async def test_join_and_leave_markers(self):
        self.cookies()
        for at, who, before, after in ((1010, "Cat (@cat)", "none", "Deadlock 1"), (1020, "Cat (@cat)", "Deadlock 1", "Lobby"),
                                       (1030, "Pitboss", "none", "Deadlock 1"), (1040, "Dan (@dan)", "none", "general")):
            db.add_event(self.db, at, "voice_updated", "voice", "x", user_id=99 if who == "Pitboss" else 3, user_name=who,
                         data={"changes": {"channel": [before, after]}})
        page = await (await self.client.get(f"/voice/call/{self.call}")).text()
        self.assertIn("Cat joined", page)
        self.assertIn("Cat left", page)  # moved to another channel
        self.assertNotIn("Pitboss joined", page)  # the recorder itself
        self.assertNotIn("Dan", page)

    async def test_transcript_download(self):
        self.cookies()
        text = await (await self.client.get(f"/voice/call/{self.call}.txt")).text()
        self.assertEqual(text, "[0:00] Bob <b>: hello there\n[0:03] Ann: hi bob\n")

    async def test_clip_audio(self):
        self.cookies()
        r = await self.client.get("/voice/clip/1.ogg")
        self.assertEqual((r.status, r.headers["Content-Type"], r.headers["Content-Security-Policy"]), (200, "audio/ogg", "sandbox"))
        with self.db:
            self.db.execute("UPDATE voice_clips SET file = '../../etc/passwd' WHERE id = 1")
        self.assertEqual((await self.client.get("/voice/clip/1.ogg")).status, 404)
        self.assertEqual((await self.client.get("/voice/clip/99.ogg")).status, 404)

    async def test_settings(self):
        self.cookies()
        origin = {"Origin": "http://pitstop.test"}
        self.assertEqual((await self.client.post("/voice/settings", data={"model": "small.en"}, allow_redirects=False)).status, 403)
        r = await self.client.post("/voice/settings", data=[("autojoin", "10"), ("autojoin", "11"), ("model", "medium.en")],
                                   headers=origin, allow_redirects=False)
        self.assertEqual(r.status, 302)
        self.assertEqual(db.autojoin_channels(self.db), {10})  # the text channel is ignored
        self.assertEqual(db.get_setting(self.db, "voice_model"), "medium.en")
        self.assertIsNone(db.get_setting(self.db, "voice_live_channel"))  # left on the default
        r = await self.client.post("/voice/settings", data={"model": "small.en", "live": "11"}, headers=origin, allow_redirects=False)
        self.assertEqual(db.get_setting(self.db, "voice_live_channel"), "11")
        r = await self.client.post("/voice/settings", data={"model": "small.en", "live": "10"}, headers=origin, allow_redirects=False)
        self.assertEqual(r.status, 400)  # a voice channel isn't a text channel
        self.assertIsNone(db.get_setting(self.db, "voice_fast_model"))  # left on small.en
        await self.client.post("/voice/settings", data={"model": "large-v3-turbo", "fast": ""}, headers=origin, allow_redirects=False)
        self.assertEqual(db.get_setting(self.db, "voice_fast_model"), "")  # no live model: the final model writes every line
        r = await self.client.post("/voice/settings", data={"model": "small.en", "fast": "evil/repo"}, headers=origin, allow_redirects=False)
        self.assertEqual(r.status, 400)
        r = await self.client.post("/voice/settings", data={"model": "someone/evil-repo"}, headers=origin, allow_redirects=False)
        self.assertEqual(r.status, 400)

    async def test_delete(self):
        self.cookies()
        origin = {"Origin": "http://pitstop.test"}
        live = db.start_call(self.db, 99, SimpleNamespace(id=10, name="Deadlock 1"), None, 2000)
        self.assertEqual((await self.client.post(f"/voice/call/{live}/delete", headers=origin, allow_redirects=False)).status, 409)
        r = await self.client.post(f"/voice/call/{self.call}/delete", headers=origin, allow_redirects=False)
        self.assertEqual(r.status, 302)
        self.assertIsNone(db.get_call(self.db, self.call))
        self.assertEqual(db.call_clips(self.db, self.call), [])
        self.assertFalse((Path(self.dir.name) / str(self.call)).exists())


class ClaudeReview(VoiceCall):
    """The call page's Review, Summary and Ask sections, with fake rows instead of Claude."""
    ORIGIN = {"Origin": "http://pitstop.test"}

    async def asyncSetUp(self):
        await super().asyncSetUp()
        db.set_setting(self.db, "voice_claude", "1")
        self.cookies()

    async def page(self):
        return await (await self.client.get(f"/voice/call/{self.call}")).text()

    async def post(self, what, data):
        return await self.client.post(f"/voice/call/{self.call}/{what}", data=data, headers=self.ORIGIN, allow_redirects=False)

    async def test_off_without_a_key(self):
        db.set_setting(self.db, "voice_claude", "")
        self.assertIn("Claude reviews are off", await self.page())
        self.assertIn("<td>Off</td>", await (await self.client.get("/voice")).text())

    async def test_states_on_the_call_list(self):
        self.assertIn("Waiting for final transcript", await (await self.client.get("/voice")).text())  # one clip still transcribing
        db.save_transcript(self.db, 4, text="bye")
        self.assertIn("Reviewing…", await (await self.client.get("/voice")).text())
        db.update_call(self.db, self.call, review_status="failed", review_error="overloaded <b>")
        self.assertIn("Failed</span>: overloaded &lt;b&gt;", await (await self.client.get("/voice")).text())

    async def test_questions_and_answers(self):
        db.add_questions(self.db, self.call, 1, [
            {"variants": [{"text": "hello", "clips": [1]}], "guess": "Hallo", "confidence": "high", "question": "Is <hello> Hallo?"},
            {"variants": [{"text": "bob", "clips": [3]}], "guess": "Bobby", "confidence": "low", "question": "Is bob Bobby?"}])
        page = await self.page()
        self.assertIn("Is &lt;hello&gt; Hallo?", page)
        self.assertIn('data-seek="0">0:00</button>', page)  # where it was heard, linked to the player
        self.assertIn("2 questions waiting", await (await self.client.get("/voice")).text())
        self.assertEqual((await self.client.post(f"/voice/call/{self.call}/answer", data={"q1": "guess"}, allow_redirects=False)).status, 403)
        await self.post("answer", {"q1": "guess", "q2": "own", "own2": ""})  # an empty own answer stays unanswered
        self.assertEqual([q["answer"] for q in db.call_questions(self.db, self.call)], ["Hallo", None])
        self.assertEqual(db.get_call(self.db, self.call)["review_status"], "questions")  # waits for the rest
        await self.post("answer", {"q2": "leave"})
        self.assertIsNone(db.get_call(self.db, self.call)["review_status"])  # the next round can start
        self.assertEqual(db.get_setting(self.db, "voice_glossary"), "Hallo (heard as hello)")
        page = await self.page()
        self.assertIn('data-o="hello there">Hallo there</p>', page)  # corrected, original kept for "Show original"
        self.assertIn('id="orig"', page)
        self.assertIn("Hallo there", await (await self.client.get(f"/voice/call/{self.call}.txt")).text())
        logs = [r["summary"] for r in self.db.execute("SELECT summary FROM events WHERE kind = 'panel_change'")]
        self.assertIn('Crafty answered Claude on voice call 1: "Is <hello> Hallo?" → Hallo', logs)
        self.assertIn('Crafty answered Claude on voice call 1: "Is bob Bobby?" → leave as is', logs)

    async def test_summary_and_ask(self):
        self.assertNotIn("Ask about this call", await self.page())  # only once there's a summary
        self.assertEqual((await self.post("ask", {"question": "Who?"})).status, 400)
        db.update_call(self.db, self.call, review_status="done", summary=json.dumps(
            {"overview": "A <short> chat.", "topics": ["Greetings [0:03]"], "decisions": [], "people": [{"name": "Ann", "points": ["Said hi"]}]}))
        other = db.start_call(self.db, 99, SimpleNamespace(id=10, name="Deadlock 2"), 5, 500)
        db.update_call(self.db, other, status="done", review_status="done", summary=db.get_call(self.db, self.call)["summary"])
        page = await self.page()
        self.assertIn("A &lt;short&gt; chat.", page)
        self.assertIn('data-seek="3000">[0:03]</button>', page)
        self.assertIn(f'name="include" value="{other}"', page)
        self.assertIn("Re-run summary", page)
        await self.post("ask", {"question": "  What did Ann say?  ", "include": [str(other), "999", "x"]})
        ask = db.call_asks(self.db, self.call)[0]
        self.assertEqual((ask["question"], json.loads(ask["include"])), ("What did Ann say?", [other]))  # unknown calls dropped
        self.assertIn("Thinking…", await self.page())
        db.save_ask(self.db, ask["id"], answer="Ann said hi [1:02:03].")
        page = await self.page()
        self.assertIn('data-seek="3723000">[1:02:03]</button>', page)
        self.assertNotIn("Thinking…", page)
        self.assertEqual((await self.post("ask", {"question": "x" * 1001})).status, 400)

    async def test_rerun(self):
        self.assertEqual((await self.post("rerun", {"what": "review"})).status, 400)  # still waiting for the transcript
        db.update_call(self.db, self.call, review_status="old")
        self.assertIn("Review this call", await self.page())
        await self.post("rerun", {"what": "review"})
        self.assertIsNone(db.get_call(self.db, self.call)["review_status"])
        db.update_call(self.db, self.call, review_status="done", summary="{}")
        await self.post("rerun", {"what": "summary"})
        self.assertEqual(db.get_call(self.db, self.call)["review_status"], "summarise")
        logs = [r["summary"] for r in self.db.execute("SELECT summary FROM events WHERE kind = 'panel_change'")]
        self.assertIn("Crafty re-ran Claude's summary of voice call 1 (🔊Deadlock 1)", logs)

    async def test_dnd_summary(self):
        self.assertNotIn("Summarise with Claude", await self.page())  # waits for the final transcript
        db.save_transcript(self.db, 4, text="bye")
        with mock.patch.object(dash.dnd, "SESSIONS", Path(self.dir.name) / "sessions"):
            self.assertIn("Summarise with Claude", await self.page())
            self.assertEqual((await self.post("dnd", {"action": "start", "new": "../x"})).status, 400)
            await self.post("dnd", {"action": "start", "new": "Curse "})
            run = db.call_dnd(self.db, self.call)
            self.assertEqual((run["campaign"], run["status"]), ("curse", "claude"))
            self.assertIn("Claude is reading", await self.page())
            self.assertEqual((await self.post("dnd", {"action": "reply", "text": "hi"})).status, 400)  # not your turn
            msgs = [{"role": "user", "content": []}, {"role": "assistant", "content": [{"type": "text", "text": "1. Is **Vera** Veyra?"}]}]
            db.update_dnd(self.db, run["id"], status="you", messages=json.dumps(msgs), sent="35 characters in 1 part, last timestamp 0:03")
            page = await self.page()
            self.assertIn("<ol><li>Is <b>Vera</b> Veyra?</li></ol>", page)
            self.assertIn("sent 35 characters in 1 part, last timestamp 0:03", page)
            await self.post("dnd", {"action": "reply", "text": " 1: yes "})
            run = db.call_dnd(self.db, self.call)
            self.assertEqual((run["status"], json.loads(run["messages"])[-1]), ("claude", {"role": "user", "content": "1: yes"}))
            db.update_dnd(self.db, run["id"], status="done", summary="Written for: <the table>", filename="session-01-1970-01-01.md")
            page = await self.page()
            self.assertIn("<p>Written for: &lt;the table&gt;</p>", page)
            self.assertIn("Copy summary", page)
            self.assertIn("Saved data/sessions/curse/session-01-1970-01-01.md", page)
            await self.post("dnd", {"action": "restart"})
            self.assertEqual(db.call_dnd(self.db, self.call)["status"], "claude")
        logs = [r["summary"] for r in self.db.execute("SELECT summary FROM events WHERE kind = 'panel_change'")]
        self.assertIn("Crafty started a D&D summary (curse) on voice call 1", logs)

    async def test_glossary_setting(self):
        await self.client.post("/voice/settings", data={"model": "small.en", "glossary": " Veyra (heard as Vera) "}, headers=self.ORIGIN)
        self.assertEqual(db.get_setting(self.db, "voice_glossary"), "Veyra (heard as Vera)")
        await self.client.post("/voice/settings", data={"model": "small.en"}, headers=self.ORIGIN)  # a form without it keeps it
        self.assertEqual(db.get_setting(self.db, "voice_glossary"), "Veyra (heard as Vera)")
        self.assertIn("Veyra (heard as Vera)</textarea>", await (await self.client.get("/voice")).text())
