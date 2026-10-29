import json
import tempfile
import unittest
from pathlib import Path

from aiohttp import web
from aiohttp.test_utils import TestServer

from core import api as api_mod
from core.api import APIError, DeadlockAPI


class ApiLog(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        def reply(response):
            async def handler(request):
                return response()
            return handler

        app = web.Application()
        app.router.add_get("/ok", reply(lambda: web.json_response({"a": 1})))
        app.router.add_get("/missing", reply(lambda: web.Response(status=404)))
        app.router.add_get("/busy", reply(lambda: web.Response(status=503)))
        self.server = TestServer(app)
        await self.server.start_server()
        self.tmp = tempfile.TemporaryDirectory()
        self.log = Path(self.tmp.name) / "api.jsonl"
        self.old_base = api_mod.BASE_URL
        api_mod.BASE_URL = str(self.server.make_url(""))
        self.api = DeadlockAPI(log_path=self.log)
        await self.api.start()

    async def asyncTearDown(self):
        await self.api.close()
        await self.server.close()
        api_mod.BASE_URL = self.old_base
        self.tmp.cleanup()

    async def test_every_call_is_logged(self):
        self.assertEqual(await self.api.get("/ok", x=1, flag=True), {"a": 1})
        self.assertIsNone(await self.api.get("/missing"))
        with self.assertRaises(APIError):
            await self.api.get("/busy")
        lines = [json.loads(l) for l in self.log.read_text(encoding="utf8").splitlines()]
        self.assertEqual([(l["url"], l["status"]) for l in lines], [("/ok", 200), ("/missing", 404), ("/busy", 503)])
        self.assertEqual(lines[0]["params"], {"x": 1, "flag": "true"})
        self.assertEqual(lines[0]["bytes"], len('{"a": 1}'))
        self.assertTrue(all(isinstance(l["t"], int) and l["ms"] >= 0 for l in lines))

    async def test_no_log_path_and_unwritable_path_never_break_calls(self):
        self.api.log_path = None
        self.assertEqual(await self.api.get("/ok"), {"a": 1})
        self.api.log_path = Path(self.tmp.name) / "missing-dir" / "api.jsonl"
        self.assertEqual(await self.api.get("/ok"), {"a": 1})


if __name__ == "__main__":
    unittest.main()
