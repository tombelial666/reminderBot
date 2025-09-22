import asyncio
import logging
import os
import signal
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Tuple, Dict

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from dateparser import parse as dp_parse
from dateparser.search import search_dates
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.constants import ParseMode
from telegram.ext import (Application, ApplicationBuilder, CommandHandler,
                          ContextTypes, CallbackQueryHandler, MessageHandler, filters)
from telegram import BotCommand

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
DEFAULT_LANG = os.getenv("REMIND_BOT_LANG", "ru").lower()
DB_PATH = os.getenv("REMIND_DB_PATH", "reminders.db")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("reminder-bot")

# externalized i18n and keyboards
from i18n import t, set_bundles
from keyboards import (
    main_menu,
    inline_main_menu,
    inline_lang_menu,
    inline_tz_menu,
    inline_rid_menu,
    inline_hours_menu,
    inline_minutes_menu_for_at,
    inline_minutes_menu_for_in,
    inline_insert_menu,
    inline_dates_menu,
    inline_snooze_menu,
)


# =============================
# I18N (RU/TH)
# =============================

_BUNDLES: Dict[str, Dict[str, str]] = {
    "ru": {
        "help": (
            "Привет! Я бот‑напоминальщик. Ниже максимально простая инструкция:\n\n"
            "1) Главное меню (кнопки внизу):\n"
            "   • /list — показать все активные напоминания.\n"
            "   • /watch — включить тикающий просмотр по ID.\n"
            "   • /help — показать эту подсказку.\n"
            "   • /menu — открыть инлайн‑меню (удобный выбор времени/даты).\n"
            "   • /lang — выбрать язык интерфейса.\n\n"
            "2) Как создать напоминание ЧЕРЕЗ (минуты/часы):\n"
            "   Вариант А — вручную: /in 20m выпить воду\n"
            "   Вариант Б — без ввода времени: /menu → ‘/in (min)’ → выбрать минуты (шаг 5) → бот попросит текст → отправьте текст.\n\n"
            "3) Как создать напоминание НА ВРЕМЯ:\n"
            "   Вариант А — вручную: /at завтра 9:30 позвонить\n"
            "   Вариант Б — без ввода времени: /menu → ‘/at (hh:mm)’ → выбрать дату → час → минуты → бот попросит текст → отправьте текст.\n\n"
            "4) Snooze (отложить): когда придёт напоминание, под ним появятся кнопки: +15m / +30m / +60m.\n\n"
            "5) Управление:\n"
            "   • /cancel <id> — отменить напоминание.\n"
            "   • /watch <id> — показать тикающий таймер до конкретного напоминания.\n"
            "   • /tz [Region/City] — показать/сменить часовой пояс (например, Europe/Moscow).\n"
            "   • /lang — выбрать язык (ru/th/en).\n\n"
            "Подсказки: даты/время понимаются на ru/en/th. По умолчанию TZ: {tz}. Язык сейчас: {lang} (дефолт: {def_lang})."
        ),
        "need_duration": "Укажите длительность и текст. Например: /in 20m выпить воду",
        "empty_text": "Пустой текст напоминания. Добавьте текст после длительности.",
        "time_passed": "Время уже прошло. Укажите длительность больше нуля.",
        "in_ok": "Ок, напомню через {delta} в {when_local} ({tz}).\nID: {rid}",
        "at_need": "Укажите дату/время и текст. Например: /at завтра 9:00 купить хлеб",
        "at_unparsed": "Не смог понять дату/время. Примеры: 'завтра 9:30', '2025-12-31 23:00'",
        "at_empty": "Пустой текст напоминания. Добавьте текст после даты/времени.",
        "at_past": "Это время уже прошло. Укажите будущий момент.",
        "at_ok": "Ок, напомню {when_local} ({tz}) — через {delta}.\nID: {rid}",
        "list_empty": "Активных напоминаний нет.",
        "list_header": "Активные напоминания (TZ {tz}):",
        "cancel_need": "Укажите ID: /cancel <id>",
        "cancel_nan": "ID должен быть числом: /cancel 123",
        "cancel_ok": "Отменено напоминание ID {rid}.",
        "cancel_not_found": "Не найдено активное напоминание с таким ID (или уже выполнено/отменено).",
        "snooze_need": "Укажите: /snooze <id> <длительность>",
        "snooze_ok": "Отложено до {when_local} ({tz}) — через {delta}. ID: {rid}",
        "tz_show": "Текущий часовой пояс: {tz}\nУстановить: /tz Region/City (напр., Europe/Moscow)",
        "tz_bad": "Некорректный часовой пояс. Пример: Europe/Moscow",
        "tz_ok": "Часовой пояс установлен: {tz}",
        "lang_show": "Текущий язык: {lang}\nУстановить: /lang ru | th | en",
        "lang_bad": "Поддерживаются только: ru, th, en",
        "lang_ok": "Язык установлен: {lang}",
        "error": "Произошла внутренняя ошибка. Попробуйте позже.",
        "late_prefix": "(Поздно) "
        ,"btn_insert_in": "Вставить /in"
        ,"btn_insert_at": "Вставить /at"
        ,"btn_insert_snooze": "Вставить /snooze"
        ,"btn_list": "Список"
        ,"btn_watch": "Наблюдать"
        ,"btn_cancel": "Отменить"
        ,"btn_tz": "Часовой пояс"
        ,"btn_lang": "Язык"
        ,"btn_back": "Назад"
        ,"btn_tools": "Инструменты"
        ,"choose_action": "Выберите действие:"
        ,"choose_watch": "Выберите напоминание для наблюдения:"
        ,"choose_cancel": "Выберите напоминание для отмены:"
        ,"choose_lang": "Выберите язык:"
        ,"choose_tz": "Выберите часовой пояс:"
        ,"choose_at_hour": "Выберите час (0–23):"
        ,"choose_at_min": "Выберите минуты (шаг 5):"
        ,"choose_in_min": "Через сколько минут (шаг 5):"
        ,"choose_at_date": "Выберите дату:"
        ,"btn_insert_cmd": "Вставить команду"
        ,"enter_text": "Введите текст напоминания и просто отправьте сообщением"
        ,"snooze_15": "+15м"
        ,"snooze_30": "+30м"
        ,"snooze_60": "+60м"
    },
    "th": {
        "help": (
            "สวัสดี! ฉันคือบอทเตือนความจำ\n\n"
            "คำสั่ง:\n"
            "/in <ระยะเวลา> <ข้อความ> — เตือนภายในเวลา.\n"
            "เช่น: /in 10m ดื่มน้ำ; /in 2 ชม 15 นาที ส่งรายงาน\n\n"
            "/at <วันเวลา> <ข้อความ> — เตือนในเวลาที่กำหนด.\n"
            "เช่น: /at พรุ่งนี้ 9:30 ซื้อขนมปัง; /at 2025-12-31 23:00 อวยพร\n\n"
            "/list — แสดงการเตือนที่ใช้งานอยู่\n"
            "/cancel <id> — ยกเลิกตาม ID\n"
            "/snooze <id> <ระยะเวลา> — เลื่อนการเตือน\n"
            "/tz [Region/City] — แสดง/ตั้งค่าโซนเวลา\n"
            "/lang [ru|th|en] — แสดง/ตั้งค่าภาษา\n\n"
            "โซนเวลา: {tz}\nภาษา: {lang} (ค่าเริ่มต้น: {def_lang})"
        ),
        "need_duration": "กรุณาระบุระยะเวลาและข้อความ เช่น /in 20m ดื่มน้ำ",
        "empty_text": "ไม่มีข้อความ โปรดเพิ่มข้อความหลังระยะเวลา",
        "time_passed": "เวลาผ่านไปแล้ว โปรดระบุระยะเวลามากกว่า 0",
        "in_ok": "ตกลง จะเตือนใน {delta} เวลา {when_local} ({tz})\nID: {rid}",
        "at_need": "กรุณาระบุวันเวลาและข้อความ เช่น /at พรุ่งนี้ 9:00 ซื้อขนมปัง",
        "at_unparsed": "ไม่สามารถอ่านวันเวลาได้ เช่น 'พรุ่งนี้ 9:30', '2025-12-31 23:00'",
        "at_empty": "ไม่มีข้อความ โปรดเพิ่มข้อความหลังวันเวลา",
        "at_past": "เวลานั้นผ่านมาแล้ว โปรดระบุเวลาในอนาคต",
        "at_ok": "ตกลง จะเตือน {when_local} ({tz}) — ภายใน {delta}\nID: {rid}",
        "list_empty": "ยังไม่มีการเตือนที่ใช้งาน",
        "list_header": "การเตือนที่ใช้งานอยู่ (TZ {tz}):",
        "cancel_need": "โปรดระบุ ID: /cancel <id>",
        "cancel_nan": "ID ต้องเป็นตัวเลข: /cancel 123",
        "cancel_ok": "ยกเลิกการเตือน ID {rid} แล้ว",
        "cancel_not_found": "ไม่พบการเตือนที่ใช้งานด้วย ID นี้",
        "snooze_need": "โปรดระบุ: /snooze <id> <ระยะเวลา>",
        "snooze_ok": "เลื่อนไปถึง {when_local} ({tz}) — ภายใน {delta} ID: {rid}",
        "tz_show": "โซนเวลา: {tz}\nตั้งค่า: /tz Region/City (เช่น Europe/Moscow)",
        "tz_bad": "โซนเวลาไม่ถูกต้อง ตัวอย่าง: Europe/Moscow",
        "tz_ok": "ตั้งค่าโซนเวลาเป็น {tz}",
        "lang_show": "ภาษาปัจจุบัน: {lang}\nตั้งค่า: /lang ru หรือ /lang th",
        "lang_bad": "รองรับเฉพาะ: ru, th",
        "lang_ok": "ตั้งค่าภาษาเป็น {lang}",
        "error": "เกิดข้อผิดพลาดภายใน ลองใหม่ภายหลัง",
        "late_prefix": "(ล่าช้า) "
        ,"btn_insert_in": "แทรก /in"
        ,"btn_insert_at": "แทรก /at"
        ,"btn_insert_snooze": "แทรก /snooze"
        ,"btn_list": "รายการ"
        ,"btn_watch": "ติดตาม"
        ,"btn_cancel": "ยกเลิก"
        ,"btn_tz": "โซนเวลา"
        ,"btn_lang": "ภาษา"
        ,"btn_back": "กลับ"
        ,"btn_tools": "เครื่องมือ"
        ,"choose_action": "เลือกการทำงาน:"
        ,"choose_watch": "เลือกการเตือนเพื่อเฝ้าดู:"
        ,"choose_cancel": "เลือกการเตือนเพื่อยกเลิก:"
        ,"choose_lang": "เลือกภาษา:"
        ,"choose_tz": "เลือกโซนเวลา:"
        ,"choose_at_hour": "เลือกชั่วโมง (0–23):"
        ,"choose_at_min": "เลือกนาที (ทุก 5 นาที):"
        ,"choose_in_min": "ภายในกี่นาที (ทุก 5 นาที):"
        ,"choose_at_date": "เลือกวันที่:"
        ,"btn_insert_cmd": "แทรกคำสั่ง"
        ,"enter_text": "พิมพ์ข้อความเตือนแล้วส่งมาได้เลย"
        ,"snooze_15": "+15น"
        ,"snooze_30": "+30น"
        ,"snooze_60": "+60น"
    },
    "en": {
        "help": (
            "Hi! I'm a reminder bot.\n\n"
            "Commands:\n"
            "/in <duration> <text> — remind after a period.\n"
            "Ex.: /in 10m drink water; /in 2h 15m send report.\n\n"
            "/at <datetime> <text> — remind at a specific time.\n"
            "Ex.: /at tomorrow 9:30 buy bread; /at 2025-12-31 23:00 celebrate.\n\n"
            "/list — show active reminders.\n"
            "/cancel <id> — cancel by ID.\n"
            "/snooze <id> <duration> — postpone an active reminder.\n"
            "/tz [Region/City] — show/set timezone.\n"
            "/lang [ru|th|en] — show/set language.\n\n"
            "Timezone: {tz}\nLanguage: {lang} (default: {def_lang})"
        ),
        "need_duration": "Provide duration and text. E.g. /in 20m drink water",
        "empty_text": "Empty reminder text. Add text after duration.",
        "time_passed": "Time already passed. Use duration > 0.",
        "in_ok": "Ok, will remind in {delta} at {when_local} ({tz}).\nID: {rid}",
        "at_need": "Provide datetime and text. E.g. /at tomorrow 9:00 buy bread",
        "at_unparsed": "Couldn't parse date/time. Examples: 'tomorrow 9:30', '2025-12-31 23:00'",
        "at_empty": "Empty reminder text. Add text after datetime.",
        "at_past": "That time is in the past. Use a future moment.",
        "at_ok": "Ok, will remind {when_local} ({tz}) — in {delta}.\nID: {rid}",
        "list_empty": "No active reminders.",
        "list_header": "Active reminders (TZ {tz}):",
        "cancel_need": "Provide ID: /cancel <id>",
        "cancel_nan": "ID must be a number: /cancel 123",
        "cancel_ok": "Canceled reminder ID {rid}.",
        "cancel_not_found": "No active reminder with that ID (or already done/canceled).",
        "snooze_need": "Usage: /snooze <id> <duration>",
        "snooze_ok": "Snoozed to {when_local} ({tz}) — in {delta}. ID: {rid}",
        "tz_show": "Current timezone: {tz}\nSet: /tz Region/City (e.g., Europe/Moscow)",
        "tz_bad": "Invalid timezone. Example: Europe/Moscow",
        "tz_ok": "Timezone set to: {tz}",
        "lang_show": "Current language: {lang}\nSet: /lang ru | th | en",
        "lang_bad": "Supported: ru, th, en",
        "lang_ok": "Language set: {lang}",
        "error": "Internal error. Please try again later.",
        "late_prefix": "(Late) "
        ,"btn_insert_in": "Insert /in"
        ,"btn_insert_at": "Insert /at"
        ,"btn_insert_snooze": "Insert /snooze"
        ,"btn_list": "List"
        ,"btn_watch": "Watch"
        ,"btn_cancel": "Cancel"
        ,"btn_tz": "Timezone"
        ,"btn_lang": "Language"
        ,"btn_back": "Back"
        ,"btn_tools": "Tools"
        ,"choose_action": "Choose an action:"
        ,"choose_watch": "Choose a reminder to watch:"
        ,"choose_cancel": "Choose a reminder to cancel:"
        ,"choose_lang": "Choose language:"
        ,"choose_tz": "Choose timezone:"
        ,"choose_at_hour": "Choose hour (0–23):"
        ,"choose_at_min": "Choose minutes (step 5):"
        ,"choose_in_min": "In how many minutes (step 5):"
        ,"choose_at_date": "Choose a date:"
        ,"btn_insert_cmd": "Insert command"
        ,"enter_text": "Type the reminder text and send it"
        ,"snooze_15": "+15m"
        ,"snooze_30": "+30m"
        ,"snooze_60": "+60m"
    },
}

