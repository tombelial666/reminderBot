import unittest
from datetime import timedelta

import remind_bot as rb
import logging


class FakeBot:
    def __init__(self) -> None:
        self.sent = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        self.sent.append((chat_id, text))


class Msg:
    def __init__(self, text: str):
        self.text = text
        self.replies = []

    async def reply_text(self, text: str, **kwargs):
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

    async def test_audit_flow_commands(self):
        # Проверяем, что audit_event не падает и логгер настроен
        # (эмулируем команды — проверяем, что обработчики выполняются без исключений)
        handlers = rb.BotHandlers(self.app, self.db, self.sched, "Europe/Moscow")
        upd_start = type(
            "Upd",
            (),
            {
                "effective_chat": type("A", (), {"id": self.chat_id})(),
                "effective_user": type("A", (), {"id": self.user_id})(),
                "effective_message": Msg("/start"),
            },
        )()
        await handlers.start(upd_start, type("Ctx", (), {})())
        upd_menu = type(
            "Upd",
            (),
            {
                "effective_chat": type("A", (), {"id": self.chat_id})(),
                "effective_user": type("A", (), {"id": self.user_id})(),
                "effective_message": Msg("/menu"),
            },
        )()
        await handlers.cmd_menu(upd_menu, type("Ctx", (), {})())
        upd_in = type(
            "Upd",
            (),
            {
                "effective_chat": type("A", (), {"id": self.chat_id})(),
                "effective_user": type("A", (), {"id": self.user_id})(),
                "effective_message": Msg("/in 1m test"),
            },
        )()
        await handlers.cmd_in(upd_in, type("Ctx", (), {})())
        upd_tz = type(
            "Upd",
            (),
            {
                "effective_chat": type("A", (), {"id": self.chat_id})(),
                "effective_user": type("A", (), {"id": self.user_id})(),
                "effective_message": Msg("/tz 09:30"),
            },
        )()
        await handlers.cmd_tz(upd_tz, type("Ctx", (), {"args": ["09:30"]})())

    async def test_audit_writes_to_file(self):
        # Перенастроим audit_logger на временный файл и проверим записи
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp_path = tmp.name
        tmp.close()
        # очистим хендлеры и добавим свой
        for h in list(rb.audit_logger.handlers):
            rb.audit_logger.removeHandler(h)
        fh = logging.FileHandler(tmp_path, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter("%(message)s"))
        rb.audit_logger.addHandler(fh)
        rb.audit_logger.setLevel(logging.INFO)

        # вызовем несколько команд, которые пишут аудит
        handlers = rb.BotHandlers(self.app, self.db, self.sched, "Europe/Moscow")
        upd_start = type("Upd", (), {"effective_chat": type("A", (), {"id": self.chat_id})(), "effective_user": type("A", (), {"id": self.user_id})(), "effective_message": Msg("/start")})()
        await handlers.start(upd_start, type("Ctx", (), {})())
        upd_menu = type("Upd", (), {"effective_chat": type("A", (), {"id": self.chat_id})(), "effective_user": type("A", (), {"id": self.user_id})(), "effective_message": Msg("/menu")})()
        await handlers.cmd_menu(upd_menu, type("Ctx", (), {})())

        # убедимся, что файл непустой и содержит JSON с action
        with open(tmp_path, "r", encoding="utf-8") as f:
            data = f.read()
        self.assertTrue(len(data) > 0)
        self.assertIn('"action"', data)

        try:
            os.remove(tmp_path)
        except Exception:
            pass

    async def test_audit_at_command_logged(self):
        # Перенастраиваем audit_logger на временный файл
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(delete=False)
        tmp_path = tmp.name
        tmp.close()
        for h in list(rb.audit_logger.handlers):
            rb.audit_logger.removeHandler(h)
        fh = logging.FileHandler(tmp_path, encoding="utf-8")
        fh.setLevel(logging.INFO)
        fh.setFormatter(logging.Formatter("%(message)s"))
        rb.audit_logger.addHandler(fh)
        rb.audit_logger.setLevel(logging.INFO)

        # Выполним /at
        handlers = rb.BotHandlers(self.app, self.db, self.sched, "Europe/Moscow")
        upd = type(
            "Upd",
            (),
            {
                "effective_chat": type("A", (), {"id": self.chat_id})(),
                "effective_user": type("A", (), {"id": self.user_id})(),
                "effective_message": Msg("/at завтра 09:30 купить хлеб"),
            },
        )()
        await handlers.cmd_at(upd, type("Ctx", (), {})())

        # Проверим, что в файле появился action create:reminder_at
        with open(tmp_path, "r", encoding="utf-8") as f:
            content = f.read()
        self.assertIn("create:reminder_at", content)
        try:
            os.remove(tmp_path)
        except Exception:
            pass

    async def test_callbacks_audit_multi_level(self):
        # Проверим, что callback-и не падают и audit вызывается (проверим через отсутствие исключений)
        handlers = rb.BotHandlers(self.app, self.db, self.sched, "Europe/Moscow")
        # Упростим: напрямую вызовем on_callback через Application handler недоступен в фейках,
        # поэтому проверим сам audit_event — он доступен, и функция не должна падать при JSON-сереализации
        rb.audit_event(self.chat_id, self.user_id, "cb:open:at")
        rb.audit_event(self.chat_id, self.user_id, "cb:at_date", date="2025-12-31")
        rb.audit_event(self.chat_id, self.user_id, "cb:at_hh", hh="09")
        rb.audit_event(self.chat_id, self.user_id, "cb:at_set", hh="09", mm="30")


if __name__ == "__main__":
    unittest.main()
