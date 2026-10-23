#!/usr/bin/env bash
# Restore a dump made by backup_db.sh into an EMPTY database, then report the schema revision.
#
#   DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/agentmesh_restore ops/restore_db.sh agentmesh-....dump
#
# Restore into a new database and point the API at it after checking it; never restore over a live one.
# Afterwards run `alembic upgrade head` if the dump predates the deployed code, then
# GET /api/v1/admin/reconciliation to confirm the ledger is consistent.
set -euo pipefail

file="${1:?usage: restore_db.sh <dump file>}"
url="${DATABASE_URL:?DATABASE_URL is required}"
url="${url/postgresql+asyncpg:/postgresql:}"
pg_restore="${PG_RESTORE:-pg_restore}"
psql="${PSQL:-psql}"

tables=$($psql "$url" -tAc "select count(*) from information_schema.tables where table_schema='public'")
if [ "$tables" != "0" ]; then
  echo "Refusing to restore: the target database is not empty ($tables tables)." >&2
  exit 1
fi
$pg_restore --no-owner --no-privileges --exit-on-error --dbname="$url" < "$file"
echo "Restored $file; schema revision: $($psql "$url" -tAc 'select version_num from alembic_version')"
