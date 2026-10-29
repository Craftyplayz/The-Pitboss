import base64
import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

import admin


def write(path, calls, junk=False):
    with open(path, "w", encoding="utf8") as f:
        for c in calls:
            f.write(json.dumps(c) + "\n")
        if junk:
            f.write('{"t": 5, "url"')  # cut-off last line


class Logs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        write(self.dir / "api-bot.jsonl", [{"t": 10, "url": "/v1/players/1/match-history", "params": {}, "status": 200, "ms": 100, "bytes": 1000},
                                           {"t": 30, "url": "/v1/matches/9/metadata", "params": {}, "status": 503, "ms": 900, "bytes": 0}], junk=True)
        write(self.dir / "api-web.jsonl", [{"t": 20, "url": "/v1/players/steam", "params": {"account_ids": "1,2"}, "status": "error", "ms": 50, "bytes": 0}])

    def tearDown(self):
        self.tmp.cleanup()

    def test_read_merges_newest_first_and_skips_broken_lines(self):
        calls = admin.read_calls(self.dir)
        self.assertEqual([(c["t"], c["src"]) for c in calls], [(30, "bot"), (20, "web"), (10, "bot")])
        self.assertTrue(all(c["line"] > 0 for c in calls))

    def test_filter_and_stats(self):
        calls = admin.read_calls(self.dir)
        self.assertEqual(len(admin.filter_calls(calls, src="web")), 1)
        self.assertEqual(len(admin.filter_calls(calls, q="account_ids")), 1)  # matches params too
        self.assertEqual([c["t"] for c in admin.filter_calls(calls, errors=True)], [30, 20])
        s = admin.call_stats(calls)
        self.assertEqual((s["count"], s["errors"], s["avg_ms"], s["max_ms"], s["bytes"]), (3, 2, 350, 900, 1000))
        self.assertEqual(admin.call_stats([])["count"], 0)

    def test_size(self):
        self.assertEqual(admin.size(512), "512 B")
        self.assertEqual(admin.size(2048), "2.0 KB")


class Page(unittest.IsolatedAsyncioTestCase):
    async def client(self, password):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        write(Path(tmp.name) / "api-web.jsonl", [{"t": 1, "url": "/v1/<b>x", "params": {}, "status": 200, "ms": 5, "bytes": 9}])
        app = web.Application()
        app["log_dir"], app["admin_password"] = Path(tmp.name), password
        app.router.add_get("/admin", admin.admin)
        c = TestClient(TestServer(app))
        await c.start_server()
        self.addAsyncCleanup(c.close)
        return c

    @staticmethod
    def auth(pw):
        return {"Authorization": "Basic " + base64.b64encode(f"admin:{pw}".encode()).decode()}

    async def test_off_without_password(self):
        c = await self.client("")
        self.assertEqual((await c.get("/admin", headers=self.auth(""))).status, 404)

    async def test_needs_the_right_password(self):
        c = await self.client("s3cret")
        r = await c.get("/admin")
        self.assertEqual(r.status, 401)
        self.assertIn("Basic", r.headers["WWW-Authenticate"])
        self.assertEqual((await c.get("/admin", headers=self.auth("wrong"))).status, 401)
        r = await c.get("/admin", headers=self.auth("s3cret"))
        self.assertEqual(r.status, 200)
        text = await r.text()
        self.assertIn("&lt;b&gt;x", text)  # logged URLs are escaped
        self.assertNotIn("<b>x", text)


if __name__ == "__main__":
    unittest.main()
