import unittest

from telegram import InlineKeyboardMarkup, ReplyKeyboardMarkup

# Импортируем remind_bot, чтобы инициализировались I18N bundles через set_bundles()
import remind_bot as rb  # noqa: F401
from keyboards import main_menu, inline_main_menu


class KeyboardLabelsTests(unittest.TestCase):
    def test_reply_keyboard_ru_emojis_and_hints(self):
        kb: ReplyKeyboardMarkup = main_menu("ru")
        rows = kb.keyboard
        # Первая строка: /start, /list, /watch, /help
        self.assertTrue(rows[0][0].text.startswith("/start "))
        self.assertIn("/list ", rows[0][1].text)
        self.assertIn("/watch ", rows[0][2].text)
        self.assertIn("/help ", rows[0][3].text)
        # Вторая строка: /at (чч:мм) ⏰ и /in (мин) ⌛
        self.assertIn("/at (чч:мм)", rows[1][0].text)
        self.assertTrue(rows[1][0].text.endswith("⏰"))
        self.assertIn("/in (мин)", rows[1][1].text)
        self.assertTrue(rows[1][1].text.endswith("⌛"))
        # Третья /menu, четвертая /tz, /lang
        self.assertTrue(rows[2][0].text.startswith("/menu "))
        self.assertTrue(rows[3][0].text.startswith("/tz "))
        self.assertTrue(rows[3][1].text.startswith("/lang "))

    def test_reply_keyboard_en_hints(self):
        kb: ReplyKeyboardMarkup = main_menu("en")
        rows = kb.keyboard
        self.assertIn("/at (hh:mm)", rows[1][0].text)
        self.assertIn("/in (min)", rows[1][1].text)

    def test_reply_keyboard_th_hints(self):
        kb: ReplyKeyboardMarkup = main_menu("th")
        rows = kb.keyboard
        # Указанные подсказки из hint_at/hint_in
        self.assertIn("/at (ชม:นาที)", rows[1][0].text)
        self.assertIn("/in (นาที)", rows[1][1].text)

    def test_inline_main_menu_emojis(self):
        mk: InlineKeyboardMarkup = inline_main_menu("ru")
        rows = mk.inline_keyboard
        # 1-я строка: 🗒️, ⏱️
        self.assertTrue(rows[0][0].text.startswith("🗒️ "))
        self.assertTrue(rows[0][1].text.startswith("⏱️ "))
        # 2-я строка: ❌
        self.assertTrue(rows[1][0].text.startswith("❌ "))
        # 3-я строка: 🌐
        self.assertTrue(rows[2][0].text.startswith("🌐 "))
        # 4-я строка: 🔔
        self.assertTrue(rows[3][0].text.startswith("🔔 "))
        # 5-я строка: ⏰ /at ..., ⌛ /in ...
        self.assertTrue(rows[4][0].text.startswith("⏰ /at "))
        self.assertTrue(rows[4][1].text.startswith("⌛ /in "))


class CommandEmojiHintTests(unittest.IsolatedAsyncioTestCase):
    class FakeBot:
        def __init__(self) -> None:
            self.sent = []

        async def send_message(self, chat_id: int, text: str, reply_markup=None, disable_notification=False):
            self.sent.append((chat_id, text, reply_markup, disable_notification))

    class FakeApplication:
        def __init__(self) -> None:
            self.bot = CommandEmojiHintTests.FakeBot()
            from unittest.mock import MagicMock
            self.job_queue = MagicMock()

    class FakeMessage:
        def __init__(self, text: str, message_id: int = 1):
            self.text = text
            self.message_id = message_id
            self.replies = []
            self.reply_markups = []

        async def reply_text(self, text: str, reply_markup=None, disable_notification=False):
            self.replies.append(text)
            self.reply_markups.append(reply_markup)

    class FakeActor:
        def __init__(self, _id: int, username: str = "testuser"):
            self.id = _id
            self.username = username

    class FakeUpdate:
        def __init__(self, chat_id: int, user_id: int, text: str, message_id: int = 1):
            self.effective_chat = CommandEmojiHintTests.FakeActor(chat_id)
            self.effective_user = CommandEmojiHintTests.FakeActor(user_id)
            self.effective_message = CommandEmojiHintTests.FakeMessage(text, message_id)

    class FakeContext:
        def __init__(self, args=None, user_data=None):
            from unittest.mock import MagicMock
            self.args = args or []
            self.user_data = user_data or {}
            self.job = MagicMock()

    async def asyncSetUp(self):
        import tempfile
        self.db = rb.ReminderDB(tempfile.NamedTemporaryFile(delete=False).name)
        self.app = self.FakeApplication()
        self.sched = rb.ReminderScheduler(self.app, self.db)
        self.sched.start()
        self.handlers = rb.BotHandlers(self.app, self.db, self.sched, "Europe/Moscow")
        self.chat_id = 111
        self.user_id = 222

    async def asyncTearDown(self):
        try:
            self.sched.shutdown()
        except Exception:
            pass

    async def test_tz_with_emoji_arg_prompts_city(self):
        upd = self.FakeUpdate(self.chat_id, self.user_id, "/tz 🌍")
        ctx = self.FakeContext(args=["🌍"])
        await self.handlers.cmd_tz(upd, ctx)
        out = "\n".join(upd.effective_message.replies)
        # Теперь просим локальное время
        self.assertTrue(("Введите ваше локальное время" in out) or ("Enter your local time" in out))

    async def test_back_navigation_multi_level(self):
        # Проверим стековую навигацию публичной утилитой apply_back_navigation
        import remind_bot as rb
        stack = ["main", "at_date", "at_hour", "at_minute"]
        user_data = {"pending_at_hhmm": "10:10"}
        s1 = rb.apply_back_navigation(stack, user_data)
        self.assertEqual(s1, "at_hour")
        self.assertNotIn("pending_at_hhmm", user_data)
        s2 = rb.apply_back_navigation(stack, user_data)
        self.assertEqual(s2, "at_date")
        s3 = rb.apply_back_navigation(stack, user_data)
        self.assertEqual(s3, "main")


    async def test_lang_with_emoji_arg_shows_menu(self):
        upd = self.FakeUpdate(self.chat_id, self.user_id, "/lang 🌐")
        ctx = self.FakeContext(args=["🌐"])
        await self.handlers.cmd_lang(upd, ctx)
        out = "\n".join(upd.effective_message.replies)
        # Должно отобразить меню выбора языка, а не ошибку парсинга аргумента
        self.assertIn("Выберите язык", out)

    async def test_in_hint_with_emoji_opens_minutes_picker(self):
        # RU по умолчанию
        upd = self.FakeUpdate(self.chat_id, self.user_id, "/in (мин) ⌛")
        ctx = self.FakeContext()
        await self.handlers.cmd_in(upd, ctx)
        out = "\n".join(upd.effective_message.replies)
        self.assertIn("Через сколько минут", out)
        self.assertIsInstance(upd.effective_message.reply_markups[-1], InlineKeyboardMarkup)

    async def test_at_hint_with_emoji_opens_date_picker(self):
        upd = self.FakeUpdate(self.chat_id, self.user_id, "/at (чч:мм) ⏰")
        ctx = self.FakeContext()
        await self.handlers.cmd_at(upd, ctx)
        out = "\n".join(upd.effective_message.replies)
        self.assertIn("Выберите дату", out)
        self.assertIsInstance(upd.effective_message.reply_markups[-1], InlineKeyboardMarkup)


if __name__ == "__main__":
    unittest.main()


