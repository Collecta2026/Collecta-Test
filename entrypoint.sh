#!/bin/sh
set -e
echo "Waiting for the database..."
python - <<'PY'
import os, time, sys
try:
    import psycopg
except Exception:
    psycopg = None
url = os.environ.get("DATABASE_URL", "").replace("postgresql+psycopg://", "postgresql://")
if psycopg and url.startswith("postgresql://"):
    for _ in range(40):
        try:
            psycopg.connect(url).close(); print("Database is up."); break
        except Exception as e:
            print("  ...waiting:", e); time.sleep(2)
    else:
        sys.exit("Database not reachable.")
PY
echo "Seeding (idempotent)..."
python seed.py || true
echo "Starting web server on 0.0.0.0:8000"
exec gunicorn -b 0.0.0.0:8000 -w 3 --timeout 120 app:app
