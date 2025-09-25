PY?=python3
PIP?=$(PY) -m pip
VENV=.venv

.PHONY: venv deps test e2e docker-build docker-up docker-logs

venv:
	$(PY) -m venv $(VENV)
	$(VENV)/bin/python -m pip install --upgrade pip

deps: venv
	$(VENV)/bin/pip install -r requirements.txt
	$(VENV)/bin/pip install pytest telethon

test: deps
	$(VENV)/bin/pytest -q

e2e: deps
	E2E_TELEGRAM=1 $(VENV)/bin/pytest -q -s tests/test_e2e.py

docker-build:
	docker compose build

docker-up:
	docker compose up -d bot

docker-logs:
	docker logs --tail=100 -f remind-bot


