## Memo Reminder Bot

Минималистичный бот-напоминалка с поддержкой TZ (IANA/UTC±HH:MM), офлайн-картой город→часовой пояс, инлайн-меню и аудит‑логом.

### Быстрый старт (локально)
- Требования: Python 3.11+.
- Установка:
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Переменные окружения
- Основные:
  - TELEGRAM_BOT_TOKEN — токен бота (альтернатива TELEGRAM_BOT_TOKEN_FILE).
  - TELEGRAM_BOT_TOKEN_FILE — путь к файлу с токеном (для Docker: `/data/.telegram_token`).
  - REMIND_AUDIT_LOG_PATH — путь к файлу аудита (например `./data/audit.log` или `/data/audit.log`).
  - REMIND_ADMIN_ID — список id/юзернеймов админов (например: `"242605892,@username"`).
  - REMIND_WEBAPP_URL — опционально, URL веб-приложения.

См. `.env.example` для набора переменных.

### Запуск в Docker
```bash
docker compose build
docker compose up -d bot
```
Требуется файл токена и директория данных:
```bash
mkdir -p ./data
echo "<BOT_TOKEN>" > ./data/.telegram_token
chmod 600 ./data/.telegram_token
```
В docker-compose уже прописаны:
- Монтирование `./data` → `/data` (БД/аудит/токен).
- `TELEGRAM_BOT_TOKEN_FILE=/data/.telegram_token`
- `REMIND_AUDIT_LOG_PATH=/data/audit.log`

Проверка:
```bash
docker logs --tail=50 remind-bot
```

### Логи
- Аудит: JSON-события в `REMIND_AUDIT_LOG_PATH`.
- Просмотр в реальном времени:
```bash
tail -f ./data/audit.log
```

### Тесты
- Юнит/интеграционные:
```bash
pytest -q
```

- E2E одним скриптом:
```bash
bash scripts/e2e_run.sh
```

### E2E (Telethon, реальный Telegram)
1) Установить зависимости:
```bash
source .venv/bin/activate
pip install telethon pytest
```
2) Создать `.env.e2e` (пример):
```env
E2E_TELEGRAM=1
E2E_API_ID=28371413
E2E_API_HASH=9b12da446ceec5c488ab8532491e2e59
E2E_PHONE=+7XXXXXXXXXX
E2E_SESSION=<StringSession пользователя>
E2E_BOT_USERNAME=<username_бота_без_@>
```
3) Сгенерировать StringSession пользователя:
```bash
python gen_session.py
```
Вводите ТОЛЬКО номер телефона (+7…), код, 2FA. Ожидаемо: `AUTHORIZED=True`.

4) Запуск E2E:
```bash
pytest -q -s tests/test_e2e.py
```

### UI/UX
- Back на корне инлайн-меню скрывает клавиатуру.
- На шагах ввода текста есть «Отмена».
- `/in` с клавиатуры — шаг 5 минут; ручной ввод разрешает любую минуту.
- `/tz HH:MM` — фиксированный UTC±HH:MM, ограничение ±14:00.

### Примечания
- Карта город→TZ офлайн: `geonamescache`, `timezonefinder`.
- TZ: поддержка IANA и фиксированных UTC±HH:MM.
- Аудит: логируются команды и инлайн‑действия.

### CI
- GitHub Actions: линт/тесты на pushes/PR к ветке main, сборка Docker-образа.

### Makefile
- Частые цели:
```bash
make venv      # создать venv
make deps      # установить зависимости
make test      # запустить pytest
make e2e       # e2e (потребуется .env.e2e)
make docker-build
make docker-up
make docker-logs
```

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

E2E (опционально, требует Telethon):
```bash
pip install -r requirements-dev.txt
export E2E_TELEGRAM=1
export E2E_API_ID=xxxx
export E2E_API_HASH=yyyy
export E2E_PHONE='+<phone>'
export E2E_BOT_USERNAME='belialreminderbot'
python -m unittest -v tests/test_e2e.py
```

## Безопасность
- Не коммитьте `.telegram_token` и `reminders.db`