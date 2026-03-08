#!/usr/bin/env bash
set -euo pipefail

echo "Waiting for database..."
python - <<'PY'
import time

from sqlalchemy import create_engine, text

from app.config import get_settings

settings = get_settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)

for attempt in range(1, 31):
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("Database connection ready.")
        break
    except Exception as exc:
        if attempt >= 30:
            raise SystemExit(f"Database is not reachable after {attempt} attempts: {exc}") from exc
        time.sleep(2)
PY

echo "Running migrations..."
alembic upgrade head

echo "Starting process manager..."
exec supervisord -c /app/deploy/supervisord.conf
