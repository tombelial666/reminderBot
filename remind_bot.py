import asyncio
import logging
import os
import signal
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from dateparser import parse as dp_parse
from dateparser.search import search_dates
from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import (Application, ApplicationBuilder, CommandHandler,
                          ContextTypes)

try:
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # Python <3.9 fallback (not expected)


# =============================
# Конфиг и логирование
# =============================

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TOKEN_FILE = os.getenv("TELEGRAM_BOT_TOKEN_FILE", ".telegram_token")
if not BOT_TOKEN:
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, "r", encoding="utf-8") as _tf:
                BOT_TOKEN = _tf.read().strip()
    except Exception:
        pass
DEFAULT_TZ = os.getenv("REMIND_BOT_TZ", "Asia/Bangkok")
DB_PATH = os.getenv("REMIND_DB_PATH", "reminders.db")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("reminder-bot")


# =============================
# Утилиты времени
# =============================

@dataclass
class ParsedAt:
    when_utc: datetime
    source_text: str


def get_tz(tz_name: str) -> timezone:
    if ZoneInfo is None:
        return timezone.utc
    try:
        return ZoneInfo(tz_name)
    except Exception:
        logger.warning("Не удалось применить TZ %s, использую UTC", tz_name)
        return timezone.utc


def is_valid_tz(tz_name: str) -> bool:
    try:
        _ = get_tz(tz_name)
        # Если вернулся UTC из-за ошибки — проверить явно
        if ZoneInfo is None:
            return tz_name.lower() in ("utc", "gmt")
        try:
            ZoneInfo(tz_name)
            return True
        except Exception:
            return False
    except Exception:
        return False


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def clamp_future(dt: datetime) -> Optional[datetime]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if dt < now_utc():
        return None
    return dt


def format_timedelta_brief(delta: timedelta) -> str:
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        total_seconds = -total_seconds
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts: List[str] = []
    if days:
        parts.append(f"{days}д")
    if hours:
        parts.append(f"{hours}ч")
    if minutes:
        parts.append(f"{minutes}м")
    if not parts and seconds:
        parts.append(f"{seconds}с")
    return " ".join(parts) or "0с"


