import json
import logging
import httpx
from sqlalchemy import select
from .models import BotSecret
from .errors import DomainError, RetryLater

# HTTPX includes the URL (and hence Bot API credentials) in INFO messages.
logging.getLogger("httpx").disabled = True
logging.getLogger("httpcore").disabled = True


class TelegramError(DomainError):
    pass


class BotClient:
    def __init__(self, token: str, test_environment=False, transport=None):
        self._token, self.test_environment, self.transport = token, test_environment, transport

    def __repr__(self):
        return "BotClient(token=[REDACTED])"

    def call(self, method: str, *, files=None, **parameters):
        if not self._token:
            raise TelegramError("MASTER_NOT_CONFIGURED", "Falta configurar el Master Bot.", 503)
        base = f"https://api.telegram.org/bot{self._token}/{'test/' if self.test_environment else ''}"
        try:
            with httpx.Client(timeout=8, transport=self.transport, follow_redirects=False) as client:
                if files:
                    data = {
                        k: json.dumps(v) if isinstance(v, (dict, list, bool)) else str(v)
                        for k, v in parameters.items()
                    }
                    response = client.post(base + method, data=data, files=files)
                else:
                    response = client.post(base + method, json=parameters)
                result = response.json()
        except (httpx.HTTPError, ValueError):
            raise TelegramError(
                "TELEGRAM_TRANSPORT_UNKNOWN", "No se pudo confirmar la respuesta de Telegram.", 502
            ) from None
        if not result.get("ok"):
            code = result.get("error_code", response.status_code)
            if code == 429:
                raise RetryLater(int(result.get("parameters", {}).get("retry_after", 5)))
            safe_code = {401: "TOKEN_INVALID", 403: "TELEGRAM_FORBIDDEN", 400: "TELEGRAM_BAD_REQUEST"}.get(
                code, "TELEGRAM_API_ERROR"
            )
            raise TelegramError(
                safe_code, "Telegram rechazó la operación. Revisa el estado y los permisos del bot.", 502
            )
        return result["result"]

    def download(self, file_id: str, max_bytes: int):
        info = self.call("getFile", file_id=file_id)
        if info.get("file_size", 0) > max_bytes:
            raise DomainError("UPLOAD_SIZE", "Archivo demasiado grande.", 413)
        path = info.get("file_path", "")
        if not path or ".." in path or ":" in path or path.startswith("/"):
            raise DomainError("INVALID_FILE", "Archivo no disponible.")
        url = (
            f"https://api.telegram.org/file/bot{self._token}/{'test/' if self.test_environment else ''}{path}"
        )
        try:
            with (
                httpx.Client(timeout=10, transport=self.transport) as client,
                client.stream("GET", url) as response,
            ):
                response.raise_for_status()
                data = bytearray()
                for chunk in response.iter_bytes():
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise DomainError("UPLOAD_SIZE", "Archivo demasiado grande.", 413)
                return bytes(data)
        except httpx.HTTPError:
            raise TelegramError("TELEGRAM_DOWNLOAD_FAILED", "No se pudo descargar el archivo.", 502) from None


class BotClients:
    def __init__(self, settings, vault, factory=BotClient):
        self.settings, self.vault, self.factory = settings, vault, factory

    def master(self):
        return self.factory(
            self.settings.master_bot_token.get_secret_value(), self.settings.telegram_test_environment
        )

    def child(self, session, bot):
        secret = session.scalar(
            select(BotSecret).where(BotSecret.bot_id == bot.id, BotSecret.tenant_id == bot.tenant_id)
        )
        if not secret:
            raise DomainError("TOKEN_NOT_READY", "El bot sigue en configuración.", 409)
        token = self.vault.decrypt(secret.token_ciphertext, f"{bot.tenant_id}:{bot.id}:token")
        return self.factory(token, self.settings.telegram_test_environment)
