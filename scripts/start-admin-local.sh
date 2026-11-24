#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="$PWD/.venv/bin/python"

if [[ ! -x "$PYTHON" ]]; then
  echo "ERREUR : environnement Python .venv introuvable."
  exit 1
fi

if [[ ! -f ".env" || ! -f ".env.admin.local" ]]; then
  echo "ERREUR : configuration .env ou .env.admin.local absente."
  exit 1
fi

# Ne jamais reprendre un ancien tunnel PostgreSQL du terminal.
unset DATABASE_URL

# Charger uniquement la clé JWT locale persistante.
set -a
source .env.admin.local
set +a

"$PYTHON" - <<'PY'
import os
import socket
import sys
from sqlalchemy.engine import make_url

secret = os.getenv("ADMIN_JWT_SECRET", "")

if len(secret) < 32:
    sys.exit("ERREUR : ADMIN_JWT_SECRET invalide.")

from app.core.config import settings
from app.db.session import test_database_connection

url = make_url(settings.database_url)

if url.host in ("127.0.0.1", "localhost"):
    print("ATTENTION : PostgreSQL utilise une adresse locale.")

try:
    print("PostgreSQL :", test_database_connection())
except Exception as exc:
    sys.exit(f"ERREUR PostgreSQL : {type(exc).__name__}")

with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
    try:
        sock.bind(("127.0.0.1", 8001))
    except OSError:
        sys.exit("ERREUR : port 8001 déjà occupé.")

print("JWT : OK")
print("Port 8001 : disponible")
PY

echo
echo "Démarrage Whatzabi Admin..."
echo "Adresse : http://127.0.0.1:8001/admin/login"
echo

exec "$PYTHON" -m uvicorn app.main:app \
  --host 127.0.0.1 \
  --port 8001
