import types
import unittest
from datetime import datetime, timezone

from remind_bot import ReminderDB, ReminderScheduler


class DummyBot:
    def __init__(self):
        self.calls = []

    async def send_message(self, **kwargs):
        self.calls.append(kwargs)


class DummyDB:
    def __init__(self):
        self._row = {
            "id": 1,
            "chat_id": 111,
            "user_id": 222,
            "text": "ping",
            "due_at_utc": datetime.now(timezone.utc).isoformat(),
            "status": "scheduled",
        }
        self.sound_on = True

    async def get_by_id(self, rid: int):
        return self._row if rid == 1 else None

    async def get_user_sound(self, chat_id: int, user_id: int) -> bool:
        return self.sound_on

    async def get_user_lang(self, chat_id: int, user_id: int):
        return "ru"


class DummyScheduler:
    def __init__(self):
        self.jobs = []

    def add_job(self, func, trigger=None, id=None, kwargs=None, **kw):
        self.jobs.append((func, kwargs))

    def start(self):
        pass

    def shutdown(self, wait=False):
        pass


class SoundTests(unittest.IsolatedAsyncioTestCase):
    async def test_db_sound_default_and_set(self):
        db = ReminderDB(":memory:")
        # default true
        self.assertTrue(await db.get_user_sound(1, 2))
        # set false
        await db.set_user_sound(1, 2, False)
        self.assertFalse(await db.get_user_sound(1, 2))
        # set true
        await db.set_user_sound(1, 2, True)
        self.assertTrue(await db.get_user_sound(1, 2))

    async def test_scheduler_uses_disable_notification(self):
        app = types.SimpleNamespace(bot=DummyBot())
        db = DummyDB()
        rs = ReminderScheduler(app, db)  # type: ignore
        rs.scheduler = DummyScheduler()

        # Case 1: sound_on True -> disable_notification False/absent
        db.sound_on = True
        await rs._deliver_job(1, 111, "hello")
        self.assertTrue(any(k.get("disable_notification") in (None, False) for k in (c for c in [call for call in app.bot.calls])))

        # Case 2: sound_on False -> disable_notification True
        app.bot.calls.clear()
        db.sound_on = False
        await rs._deliver_job(1, 111, "hello")
        self.assertTrue(any(k.get("disable_notification") is True for k in app.bot.calls))


if __name__ == "__main__":
    unittest.main()