set_bundles(_BUNDLES, DEFAULT_LANG)


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


def _split_delta(delta: timedelta) -> Tuple[int, int, int, int]:
    total_seconds = int(delta.total_seconds())
    if total_seconds < 0:
        total_seconds = -total_seconds
    days, rem = divmod(total_seconds, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    return days, hours, minutes, seconds


def format_timedelta_brief_localized(user_lang: str, delta: timedelta) -> str:
    lang = (user_lang or DEFAULT_LANG).lower()
    days, hours, minutes, seconds = _split_delta(delta)
    parts: List[str] = []
    if lang == "en":
        if days:
            parts.append(f"{days}d")
        if hours:
            parts.append(f"{hours}h")
        if minutes:
            parts.append(f"{minutes}m")
        if not parts and seconds:
            parts.append(f"{seconds}s")
    elif lang == "th":
        if days:
            parts.append(f"{days} วัน")
        if hours:
            parts.append(f"{hours} ชม")
        if minutes:
            parts.append(f"{minutes} น")
        if not parts and seconds:
            parts.append(f"{seconds} วิ")
    else:  # ru default
        if days:
            parts.append(f"{days}д")
        if hours:
            parts.append(f"{hours}ч")
        if minutes:
            parts.append(f"{minutes}м")
        if not parts and seconds:
            parts.append(f"{seconds}с")
    return " ".join(parts) or ("0s" if lang == "en" else ("0 วิ" if lang == "th" else "0с"))


def parse_duration_prefix(text: str) -> Tuple[Optional[timedelta], str]:
    """Парсит длительность в начале строки (RU/EN/TH)."""
    import re

    s = text.strip()
    if not s:
        return None, ""

    # Удаляем ведущие маркеры: in|через|อีก|ใน
    s = re.sub(r"(?iu)^(in|через|อีก|ใน)\s+", "", s)

    # Разрешенные соединители
    connectors = {"и", "and", ",", "และ"}

    tokens = s.split()

    def is_duration_token(tok: str) -> Optional[Tuple[int, str]]:
        m = re.fullmatch(r"(?iu)(\d+)\s*([a-zA-Zа-яА-ЯёЁก-๙\.]+)", tok)
        if not m:
            return None
        return int(m.group(1)), m.group(2).lower().strip('.')

    # Попробуем токенами
    prefix = []
    idx = 0
    while idx < len(tokens):
        tok = tokens[idx]
        if tok.lower() in connectors:
            idx += 1
            continue
        parsed = is_duration_token(tok)
        if parsed is None:
            break
        prefix.append(parsed)
        idx += 1

    # Если не нашли — слитные шаблоны в начале строки
    if not prefix:
        miter = re.finditer(r"(?iu)^(?:\s*(?:in|через|อีก|ใน)\s*)?(\s*\d+\s*[a-zA-Zа-яА-ЯёЁก-๙\.]+)+", s)
        try:
            m0 = next(miter)
        except StopIteration:
            return None, text.strip()
        dur_str = m0.group(0)
        rest = s[len(dur_str):].lstrip()
        parts = re.findall(r"(?iu)(\d+)\s*([a-zA-Zа-яА-ЯёЁก-๙\.]+)", dur_str)
        if not parts:
            return None, text.strip()
        prefix = [(int(v), u.lower().strip('.')) for v, u in parts]
        remainder = rest
    else:
        remainder = " ".join(tokens[idx:]).strip()

    unit_map = {
        # EN/RU seconds
        "s": "seconds", "sec": "seconds", "secs": "seconds", "second": "seconds", "seconds": "seconds",
        "с": "seconds", "сек": "seconds", "секунда": "seconds", "секунды": "seconds", "секунд": "seconds",
        # TH seconds
        "วินาที": "seconds", "วิ": "seconds", "ว": "seconds",
        # minutes
        "m": "minutes", "min": "minutes", "mins": "minutes", "minute": "minutes", "minutes": "minutes",
        "м": "minutes", "мин": "minutes", "минута": "minutes", "минуты": "minutes", "минут": "minutes",
        "นาที": "minutes", "น": "minutes",
        # hours
        "h": "hours", "hr": "hours", "hour": "hours", "hours": "hours",
        "ч": "hours", "час": "hours", "часа": "hours", "часов": "hours",
        "ชั่วโมง": "hours", "ชม": "hours", "ช": "hours",
        # days
        "d": "days", "day": "days", "days": "days",
        "д": "days", "день": "days", "дня": "days", "дней": "days",
        "วัน": "days",
        # weeks
        "w": "weeks", "wk": "weeks", "week": "weeks", "weeks": "weeks",
        "н": "weeks", "нед": "weeks", "неделя": "weeks", "недели": "weeks", "недель": "weeks",
        "สัปดาห์": "weeks",
        # months (approx)
        "mo": "days", "mon": "days", "month": "days", "months": "days",
        "мес": "days", "месяц": "days", "месяца": "days", "месяцев": "days",
        "เดือน": "days",
        # years (approx)
        "y": "days", "yr": "days", "year": "days", "years": "days",
        "г": "days", "год": "days", "года": "days", "лет": "days",
        "ปี": "days",
    }

    total = timedelta(0)
    for value, unit in prefix:
        if unit not in unit_map:
            break
        kind = unit_map[unit]
        if kind == "seconds":
            total += timedelta(seconds=value)
        elif kind == "minutes":
            total += timedelta(minutes=value)
        elif kind == "hours":
            total += timedelta(hours=value)
        elif kind == "days":
            # для месяцев/лет приблизительно
            if unit in {"mo", "mon", "month", "months", "мес", "месяц", "месяца", "месяцев", "เดือน"}:
                total += timedelta(days=30 * value)
            elif unit in {"y", "yr", "year", "years", "г", "год", "года", "лет", "ปี"}:
                total += timedelta(days=365 * value)
            else:
                total += timedelta(days=value)
    if total.total_seconds() == 0:
        return None, text.strip()
    return total, remainder


def parse_at_datetime(text: str, tz: timezone) -> Optional[ParsedAt]:
    base = datetime.now(tz)
    # Ensure parser interprets naive times in the user's timezone
    tz_name = getattr(tz, "key", None) or str(tz) or DEFAULT_TZ
    settings = {
        "PREFER_DATES_FROM": "future",
        "RELATIVE_BASE": base,
        "RETURN_AS_TIMEZONE_AWARE": True,
        "TIMEZONE": tz_name,
        "TO_TIMEZONE": tz_name,
    }
    try:
        found = search_dates(text, languages=["ru", "en", "th"], settings=settings)
    except Exception:
        found = None
    dt = None
    matched = None
    if found:
        for match_text, match_dt in found:
            if match_dt is None:
                continue
            matched = match_text
            dt = match_dt
            break
    if dt is None:
        dt = dp_parse(text, languages=["ru", "en", "th"], settings=settings)
        matched = text if dt else None
    if dt is None:
        return None
    # Normalize to user's timezone
    if dt.tzinfo is None:
        dt_local = dt.replace(tzinfo=tz)
    else:
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS user_prefs (
                chat_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                tz TEXT NOT NULL,
                updated_at_utc TEXT NOT NULL,
                lang TEXT DEFAULT 'ru',
                PRIMARY KEY (chat_id, user_id)
            );
            """
        )
        # Миграция: добавить колонку lang, если её нет
        try:
            cur.execute("ALTER TABLE user_prefs ADD COLUMN lang TEXT DEFAULT 'ru'")
        except Exception:
            pass
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

    async def update_due(self, reminder_id: int, user_id: int, new_due_at_utc: datetime) -> bool:
        def _op() -> bool:
            cur = self.conn.cursor()
            cur.execute(
                "UPDATE reminders SET due_at_utc=?, status='scheduled' WHERE id=? AND user_id=? AND status='scheduled'",
                (new_due_at_utc.isoformat(), reminder_id, user_id),
            )
            self.conn.commit()
            return cur.rowcount > 0
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
                "INSERT INTO user_prefs(chat_id, user_id, tz, updated_at_utc, lang) VALUES (?, ?, ?, ?, COALESCE((SELECT lang FROM user_prefs WHERE chat_id=? AND user_id=?),'ru')) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET tz=excluded.tz, updated_at_utc=excluded.updated_at_utc",
                (chat_id, user_id, tz_name, now_utc().isoformat(), chat_id, user_id),
            )
            self.conn.commit()
        await asyncio.to_thread(_op)

    async def get_user_lang(self, chat_id: int, user_id: int) -> Optional[str]:
        def _op() -> Optional[str]:
            cur = self.conn.cursor()
            cur.execute("SELECT lang FROM user_prefs WHERE chat_id=? AND user_id=?", (chat_id, user_id))
            row = cur.fetchone()
            return row["lang"] if row else None
        return await asyncio.to_thread(_op)

    async def set_user_lang(self, chat_id: int, user_id: int, lang: str) -> None:
        def _op() -> None:
            cur = self.conn.cursor()
            cur.execute(
                "INSERT INTO user_prefs(chat_id, user_id, tz, updated_at_utc, lang) VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(chat_id, user_id) DO UPDATE SET lang=excluded.lang, updated_at_utc=excluded.updated_at_utc",
                (chat_id, user_id, DEFAULT_TZ, now_utc().isoformat(), lang),
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
            misfire_grace_time=60 * 60 * 24,
            coalesce=True,
            max_instances=5,
        )
        logger.info("Scheduled reminder id=%s at %s UTC", reminder_id, when_utc.isoformat())

    async def _deliver_job(self, reminder_id: int, chat_id: int, text: str) -> None:
        try:
            # При доставке показываем кнопки быстрого snooze
            lang = DEFAULT_LANG
            try:
                row = await self.db.get_by_id(reminder_id)
                if row:
                    user_id = int(row["user_id"])
                    lang = await self.db.get_user_lang(chat_id, user_id) or DEFAULT_LANG
            except Exception:
                pass
            await self.app.bot.send_message(chat_id=chat_id, text=text, reply_markup=inline_snooze_menu(lang, reminder_id))
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
        self.default_lang = DEFAULT_LANG

    async def _get_user_tz(self, chat_id: int, user_id: int) -> Tuple[str, timezone]:
        tz_name = await self.db.get_user_tz(chat_id, user_id)
        if not tz_name:
            tz_name = self.default_tz_name
        return tz_name, get_tz(tz_name)

    async def _get_user_lang(self, chat_id: int, user_id: int) -> str:
        lang = await self.db.get_user_lang(chat_id, user_id)
        return (lang or self.default_lang).lower()

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        try:
            chat_id = update.effective_chat.id
            user_id = update.effective_user.id
            tz_name, _ = await self._get_user_tz(chat_id, user_id)
            lang = await self._get_user_lang(chat_id, user_id)
            msg = t(lang, "help", tz=tz_name, lang=lang, def_lang=self.default_lang)
            # Вернём обычную клавиатуру для авто-команд
            webapp_url = os.getenv("REMIND_WEBAPP_URL")
            await update.effective_message.reply_text(msg, reply_markup=main_menu(lang, webapp_url))
            try:
                await update.effective_message.reply_text(t(lang, "choose_action"), reply_markup=inline_main_menu(lang, webapp_url))
            except Exception:
                pass
        except Exception:
            logger.exception("Ошибка в /start")

    async def cmd_lang(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        arg = None
        if context.args:
            arg = " ".join(context.args).strip().lower()
        try:
            current = await self._get_user_lang(chat_id, user_id)
            if not arg:
                # Показать выпадающий список выбора языка
                await msg.reply_text(t(current, "choose_lang"), reply_markup=inline_lang_menu(current))
                return
            if arg not in {"ru", "th", "en"}:
                await msg.reply_text(t(current, "lang_bad"), reply_markup=inline_lang_menu(current))
                return
            await self.db.set_user_lang(chat_id, user_id, arg)
            await msg.reply_text(t(arg, "lang_ok", lang=arg), reply_markup=inline_lang_menu(arg))
        except Exception:
            logger.exception("Ошибка в /lang")
            await msg.reply_text(t("ru", "error"))

    async def cmd_tz(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        arg = None
        if context.args:
            arg = " ".join(context.args).strip()
        try:
            lang = await self._get_user_lang(chat_id, user_id)
            if not arg:
                # Показать выпадающий список часовых поясов
                await msg.reply_text(t(lang, "choose_tz"), reply_markup=inline_tz_menu(lang))
                return
            candidate = arg
            if not is_valid_tz(candidate):
                await msg.reply_text(t(lang, "tz_bad"))
                return
            await self.db.set_user_tz(chat_id, user_id, candidate)
            await msg.reply_text(t(lang, "tz_ok", tz=candidate))
        except Exception:
            logger.exception("Ошибка в /tz")
            await msg.reply_text(t("ru", "error"))

    async def cmd_menu(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        try:
            lang = await self._get_user_lang(chat_id, user_id)
            webapp_url = os.getenv("REMIND_WEBAPP_URL")
            await msg.reply_text(t(lang, "choose_action"), reply_markup=inline_main_menu(lang, webapp_url))
        except Exception:
            logger.exception("Ошибка в /menu")

    async def cmd_in(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        args_text = (msg.text or "").split(maxsplit=1)
        text_tail = args_text[1] if len(args_text) > 1 else ""
        try:
            lang = await self._get_user_lang(chat_id, user_id)
            # Если нажата кнопка "/in (min)" из обычной клавиатуры — откроем список минут
            if text_tail.strip().lower() == "(min)":
                await msg.reply_text(t(lang, "choose_in_min"), reply_markup=inline_minutes_menu_for_in(lang))
                return
            tz_name, tz = await self._get_user_tz(chat_id, user_id)
            delta, remainder = parse_duration_prefix(text_tail)
            if not delta:
                await msg.reply_text(t(lang, "need_duration"))
                return
            if not remainder:
                await msg.reply_text(t(lang, "empty_text"))
                return
            when_local = datetime.now(tz) + delta
            when_utc = when_local.astimezone(timezone.utc)
            if when_utc <= now_utc():
                await msg.reply_text(t(lang, "time_passed"))
                return
            reminder_id = await self.db.add_reminder(chat_id, user_id, remainder, when_utc, tz_name)
            self.sched.schedule_reminder(reminder_id, chat_id, remainder, when_utc)
            await msg.reply_text(
                t(lang, "in_ok", delta=format_timedelta_brief_localized(lang, delta), when_local=when_local.strftime('%Y-%m-%d %H:%M'), tz=tz_name, rid=reminder_id)
            )
        except Exception:
            logger.exception("Ошибка в /in")
            await msg.reply_text(t("ru", "error"))

    async def cmd_at(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        args_text = (msg.text or "").split(maxsplit=1)
        text_tail = args_text[1] if len(args_text) > 1 else ""
        try:
            lang = await self._get_user_lang(chat_id, user_id)
            # Если нажата кнопка "/at (hh:mm)" из обычной клавиатуры — откроем выбор даты/времени
            if text_tail.strip().lower() == "(hh:mm)":
                await msg.reply_text(t(lang, "choose_at_date"), reply_markup=inline_dates_menu(lang))
                return
            if not text_tail:
                await msg.reply_text(t(lang, "at_need"))
                return
            tz_name, tz = await self._get_user_tz(chat_id, user_id)
            parsed = parse_at_datetime(text_tail, tz)
            if not parsed:
                await msg.reply_text(t(lang, "at_unparsed"))
                return
            reminder_text = text_tail
            if parsed.source_text:
                idx = reminder_text.lower().find(parsed.source_text.lower())
                if idx >= 0:
                    reminder_text = (reminder_text[:idx] + reminder_text[idx + len(parsed.source_text):]).strip(
                        ", .;:-"
                    )
            if not reminder_text:
                await msg.reply_text(t(lang, "at_empty"))
                return
            when_utc = parsed.when_utc
            when_local = when_utc.astimezone(tz)
            if when_utc <= now_utc():
                await msg.reply_text(t(lang, "at_past"))
                return
            reminder_id = await self.db.add_reminder(chat_id, user_id, reminder_text, when_utc, tz_name)
            self.sched.schedule_reminder(reminder_id, chat_id, reminder_text, when_utc)
            delta = when_utc - now_utc()
            await msg.reply_text(
                t(lang, "at_ok", when_local=when_local.strftime('%Y-%m-%d %H:%M'), tz=tz_name, delta=format_timedelta_brief_localized(lang, delta), rid=reminder_id)
            )
        except Exception:
            logger.exception("Ошибка в /at")
            await msg.reply_text(t("ru", "error"))

    async def cmd_list(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        try:
            lang = await self._get_user_lang(chat_id, user_id)
            tz_name, tz = await self._get_user_tz(chat_id, user_id)
            rows = await self.db.get_active_for_user(chat_id, user_id, limit=50)
            if not rows:
                await msg.reply_text(t(lang, "list_empty"))
                return
            lines = [t(lang, "list_header", tz=tz_name)]
            for r in rows:
                when_utc = datetime.fromisoformat(r["due_at_utc"]).astimezone(timezone.utc)
                when_local = when_utc.astimezone(tz)
                delta = when_utc - now_utc()
                lines.append(f"ID {r['id']}: {when_local.strftime('%Y-%m-%d %H:%M')} ({tz_name}) — {format_timedelta_brief_localized(lang, delta)} — {r['text']}")
            await msg.reply_text("\n".join(lines), reply_markup=inline_rid_menu(lang, rows, action="watch"))
        except Exception:
            logger.exception("Ошибка в /list")
            await msg.reply_text(t("ru", "error"))

    async def cmd_cancel(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        args = (msg.text or "").split(maxsplit=1)
        try:
            lang = await self._get_user_lang(chat_id, user_id)
            if len(args) < 2:
                await msg.reply_text(t(lang, "cancel_need"))
                return
            try:
                rid = int(args[1].strip())
            except ValueError:
                await msg.reply_text(t(lang, "cancel_nan"))
                return
            await self._cancel_id(chat_id, user_id, rid, msg, lang)
        except Exception:
            logger.exception("Ошибка в /cancel")
            await msg.reply_text(t("ru", "error"))

    async def cmd_snooze(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        raw = (msg.text or "")
        try:
            lang = await self._get_user_lang(chat_id, user_id)
            parts = raw.split(maxsplit=2)
            if len(parts) < 3:
                await msg.reply_text(t(lang, "snooze_need"))
                return
            try:
                rid = int(parts[1])
            except ValueError:
                await msg.reply_text(t(lang, "snooze_need"))
                return
            duration_text = parts[2]
            delta, _ = parse_duration_prefix(duration_text)
            if not delta:
                await msg.reply_text(t(lang, "snooze_need"))
                return
            tz_name, tz = await self._get_user_tz(chat_id, user_id)
            row = await self.db.get_by_id(rid)
            if not row or int(row["chat_id"]) != chat_id or int(row["user_id"]) != user_id or row["status"] != "scheduled":
                await msg.reply_text(t(lang, "cancel_not_found"))
                return
            new_when_local = datetime.now(tz) + delta
            new_when_utc = new_when_local.astimezone(timezone.utc)
            if new_when_utc <= now_utc():
                await msg.reply_text(t(lang, "time_passed"))
                return
            ok = await self.db.update_due(rid, user_id, new_when_utc)
            if not ok:
                await msg.reply_text(t(lang, "cancel_not_found"))
                return
            self.sched.schedule_reminder(rid, chat_id, row["text"], new_when_utc)
            await msg.reply_text(
                t(lang, "snooze_ok", when_local=new_when_local.strftime('%Y-%m-%d %H:%M'), tz=tz_name, delta=format_timedelta_brief_localized(lang, new_when_utc - now_utc()), rid=rid)
            )
        except Exception:
            logger.exception("Ошибка в /snooze")
            await msg.reply_text(t("ru", "error"))

    async def _tick(self, context: ContextTypes.DEFAULT_TYPE) -> None:
        data = context.job.data or {}
        chat_id = data.get("chat_id")
        message_id = data.get("message_id")
        rid = data.get("rid")
        lang = data.get("lang") or self.default_lang
        try:
            row = await self.db.get_by_id(rid)
            if not row or row["status"] != "scheduled":
                try:
                    await self.app.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=t(lang, "cancel_not_found"))
                except Exception:
                    pass
                context.job.schedule_removal()
                return
            when_utc = datetime.fromisoformat(row["due_at_utc"]).astimezone(timezone.utc)
            tz_name, tz = await self._get_user_tz(chat_id, row["user_id"])  # type: ignore
            when_local = when_utc.astimezone(tz)
            delta = when_utc - now_utc()
            if delta.total_seconds() <= 0:
                try:
                    await self.app.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=t(lang, "at_ok", when_local=when_local.strftime('%Y-%m-%d %H:%M'), tz=tz_name, delta=format_timedelta_brief_localized(lang, timedelta(0)), rid=row["id"]))
                except Exception:
                    pass
                context.job.schedule_removal()
                return
            text = f"⏳ ID {row['id']}: {when_local.strftime('%Y-%m-%d %H:%M')} ({tz_name}) — {format_timedelta_brief_localized(lang, delta)}"
            try:
                await self.app.bot.edit_message_text(chat_id=chat_id, message_id=message_id, text=text)
            except Exception:
                pass
        except Exception:
            logger.exception("Ошибка в обновлении /watch")

    async def _watch_id(self, chat_id: int, user_id: int, rid: int, msg, lang: str) -> None:
        row = await self.db.get_by_id(rid)
        if not row or int(row["chat_id"]) != chat_id:
            await msg.reply_text(t(lang, "cancel_not_found"))
            return
        when_utc = datetime.fromisoformat(row["due_at_utc"]).astimezone(timezone.utc)
        tz_name, tz = await self._get_user_tz(chat_id, user_id)
        when_local = when_utc.astimezone(tz)
        delta = when_utc - now_utc()
        m = await msg.reply_text(f"⏳ ID {rid}: {when_local.strftime('%Y-%m-%d %H:%M')} ({tz_name}) — {format_timedelta_brief_localized(lang, delta)}")
        self.app.job_queue.run_repeating(self._tick, interval=60, first=60, data={"chat_id": chat_id, "message_id": m.message_id, "rid": rid, "lang": lang})

    async def _cancel_id(self, chat_id: int, user_id: int, rid: int, msg, lang: str) -> None:
        ok = await self.db.cancel(rid, user_id)
        if ok:
            try:
                self.sched.scheduler.remove_job(f"reminder:{rid}")
            except Exception:
                pass
            await msg.reply_text(t(lang, "cancel_ok", rid=rid))
        else:
            await msg.reply_text(t(lang, "cancel_not_found"))

    async def cmd_watch(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        args = (msg.text or "").split(maxsplit=1)
        try:
            lang = await self._get_user_lang(chat_id, user_id)
            if len(args) < 2:
                # показать выбор активных напоминаний
                rows = await self.db.get_active_for_user(chat_id, user_id, limit=20)
                if not rows:
                    await msg.reply_text(t(lang, "list_empty"))
                    return
                await msg.reply_text(t(lang, "choose_watch"), reply_markup=inline_rid_menu(lang, rows, action="watch"))
                return
            rid = int(args[1].strip())
            await self._watch_id(chat_id, user_id, rid, msg, lang)
        except Exception:
            logger.exception("Ошибка в /watch")
            await msg.reply_text(t("ru", "error"))

    # Рестарт (удаление БД) — осторожно
    async def bot_restart(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        try:
            # Безопасность: разрешим только владельцу чата (личка) или пользователю-админу по env
            admin_id = os.getenv("REMIND_ADMIN_ID")
            if admin_id and str(update.effective_user.id) != str(admin_id):
                await msg.reply_text("Недостаточно прав.")
                return
            # Остановим планировщик
            self.sched.shutdown()
            # Удалим БД
            try:
                if os.path.exists(DB_PATH):
                    os.remove(DB_PATH)
            except Exception:
                logger.exception("Не удалось удалить БД")
            # Ответ
            await msg.reply_text("Перезапуск... База очищена.")
            # Попробуем рестарт через systemd
            try:
                import subprocess
                subprocess.Popen(["/bin/systemctl", "restart", "remind-bot"])  # type: ignore
                return
            except Exception:
                pass
            # Если systemd недоступен — завершим процесс
            os._exit(0)
        except Exception:
            logger.exception("Ошибка в /botrestart")
            await msg.reply_text("Ошибка при попытке перезапуска")


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
            try:
                try:
                    # Префикс "поздно" — используем локализованный префикс через t()
                    await app.bot.send_message(chat_id=chat_id, text=t(DEFAULT_LANG, "late_prefix") + text)
                except Exception:
                    logger.exception("Не удалось доставить просроченное уведомление id=%s", rid)
                await db.mark_sent(rid)
                sent_immediately += 1
            except Exception:
                logger.exception("Ошибка при обработке просроченного уведомления id=%s", rid)
        else:
            sched.schedule_reminder(rid, chat_id, text, when_utc)
    if sent_immediately:
        logger.info("Отправлено просроченных сразу: %s", sent_immediately)


# =============================
# Инициализация приложения
# =============================

async def on_startup(app: Application) -> None:
    logger.info("Бот запускается...")
    try:
        # Подсказки команд в меню Telegram
        await app.bot.set_my_commands([
            BotCommand("start", "Start / Help"),
            BotCommand("menu", "Open inline menu"),
            BotCommand("in", "Remind after duration"),
            BotCommand("at", "Remind at time"),
            BotCommand("snooze", "Postpone reminder"),
            BotCommand("list", "List reminders"),
            BotCommand("watch", "Watch reminder"),
            BotCommand("cancel", "Cancel reminder by id"),
            BotCommand("tz", "Show/Set timezone"),
            BotCommand("lang", "Show/Set language"),
        ])
    except Exception:
        logger.exception("Не удалось установить команды меню")

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

    db = ReminderDB(DB_PATH)
    sched = ReminderScheduler(application, db)
    handlers = BotHandlers(application, db, sched, DEFAULT_TZ)

    application.add_handler(CommandHandler("start", handlers.start))
    application.add_handler(CommandHandler("help", handlers.start))
    application.add_handler(CommandHandler("in", handlers.cmd_in))
    application.add_handler(CommandHandler("at", handlers.cmd_at))
    application.add_handler(CommandHandler("list", handlers.cmd_list))
    application.add_handler(CommandHandler("cancel", handlers.cmd_cancel))
    application.add_handler(CommandHandler("tz", handlers.cmd_tz))
    application.add_handler(CommandHandler("lang", handlers.cmd_lang))
    application.add_handler(CommandHandler("watch", handlers.cmd_watch))
    application.add_handler(CommandHandler("snooze", handlers.cmd_snooze))
    application.add_handler(CommandHandler("menu", handlers.cmd_menu))
    # Обработчик ввода текста для завершения выбора at/in
    async def on_free_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        chat_id = update.effective_chat.id
        user_id = update.effective_user.id
        try:
            lang = await handlers._get_user_lang(chat_id, user_id)
            pending_hhmm = context.user_data.get("pending_at_hhmm")
            pending_in = context.user_data.get("pending_in_min")
            text = (msg.text or "").strip()
            if pending_hhmm:
                # Используем выбранные час:мин и выбранную дату (если задана), иначе текущую дату пользователя
                tz_name, tz = await handlers._get_user_tz(chat_id, user_id)
                now_loc = datetime.now(tz)
                hh, mm = pending_hhmm.split(":", 1)
                date_part = context.user_data.pop("pending_at_date", None)
                if date_part:
                    try:
                        y, m, d = [int(x) for x in date_part.split("-")]
                        base_date = now_loc.replace(year=y, month=m, day=d)
                    except Exception:
                        base_date = now_loc
                else:
                    base_date = now_loc
                dt_local = base_date.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
                if dt_local <= now_loc:
                    dt_local = dt_local + timedelta(days=1)
                when_utc = dt_local.astimezone(timezone.utc)
                reminder_id = await handlers.db.add_reminder(chat_id, user_id, text, when_utc, tz_name)
                handlers.sched.schedule_reminder(reminder_id, chat_id, text, when_utc)
                await msg.reply_text(
                    t(lang, "at_ok", when_local=dt_local.strftime('%Y-%m-%d %H:%M'), tz=tz_name, delta=format_timedelta_brief_localized(lang, when_utc - now_utc()), rid=reminder_id)
                )
                context.user_data.pop("pending_at_hhmm", None)
                return
            if pending_in:
                tz_name, tz = await handlers._get_user_tz(chat_id, user_id)
                delta = timedelta(minutes=int(pending_in))
                when_local = datetime.now(tz) + delta
                when_utc = when_local.astimezone(timezone.utc)
                reminder_id = await handlers.db.add_reminder(chat_id, user_id, text, when_utc, tz_name)
                handlers.sched.schedule_reminder(reminder_id, chat_id, text, when_utc)
                await msg.reply_text(
                    t(lang, "in_ok", delta=format_timedelta_brief_localized(lang, delta), when_local=when_local.strftime('%Y-%m-%d %H:%M'), tz=tz_name, rid=reminder_id)
                )
                context.user_data.pop("pending_in_min", None)
        except Exception:
            logger.exception("Ошибка при завершении выбора at/in")

    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), on_free_text))

    # Callback handlers (inline)
    async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        q = update.callback_query
        if not q:
            return
        await q.answer()
        chat_id = q.message.chat.id  # type: ignore
        user_id = q.from_user.id  # type: ignore
        lang = await handlers._get_user_lang(chat_id, user_id)
        data = q.data or ""
        try:
            if data == "back":
                try:
                    await q.edit_message_reply_markup(reply_markup=inline_main_menu(lang))
                except Exception:
                    pass
                return
            if data == "list":
                rows = await handlers.db.get_active_for_user(chat_id, user_id, limit=20)
                if not rows:
                    await q.edit_message_text(t(lang, "list_empty"), reply_markup=inline_main_menu(lang))
                    return
                await q.edit_message_text(t(lang, "list_header", tz=(await handlers._get_user_tz(chat_id, user_id))[0]), reply_markup=inline_rid_menu(lang, rows, action="watch"))
                return
            if data == "open:watch":
                rows = await handlers.db.get_active_for_user(chat_id, user_id, limit=20)
                if not rows:
                    await q.edit_message_text(t(lang, "list_empty"), reply_markup=inline_main_menu(lang))
                    return
                await q.edit_message_text(t(lang, "choose_watch"), reply_markup=inline_rid_menu(lang, rows, action="watch"))
                return
            if data == "open:cancel":
                rows = await handlers.db.get_active_for_user(chat_id, user_id, limit=20)
                if not rows:
                    await q.edit_message_text(t(lang, "list_empty"), reply_markup=inline_main_menu(lang))
                    return
                await q.edit_message_text(t(lang, "choose_cancel"), reply_markup=inline_rid_menu(lang, rows, action="cancel"))
                return
            if data == "open:lang":
                await q.edit_message_text(t(lang, "choose_lang"), reply_markup=inline_lang_menu(lang))
                return
            if data == "open:tz":
                await q.edit_message_text(t(lang, "choose_tz"), reply_markup=inline_tz_menu(lang))
                return
            if data == "open:at":
                await q.edit_message_text(t(lang, "choose_at_date"), reply_markup=inline_dates_menu(lang))
                return
            if data.startswith("at_date:"):
                date_str = data.split(":", 1)[1]
                context.user_data["pending_at_date"] = date_str
                await q.edit_message_text(t(lang, "choose_at_hour"), reply_markup=inline_hours_menu(lang))
                return
            if data == "open:in":
                await q.edit_message_text(t(lang, "choose_in_min"), reply_markup=inline_minutes_menu_for_in(lang))
                return
            if data.startswith("at_hh:"):
                hh = data.split(":", 1)[1]
                await q.edit_message_text(t(lang, "choose_at_min"), reply_markup=inline_minutes_menu_for_at(lang, hh))
                return
            if data.startswith("at_set:"):
                _, hh, mm = data.split(":", 2)
                # Сохраним intention в user_data и попросим текст
                context.user_data["pending_at_hhmm"] = f"{hh}:{mm}"
                await q.edit_message_text(t(lang, "enter_text"))
                return
            if data.startswith("in_set:"):
                minutes = data.split(":", 1)[1]
                context.user_data["pending_in_min"] = int(minutes)
                await q.edit_message_text(t(lang, "enter_text"))
                return
            if data.startswith("lang:"):
                new_lang = data.split(":", 1)[1]
                if new_lang in {"ru", "th", "en"}:
                    await handlers.db.set_user_lang(chat_id, user_id, new_lang)
                    lang = new_lang
                    await q.edit_message_text(t(lang, "lang_ok", lang=lang), reply_markup=inline_main_menu(lang))
                else:
                    await q.edit_message_text(t(lang, "lang_bad"), reply_markup=inline_main_menu(lang))
                return
            if data.startswith("tz:"):
                tz_name = data.split(":", 1)[1]
                if is_valid_tz(tz_name):
                    await handlers.db.set_user_tz(chat_id, user_id, tz_name)
                    await q.edit_message_text(t(lang, "tz_ok", tz=tz_name), reply_markup=inline_main_menu(lang))
                else:
                    await q.edit_message_text(t(lang, "tz_bad"), reply_markup=inline_main_menu(lang))
                return
            if data.startswith("watch:"):
                rid = int(data.split(":", 1)[1])
                await handlers._watch_id(chat_id, user_id, rid, q.message, lang)  # type: ignore
                return
            if data.startswith("cancel:"):
                rid = int(data.split(":", 1)[1])
                await handlers._cancel_id(chat_id, user_id, rid, q.message, lang)  # type: ignore
                return
            if data.startswith("snooze_do:"):
                _, rid, mins = data.split(":", 2)
                rid = int(rid)
                mins = int(mins)
                row = await handlers.db.get_by_id(rid)
                if not row or int(row["chat_id"]) != chat_id or row["status"] != "scheduled":
                    await q.edit_message_text(t(lang, "cancel_not_found"))
                    return
                tz_name, tz = await handlers._get_user_tz(chat_id, int(row["user_id"]))
                new_when_local = datetime.now(tz) + timedelta(minutes=mins)
                new_when_utc = new_when_local.astimezone(timezone.utc)
                ok = await handlers.db.update_due(rid, int(row["user_id"]), new_when_utc)
                if ok:
                    handlers.sched.schedule_reminder(rid, chat_id, row["text"], new_when_utc)
                    await q.edit_message_text(t(lang, "snooze_ok", when_local=new_when_local.strftime('%Y-%m-%d %H:%M'), tz=tz_name, delta=format_timedelta_brief_localized(lang, new_when_utc - now_utc()), rid=rid))
                else:
                    await q.edit_message_text(t(lang, "cancel_not_found"))
                return
        except Exception:
            logger.exception("Ошибка в callback")

    application.add_handler(CallbackQueryHandler(on_callback))
    # Рестарт (удаление БД) — осторожно
    async def bot_restart(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        msg = update.effective_message
        try:
            # Безопасность: разрешим только владельцу чата (личка) или пользователю-админу по env
            admin_id = os.getenv("REMIND_ADMIN_ID")
            if admin_id and str(update.effective_user.id) != str(admin_id):
                await msg.reply_text("Недостаточно прав.")
                return
            # Остановим планировщик
            sched.shutdown()
            # Удалим БД
            try:
                if os.path.exists(DB_PATH):
                    os.remove(DB_PATH)
            except Exception:
                logger.exception("Не удалось удалить БД")
            # Ответ
            await msg.reply_text("Перезапуск... База очищена.")
            # Попробуем рестарт через systemd
            try:
                import subprocess
                subprocess.Popen(["/bin/systemctl", "restart", "remind-bot"])  # type: ignore
                return
            except Exception:
                pass
            # Если systemd недоступен — завершим процесс
            os._exit(0)
        except Exception:
            logger.exception("Ошибка в /botrestart")
            await msg.reply_text("Ошибка при попытке перезапуска")

    application.add_handler(CommandHandler("botrestart", bot_restart))

    async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        logger.exception("Исключение в обработчике", exc_info=context.error)
        try:
            if isinstance(update, Update) and update.effective_message:
                # попробуем определить язык пользователя для сообщения об ошибке
                try:
                    chat_id = update.effective_chat.id
                    user_id = update.effective_user.id
                    lang = await db.get_user_lang(chat_id, user_id) or DEFAULT_LANG
                except Exception:
                    lang = DEFAULT_LANG
                await update.effective_message.reply_text(t(lang, "error"))
        except Exception:
            pass

    application.add_error_handler(error_handler)

    application.post_init = lambda app=application: on_post_init(app, db, sched, DEFAULT_TZ)
    application.post_shutdown = lambda app=application: on_shutdown(app, sched)

    return application


def main() -> None:
    app = build_application()

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
    app.run_polling(close_loop=False, allowed_updates=Update.ALL_TYPES, drop_pending_updates=True)


if __name__ == "__main__":
    main()
