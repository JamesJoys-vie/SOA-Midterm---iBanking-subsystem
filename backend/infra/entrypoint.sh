#!/bin/sh
set -e
# Apply DB migrations first if this service has any (alembic.ini present)
if [ -f alembic.ini ]; then
  alembic upgrade head
fi
# UVICORN_WORKERS > 1 = several processes (one GIL each); the service must be safe to run as replicas
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers "${UVICORN_WORKERS:-1}"
