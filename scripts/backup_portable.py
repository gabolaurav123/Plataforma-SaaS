"""Encrypted logical backup for a database managed exclusively by these migrations.

Uses one repeatable-read, read-only transaction. Includes schema and application
records, not PostgreSQL server roles or external storage. Prefer pg_dump for an
independently modified database. The restore drill verifies every included row.
"""

import argparse
import base64
import gzip
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from platform_app.security import LocalKeyring, Vault


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-host", required=True)
    parser.add_argument("--expect-version", default="0004")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args()
    uri = os.environ["MIGRATION_DATABASE_URL"]
    assert make_url(uri).host == args.expect_host, "Target host differs from the approved database"
    root = Path(__file__).resolve().parents[1]
    schema = (root / "docs/schema-postgres.sql").read_text(encoding="utf-8")
    marker = "-- Running upgrade 0004 -> 0005"
    if args.expect_version == "0004":
        schema = schema.split(marker)[0] + "COMMIT;\n"
    elif args.expect_version == "0005":
        schema = schema.split("-- Running upgrade 0005 -> 0006")[0] + "COMMIT;\n"
    elif args.expect_version != "0006":
        raise ValueError("Only the checked migration versions are supported")
    engine = create_engine(uri, connect_args={"connect_timeout": 20}, isolation_level="REPEATABLE READ")
    columns_sql = """SELECT c.relname AS table_name, a.attname AS column_name,
        format_type(a.atttypid,a.atttypmod) AS type, a.attnotnull AS required
        FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
        JOIN pg_attribute a ON a.attrelid=c.oid
        WHERE n.nspname='public' AND c.relkind='r' AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY c.relname,a.attnum"""
    try:
        with engine.connect() as db, db.begin():
            db.execute(text("SET TRANSACTION READ ONLY"))
            version = db.scalar(text("SELECT version_num FROM alembic_version"))
            assert version == args.expect_version, "Unexpected database migration version"
            columns = [dict(row) for row in db.execute(text(columns_sql)).mappings()]
            dependencies = list(
                db.execute(
                    text("""SELECT child.relname,parent.relname
                FROM pg_constraint f JOIN pg_class child ON child.oid=f.conrelid
                JOIN pg_class parent ON parent.oid=f.confrelid JOIN pg_namespace n ON n.oid=child.relnamespace
                WHERE f.contype='f' AND n.nspname='public'""")
                )
            )
            tables = {row["table_name"]: {"columns": [], "rows": []} for row in columns}
            for column in columns:
                tables[column["table_name"]]["columns"].append(column)
            for name, table in tables.items():
                quoted = engine.dialect.identifier_preparer.quote(name)
                fields = []
                for column in table["columns"]:
                    field = engine.dialect.identifier_preparer.quote(column["column_name"])
                    fields.append(field + ("::text AS " + field if column["type"] == "bigint" else ""))
                table["rows"] = [
                    dict(row)
                    for row in db.execute(text("SELECT " + ",".join(fields) + " FROM " + quoted)).mappings()
                ]
            order = []
            while len(order) < len(tables):
                ready = [
                    name
                    for name in tables
                    if name not in order
                    and all(
                        parent in order or parent == name for child, parent in dependencies if child == name
                    )
                ]
                assert ready, "Cyclic foreign keys require pg_dump instead"
                order.extend(ready)
    finally:
        engine.dispose()
    backup = {
        "format": 1,
        "version": version,
        "created_at": int(time.time()),
        "schema": schema,
        "columns_sql": columns_sql,
        "order": order,
        "tables": tables,
    }
    serialized = json.dumps(backup, ensure_ascii=False, separators=(",", ":"))
    vault = Vault(
        LocalKeyring(json.loads(os.environ["ENCRYPTION_KEYS"]), os.environ.get("ACTIVE_KEY_VERSION", "v1"))
    )
    context = "database-backup:" + str(backup["created_at"])
    envelope = {
        "format": 1,
        "context": context,
        "sha256": hashlib.sha256(serialized.encode()).hexdigest(),
        "ciphertext": vault.encrypt(base64.b64encode(gzip.compress(serialized.encode())).decode(), context),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as file:
        json.dump(envelope, file)
    if args.verify:
        # Verify the saved encrypted file, not only the pre-encryption in-memory rows.
        saved = json.loads(args.output.read_text(encoding="utf-8"))
        restored = gzip.decompress(base64.b64decode(vault.decrypt(saved["ciphertext"], saved["context"])))
        assert hashlib.sha256(restored).hexdigest() == saved["sha256"]
        result = subprocess.run(
            ["node", str(root / "qa/restore-backup.mjs")],
            input=restored,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode:
            sys.stdout.write(result.stdout.decode("utf-8", errors="replace"))
            raise RuntimeError("Isolated restoration failed; production was not changed")
        sys.stdout.write(result.stdout.decode())
    print(
        json.dumps(
            {
                "encrypted_backup": str(args.output.resolve()),
                "migration_version": version,
                "tables": len(tables),
                "rows": sum(len(table["rows"]) for table in tables.values()),
                "sha256": envelope["sha256"],
            }
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Database driver exceptions can contain values or credentials.
        print(json.dumps({"backup_failed": type(error).__name__}))
        raise SystemExit(1) from None
