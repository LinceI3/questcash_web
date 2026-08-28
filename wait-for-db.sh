#!/bin/sh
# Punto de entrada del contenedor de QuestCash.
#
# Espera a que Postgres acepte conexiones y entrega el proceso a gunicorn.
# NO arranca `python app.py`: ese es el servidor de desarrollo de Werkzeug,
# mono-hilo y con consola de depuración. En producción sirve gunicorn.
set -e

DB_HOST="${DB_HOST:-db}"
DB_PORT="${DB_PORT:-5432}"

echo "Esperando a la base de datos en ${DB_HOST}:${DB_PORT}..."
while ! nc -z "$DB_HOST" "$DB_PORT"; do
  sleep 1
done
echo "Base de datos lista"

# `exec` deja a gunicorn como PID 1 para que reciba SIGTERM directamente
# y cierre las conexiones de forma ordenada al parar el contenedor.
exec gunicorn \
  --bind "0.0.0.0:${PORT:-5000}" \
  --workers "${GUNICORN_WORKERS:-2}" \
  --timeout "${GUNICORN_TIMEOUT:-60}" \
  --graceful-timeout 30 \
  --access-logfile - \
  --error-logfile - \
  app:app
