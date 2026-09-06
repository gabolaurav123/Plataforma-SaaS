#!/bin/sh
set -eu
umask 077
: "${BACKUP_DIR:?Set a private backup destination}"
mkdir -p "$BACKUP_DIR"
backup_name="creator-platform-$(date -u +%Y%m%dT%H%M%SZ).dump"
docker compose exec -T db pg_dump -U platform_system -d creator_platform -Fc > "$BACKUP_DIR/$backup_name"
chmod 600 "$BACKUP_DIR/$backup_name"
sha256sum "$BACKUP_DIR/$backup_name"
receipt_name="${backup_name%.dump}-receipts.tar.gz"
docker compose exec -T api tar -C /app/storage -czf - . > "$BACKUP_DIR/$receipt_name"
sha256sum "$BACKUP_DIR/$receipt_name"
