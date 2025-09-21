import asyncio
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import remind_bot as rb


# --------- Fakes for Telegram ---------
class FakeBot:
    def __init__(self) -> None:
        self.sent = []  # tuples (chat_id, text)

    async def send_message(self, chat_id: int, text: str):
        self.sent.append((chat_id, text))


class FakeApplication:
    def __init__(self) -> None:
        self.bot = FakeBot()


class FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.replies = []

    async def reply_text(self, text: str):
        self.replies.append(text)


class FakeActor:
    def __init__(self, _id: int):
        self.id = _id


class FakeUpdate:
    def __init__(self, chat_id: int, user_id: int, text: str):
        self.effective_chat = FakeActor(chat_id)
        self.effective_user = FakeActor(user_id)
        self.effective_message = FakeMessage(text)


class FakeContext:
    def __init__(self, args=None):
        self.args = args or []


# --------- Helpers ---------

def make_db():
    tmp = tempfile.NamedTemporaryFile(delete=False)
    tmp.close()
    return rb.ReminderDB(tmp.name)


def make_handlers(db: rb.ReminderDB, default_tz: str = "Europe/Berlin"):
    app = FakeApplication()
    sched = rb.ReminderScheduler(app, db)
    # start scheduler for tests that need get_job/remove_job
    sched.start()
    return app, sched, rb.BotHandlers(app, db, sched, default_tz)


class ParseTests(unittest.TestCase):
    def test_parse_duration_basic(self):
        delta, text = rb.parse_duration_prefix("10m вода")
        self.assertIsNotNone(delta)
        self.assertEqual(text, "вода")
        self.assertAlmostEqual(delta.total_seconds(), 600, delta=1)

    def test_parse_duration_slitny(self):
        delta, text = rb.parse_duration_prefix("1h30m кофе")
        self.assertIsNotNone(delta)
        self.assertEqual(text, "кофе")
        self.assertAlmostEqual(delta.total_seconds(), 5400, delta=1)

    def test_parse_duration_ru(self):
        delta, text = rb.parse_duration_prefix("через 2 ч 15 мин отчёт")
        self.assertIsNotNone(delta)
        self.assertEqual(text, "отчёт")
        self.assertAlmostEqual(delta.total_seconds(), (2*3600+15*60), delta=2)

    def test_parse_at_datetime(self):
        tz = rb.get_tz("Europe/Moscow")
        parsed = rb.parse_at_datetime("завтра 9:30 хлеб", tz)
        self.assertIsNotNone(parsed)
        self.assertGreater(parsed.when_utc, rb.now_utc())


class DBAndHandlersAsyncTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.db = make_db()
        self.app, self.sched, self.handlers = make_handlers(self.db, default_tz="Europe/Moscow")
        self.chat_id = 1001
        self.user_id = 5001

    async def asyncTearDown(self):
        try:
            self.sched.shutdown()
        except Exception:
            pass

    async def test_tz_show_and_set(self):
        # show
        upd = FakeUpdate(self.chat_id, self.user_id, "/tz")
        ctx = FakeContext()
        await self.handlers.cmd_tz(upd, ctx)
        self.assertTrue(any("Текущий часовой пояс" in r for r in upd.effective_message.replies))
        # set
        upd2 = FakeUpdate(self.chat_id, self.user_id, "/tz Europe/Berlin")
        ctx2 = FakeContext(["Europe/Berlin"])
        await self.handlers.cmd_tz(upd2, ctx2)
        self.assertIn("Europe/Berlin", "\n".join(upd2.effective_message.replies))
        tz = await self.db.get_user_tz(self.chat_id, self.user_id)
        self.assertEqual(tz, "Europe/Berlin")

    async def test_in_schedules_and_persists(self):
        upd = FakeUpdate(self.chat_id, self.user_id, "/in 1m тест")
        ctx = FakeContext()
        await self.handlers.cmd_in(upd, ctx)
        # DB has scheduled
        rows = await self.db.get_active_for_user(self.chat_id, self.user_id)
        self.assertEqual(len(rows), 1)
        rid = rows[0]["id"]
        # scheduler has job
        job = self.sched.scheduler.get_job(f"reminder:{rid}")
        self.assertIsNotNone(job)

    async def test_at_parses_and_persists(self):
        upd = FakeUpdate(self.chat_id, self.user_id, "/at завтра 09:30 купить хлеб")
        ctx = FakeContext()
        await self.handlers.cmd_at(upd, ctx)
        rows = await self.db.get_active_for_user(self.chat_id, self.user_id)
        self.assertEqual(len(rows), 1)
        txt = rows[0]["text"]
        self.assertNotIn("завтра", txt.lower())

    async def test_list_outputs(self):
        # prepare one reminder
        upd = FakeUpdate(self.chat_id, self.user_id, "/in 1m test")
        await self.handlers.cmd_in(upd, FakeContext())
        # list
        upd2 = FakeUpdate(self.chat_id, self.user_id, "/list")
        await self.handlers.cmd_list(upd2, FakeContext())
        out = "\n".join(upd2.effective_message.replies)
        self.assertIn("Активные напоминания", out)
        self.assertIn("TZ", out)

    async def test_cancel(self):
        upd = FakeUpdate(self.chat_id, self.user_id, "/in 1m cancelme")
        await self.handlers.cmd_in(upd, FakeContext())
        rows = await self.db.get_active_for_user(self.chat_id, self.user_id)
        rid = rows[0]["id"]
        upd2 = FakeUpdate(self.chat_id, self.user_id, f"/cancel {rid}")
        await self.handlers.cmd_cancel(upd2, FakeContext([str(rid)]))
        # job removed
        self.assertIsNone(self.sched.scheduler.get_job(f"reminder:{rid}"))
        # status canceled
        row = await self.db.get_by_id(rid)
        self.assertEqual(row["status"], "canceled")

    async def test_reload_sends_overdue_and_reschedules_future(self):
        # Create overdue
        past_utc = rb.now_utc() - timedelta(seconds=1)
        rid1 = await self.db.add_reminder(self.chat_id, self.user_id, "overdue", past_utc, "Europe/Moscow")
        # Create future
        fut_utc = rb.now_utc() + timedelta(minutes=2)
        rid2 = await self.db.add_reminder(self.chat_id, self.user_id, "future", fut_utc, "Europe/Moscow")
        # Reload
        await rb.reload_and_schedule(self.app, self.db, self.sched, "Europe/Moscow")
        # overdue sent immediately
        self.assertTrue(any("(Поздно)" in t for _, t in self.app.bot.sent))
        # scheduled job exists for future
        self.assertIsNotNone(self.sched.scheduler.get_job(f"reminder:{rid2}"))


if __name__ == "__main__":
    unittest.main()
