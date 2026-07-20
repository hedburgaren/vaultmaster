import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from sqlalchemy import inspect
from starlette.middleware.base import BaseHTTPMiddleware

from api.config import get_settings
from api.database import engine, Base
from api.models import *  # noqa: F401 — register all models
from api.rate_limiter import limiter

logger = logging.getLogger(__name__)
settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: create tables. Wrap in try/except so a worker that loses
    # the race vs. another uvicorn worker (both trying create_all against
    # fresh tables at the same time) doesn't fail the entire startup —
    # has_table-checkfirst is racy because the implicit composite TYPE
    # gets created before the TABLE commit is visible to peers.
    try:
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
    except Exception as exc:
        msg = str(exc)
        if "already exists" in msg or "UniqueViolationError" in msg:
            # DDL is transactional in Postgres, so engine.begin() rolled back
            # everything create_all had built in THIS transaction, not just the
            # object that collided. In the peer-worker race that is harmless
            # because the winner committed the full schema. It is not harmless
            # when the collision comes from a leftover index or type from a
            # removed model: then nothing was created, the exception is
            # swallowed, and the API logs "started" over an incomplete schema.
            #
            # So verify rather than assume. The tables either exist or they do
            # not, and that is a cheap question to ask.
            logger.warning("create_all raised %r, verifying the schema is actually present", msg[:200])
            try:
                async with engine.begin() as conn:
                    present = set(await conn.run_sync(
                        lambda sync_conn: inspect(sync_conn).get_table_names()
                    ))
            except Exception as probe_exc:
                logger.critical("could not verify schema after create_all raced: %s", probe_exc)
                raise
            expected = set(Base.metadata.tables.keys())
            missing = expected - present
            if missing:
                logger.critical(
                    "create_all did not complete and %d table(s) are MISSING: %s. "
                    "Refusing to start: an API serving an incomplete schema fails "
                    "in ways that look like data loss.",
                    len(missing), ", ".join(sorted(missing)),
                )
                raise RuntimeError(f"incomplete schema, missing tables: {sorted(missing)}")
            logger.warning("create_all race vs. peer worker, all %d tables present, continuing", len(expected))
        else:
            raise

    # A model column without its migration passes create_all (which ignores
    # columns on existing tables), passes startup, passes the health check,
    # and then breaks every query touching that table. Happened 2026-07-19
    # with backup_artifact.purged_at. Refuse to start instead.
    from api.services.schema_guard import assert_schema_matches
    n_tables = await assert_schema_matches()
    # print, not logger: module loggers are not routed through uvicorn's
    # config, so the confirmation was invisible and the guard's execution
    # could not be distinguished from its absence.
    import sys as _sys
    print(f"schema guard (api): {n_tables} tables match their models",
          file=_sys.stderr, flush=True)

    logger.info("VaultMaster API started")
    yield
    # Shutdown
    await engine.dispose()
    logger.info("VaultMaster API stopped")


app = FastAPI(
    title="VaultMaster",
    description="Backup Control Center — REST API",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

from api.middleware.audit import AuditLogMiddleware
app.add_middleware(AuditLogMiddleware)


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded. Try again later."})


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=63072000; includeSubDomains; preload"
        return response


app.add_middleware(SecurityHeadersMiddleware)

allowed_origins = [o.strip() for o in (settings.allowed_origins or "").split(",") if o.strip()]
_env = (os.environ.get("ENV") or os.environ.get("ENVIRONMENT") or "").lower()
if not allowed_origins:
    if _env in ("prod", "production"):
        raise RuntimeError(
            "ALLOWED_ORIGINS must be set when ENV=production. "
            "Refusing to start with wildcard CORS + allow_credentials=True."
        )
    # Dev/test fallback — explicit, no wildcard. Loopback only.
    allowed_origins = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:8100",
        "http://127.0.0.1:8100",
    ]
    logger.warning(
        "ALLOWED_ORIGINS not set; falling back to loopback origins (%s). "
        "Set ALLOWED_ORIGINS in the env for production.",
        allowed_origins,
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-API-Key"],
)

# Register routers
from api.routers import auth, servers, jobs, runs, artifacts, storage, retention, notifications, dashboard, audit, webhooks, users, metrics, system_settings, validations, credentials, mcp_clients
from api.mcp import server as mcp_server

app.include_router(auth.router, prefix="/api/v1")
app.include_router(servers.router, prefix="/api/v1")
app.include_router(jobs.router, prefix="/api/v1")
app.include_router(runs.router, prefix="/api/v1")
app.include_router(artifacts.router, prefix="/api/v1")
app.include_router(storage.router, prefix="/api/v1")
app.include_router(retention.router, prefix="/api/v1")
app.include_router(notifications.router, prefix="/api/v1")
app.include_router(dashboard.router, prefix="/api/v1")
app.include_router(audit.router, prefix="/api/v1")
app.include_router(webhooks.router, prefix="/api/v1")
app.include_router(users.router, prefix="/api/v1")
app.include_router(system_settings.router, prefix="/api/v1")
app.include_router(validations.router, prefix="/api/v1")
app.include_router(credentials.router, prefix="/api/v1")
app.include_router(mcp_clients.router, prefix="/api/v1")
app.include_router(mcp_server.router, prefix="/api")
app.include_router(metrics.router, prefix="/api")


@app.get("/api/health")
async def health():
    """Report whether the dependencies this service cannot work without are up.

    Used to return a static {"status": "ok"} that could not fail. A health check
    that cannot fail is not a health check: it reports the web process is
    accepting connections, which the caller already knew by getting a response,
    and stays green through a dead database or a stopped worker.

    Returns 503 when a dependency is down, so anything watching this endpoint
    finds out from the endpoint rather than from a missing backup.
    """
    from sqlalchemy import text as _text

    from api.database import async_session

    checks: dict[str, str] = {}
    healthy = True

    try:
        async with async_session() as session:
            await session.execute(_text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"FAILED: {type(e).__name__}: {str(e)[:120]}"
        healthy = False

    try:
        import redis.asyncio as _redis

        client = _redis.from_url(get_settings().redis_url)
        try:
            await client.ping()
            checks["redis"] = "ok"
        finally:
            await client.aclose()
    except Exception as e:
        checks["redis"] = f"FAILED: {type(e).__name__}: {str(e)[:120]}"
        healthy = False

    body = {
        "status": "ok" if healthy else "degraded",
        "service": "vaultmaster",
        "checks": checks,
    }
    if not healthy:
        return JSONResponse(status_code=503, content=body)
    return body
