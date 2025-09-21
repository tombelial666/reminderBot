import unittest
from datetime import timedelta

import remind_bot as rb


class FakeBot:
    def __init__(self) -> None:
        self.sent = []

    async def send_message(self, chat_id: int, text: str):
        self.sent.append((chat_id, text))


class Msg:
    def __init__(self, text: str):
        self.text = text
        self.replies = []

    async def reply_text(self, text: str):
        self.replies.append(text)


class DSTAndLoadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        import tempfile
        self.db = rb.ReminderDB(tempfile.NamedTemporaryFile(delete=False).name)
        self.app = type("App", (), {"bot": FakeBot()})()
        self.sched = rb.ReminderScheduler(self.app, self.db)
        self.sched.start()
        self.chat_id = 2001
        self.user_id = 6001

    async def asyncTearDown(self):
        try:
            self.sched.shutdown()
        except Exception:
            pass

    async def test_dst_listing_label(self):
        handlers = rb.BotHandlers(self.app, self.db, self.sched, "Europe/Berlin")
        upd = type(
            "Upd",
            (),
            {
                "effective_chat": type("A", (), {"id": self.chat_id})(),
                "effective_user": type("A", (), {"id": self.user_id})(),
                "effective_message": Msg("/in 2m dst"),
            },
        )()
        await handlers.cmd_in(upd, type("Ctx", (), {})())
        upd2 = type(
            "Upd",
            (),
            {
                "effective_chat": type("A", (), {"id": self.chat_id})(),
                "effective_user": type("A", (), {"id": self.user_id})(),
                "effective_message": Msg("/list"),
            },
        )()
        await handlers.cmd_list(upd2, type("Ctx", (), {})())
        out = "\n".join(upd2.effective_message.replies)
        self.assertIn("TZ Europe/Berlin", out)
        self.assertIn("Активные напоминания", out)

    async def test_light_load_many_jobs(self):
        handlers = rb.BotHandlers(self.app, self.db, self.sched, "Europe/Moscow")
        for i in range(50):
            upd = type(
                "Upd",
                (),
                {
                    "effective_chat": type("A", (), {"id": self.chat_id})(),
                    "effective_user": type("A", (), {"id": self.user_id})(),
                    "effective_message": Msg(f"/in 1m job{i}"),
                },
            )()
            await handlers.cmd_in(upd, type("Ctx", (), {})())
        rows = await self.db.get_active_for_user(self.chat_id, self.user_id, limit=100)
        self.assertGreaterEqual(len(rows), 50)
        count = 0
        for r in rows:
            if self.sched.scheduler.get_job(f"reminder:{r['id']}") is not None:
                count += 1
        self.assertGreaterEqual(count, 50)


if __name__ == "__main__":
    unittest.main()
