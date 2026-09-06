"""Optional webhook-only HTTP listener in the same process. No website or Mini App."""

import json
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from .errors import DomainError, RetryLater
from .api.webhooks import ingest
from .services.external_payments import receive


def create_ingress(runtime):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.state.runtime = runtime

    async def read_body(request):
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 512 * 1024:
                raise DomainError("BODY_TOO_LARGE", "Solicitud demasiado grande.", 413)
        return bytes(body)

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse({"code": error.code}, status_code=error.status)

    @app.exception_handler(RetryLater)
    async def retry(request, error):
        return JSONResponse(
            {"code": error.code}, status_code=503, headers={"Retry-After": str(error.seconds)}
        )

    @app.middleware("http")
    async def safe_errors(request, call_next):
        # Catch inside the ASGI stack: ServerErrorMiddleware otherwise re-raises
        # and an access path containing an unguessable webhook key may be logged.
        try:
            return await call_next(request)
        except Exception:
            return JSONResponse({"code": "WEBHOOK_UNAVAILABLE"}, status_code=503)

    @app.get("/health/live")
    def live():
        return {"status": "ok", "service": "telegram-platform"}

    @app.post("/payments/hooks/{key}")
    async def payments(key: str, request: Request):
        if not runtime.settings.payment_webhooks_enabled:
            raise DomainError("NOT_FOUND", "Servicio no habilitado.", 404)
        try:
            await run_in_threadpool(receive, runtime, key, await read_body(request), dict(request.headers))
        except (ValueError, KeyError, TypeError):
            raise DomainError("INVALID_EVENT", "Evento no válido.") from None
        return {"ok": True}

    @app.post("/telegram/webhook/{key}")
    async def telegram(key: str, request: Request):
        if runtime.settings.telegram_transport != "webhook":
            raise DomainError("NOT_FOUND", "Servicio no habilitado.", 404)
        try:
            update = json.loads(await read_body(request))
        except ValueError:
            raise DomainError("INVALID_UPDATE", "Evento no válido.") from None
        return await run_in_threadpool(
            ingest, key, request.headers.get("x-telegram-bot-api-secret-token", ""), update, runtime
        )

    return app
