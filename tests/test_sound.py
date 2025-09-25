import asyncio
import tempfile
import unittest

import remind_bot as rb


class DummyBot:
    def __init__(self) -> None:
        self.sent = []  # (chat_id, text, disable_notification)

    async def send_message(self, chat_id: int, text: str, reply_markup=None, disable_notification: bool | None = None):
        self.sent.append((chat_id, text, bool(disable_notification)))


class DummyApp:
    def __init__(self) -> None:
        self.bot = DummyBot()


class SoundAndMelodyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = rb.ReminderDB(tempfile.NamedTemporaryFile(delete=False).name)
        self.app = DummyApp()
        self.sched = rb.ReminderScheduler(self.app, self.db)
        self.sched.start()
        self.chat_id = 3001
        self.user_id = 7001

    async def asyncTearDown(self):
        try:
            self.sched.shutdown()
        except Exception:
            pass

    async def test_sound_toggle_affects_delivery(self):
        handlers = rb.BotHandlers(self.app, self.db, self.sched, "Europe/Moscow")
        # By default sound is on
        await self.db.set_user_sound(self.chat_id, self.user_id, True)
        # schedule reminder
        fut = rb.now_utc() + rb.timedelta(seconds=1)
        rid = await self.db.add_reminder(self.chat_id, self.user_id, "beep", fut, "Europe/Moscow")
        self.sched.schedule_reminder(rid, self.chat_id, "beep", fut)
        # simulate deliver
        await self.sched._deliver_job(rid, self.chat_id, "beep")
        self.assertTrue(self.app.bot.sent[-1][2] is False or self.app.bot.sent[-1][2] == False)
        # turn sound off
        await self.db.set_user_sound(self.chat_id, self.user_id, False)
        await self.sched._deliver_job(rid, self.chat_id, "beep2")
        self.assertTrue(self.app.bot.sent[-1][2])

    async def test_melody_set_and_get(self):
        # default
        val = await self.db.get_user_melody(self.chat_id, self.user_id)
        self.assertEqual(val, "default")
        # set
        await self.db.set_user_melody(self.chat_id, self.user_id, "bell")
        val2 = await self.db.get_user_melody(self.chat_id, self.user_id)
        self.assertEqual(val2, "bell")


if __name__ == "__main__":
    unittest.main()


