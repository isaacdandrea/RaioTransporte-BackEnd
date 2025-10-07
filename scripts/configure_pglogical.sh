#!/usr/bin/env bash
set -euo pipefail

CONTAINER_NAME="mobilidade_postgis"
DB_NAME="mobilidadenew"
DB_USER="mobilidade"

if ! docker ps --format '{{.Names}}' | grep -q "^${CONTAINER_NAME}$"; then
  echo "Container ${CONTAINER_NAME} is not running." >&2
  exit 1
fi

echo "[1/5] Installing pglogical extension package inside ${CONTAINER_NAME}..."
docker exec -u root "${CONTAINER_NAME}" bash -lc "apt-get update && apt-get install -y --no-install-recommends postgresql-15-pglogical && rm -rf /var/lib/apt/lists/*"

echo "[2/5] Ensuring target database ${DB_NAME} exists..."
docker exec -u postgres "${CONTAINER_NAME}" psql -tAc "SELECT 1 FROM pg_database WHERE datname='${DB_NAME}'" | grep -q 1 || \
  docker exec -u postgres "${CONTAINER_NAME}" createdb -O "${DB_USER}" "${DB_NAME}"

echo "[3/5] Creating pglogical extension in ${DB_NAME}..."
docker exec -u postgres "${CONTAINER_NAME}" psql -v ON_ERROR_STOP=1 -d "${DB_NAME}" -c "CREATE EXTENSION IF NOT EXISTS pglogical;"

echo "[4/5] Setting wal_level to logical..."
docker exec -u postgres "${CONTAINER_NAME}" psql -v ON_ERROR_STOP=1 -d postgres -c "ALTER SYSTEM SET wal_level = 'logical';"

echo "[5/5] Restarting ${CONTAINER_NAME} to apply wal_level change..."
docker restart "${CONTAINER_NAME}"

echo "Done. wal_level is now:"
docker exec -u postgres "${CONTAINER_NAME}" psql -tAc "SHOW wal_level;"

echo "Installed extensions in ${DB_NAME}:"
docker exec -u postgres "${CONTAINER_NAME}" psql -d "${DB_NAME}" -c "\\dx pglogical"
