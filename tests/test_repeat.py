import asyncio
import types
from datetime import datetime, timedelta, timezone
import unittest

from remind_bot import ReminderScheduler, Application, ReminderDB


class DummyBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id: int, text: str, reply_markup=None, disable_notification: bool = False):
        self.sent.append({
            "chat_id": chat_id,
            "text": text,
            "reply_markup": reply_markup,
            "disable_notification": disable_notification,
        })


class DummyApp:
    def __init__(self):
        self.bot = DummyBot()


class DummyDB:
    def __init__(self):
        # reminder rows by id
        self.rows = {}
        self.lang = {}
        self.marked_sent = []

    async def get_by_id(self, rid: int):
        return self.rows.get(rid)

    async def get_user_lang(self, chat_id: int, user_id: int):
        return self.lang.get((chat_id, user_id), "ru")

    async def mark_sent(self, rid: int):
        self.marked_sent.append(rid)


class DummyScheduler:
    def __init__(self):
        self.jobs = []

    def start(self):
        pass

    def shutdown(self, wait=False):
        pass

    def remove_job(self, job_id):
        pass

    def add_job(self, func, trigger=None, id=None, kwargs=None, **kw):
        self.jobs.append((func, trigger, id, kwargs, kw))


class RepeatTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.app = DummyApp()
        self.db = DummyDB()
        # add one scheduled reminder
        self.db.rows[1] = {
            "id": 1,
            "chat_id": 111,
            "user_id": 222,
            "text": "test",
            "due_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "scheduled",
        }
        self.db.lang[(111, 222)] = "ru"
        self.rs = ReminderScheduler(types.SimpleNamespace(bot=self.app.bot), self.db)  # type: ignore
        # swap scheduler to dummy
        self.rs.scheduler = DummyScheduler()

    async def test_deliver_schedules_repeat(self):
        await self.rs._deliver_job(1, 111, "msg")
        self.assertEqual(len(self.app.bot.sent), 1)
        # one repeat job planned
        self.assertTrue(any(job[0] == self.rs._repeat_check for job in self.rs.scheduler.jobs))
        # mark_sent is NOT called immediately
        self.assertEqual(self.db.marked_sent, [])

    async def test_repeat_check_resends_when_still_scheduled(self):
        await self.rs._repeat_check(1, 111, "msg")
        self.assertGreaterEqual(len(self.app.bot.sent), 1)
        self.assertTrue(any(job[0] == self.rs._repeat_check for job in self.rs.scheduler.jobs))

    async def test_repeat_check_stops_when_sent(self):
        self.db.rows[1]["status"] = "sent"
        await self.rs._repeat_check(1, 111, "msg")
        # no resend
        self.assertEqual(len(self.app.bot.sent), 0)


if __name__ == "__main__":
    unittest.main()


