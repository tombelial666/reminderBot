# syntax=docker/dockerfile:1.7
# Multi-stage for smaller final image
FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System deps
RUN apt-get update -y \
    && apt-get install -y --no-install-recommends \
       tzdata \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install deps first (better layer cache)
COPY requirements.txt /app/requirements.txt
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -r /app/requirements.txt

# Copy source
COPY . /app

# Create non-root user
RUN useradd -m -u 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

# Data directory for SQLite (mount as volume in compose)
VOLUME ["/data"]

# Defaults (override by env)
ENV REMIND_DB_PATH=/data/reminders.db \
    REMIND_BOT_TZ=Asia/Bangkok \
    REMIND_BOT_LANG=ru

# Run
CMD ["python", "/app/remind_bot.py"]
