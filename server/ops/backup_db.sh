#!/usr/bin/env bash
# Back up the AgentMesh PostgreSQL database to a compressed, timestamped custom-format dump.
#
#   DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/agentmesh ops/backup_db.sh /var/backups/agentmesh
#
# Keeps the newest $KEEP dumps (default 14) in the target directory. Set PG_DUMP to use a specific binary
# (it must be at least the server's major version), e.g. PG_DUMP="docker run --rm --network host postgres:16 pg_dump".
set -euo pipefail

dest="${1:?usage: backup_db.sh <directory>}"
url="${DATABASE_URL:?DATABASE_URL is required}"
url="${url/postgresql+asyncpg:/postgresql:}"   # libpq does not know the SQLAlchemy driver suffix
keep="${KEEP:-14}"
pg_dump="${PG_DUMP:-pg_dump}"

mkdir -p "$dest"
umask 077   # dumps contain account and ledger data
file="$dest/agentmesh-$(date -u +%Y%m%dT%H%M%SZ).dump"
$pg_dump --format=custom --no-owner --no-privileges --dbname="$url" > "$file.partial"
mv "$file.partial" "$file"
echo "Wrote $file ($(du -h "$file" | cut -f1))"

ls -1t "$dest"/agentmesh-*.dump 2>/dev/null | tail -n +"$((keep + 1))" | xargs -r rm -f
