import time
import unittest

from aiohttp import web

from dash import can_manage, changes, sign, unsign

KEY = "secret"
CHANNELS = [{"id": "1", "type": 0}, {"id": "2", "type": 2}, {"id": "3", "type": 15}, {"id": "4", "type": 5}]


class Session(unittest.TestCase):
    def test_round_trip(self):
        data = {"id": "9", "exp": time.time() + 60}
        self.assertEqual(unsign(sign(data, KEY), KEY), data)

    def test_rejects_forged_expired_and_missing(self):
        token = sign({"id": "9", "exp": time.time() + 60}, KEY)
        self.assertIsNone(unsign(token, "other key"))
        self.assertIsNone(unsign(token[:-1] + ("0" if token[-1] != "0" else "1"), KEY))
        self.assertIsNone(unsign(sign({"id": "9", "exp": time.time() - 1}, KEY), KEY))
        self.assertIsNone(unsign(None, KEY))


class CanManage(unittest.TestCase):
    def test_permissions(self):
        self.assertTrue(can_manage([{"id": "5", "permissions": str(1 << 5)}], 5))  # Manage Server
        self.assertTrue(can_manage([{"id": "5", "permissions": str(1 << 3)}], 5))  # Administrator
        self.assertTrue(can_manage([{"id": "5", "permissions": "0", "owner": True}], 5))
        self.assertFalse(can_manage([{"id": "5", "permissions": str(1 << 10)}], 5))
        self.assertFalse(can_manage([{"id": "6", "permissions": str(1 << 3)}], 5))  # admin elsewhere only


class Changes(unittest.TestCase):
    def test_valid(self):
        new = changes({"recap_forum_id": "3", "voice_hub_id": "2", "welcome_channel_id": "4",
                       "welcome_message": "  hi {user}  "}, CHANNELS)
        self.assertEqual(new["recap_forum_id"], "3")
        self.assertEqual(new["patch_notes_id"], "")  # not sent: unset
        self.assertEqual(new["welcome_channel_id"], "4")  # announcement channels count as text
        self.assertEqual(new["welcome_message"], "hi {user}")

    def test_wrong_type_or_unknown_channel(self):
        with self.assertRaises(web.HTTPBadRequest):
            changes({"voice_hub_id": "1"}, CHANNELS)  # text channel as voice hub
        with self.assertRaises(web.HTTPBadRequest):
            changes({"welcome_channel_id": "99"}, CHANNELS)

    def test_message_capped(self):
        self.assertEqual(len(changes({"welcome_message": "x" * 3000}, CHANNELS)["welcome_message"]), 2000)
