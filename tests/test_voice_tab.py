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


class VoiceTab(unittest.IsolatedAsyncioTestCase):
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
