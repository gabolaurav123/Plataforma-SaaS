"""Run once after setting ONLY the new Master Bot credentials and HTTPS URLs."""

from platform_app.runtime import Runtime
from platform_app.errors import DomainError

try:
    runtime = Runtime()
    if runtime.settings.environment == "production" and not runtime.settings.master_bot_username:
        raise SystemExit("MASTER_BOT_USERNAME is required to verify the new Master before configuring it.")
    result = runtime.manager.configure_master()
    print(result["message"])
    for instruction in result["instructions"]:
        print(instruction)
except DomainError as error:
    print(error.code + ": " + error.message)
    raise SystemExit(1) from None
