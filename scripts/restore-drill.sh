#!/bin/sh
set -eu
# Restores ONLY to a new isolated database, never over the operating database.
: "${BACKUP_FILE:?Set path to a database dump}"
case "${RESTORE_DATABASE:-}" in creator_restore_*) ;; *) echo 'RESTORE_DATABASE must start with creator_restore_' >&2; exit 1;; esac
docker compose exec -T db createdb -U platform_system "$RESTORE_DATABASE"
docker compose exec -T db pg_restore -U platform_system --no-owner -d "$RESTORE_DATABASE" < "$BACKUP_FILE"
docker compose exec -T db psql -U platform_system -d "$RESTORE_DATABASE" -c 'SELECT version_num FROM alembic_version; SELECT count(*) FROM tenants; SELECT count(*) FROM managed_bots;'
echo 'Retained isolated restored database for inspection. No operating database was overwritten.'
