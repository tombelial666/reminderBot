from telegram import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from typing import List, Dict
from i18n import t
from datetime import datetime, timedelta


def main_menu(lang: str = "ru", webapp_url: str | None = None) -> ReplyKeyboardMarkup:
    # Только авто-отправляемые команды: /list, /watch, /lang
    if lang == "th":
        rows = [["/list", "/watch", "/help"], ["/at (hh:mm)", "/in (min)"], ["/menu"], ["/tz", "/lang"]]
    elif lang == "en":
        rows = [["/list", "/watch", "/help"], ["/at (hh:mm)", "/in (min)"], ["/menu"], ["/tz", "/lang"]]
    else:
        rows = [["/list", "/watch", "/help"], ["/at (hh:mm)", "/in (min)"], ["/menu"], ["/tz", "/lang"]]
    kb_rows = [[KeyboardButton(text) for text in row] for row in rows]
    if webapp_url and webapp_url.startswith("https://"):
        kb_rows.append([KeyboardButton(text=t(lang, "btn_tools"), web_app=WebAppInfo(url=webapp_url))])
    return ReplyKeyboardMarkup(kb_rows, resize_keyboard=True)


def inline_main_menu(lang: str = "ru", webapp_url: str | None = None) -> InlineKeyboardMarkup:
    buttons = [
        [
            InlineKeyboardButton(t(lang, "btn_list"), callback_data="list"),
            InlineKeyboardButton(t(lang, "btn_watch"), callback_data="open:watch"),
        ],
        [
            InlineKeyboardButton(t(lang, "btn_cancel"), callback_data="open:cancel"),
        ],
        [
            InlineKeyboardButton(t(lang, "btn_tz"), callback_data="open:tz"),
            InlineKeyboardButton(t(lang, "btn_lang"), callback_data="open:lang"),
        ],
        [
            InlineKeyboardButton("/at (hh:mm)", callback_data="open:at"),
            InlineKeyboardButton("/in (min)", callback_data="open:in"),
        ],
    ]
    if webapp_url and webapp_url.startswith("https://"):
        buttons.append([InlineKeyboardButton(t(lang, "btn_tools"), web_app=WebAppInfo(url=webapp_url))])
    return InlineKeyboardMarkup(buttons)


def inline_lang_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("Русский", callback_data="lang:ru")],
        [InlineKeyboardButton("ไทย", callback_data="lang:th")],
        [InlineKeyboardButton("English", callback_data="lang:en")],
        [InlineKeyboardButton(t(lang, "btn_back"), callback_data="back")],
    ]
    return InlineKeyboardMarkup(buttons)


def inline_tz_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    buttons = [
        [InlineKeyboardButton("Asia/Bangkok", callback_data="tz:Asia/Bangkok")],
        [InlineKeyboardButton("Europe/Moscow", callback_data="tz:Europe/Moscow")],
        [InlineKeyboardButton("Europe/London", callback_data="tz:Europe/London")],
        [InlineKeyboardButton("UTC", callback_data="tz:UTC")],
        [InlineKeyboardButton(t(lang, "btn_back"), callback_data="back")],
    ]
    return InlineKeyboardMarkup(buttons)


def inline_rid_menu(lang: str, reminders: List[Dict], action: str) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for r in reminders[:10]:
        rid = str(r["id"])  # sqlite3.Row indexable
        rows.append([InlineKeyboardButton(f"ID {rid}", callback_data=f"{action}:{rid}")])
    rows.append([InlineKeyboardButton(t(lang, "btn_back"), callback_data="back")])
    return InlineKeyboardMarkup(rows)


def inline_hours_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    hours = [f"{h:02d}" for h in range(24)]
    for i in range(0, 24, 6):
        chunk = hours[i:i+6]
        rows.append([InlineKeyboardButton(h, callback_data=f"at_hh:{h}") for h in chunk])
    rows.append([InlineKeyboardButton(t(lang, "btn_back"), callback_data="back")])
    return InlineKeyboardMarkup(rows)


def inline_minutes_menu_for_at(lang: str, hh: str) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    mins = [f"{m:02d}" for m in range(0, 60, 5)]
    for i in range(0, len(mins), 6):
        chunk = mins[i:i+6]
        rows.append([InlineKeyboardButton(m, callback_data=f"at_set:{hh}:{m}") for m in chunk])
    rows.append([InlineKeyboardButton(t(lang, "btn_back"), callback_data="open:at")])
    return InlineKeyboardMarkup(rows)


def inline_minutes_menu_for_in(lang: str = "ru") -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    mins = [str(m) for m in range(5, 65, 5)]
    for i in range(0, len(mins), 6):
        chunk = mins[i:i+6]
        rows.append([InlineKeyboardButton(m, callback_data=f"in_set:{m}") for m in chunk])
    rows.append([InlineKeyboardButton(t(lang, "btn_back"), callback_data="back")])
    return InlineKeyboardMarkup(rows)


def inline_insert_menu(lang: str, command_text: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(t(lang, "btn_insert_cmd"), switch_inline_query_current_chat=command_text)],
        [InlineKeyboardButton(t(lang, "btn_back"), callback_data="back")],
    ])


def inline_dates_menu(lang: str = "ru") -> InlineKeyboardMarkup:
    # Сегодня + следующие 6 дней
    today = datetime.utcnow().date()
    labels: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for i in range(7):
        d = today + timedelta(days=i)
        label = d.strftime("%Y-%m-%d")
        row.append(InlineKeyboardButton(label, callback_data=f"at_date:{label}"))
        if len(row) == 3:
            labels.append(row)
            row = []
    if row:
        labels.append(row)
    labels.append([InlineKeyboardButton(t(lang, "btn_back"), callback_data="back")])
    return InlineKeyboardMarkup(labels)


def inline_snooze_menu(lang: str, rid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(t(lang, "snooze_15"), callback_data=f"snooze_do:{rid}:15"),
            InlineKeyboardButton(t(lang, "snooze_30"), callback_data=f"snooze_do:{rid}:30"),
            InlineKeyboardButton(t(lang, "snooze_60"), callback_data=f"snooze_do:{rid}:60"),
        ]
    ])
