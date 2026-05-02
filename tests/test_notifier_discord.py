"""Smoke tests for the Discord notifier branch.

Run with: python -m tests.test_notifier_discord
(no pytest required; uses respx if available, falls back to httpx.MockTransport.)
"""

import asyncio
import json
import sys
from typing import Any

import httpx

from api.services import notifier


class _MockChannel:
    def __init__(self, channel_type: str, config: dict, name: str = "test"):
        self.channel_type = channel_type
        self.config = config
        self.name = name


def _mock_transport(status: int = 204, body: bytes = b""):
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["method"] = request.method
        captured["headers"] = dict(request.headers)
        try:
            captured["json"] = json.loads(request.content) if request.content else None
        except Exception:
            captured["json"] = None
        return httpx.Response(status, content=body)

    return httpx.MockTransport(handler), captured


async def _patch_async_client(transport: httpx.MockTransport):
    """Replace httpx.AsyncClient with one bound to mock transport."""
    original = httpx.AsyncClient

    class _Patched(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = _Patched
    return original


def _restore_client(original):
    httpx.AsyncClient = original


async def test_bridge_mode_success():
    transport, captured = _mock_transport(status=204)
    original = await _patch_async_client(transport)
    try:
        ch = _MockChannel("discord", {
            "bridge_url": "http://arc-discord-bridge:8600",
            "bridge_token": "test-token",
            "channel": "allmänt",
        })
        success, msg = await notifier.send_notification(ch, "Backup Failed", "pg_dump returned 1")
        assert success is True, f"expected success, got {msg}"
        assert "bridge" in msg.lower(), msg
        assert captured["url"].endswith("/send"), captured["url"]
        assert captured["headers"]["x-bridge-token"] == "test-token"
        assert captured["json"]["channel"] == "allmänt"
        assert captured["json"]["embeds"][0]["title"] == "Backup Failed"
        assert captured["json"]["embeds"][0]["color"] == 0xE74C3C
    finally:
        _restore_client(original)


async def test_webhook_mode_success():
    transport, captured = _mock_transport(status=204)
    original = await _patch_async_client(transport)
    try:
        ch = _MockChannel("discord", {
            "webhook_url": "https://discord.com/api/webhooks/123/abc",
        })
        success, msg = await notifier.send_notification(ch, "Backup Successful", "all good")
        assert success is True, f"expected success, got {msg}"
        assert "webhook" in msg.lower(), msg
        assert captured["url"].startswith("https://discord.com/api/webhooks/"), captured["url"]
        assert captured["json"]["embeds"][0]["color"] == 0x2ECC71
    finally:
        _restore_client(original)


async def test_missing_config_returns_false():
    ch = _MockChannel("discord", {})
    success, msg = await notifier.send_notification(ch, "x", "y")
    assert success is False
    assert "bridge_url" in msg or "webhook_url" in msg, msg


async def test_bridge_failure_returns_false():
    transport, _ = _mock_transport(status=401, body=b'{"error":"unauthorized"}')
    original = await _patch_async_client(transport)
    try:
        ch = _MockChannel("discord", {
            "bridge_url": "http://arc-discord-bridge:8600",
            "bridge_token": "wrong",
            "channel": "allmänt",
        })
        success, msg = await notifier.send_notification(ch, "x", "y")
        assert success is False, msg
        assert "401" in msg, msg
    finally:
        _restore_client(original)


async def test_color_mapping():
    assert notifier._discord_color_for_subject("Backup Failed") == 0xE74C3C
    assert notifier._discord_color_for_subject("Backup Successful") == 0x2ECC71
    assert notifier._discord_color_for_subject("Storage Warning") == 0xF39C12
    assert notifier._discord_color_for_subject("Backup Started") == 0x3498DB


async def main():
    tests = [
        test_bridge_mode_success,
        test_webhook_mode_success,
        test_missing_config_returns_false,
        test_bridge_failure_returns_false,
        test_color_mapping,
    ]
    failures = 0
    for t in tests:
        try:
            await t()
            print(f"PASS  {t.__name__}")
        except AssertionError as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:
            failures += 1
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    if failures:
        sys.exit(1)
    print(f"\n{len(tests)} passed.")


if __name__ == "__main__":
    asyncio.run(main())
