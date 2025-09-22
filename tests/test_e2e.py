import os
import time
import unittest
from datetime import datetime

E2E_ENABLED = os.getenv("E2E_TELEGRAM") == "1"
try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors.rpcerrorlist import PhoneCodeRequiredError
except Exception:  # pragma: no cover
    TelegramClient = None  # type: ignore


@unittest.skipUnless(E2E_ENABLED and TelegramClient is not None, "E2E disabled or Telethon not installed")
class E2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api_id = os.getenv("E2E_API_ID")
        api_hash = os.getenv("E2E_API_HASH")
        phone = os.getenv("E2E_PHONE")
        session = os.getenv("E2E_SESSION")  # optional StringSession
        if not api_id or not api_hash or not phone:
            raise unittest.SkipTest("E2E env vars missing: E2E_API_ID/E2E_API_HASH/E2E_PHONE")
        if session:
            cls.client = TelegramClient(StringSession(session), int(api_id), api_hash)
        else:
            cls.client = TelegramClient("e2e_session", int(api_id), api_hash)
        cls.client.start(phone=phone)
        cls.bot_username = os.getenv("E2E_BOT_USERNAME")  # e.g., belialreminderbot
        if not cls.bot_username:
            raise unittest.SkipTest("E2E_BOT_USERNAME missing")

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "client"):
            cls.client.disconnect()

    def test_flow_start_in_list(self):
        async def run_flow():
            me = await self.client.get_me()
            self.assertTrue(me)
            bot = await self.client.get_entity(self.bot_username)
            # ensure dialog
            await self.client.send_message(bot, "/start")
            await self.client.send_message(bot, "/lang en")
            await self.client.send_message(bot, "/in 1m e2e_test")
            # wait for ack
            ack = None
            async for msg in self.client.iter_messages(bot, limit=10):
                if "e2e_test" in (msg.message or ""):
                    ack = msg
                    break
            self.assertIsNotNone(ack)
            # list
            await self.client.send_message(bot, "/list")
            listed = None
            async for msg in self.client.iter_messages(bot, limit=10):
                if "Active reminders" in (msg.message or "") or "Активные" in (msg.message or ""):
                    listed = msg
                    break
            self.assertIsNotNone(listed)
        self.client.loop.run_until_complete(run_flow())