def parse_duration_prefix(text: str) -> Tuple[Optional[timedelta], str]:
    """Парсит длительность в начале строки (RU/EN). Поддерживает варианты:
    - "in 10m buy" / "через 10 минут купить"
    - "1h30m сделать" / "2 ч 15 мин ..."
    Возвращает (timedelta | None, остаток_строки)
    """
    import re

    s = text.strip()
    if not s:
        return None, ""

    # Удаляем ведущие маркеры
    s = re.sub(r"^(in|через)\s+", "", s, flags=re.IGNORECASE)

    # Разрешенные соединители между кусками длительности
    connectors = {"и", "and", ","}

    tokens = s.split()
    consumed = []

    def is_duration_token(tok: str) -> Optional[Tuple[int, str]]:
        m = re.fullmatch(r"(?i)(\d+)\s*([a-zа-яё]+)", tok)
        if not m:
            # также поддержим слитные, типа 1h30m как два токена не распознаются — разрежем вручную
            return None
        return int(m.group(1)), m.group(2).lower()

    # Попробуем также быстрый матч в начале строки: цепочка (num+unit)
    prefix = []
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        low = tok.lower()
        if low in connectors:
            consumed.append(tok)
            idx += 1
            continue
        parsed = is_duration_token(tok)
        if parsed is None:
            break
        consumed.append(tok)
        prefix.append(parsed)
        idx += 1

    # Если не нашли по токенам, попробуем слитные шаблоны в начале строки
    if not prefix:
        miter = re.finditer(r"(?i)^(?:\s*(?:in|через)\s*)?(\s*\d+\s*[a-zа-яё]+)+", s)
        try:
            m0 = next(miter)
        except StopIteration:
            return None, text.strip()
        dur_str = m0.group(0)
        rest = s[len(dur_str):].lstrip()
        parts = re.findall(r"(?i)(\d+)\s*([a-zа-яё]+)", dur_str)
        if not parts:
            return None, text.strip()
        prefix = [(int(v), u.lower()) for v, u in parts]
        remainder = rest
    else:
        remainder = " ".join(tokens[idx:]).strip()

    # Маппинг единиц
    unit_map = {
        # seconds
        "s": "seconds", "sec": "seconds", "secs": "seconds", "second": "seconds", "seconds": "seconds",
        "с": "seconds", "сек": "seconds", "сек": "seconds", "секунда": "seconds", "секунды": "seconds", "секунд": "seconds",
        # minutes
        "m": "minutes", "min": "minutes", "mins": "minutes", "minute": "minutes", "minutes": "minutes",
        "м": "minutes", "мин": "minutes", "минута": "minutes", "минуты": "minutes", "минут": "minutes",
        # hours
        "h": "hours", "hr": "hours", "hour": "hours", "hours": "hours",
        "ч": "hours", "час": "hours", "часа": "hours", "часов": "hours",
        # days
        "d": "days", "day": "days", "days": "days",
        "д": "days", "день": "days", "дня": "days", "дней": "days",
        # weeks
        "w": "weeks", "wk": "weeks", "week": "weeks", "weeks": "weeks",
        "н": "weeks", "нед": "weeks", "неделя": "weeks", "недели": "weeks", "недель": "weeks",
        # months (approximate)
        "mo": "days", "mon": "days", "month": "days", "months": "days",
        "мес": "days", "месяц": "days", "месяца": "days", "месяцев": "days",
        # years (approximate)
        "y": "days", "yr": "days", "year": "days", "years": "days",
        "г": "days", "год": "days", "года": "days", "лет": "days",
    }
    total = timedelta(0)
    for value, unit in prefix:
        key = unit
        if key not in unit_map:
            break
        kind = unit_map[key]
        if kind == "seconds":
            total += timedelta(seconds=value)
        elif kind == "minutes":
            total += timedelta(minutes=value)
        elif kind == "hours":
            total += timedelta(hours=value)
        elif kind == "days":
            # приблизительная конверсия: 1 месяц = 30 дн, 1 год = 365 дн
            if unit in {"mo", "mon", "month", "months", "мес", "месяц", "месяца", "месяцев"}:
                total += timedelta(days=30 * value)
            elif unit in {"y", "yr", "year", "years", "г", "год", "года", "лет"}:
                total += timedelta(days=365 * value)
            else:
                total += timedelta(days=value)
    if total.total_seconds() == 0:
        return None, text.strip()
    return total, remainder


def parse_at_datetime(text: str, tz: timezone) -> Optional[ParsedAt]:
    """Парсит дату/время и возвращает UTC."""
    base = datetime.now(tz)
    settings = {
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": base,
        "RETURN_AS_TIMEZONE_AWARE": True,
    }
    # Сначала попробуем извлечь дату внутри строки, чтобы отделить текст
    try:
        found = search_dates(text, languages=["ru", "en"], settings=settings)
    except Exception:
        found = None
    dt = None
    matched = None
    if found:
        # Возьмём первый осмысленный
        for match_text, match_dt in found:
            if match_dt is None:
                continue
            matched = match_text
            dt = match_dt
            break
    if dt is None:
        # Попробуем распарсить всю строку
        dt = dp_parse(text, languages=["ru", "en"], settings=settings)
        matched = text if dt else None
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    dt_local = dt.astimezone(tz)
    dt_utc = dt_local.astimezone(timezone.utc)
    return ParsedAt(when_utc=dt_utc, source_text=matched or "")


# =============================
# Слой БД (sqlite)
# =============================

