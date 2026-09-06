"""Generate development secrets only in THIS project's ignored .env. Never reads legacy configuration."""

import base64
import json
import os
from pathlib import Path

root = Path(__file__).resolve().parents[1]
path = root / ".env"
if path.exists():
    raise SystemExit(".env already exists; preserved without changes.")
key = base64.b64encode(os.urandom(32)).decode()
path.write_text(
    "ENVIRONMENT=development\nDATABASE_URL=sqlite:///./platform.db\n"
    + "ENCRYPTION_KEYS='"
    + json.dumps({"v1": key})
    + "'\nACTIVE_KEY_VERSION=v1\n"
    + "MASTER_BOT_TOKEN=\nMASTER_WEBHOOK_SECRET="
    + base64.urlsafe_b64encode(os.urandom(32)).decode().rstrip("=")
    + "\nMASTER_BOT_USERNAME=\nPLATFORM_OWNER_IDS=\nPUBLIC_API_URL=http://localhost:8000\nMINI_APP_URL=http://localhost:3000\n"
    + "ALLOWED_ORIGINS=http://localhost:3000\nDEMO_ENABLED=false\n",
    encoding="utf-8",
)
with path.open("a", encoding="utf-8") as output:
    output.write(
        "POSTGRES_PASSWORD=" + os.urandom(32).hex() + "\nPLATFORM_API_PASSWORD=" + os.urandom(32).hex() + "\n"
    )
print("Created local .env with random encryption and webhook keys. Telegram credentials remain empty.")
