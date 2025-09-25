#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source ./.venv/bin/activate

python -m pip install --upgrade pip >/dev/null
pip install -q telethon pytest >/dev/null

if [[ ! -f .env.e2e ]]; then
  echo ".env.e2e not found" >&2
  exit 1
fi

set -a
. .env.e2e
set +a

pytest -q -s tests/test_e2e.py


