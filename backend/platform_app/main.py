import json
import logging
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from .runtime import Runtime
from .errors import DomainError, RetryLater
from .models.base import uid
from .api import creator, customer, resources, owner, webhooks

logger = logging.getLogger("platform.api")


class BodyLimit:
    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        body = bytearray()
        limit = 1024 * 1024 if scope["path"].startswith("/telegram/") else self.max_bytes
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body.extend(message.get("body", b""))
            if len(body) > limit:
                return await JSONResponse(
                    {"code": "BODY_TOO_LARGE", "message": "Archivo demasiado grande."}, status_code=413
                )(scope, receive, send)
            if not message.get("more_body"):
                break
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()

        return await self.app(scope, replay, send)


def create_app(runtime=None):
    r = runtime or Runtime()
    if r.settings.deployment_mode == "telegram":
        raise RuntimeError("El modo Telegram se inicia con python -m platform_app.polling, sin servidor web.")

    @asynccontextmanager
    async def lifespan(app):
        if r.settings.environment == "production":
            r.db.verify_production_boundary()
        yield

    app = FastAPI(
        title="Creator Engine API",
        version="0.1.0",
        description="Central multi-tenant Telegram platform. All amounts are in minor units.",
        lifespan=lifespan,
    )
    app.state.runtime = r
    for router in [creator.router, customer.router, resources.router, owner.router, webhooks.router]:
        app.include_router(router)
    app.add_middleware(BodyLimit, max_bytes=r.settings.max_upload_bytes + 65536)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[x.strip() for x in r.settings.allowed_origins.split(",")],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        expose_headers=["X-Request-ID", "X-Next-Cursor"],
    )

    @app.exception_handler(DomainError)
    async def domain_error(request, error):
        return JSONResponse({"code": error.code, "message": error.message}, status_code=error.status)

    @app.exception_handler(RetryLater)
    async def rate_error(request, error):
        return JSONResponse(
            {"code": "RATE_LIMITED", "message": "Espera un momento e inténtalo de nuevo."},
            status_code=429,
            headers={"Retry-After": str(error.seconds)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        # Pydantic's default response includes invalid inputs; bank data and initData must not be reflected.
        return JSONResponse(
            {
                "code": "INVALID_INPUT",
                "message": "Revisa los campos del formulario.",
                "fields": [".".join(str(x) for x in e["loc"]) for e in error.errors()],
            },
            status_code=422,
        )

    @app.exception_handler(IntegrityError)
    async def conflict(request, error):
        return JSONResponse(
            {"code": "CONFLICT", "message": "La operación ya existe o contiene una referencia no válida."},
            status_code=409,
        )

    @app.middleware("http")
    async def observe(request: Request, call_next):
        request_id, start = uid(), time.monotonic()
        try:
            if request.url.path.startswith("/api/auth"):
                r.limiter.check({f"auth:{request.client.host if request.client else 'unknown'}": 5})
            response = await call_next(request)
        except RetryLater as error:
            response = await rate_error(request, error)
        except Exception:
            logger.error(json.dumps({"request_id": request_id, "code": "INTERNAL_ERROR"}))
            response = JSONResponse(
                {"code": "INTERNAL_ERROR", "message": "No se pudo completar la operación."}, status_code=500
            )
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        logger.info(
            json.dumps(
                {
                    "request_id": request_id,
                    "status": response.status_code,
                    "latency_ms": round((time.monotonic() - start) * 1000, 2),
                }
            )
        )
        return response

    @app.get("/health/live")
    def live():
        return {"status": "ok", "service": "creator-engine"}

    @app.get("/health/ready")
    def ready():
        try:
            if r.settings.environment == "production":
                r.db.verify_production_boundary()
            with r.db.system() as session:
                session.execute(text("SELECT 1"))
                session.execute(text("SELECT version_num FROM alembic_version"))
            if r.limiter.redis:
                r.limiter.redis.ping()
            return {
                "status": "ready",
                "telegram_configured": bool(r.settings.master_bot_token.get_secret_value()),
                "encryption_configured": r.vault is not None,
            }
        except Exception:
            return JSONResponse({"status": "not_ready"}, status_code=503)

    return app


app = create_app()
