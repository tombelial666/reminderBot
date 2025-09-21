# Telegram Reminder Bot (Python)

Минимальный асинхронный бот‑напоминальщик на python‑telegram‑bot + APScheduler + sqlite + dateparser.

## Возможности
- Команды: `/start`, `/in`, `/at`, `/list`, `/cancel`, `/tz`
- Персистентность: sqlite `reminders.db`
- Временные зоны на пользователя (`/tz Region/City`), дефолт через `REMIND_BOT_TZ` (по умолчанию Asia/Bangkok)
- RU/EN парсинг времени, поддержка кириллицы

## Быстрый старт
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install python-telegram-bot==21.4 APScheduler==3.10.4 dateparser==1.2.0
# Токен бота (любой способ):
printf '%s' '<TELEGRAM_BOT_TOKEN>' > .telegram_token
# Запуск
python remind_bot.py
```
Опции окружения:
- `TELEGRAM_BOT_TOKEN` или файл `.telegram_token`
- `REMIND_BOT_TZ` — например, `Europe/Moscow`
- `LOG_LEVEL` — `INFO`/`DEBUG`

## Тесты
```bash
python -m unittest -v
```

## Безопасность
- Не коммитьте `.telegram_token` и `reminders.db` — они в `.gitignore`.
- Рекомендуется револьвировать токен при публикации.