class ReminderDB:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                due_at_utc TEXT NOT NULL,
                tz TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at_utc TEXT NOT NULL
            );
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reminders_status_due ON reminders(status, due_at_utc);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id);")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_reminders_chat ON reminders(chat_id);")
        # User preferences: timezone per chat+user
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_prefs (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                tz TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                PRIMARY KEY (chat_id, user_id)
            );
            """
        )
        self.conn.commit()

    async def add_reminder(self, chat_id: int, user_id: int, text: str, due_at_utc: datetime, tz_name: str) -> int:
        def _op():
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO reminders(chat_id, user_id, text, due_at_utc, tz, status, created_at_utc) VALUES (?, ?, ?, ?, ?, 'scheduled', ?)",
                (chat_id, user_id, text, due_at_utc.isoformat(), tz_name, now_utc().isoformat()),
            )
            self.conn.commit()
            return cur.lastrowid
        return await asyncio.to_thread(_op)

    async def mark_sent(self, reminder_id: int) -> None:
        def _op():
            cur = self.conn.cursor()
            cur.execute("UPDATE reminders SET status='sent' WHERE id=?", (reminder_id,))
            self.conn.commit()
        await asyncio.to_thread(_op)

    async def cancel(self, reminder_id: int, user_id: int) -> bool:
        def _op() -> bool:
            cur = self.conn.cursor()
            cur.execute("UPDATE reminders SET status='canceled' WHERE id=? AND user_id=? AND status='scheduled'", (reminder_id, user_id))
            self.conn.commit()
            return cur.rowcount > 0
        return await asyncio.to_thread(_op)

    async def get_active_for_user(self, chat_id: int, user_id: int, limit: int = 50) -> List[sqlite3.Row]:
        def _op() -> List[sqlite3.Row]:
            cur = self.conn.cursor()
            cur.execute(
                "SELECT * FROM reminders WHERE chat_id=? AND user_id=? AND status='scheduled' ORDER BY due_at_utc ASC LIMIT ?",
                (chat_id, user_id, limit),
            )
            return cur.fetchall()
        return await asyncio.to_thread(_op)

    async def get_by_id(self, reminder_id: int) -> Optional[sqlite3.Row]:
        def _op() -> Optional[sqlite3.Row]:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM reminders WHERE id=?", (reminder_id,))
            return cur.fetchone()
        return await asyncio.to_thread(_op)

    async def load_scheduled(self) -> List[sqlite3.Row]:
        def _op() -> List[sqlite3.Row]:
            cur = self.conn.cursor()
            cur.execute("SELECT * FROM reminders WHERE status='scheduled'")
            return cur.fetchall()
        return await asyncio.to_thread(_op)

    async def get_user_tz(self, chat_id: int, user_id: int) -> Optional[str]:
        def _op() -> Optional[str]:
            cur = self.conn.cursor()
            cur.execute("SELECT tz FROM user_prefs WHERE chat_id=? AND user_id=?", (chat_id, user_id))
            row = cur.fetchone()
            return row["tz"] if row else None
        return await asyncio.to_thread(_op)

    async def set_user_tz(self, chat_id: int, user_id: int, tz_name: str) -> None:
        def _op() -> None:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO user_prefs(chat_id, user_id, tz, updated_at_utc) VALUES (?, ?, ?, ?) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET tz=excluded.tz, updated_at_utc=excluded.updated_at_utc",
                (chat_id, user_id, tz_name, now_utc().isoformat()),
            )
            self.conn.commit()
        await asyncio.to_thread(_op)


# =============================
# Планировщик (APScheduler)
# =============================

class ReminderScheduler:
    def __init__(self, app: Application, db: ReminderDB) -> None:
        self.app = app
        self.db = db
        self.scheduler = AsyncIOScheduler(timezone=timezone.utc)
        self.started = False

    def start(self) -> None:
        if not self.started:
            self.scheduler.start()
            self.started = True
            logger.info("APScheduler started")

    def shutdown(self) -> None:
        if self.started:
            self.scheduler.shutdown(wait=False)
            self.started = False
            logger.info("APScheduler stopped")

    def schedule_reminder(self, reminder_id: int, chat_id: int, text: str, when_utc: datetime) -> None:
        # Удалим существующую джобу с тем же id, если есть
        job_id = f"reminder:{reminder_id}"
        try:
            self.scheduler.remove_job(job_id)
        except Exception:
            pass
        trigger = DateTrigger(run_date=when_utc)
        self.scheduler.add_job(
            self._deliver_job,
            trigger=trigger,
            id=job_id,
            kwargs={"reminder_id": reminder_id, "chat_id": chat_id, "text": text},
            misfire_grace_time=60 * 60 * 24,  # 24h grace
            coalesce=True,
            max_instances=5,
        )
        logger.info("Scheduled reminder id=%s at %s UTC", reminder_id, when_utc.isoformat())

    async def _deliver_job(self, reminder_id: int, chat_id: int, text: str) -> None:
        try:
            await self.app.bot.send_message(chat_id=chat_id, text=text)
        except Exception:
            logger.exception("Не удалось отправить сообщение для reminder_id=%s", reminder_id)
        try:
            await self.db.mark_sent(reminder_id)
        except Exception:
            logger.exception("Не удалось отметить как отправлен reminder_id=%s", reminder_id)


# =============================
# Команды бота
# =============================

class BotHandlers:
    def __init__(self, app: Application, db: ReminderDB, sched: ReminderScheduler, tz_name: str) -> None:
        self.app = app
        self.db = db
        self.sched = sched
        self.default_tz_name = tz_name

    async def _get_user_tz(self, chat_id: int, user_id: int) -> Tuple[str, timezone]:
        tz_name = await self.db.get_user_tz(chat_id, user_id)
        if not tz_name:
            tz_name = self.default_tz_name
        return tz_name, get_tz(tz_name)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            chat_id = update.effective_chat.id
            user_id = update.effective_user.id
            tz_name, _ = await self._get_user_tz(chat_id, user_id)
            tz_info = f"Текущий часовой пояс: {tz_name} (по умолчанию: {self.default_tz_name})"
            msg = (
                "Привет! Я бот-напоминальщик.\n\n"
                "Команды:\n"
                "/in <длительность> <текст> — через сколько напомнить.\n"
                "Напр.: /in 10m выпить воду; /in 2 ч 15 мин сделать отчёт.\n\n"
                "/at <дата/время> <текст> — напомнить в момент.\n"
                "Напр.: /at завтра 9:30 купить хлеб; /at 2025-12-31 23:00 поздравить.\n\n"
                "/list — показать активные напоминания.\n"
                "/cancel <id> — отменить по ID.\n"
                "/tz [Region/City] — показать или установить часовой пояс.\n\n"
                f"{tz_info}"
            )
            await update.effective_message.reply_text(msg)
        except Exception:
            logger.exception("Ошибка в /start")

    async def cmd_tz(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        arg = None
        if context.args:
            arg = " ".join(context.args).strip()
        try:
            if not arg:
                tz_name, _ = await self._get_user_tz(chat_id, user_id)
                await msg.reply_text(
                    "Текущий часовой пояс: " + tz_name + "\n" +
                    "Установить: /tz Region/City (напр., Europe/Moscow)"
                )
                return
            candidate = arg
            if not is_valid_tz(candidate):
                await msg.reply_text("Некорректный часовой пояс. Пример: Europe/Moscow")
                return
            await self.db.set_user_tz(chat_id, user_id, candidate)
            await msg.reply_text(f"Часовой пояс установлен: {candidate}")
        except Exception:
            logger.exception("Ошибка в /tz")
            await msg.reply_text("Произошла ошибка при обработке /tz")

    async def cmd_in(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        args_text = (msg.text or "").split(maxsplit=1)
        text_tail = args_text[1] if len(args_text) > 1 else ""
        try:
            tz_name, tz = await self._get_user_tz(chat_id, user_id)
            delta, remainder = parse_duration_prefix(text_tail)
            if not delta:
                await msg.reply_text("Укажите длительность и текст. Например: /in 20m выпить воду")
                return
            if not remainder:
                await msg.reply_text("Пустой текст напоминания. Добавьте текст после длительности.")
                return
            when_local = datetime.now(tz) + delta
            when_utc = when_local.astimezone(timezone.utc)
            # Пограничные случаи
            if when_utc <= now_utc():
                await msg.reply_text("Время уже прошло. Укажите длительность больше нуля.")
                return
            reminder_id = await self.db.add_reminder(chat_id, user_id, remainder, when_utc, tz_name)
            self.sched.schedule_reminder(reminder_id, chat_id, remainder, when_utc)
            await msg.reply_text(
                f"Ок, напомню через {format_timedelta_brief(delta)} в {when_local.strftime('%Y-%m-%d %H:%M')} ({tz_name}).\nID: {reminder_id}"
            )
        except Exception:
            logger.exception("Ошибка в /in")
            await msg.reply_text("Произошла ошибка при обработке /in")

    async def cmd_at(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        args_text = (msg.text or "").split(maxsplit=1)
        text_tail = args_text[1] if len(args_text) > 1 else ""
        try:
            if not text_tail:
                await msg.reply_text("Укажите дату/время и текст. Например: /at завтра 9:00 купить хлеб")
                return
            tz_name, tz = await self._get_user_tz(chat_id, user_id)
            parsed = parse_at_datetime(text_tail, tz)
            if not parsed:
                await msg.reply_text("Не смог понять дату/время. Примеры: 'завтра 9:30', '2025-12-31 23:00'")
                return
            # Уберём из текста найденную часть даты, чтобы получить сообщение
            reminder_text = text_tail
            if parsed.source_text:
                # аккуратно вырезаем только первое вхождение
                idx = reminder_text.lower().find(parsed.source_text.lower())
                if idx >= 0:
                    reminder_text = (reminder_text[:idx] + reminder_text[idx + len(parsed.source_text):]).strip(
                        ", .;:-"
                    )
            if not reminder_text:
                await msg.reply_text("Пустой текст напоминания. Добавьте текст после даты/времени.")
                return
            when_utc = parsed.when_utc
            when_local = when_utc.astimezone(tz)
            if when_utc <= now_utc():
                await msg.reply_text("Это время уже прошло. Укажите будущий момент.")
                return
            reminder_id = await self.db.add_reminder(chat_id, user_id, reminder_text, when_utc, tz_name)
            self.sched.schedule_reminder(reminder_id, chat_id, reminder_text, when_utc)
            delta = when_utc - now_utc()
            await msg.reply_text(
                f"Ок, напомню {when_local.strftime('%Y-%m-%d %H:%M')} ({tz_name}) — через {format_timedelta_brief(delta)}.\nID: {reminder_id}"
            )
        except Exception:
            logger.exception("Ошибка в /at")
            await msg.reply_text("Произошла ошибка при обработке /at")

    async def cmd_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        try:
            tz_name, tz = await self._get_user_tz(chat_id, user_id)
            rows = await self.db.get_active_for_user(chat_id, user_id, limit=50)
            if not rows:
                await msg.reply_text("Активных напоминаний нет.")
                return
            lines = [f"Активные напоминания (TZ {tz_name}):"]
            for r in rows:
                when_utc = datetime.fromisoformat(r["due_at_utc"]).astimezone(timezone.utc)
                when_local = when_utc.astimezone(tz)
                delta = when_utc - now_utc()
                lines.append(f"ID {r['id']}: {when_local.strftime('%Y-%m-%d %H:%M')} ({tz_name}) — через {format_timedelta_brief(delta)} — {r['text']}")
            await msg.reply_text("\n".join(lines))
        except Exception:
            logger.exception("Ошибка в /list")
            await msg.reply_text("Произошла ошибка при обработке /list")

    async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        args = (msg.text or "").split(maxsplit=1)
        try:
            if len(args) < 2:
                await msg.reply_text("Укажите ID: /cancel <id>")
                return
            try:
                rid = int(args[1].strip())
            except ValueError:
                await msg.reply_text("ID должен быть числом: /cancel 123")
                return
            ok = await self.db.cancel(rid, user_id)
            if ok:
                # убрать из планировщика
                try:
                    self.sched.scheduler.remove_job(f"reminder:{rid}")
                except Exception:
                    pass
                await msg.reply_text(f"Отменено напоминание ID {rid}.")
            else:
                await msg.reply_text("Не найдено активное напоминание с таким ID (или уже выполнено/отменено).")
        except Exception:
            logger.exception("Ошибка в /cancel")
            await msg.reply_text("Произошла ошибка при обработке /cancel")


# =============================
# Жизненный цикл: загрузка отложенных
# =============================

async def reload_and_schedule(app: Application, db: ReminderDB, sched: ReminderScheduler, tz_name: str) -> None:
    tz = get_tz(tz_name)
    rows = await db.load_scheduled()
    if not rows:
        return
    sent_immediately = 0
    for r in rows:
        rid = int(r["id"]) 
        chat_id = int(r["chat_id"]) 
        text = str(r["text"]) 
        when_utc = datetime.fromisoformat(r["due_at_utc"]).astimezone(timezone.utc)
        if when_utc <= now_utc():
            # просрочено — отправим сразу с пометкой
            try:
                try:
                    await app.bot.send_message(chat_id=chat_id, text=f"(Поздно) {text}")
                except Exception:
                    logger.exception("Не удалось доставить просроченное уведомление id=%s", rid)
                await db.mark_sent(rid)
                sent_immediately += 1
            except Exception:
                logger.exception("Ошибка при обработке просроченного уведомления id=%s", rid)
        else:
            # перепланируем
            sched.schedule_reminder(rid, chat_id, text, when_utc)
    if sent_immediately:
        logger.info("Отправлено просроченных сразу: %s", sent_immediately)


# =============================
# Инициализация приложения
# =============================

async def on_startup(app: Application) -> None:
    logger.info("Бот запускается...")

async def on_post_init(app: Application, db: ReminderDB, sched: ReminderScheduler, tz_name: str) -> None:
    sched.start()
    await reload_and_schedule(app, db, sched, tz_name)

async def on_shutdown(app: Application, sched: ReminderScheduler) -> None:
    logger.info("Останавливаю планировщик...")
    sched.shutdown()


def build_application() -> Application:
    if not BOT_TOKEN:
        logger.error("Не задан TELEGRAM_BOT_TOKEN в окружении или файле .telegram_token")
        raise SystemExit(1)

    application = ApplicationBuilder().token(BOT_TOKEN).build()

    # Инициализируем БД и планировщик
    db = ReminderDB(DB_PATH)
    sched = ReminderScheduler(application, db)
    handlers = BotHandlers(application, db, sched, DEFAULT_TZ)

    # Регистрируем команды
    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("in", handlers.cmd_in))
    application.add_handler(CommandHandler("at", handlers.cmd_at))
    application.add_handler(CommandHandler("list", handlers.cmd_list))
    application.add_handler(CommandHandler("cancel", handlers.cmd_cancel))
    application.add_handler(CommandHandler("tz", handlers.cmd_tz))

    # Ошибки
    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception("Исключение в обработчике", exc_info=context.error)
        try:
            if isinstance(update, Update) and update.effective_message:
                await update.effective_message.reply_text("Произошла внутренняя ошибка. Попробуйте позже.")
        except Exception:
            pass

    application.add_error_handler(error_handler)

    # Хуки жизненного цикла
    application.post_init = lambda app=application: on_post_init(app, db, sched, DEFAULT_TZ)
    application.post_shutdown = lambda app=application: on_shutdown(app, sched)

    return application


def main() -> None:
    app = build_application()

    # Корректное завершение по сигналам
    loop = asyncio.get_event_loop()

    def _stop(*_: object) -> None:
        if app and app.running:
            logger.info("Получен сигнал, останавливаю...")
            asyncio.ensure_future(app.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _stop)
        except NotImplementedError:
            pass

    logger.info("Запускаю polling")
    app.run_polling(close_loop=False, allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
