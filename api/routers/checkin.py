"""POST /servers/checkin: the laptop's call, authenticated by its own token.

Deliberately not under the servers router, whose every route needs a user
login. This one needs only X-Checkin-Token, and the token grants nothing but
"queue the due jobs of the server it belongs to".
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from api.database import get_db
from api.rate_limiter import limiter
from api.routers.audit import log_action
from api.services import checkin as svc

router = APIRouter(prefix="/servers", tags=["checkin"])


@router.post("/checkin")
@limiter.limit("30/minute")
async def checkin(
    request: Request,
    x_checkin_token: str | None = Header(default=None),
    db: AsyncSession = Depends(get_db),
):
    # Same derivation as the audit middleware and the MCP server (first
    # X-Forwarded-For, else the peer), so the check-in audit row names the same
    # address as the generic row the middleware writes for this request. The
    # rate limit itself uses the shared limiter, like every other public route:
    # slowapi get_remote_address, the socket peer, which ignores the header and
    # so cannot be dodged by a forged X-Forwarded-For.
    from api.middleware.audit import _client_ip
    ip = _client_ip(request)
    try:
        server = await svc.authenticate(db, x_checkin_token)
    except svc.CheckinRejected:
        # One answer for every reason, so the response says nothing about
        # which tokens exist. The audit middleware logs the 401 with the IP.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid check-in token")

    from api.tasks.backup_tasks import _redis_or_none
    redis_client = _redis_or_none("checkin")
    hours = float(getattr(get_settings(), "checkin_min_interval_hours", 10) or 10)
    try:
        result = await svc.process_checkin(db, server, redis_client, hours)
    finally:
        if redis_client is not None:
            try:
                redis_client.close()
            except Exception:
                pass

    await log_action(
        db,
        action="server.checkin",
        resource_type="server",
        resource_id=str(server.id),
        detail=f"Check-in from {server.name}: {len(result['queued'])} queued, {len(result['skipped'])} skipped",
        meta={"queued": result["queued"], "skipped": result["skipped"]},
        ip_address=ip,
    )
    return result
