"""Run once after setting ONLY the new Master Bot credentials and HTTPS URLs."""

from platform_app.runtime import Runtime
from platform_app.errors import DomainError

try:
    result = Runtime().manager.configure_master()
    print(result["message"])
    for instruction in result["instructions"]:
        print(instruction)
except DomainError as error:
    print(error.code + ": " + error.message)
    raise SystemExit(1) from None
