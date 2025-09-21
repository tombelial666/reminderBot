#!/usr/bin/env bash
set -euo pipefail

APP_DIR=${APP_DIR:-/opt/remind-bot}
APP_USER=${APP_USER:-remindbot}
SERVICE_NAME=${SERVICE_NAME:-remind-bot}

if [[ -d "${APP_DIR}/.git" ]]; then
  sudo -u "${APP_USER}" bash -lc "cd '${APP_DIR}' && git pull --ff-only"
else
  echo "[WARN] ${APP_DIR} не является git-репозиторием. Пропускаю git pull." >&2
fi

if [[ -f "${APP_DIR}/requirements.txt" ]]; then
  sudo -u "${APP_USER}" "${APP_DIR}/venv/bin/pip" install -r "${APP_DIR}/requirements.txt" --upgrade
fi

sudo systemctl restart "${SERVICE_NAME}"
echo "[OK] Restarted ${SERVICE_NAME}. Logs: journalctl -u ${SERVICE_NAME} -f"
