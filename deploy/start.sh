#!/bin/sh
# Staging start (E-49): migrate, then serve. Migrations are expand-only between releases so the
# previous image still runs on the new schema; that is what makes a rollback a redeploy (runbook).
set -eu
cd /app/services/api
python -m alembic -c alembic.ini upgrade head
exec python -m uvicorn clipflow_api.app:app --host 0.0.0.0 --port "${PORT:-8000}" \
  --proxy-headers --forwarded-allow-ips '*' --no-server-header
