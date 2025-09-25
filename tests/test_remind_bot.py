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

    async def send_message(self, chat_id: int, text: str, **kwargs):
        self.sent.append((chat_id, text))


class FakeApplication:
    def __init__(self) -> None:
        self.bot = FakeBot()


class FakeMessage:
    def __init__(self, text: str):
        self.text = text
        self.replies = []

    async def reply_text(self, text: str, **kwargs):
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
        self.user_data = {}


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

    def test_parse_th_duration_and_datetime(self):
        # Thai duration: "2 ชม 15 นาที"
        delta, text = rb.parse_duration_prefix("2 ชม 15 นาที งาน")
        self.assertIsNotNone(delta)
        self.assertEqual(text, "งาน")
        self.assertAlmostEqual(delta.total_seconds(), (2*3600 + 15*60), delta=2)
        # Thai datetime: "พรุ่งนี้ 9:30"
        tz = rb.get_tz("Asia/Bangkok")
        parsed = rb.parse_at_datetime("พรุ่งนี้ 9:30 ทดสอบ", tz)
        self.assertIsNotNone(parsed)


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
        # prompt local time (new behavior)
        upd = FakeUpdate(self.chat_id, self.user_id, "/tz")
        ctx = FakeContext()
        await self.handlers.cmd_tz(upd, ctx)
        prompt = "\n".join(upd.effective_message.replies)
        self.assertTrue(("Введите ваше локальное время" in prompt) or ("Enter your local time" in prompt))
        # set by full TZ name still works
        upd2 = FakeUpdate(self.chat_id, self.user_id, "/tz Europe/Berlin")
        ctx2 = FakeContext(["Europe/Berlin"])
        await self.handlers.cmd_tz(upd2, ctx2)
        self.assertIn("Europe/Berlin", "\n".join(upd2.effective_message.replies))
        tz = await self.db.get_user_tz(self.chat_id, self.user_id)
        self.assertEqual(tz, "Europe/Berlin")

    async def test_tz_city_ru_th_en(self):
        # RU city
        upd_ru = FakeUpdate(self.chat_id, self.user_id, "/tz Москва")
        await self.handlers.cmd_tz(upd_ru, FakeContext(["Москва"]))
        self.assertIn("Europe/Moscow", "\n".join(upd_ru.effective_message.replies))
        # EN city
        upd_en = FakeUpdate(self.chat_id, self.user_id, "/tz Bangkok")
        await self.handlers.cmd_tz(upd_en, FakeContext(["Bangkok"]))
        self.assertIn("Asia/Bangkok", "\n".join(upd_en.effective_message.replies))
        # TH city
        upd_th = FakeUpdate(self.chat_id, self.user_id, "/tz กรุงเทพฯ")
        await self.handlers.cmd_tz(upd_th, FakeContext(["กรุงเทพฯ"]))
        self.assertIn("Asia/Bangkok", "\n".join(upd_th.effective_message.replies))

    async def test_tz_command_with_time_input(self):
        # prompt, then send time via arg
        upd = FakeUpdate(self.chat_id, self.user_id, "/tz 09:30")
        ctx = FakeContext(["09:30"])
        await self.handlers.cmd_tz(upd, ctx)
        out = "\n".join(upd.effective_message.replies)
        # Must set UTC±HH:MM
        self.assertRegex(out, r"UTC[+-]\d{2}:\d{2}")

    async def test_lang_set_en_th_and_help(self):
        handlers = self.handlers
        # set EN
        upd_en = FakeUpdate(self.chat_id, self.user_id, "/lang en")
        await handlers.cmd_lang(upd_en, FakeContext(["en"]))
        lang = await self.db.get_user_lang(self.chat_id, self.user_id)
        self.assertEqual(lang, "en")
        # set TH
        upd_th = FakeUpdate(self.chat_id, self.user_id, "/lang th")
        await handlers.cmd_lang(upd_th, FakeContext(["th"]))
        lang2 = await self.db.get_user_lang(self.chat_id, self.user_id)
        self.assertEqual(lang2, "th")
        # /help behaves like /start (uses same handler)
        upd_help = FakeUpdate(self.chat_id, self.user_id, "/help")
        await handlers.start(upd_help, FakeContext())
        out = "\n".join(upd_help.effective_message.replies)
        self.assertIn("/lang", out)
        self.assertIn("/tz", out)

    async def test_in_with_thai_units(self):
        # set Thai first
        await self.handlers.cmd_lang(FakeUpdate(self.chat_id, self.user_id, "/lang th"), FakeContext(["th"]))
        upd = FakeUpdate(self.chat_id, self.user_id, "/in 1 ชม 30 นาที ทดสอบ")
        await self.handlers.cmd_in(upd, FakeContext())
        rows = await self.db.get_active_for_user(self.chat_id, self.user_id)
        self.assertEqual(len(rows), 1)
        # response contains confirmation
        resp = "\n".join(upd.effective_message.replies)
        self.assertTrue(resp)

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

    async def test_watch_from_reply_keyboard_without_id(self):
        # prepare one reminder
        upd = FakeUpdate(self.chat_id, self.user_id, "/in 1m watchme")
        await self.handlers.cmd_in(upd, FakeContext())
        # press reply keyboard /watch with emoji suffix
        upd2 = FakeUpdate(self.chat_id, self.user_id, "/watch ⏱️")
        await self.handlers.cmd_watch(upd2, FakeContext())
        out = "\n".join(upd2.effective_message.replies)
        # should show choose_watch text
        self.assertTrue(("Выберите" in out) or ("Choose" in out))

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
        # overdue sent immediately with localized late_prefix
        late_prefix = rb.t("ru", "late_prefix")
        self.assertTrue(any(late_prefix in t for _, t in self.app.bot.sent))
        # scheduled job exists for future
        self.assertIsNotNone(self.sched.scheduler.get_job(f"reminder:{rid2}"))


if __name__ == "__main__":
    unittest.main()
