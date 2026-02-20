"""
OAuth2 token flow for cloud storage backends (Google Drive, OneDrive).

The flow:
1. Frontend calls POST /storage/oauth/start with provider + client_id + client_secret
2. Backend returns an auth_url the user must visit
3. User authorises in browser, gets redirected to GET /storage/oauth/callback
4. Backend exchanges the code for tokens and stores them in a short-lived cache (Redis)
5. Frontend polls GET /storage/oauth/token/{state} to retrieve the token JSON

State is stored in Redis so it works across multiple uvicorn workers.
"""

import json
import logging
import secrets
from datetime import datetime, timezone, timedelta
from urllib.parse import urlencode

import httpx
import redis

from api.config import get_settings

logger = logging.getLogger(__name__)

_REDIS_PREFIX = "vm:oauth:"
_TOKEN_TTL = 600  # seconds


def _redis() -> redis.Redis:
    """Get a Redis connection."""
    settings = get_settings()
    return redis.from_url(settings.redis_url, decode_responses=True)


# ── Provider definitions ──

PROVIDERS = {
    "gdrive": {
        "auth_url": "https://accounts.google.com/o/oauth2/v2/auth",
        "token_url": "https://oauth2.googleapis.com/token",
        "scopes": "https://www.googleapis.com/auth/drive",
    },
    "onedrive": {
        "auth_url": "https://login.microsoftonline.com/common/oauth2/v2.0/authorize",
        "token_url": "https://login.microsoftonline.com/common/oauth2/v2.0/token",
        "scopes": "Files.ReadWrite.All offline_access",
    },
}


def get_redirect_uri(base_url: str) -> str:
    """Build the OAuth callback URI."""
    return f"{base_url.rstrip('/')}/api/v1/storage/oauth/callback"


def start_oauth(provider: str, client_id: str, client_secret: str, base_url: str) -> dict:
    """Start an OAuth flow. Returns {auth_url, state, redirect_uri}."""
    if provider not in PROVIDERS:
        raise ValueError(f"Unknown OAuth provider: {provider}")

    prov = PROVIDERS[provider]
    state = secrets.token_urlsafe(32)
    redirect_uri = get_redirect_uri(base_url)

    flow = {
        "provider": provider,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "token": "",
    }
    r = _redis()
    r.setex(f"{_REDIS_PREFIX}{state}", _TOKEN_TTL, json.dumps(flow))

    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": prov["scopes"],
        "state": state,
        "access_type": "offline",
        "prompt": "consent",
    }

    auth_url = f"{prov['auth_url']}?{urlencode(params)}"
    return {"auth_url": auth_url, "state": state, "redirect_uri": redirect_uri}


async def handle_callback(state: str, code: str) -> str:
    """Exchange auth code for tokens. Returns an HTML page that auto-closes."""
    r = _redis()
    raw = r.get(f"{_REDIS_PREFIX}{state}")
    if not raw:
        return _error_html("OAuth state expired or invalid. Please try again from VaultMaster.")

    flow = json.loads(raw)
    provider = flow["provider"]
    prov = PROVIDERS[provider]

    # Exchange code for token
    token_data = {
        "client_id": flow["client_id"],
        "client_secret": flow["client_secret"],
        "code": code,
        "redirect_uri": flow["redirect_uri"],
        "grant_type": "authorization_code",
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(prov["token_url"], data=token_data)
            resp.raise_for_status()
            token_json = resp.json()
    except Exception as e:
        logger.error(f"OAuth token exchange failed for {provider}: {e}")
        return _error_html(f"Token exchange failed: {e}")

    # Build rclone-compatible token JSON
    # rclone expects expiry as ISO 8601 timestamp, not expires_in seconds
    expires_in = token_json.get("expires_in", 3600)
    expiry_time = datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
    rclone_token = {
        "access_token": token_json.get("access_token", ""),
        "token_type": token_json.get("token_type", "Bearer"),
        "refresh_token": token_json.get("refresh_token", ""),
        "expiry": expiry_time.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }

    flow["token"] = json.dumps(rclone_token)
    # Save back with remaining TTL
    ttl = r.ttl(f"{_REDIS_PREFIX}{state}")
    r.setex(f"{_REDIS_PREFIX}{state}", max(ttl, 60), json.dumps(flow))
    logger.info(f"OAuth token obtained for {provider} (state={state[:8]}...)")

    return _success_html()


def get_token(state: str) -> dict:
    """Retrieve token for a completed OAuth flow."""
    r = _redis()
    raw = r.get(f"{_REDIS_PREFIX}{state}")
    if not raw:
        return {"status": "expired"}
    flow = json.loads(raw)
    if not flow.get("token"):
        return {"status": "pending"}
    token = flow["token"]
    # Clean up after retrieval
    r.delete(f"{_REDIS_PREFIX}{state}")
    return {"status": "complete", "token": token}


def _success_html() -> str:
    return """<!DOCTYPE html>
<html><head><title>VaultMaster — Authorization Complete</title>
<style>
  body { background: #0a0e14; color: #e0e0e0; font-family: monospace; display: flex;
         align-items: center; justify-content: center; height: 100vh; margin: 0; }
  .box { text-align: center; }
  h1 { color: #00ccff; font-size: 24px; }
  p { color: #888; font-size: 14px; }
</style></head>
<body><div class="box">
  <h1>✓ AUTHORIZATION COMPLETE</h1>
  <p>You can close this window and return to VaultMaster.</p>
  <p>The token has been saved automatically.</p>
  <script>setTimeout(() => window.close(), 3000);</script>
</div></body></html>"""


def _error_html(message: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><title>VaultMaster — Authorization Failed</title>
<style>
  body {{ background: #0a0e14; color: #e0e0e0; font-family: monospace; display: flex;
         align-items: center; justify-content: center; height: 100vh; margin: 0; }}
  .box {{ text-align: center; }}
  h1 {{ color: #ff4444; font-size: 24px; }}
  p {{ color: #888; font-size: 14px; max-width: 500px; }}
</style></head>
<body><div class="box">
  <h1>✗ AUTHORIZATION FAILED</h1>
  <p>{message}</p>
</div></body></html>"""
