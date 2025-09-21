#!/usr/bin/env bash
set -euo pipefail

# Configurable variables
APP_DIR=${APP_DIR:-/opt/remind-bot}
APP_USER=${APP_USER:-remindbot}
SERVICE_NAME=${SERVICE_NAME:-remind-bot}
ENV_FILE=${ENV_FILE:-/etc/remind-bot.env}
REPO_URL=${REPO_URL:-}

if [[ -z "${TELEGRAM_BOT_TOKEN:-}" ]] && [[ ! -f "${APP_DIR}/.telegram_token" ]] && [[ ! -f "${ENV_FILE}" ]]; then
  echo "[WARN] TELEGRAM_BOT_TOKEN не задан и .telegram_token не найден. Можно задать позже в ${ENV_FILE} или ${APP_DIR}/.telegram_token" >&2
fi

# 1) Packages
sudo apt update
sudo apt install -y python3 python3-venv tzdata git

# 2) User and dir
sudo useradd -r -m -d "${APP_DIR}" -s /usr/sbin/nologin "${APP_USER}" || true
sudo mkdir -p "${APP_DIR}"
sudo chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

# 3) Fetch code
if [[ -n "${REPO_URL}" ]]; then
  if [[ ! -d "${APP_DIR}/.git" ]]; then
    sudo -u "${APP_USER}" git clone "${REPO_URL}" "${APP_DIR}"
  else
    echo "[INFO] Git репозиторий уже существует, пропускаю clone"
  fi
fi

# 4) Venv and deps
sudo -u "${APP_USER}" python3 -m venv "${APP_DIR}/venv"
sudo -u "${APP_USER}" "${APP_DIR}/venv/bin/pip" install --upgrade pip
if [[ -f "${APP_DIR}/requirements.txt" ]]; then
  sudo -u "${APP_USER}" "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt"
else
  sudo -u "${APP_USER}" "${APP_DIR}/venv/bin/pip" install python-telegram-bot==21.4 APScheduler==3.10.4 dateparser==1.2.0
fi

# 5) Env file
if [[ ! -f "${ENV_FILE}" ]]; then
  sudo bash -c "cat >'${ENV_FILE}'" <<EOF
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
REMIND_BOT_TZ=${REMIND_BOT_TZ:-Asia/Bangkok}
LOG_LEVEL=${LOG_LEVEL:-INFO}
REMIND_DB_PATH=${REMIND_DB_PATH:-${APP_DIR}/reminders.db}
EOF
  sudo chmod 600 "${ENV_FILE}"
fi

# 6) systemd unit
sudo bash -c "cat >'/etc/systemd/system/${SERVICE_NAME}.service'" <<EOF
[Unit]
Description=Telegram Reminder Bot
After=network-online.target

[Service]
User=${APP_USER}
Group=${APP_USER}
WorkingDirectory=${APP_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${APP_DIR}/venv/bin/python ${APP_DIR}/remind_bot.py
Restart=on-failure
RestartSec=5
KillSignal=SIGINT
TimeoutStopSec=20
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now "${SERVICE_NAME}"

echo "[OK] Service ${SERVICE_NAME} started. Logs: journalctl -u ${SERVICE_NAME} -f"
