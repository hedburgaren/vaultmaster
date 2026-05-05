"""Audit-logging middleware.

Catches every mutating request (POST/PUT/PATCH/DELETE) under /api/v1/
and writes an audit_log row capturing:

  - the resolved user (if any) — extracted from the same JWT/API-key
    flow get_current_user uses; null for unauthenticated attempts
  - HTTP method + path
  - response status code (success and failure alike)
  - client IP
  - meta: {"status_code": …, "unauthenticated": True/False,
           "had_authorization_header": True/False}

Routers that already write a domain-specific audit row (e.g. credentials,
mcp_clients) keep doing so — the middleware adds a generic row that
captures the request envelope. This is the cheap blanket coverage; a
domain-specific row is what we read for "what changed" detail.

Bug #6 history: this middleware previously short-circuited on
status >= 400 *and* user is None, which left brute-force attempts
and 401/403 floods invisible. We now log them all.

Skip list: /auth/login, /auth/setup, /auth/setup-status (these have
their own auth-specific audit lines where appropriate, and login can't
be middleware-audited because the token isn't issued yet).
"""

from __future__ import annotations

import logging

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


logger = logging.getLogger(__name__)


_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_SKIP_PREFIXES = (
    "/api/v1/auth/login",
    "/api/v1/auth/setup",
    "/api/v1/auth/setup-status",
)


def _client_ip(request: Request) -> str | None:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else None


async def _resolve_user(request: Request):
    """Best-effort user resolution. Returns None if anything goes wrong —
    the middleware should never fail a request because of audit hiccups."""
    auth = request.headers.get("authorization")
    api_key = request.headers.get("x-api-key")
    if not auth and not api_key:
        return None

    try:
        import jwt
        from sqlalchemy import select
        from api.config import get_settings
        from api.database import async_session
        from api.models.user import User
        from api.auth import hash_api_key

        settings = get_settings()

        async with async_session() as db:
            if api_key:
                result = await db.execute(
                    select(User).where(User.api_key_hash == hash_api_key(api_key))
                )
                u = result.scalar_one_or_none()
                if u:
                    return u

            if auth and auth.lower().startswith("bearer "):
                token = auth.split(" ", 1)[1]
                try:
                    payload = jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])
                    sub = payload.get("sub")
                except Exception:
                    return None
                if sub:
                    result = await db.execute(select(User).where(User.username == sub))
                    return result.scalar_one_or_none()
    except Exception as exc:  # never let audit middleware break a request
        logger.debug("audit middleware: user resolution failed: %s", exc)
        return None
    return None


class AuditLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response: Response = await call_next(request)

        try:
            method = request.method
            path = request.url.path
            if method not in _MUTATING_METHODS:
                return response
            if not path.startswith("/api/v1/"):
                return response
            if any(path.startswith(p) for p in _SKIP_PREFIXES):
                return response

            # Bug #6 — previously this middleware skipped 4xx responses *and*
            # unauthenticated requests, so a flood of 401/403 attempts left
            # zero trace. We now log everything that survives the skip-list
            # and the method/path filter; meta carries enough context to
            # reconstruct the attempt without polluting the main columns.
            user = await _resolve_user(request)
            unauthenticated = user is None

            from api.database import async_session
            from api.routers.audit import log_action

            meta: dict = {"status_code": response.status_code}
            if unauthenticated:
                meta["unauthenticated"] = True
                meta["had_authorization_header"] = bool(
                    request.headers.get("authorization") or request.headers.get("x-api-key")
                )

            async with async_session() as db:
                await log_action(
                    db,
                    action=f"http.{method.lower()}",
                    user=user,
                    resource_type=path.lstrip("/").split("/")[2] if path.startswith("/api/v1/") else None,
                    resource_id=None,
                    detail=f"{method} {path} → {response.status_code}",
                    meta=meta,
                    ip_address=_client_ip(request),
                )
                await db.commit()
        except Exception as exc:
            logger.warning("audit middleware: log write failed: %s", exc)

        return response
