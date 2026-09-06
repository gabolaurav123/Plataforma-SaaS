#!/bin/sh
set -eu
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set=api_password="$PLATFORM_API_PASSWORD" <<'SQL'
CREATE ROLE platform_api LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS PASSWORD :'api_password';
GRANT CONNECT ON DATABASE creator_platform TO platform_api;
GRANT USAGE ON SCHEMA public TO platform_api;
SQL
