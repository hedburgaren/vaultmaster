import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


def _decrypt_config(config: dict | None) -> dict:
    """Return a working copy of `config` with `enc:vN:...`-prefixed values decrypted.

    Always operates on a copy so the SQLAlchemy-loaded dict on the channel
    object is never mutated in place (which would cause the ORM to re-flush
    plaintext values back to the database). Falls back to a shallow copy on
    crypto errors so a missing/rotated key never blocks all notifications.
    """
    try:
        from api.services.credentials_crypto import decrypt_dict_secrets
        return decrypt_dict_secrets(dict(config or {})) or {}
    except Exception as exc:  # noqa: BLE001
        logger.warning("notifier: decrypt failed (%s) — falling back to raw config", exc)
        return dict(config or {})


async def send_test_notification(channel) -> tuple[bool, str]:
    """Send a test notification through a channel."""
    message = f"🔐 VaultMaster test notification — {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}"
    return await send_notification(channel, "Test", message)


async def send_notification(channel, subject: str, message: str) -> tuple[bool, str]:
    """Send a notification through the specified channel."""
    try:
        if channel.channel_type == "slack":
            return await _send_slack(channel.config, subject, message)
        elif channel.channel_type == "ntfy":
            return await _send_ntfy(channel.config, subject, message)
        elif channel.channel_type == "telegram":
            return await _send_telegram(channel.config, subject, message)
        elif channel.channel_type == "discord":
            return await _send_discord(channel.config, subject, message)
        elif channel.channel_type == "webhook":
            return await _send_webhook(channel.config, subject, message)
        elif channel.channel_type == "email":
            return await _send_email(channel.config, subject, message)
        else:
            return False, f"Unknown channel type: {channel.channel_type}"
    except Exception as e:
        logger.error(f"Notification failed for {channel.name}: {e}")
        return False, str(e)


async def _send_slack(config: dict, subject: str, message: str) -> tuple[bool, str]:
    # Support both webhook_url (classic incoming webhooks) and bot_token + channel (Bot API)
    config = _decrypt_config(config)
    bot_token = config.get("bot_token")
    channel = config.get("channel")
    webhook_url = config.get("webhook_url")

    if bot_token and channel:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                "https://slack.com/api/chat.postMessage",
                headers={"Authorization": f"Bearer {bot_token}"},
                json={"channel": channel, "text": f"*{subject}*\n{message}", "unfurl_links": False},
            )
            data = resp.json()
            if resp.status_code == 200 and data.get("ok"):
                return True, "Slack notification sent (Bot API)"
            return False, f"Slack Bot API error: {data.get('error', resp.status_code)}"
    elif webhook_url:
        async with httpx.AsyncClient() as client:
            resp = await client.post(webhook_url, json={"text": f"*{subject}*\n{message}"})
            if resp.status_code == 200:
                return True, "Slack notification sent"
            return False, f"Slack returned {resp.status_code}"
    else:
        return False, "No webhook_url or bot_token+channel configured"


async def _send_ntfy(config: dict, subject: str, message: str) -> tuple[bool, str]:
    config = _decrypt_config(config)
    url = config.get("url")
    topic = config.get("topic", "vaultmaster")
    if not url:
        return False, "No ntfy URL configured"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{url}/{topic}",
            headers={"Title": subject, "Priority": config.get("priority", "default")},
            content=message,
        )
        if resp.status_code == 200:
            return True, "ntfy notification sent"
        return False, f"ntfy returned {resp.status_code}"


async def _send_telegram(config: dict, subject: str, message: str) -> tuple[bool, str]:
    config = _decrypt_config(config)
    bot_token = config.get("bot_token")
    chat_id = config.get("chat_id")
    if not bot_token or not chat_id:
        return False, "Missing bot_token or chat_id"
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"https://api.telegram.org/bot{bot_token}/sendMessage",
            json={"chat_id": chat_id, "text": f"*{subject}*\n{message}", "parse_mode": "Markdown"},
        )
        if resp.status_code == 200:
            return True, "Telegram notification sent"
        return False, f"Telegram returned {resp.status_code}"


async def _send_discord(config: dict, subject: str, message: str) -> tuple[bool, str]:
    """Send a Discord notification.

    Two transport modes:
      1. Bridge mode. POST to a self-hosted Discord bridge service that
         maps channel slugs to actual Discord channels.
         config = {
             "bridge_url": "http://discord-bridge:8600",
             "bridge_token": "...",
             "channel": "ops"
         }
      2. Webhook mode — POST directly to a Discord channel webhook URL.
         config = {"webhook_url": "https://discord.com/api/webhooks/..."}

    Optional:
      "embeds_enabled": bool (default True) — render as Discord embed instead of plain content.
      "username": str — webhook-mode only; overrides bot username for the message.
    """
    config = _decrypt_config(config)
    bridge_url = config.get("bridge_url")
    bridge_token = config.get("bridge_token")
    channel = config.get("channel")
    # Accept both `webhook_url` (canonical) and `url` (the generic-webhook
    # form key, which the UI happens to render). Without this fallback,
    # configs created via the UI dropdown for "Discord" would silently
    # fail with "needs bridge_url+bridge_token+channel OR webhook_url".
    webhook_url = config.get("webhook_url") or config.get("url")
    embeds_enabled = config.get("embeds_enabled", True)
    color = _discord_color_for_subject(subject)

    if bridge_url and bridge_token and channel:
        url = bridge_url.rstrip("/") + "/send"
        body: dict = {"channel": channel}
        if embeds_enabled:
            body["embeds"] = [{
                "title": subject[:256],
                "description": message[:4000],
                "color": color,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
            body["content"] = ""
        else:
            body["content"] = f"**{subject}**\n{message}"[:1900]
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json=body, headers={"x-bridge-token": bridge_token})
            if 200 <= resp.status_code < 300:
                return True, f"Discord (bridge) sent (status {resp.status_code})"
            return False, f"Discord bridge returned {resp.status_code}: {resp.text[:200]}"

    if webhook_url:
        body: dict = {}
        username = config.get("username")
        if username:
            body["username"] = username
        if embeds_enabled:
            body["embeds"] = [{
                "title": subject[:256],
                "description": message[:4000],
                "color": color,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }]
        else:
            body["content"] = f"**{subject}**\n{message}"[:1900]
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(webhook_url, json=body)
            if 200 <= resp.status_code < 300:
                return True, f"Discord (webhook) sent (status {resp.status_code})"
            return False, f"Discord webhook returned {resp.status_code}: {resp.text[:200]}"

    return False, "Discord channel needs bridge_url+bridge_token+channel OR webhook_url"


def _discord_color_for_subject(subject: str) -> int:
    s = subject.lower()
    if "fail" in s or "critical" in s or "offline" in s:
        return 0xE74C3C
    if "partial" in s or "warning" in s or "expiring" in s:
        return 0xF39C12
    if "success" in s or "completed" in s or "rotation" in s:
        return 0x2ECC71
    return 0x3498DB


async def _send_webhook(config: dict, subject: str, message: str) -> tuple[bool, str]:
    config = _decrypt_config(config)
    # Generic webhook channel uses `url` key; tolerate `webhook_url` too because
    # decrypt_dict_secrets handles both and the UI sometimes writes either.
    url = config.get("url") or config.get("webhook_url")
    if not url:
        return False, "No webhook URL configured"
    async with httpx.AsyncClient() as client:
        resp = await client.post(url, json={"subject": subject, "message": message, "timestamp": datetime.now(timezone.utc).isoformat()})
        if resp.status_code < 300:
            return True, f"Webhook sent (status {resp.status_code})"
        return False, f"Webhook returned {resp.status_code}"


async def _send_email(config: dict, subject: str, message: str) -> tuple[bool, str]:
    import smtplib
    from email.mime.text import MIMEText
    from email.utils import formataddr

    # Decrypt secrets in-flight; .config is stored with `enc:vN:...`-prefixed values.
    config = _decrypt_config(config)

    smtp_host = config.get("smtp_host")
    smtp_port = int(config.get("smtp_port", 587) or 587)
    smtp_user = config.get("smtp_user")
    smtp_password = config.get("smtp_password")
    to_email = config.get("to_email")
    from_email = config.get("from_email") or smtp_user
    from_name = config.get("from_name") or "VaultMaster"
    # Transport: 'ssl' (implicit TLS, port 465), 'starttls' (port 587, default), or 'plain'
    use_ssl = config.get("use_ssl")
    if use_ssl is None:
        use_ssl = smtp_port == 465
    use_starttls = config.get("use_starttls")
    if use_starttls is None:
        use_starttls = not use_ssl

    if not all([smtp_host, smtp_user, smtp_password, to_email]):
        return False, "Missing email configuration"

    try:
        msg = MIMEText(message)
        msg["Subject"] = f"[VaultMaster] {subject}"
        msg["From"] = formataddr((from_name, from_email))
        msg["To"] = to_email

        if use_ssl:
            server_cm = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=20)
        else:
            server_cm = smtplib.SMTP(smtp_host, smtp_port, timeout=20)

        with server_cm as server:
            if use_starttls and not use_ssl:
                server.starttls()
            server.login(smtp_user, smtp_password)
            # send_message returns a dict of recipients the server REFUSED.
            # Discarding it (as this did until 2026-07-19) means a message
            # accepted for nobody still reports "Email sent".
            refused = server.send_message(msg)
        if refused:
            return False, f"Email refused for {len(refused)} recipient(s): {list(refused)[:3]}"
        return True, "Email sent"
    except Exception as e:
        return False, f"Email failed: {e}"


async def notify_event(db, event: str, data: dict):
    """Send notifications for a specific event trigger to all matching channels.

    Bug #17: muterar ``channel.last_sent`` så att vi kan visa "senast skickad"
    i UI. Tidigare litades på caller att committa, vilket innebar att om
    callern senare gjorde en rollback (t.ex. `_check_health` som upptäcker
    server-offline → notify → exception) försvann uppdateringen. Vi committar
    nu uppdateringen explicit i ett fristående block.

    Bug #24: SMTP/HTTP-anrop sker parallellt med ``asyncio.gather`` så att
    en seg kanal (timeout 20s) inte blockerar resten. Tidigare var det
    sekventiellt — N kanaler × timeout = total wall-clock blocker.
    """
    from sqlalchemy import select
    from api.models.notification_channel import NotificationChannel

    result = await db.execute(
        select(NotificationChannel).where(
            NotificationChannel.is_active == True,
            NotificationChannel.triggers.any(event),
        )
    )
    channels = result.scalars().all()

    subject_map = {
        "run.start": "Backup Started",
        "run.success": "Backup Successful",
        "run.failed": "Backup Failed",
        "run.partial": "Backup Partial",
        "storage.warning": "Storage Warning",
        "storage.critical": "Storage Critical",
        "server.offline": "Server Offline",
        "artifact.expiring": "Artifact Expiring",
        "rotation.completed": "Rotation Completed",
        "validation.passed": "Backup Validation Passed",
        "validation.failed": "Backup Validation Failed",
        "validation.skipped": "Backup Validation Skipped",
        "credential.expiring": "Credential Expiring",
        "credential.expired": "Credential Expired",
        "backup.anomaly": "Backup Anomaly Detected",
        "security.report": "Weekly Security Scan",
    }

    subject = subject_map.get(event, event)
    message = _format_event_message(event, data)

    if not channels:
        # No channel subscribes to this event. Worth saying out loud: an event
        # nobody listens to is indistinguishable from one that was delivered.
        logger.warning("notify_event(%s): no active channel subscribes to this event", event)
        return {"delivered": [], "failed": [], "any_success": False,
                "committed": True, "no_channels": True}

    # Bug #24: parallel dispatch. SMTP is the worst offender (20s timeout),
    # but bridges and webhooks add up too. return_exceptions=True so that
    # one failed channel does not abort the rest.
    import asyncio
    results = await asyncio.gather(
        *(send_notification(channel, subject, message) for channel in channels),
        return_exceptions=True,
    )

    any_success = False
    delivered: list[str] = []
    failed: list[str] = []
    for channel, res in zip(channels, results):
        if isinstance(res, BaseException):
            logger.error(f"Notification {channel.name} ({channel.channel_type}): exception {res!r}")
            failed.append(f"{channel.name}: {res!r}"[:200])
            continue
        success, msg = res
        if success:
            channel.last_sent = datetime.now(timezone.utc)
            any_success = True
            delivered.append(channel.name)
        else:
            failed.append(f"{channel.name}: {msg}"[:200])
        logger.info(f"Notification {channel.name} ({channel.channel_type}): {msg}")

    # A notifier that cannot report its own failure is the alarm equivalent of
    # everything else that went wrong in this system: it looks fine right up
    # until the moment you needed it. Until 2026-07-19 this returned None
    # unconditionally, so no caller could tell the difference between "alerted
    # everyone" and "reached nobody".
    if not any_success:
        logger.error(
            "notify_event(%s): DELIVERED TO NOBODY. All %d channel(s) failed: %s. "
            "Alerts are not reaching anyone right now.",
            event, len(channels), "; ".join(failed) or "unknown",
        )
    elif failed:
        logger.warning(
            "notify_event(%s): partial delivery, %d ok, %d failed: %s",
            event, len(delivered), len(failed), "; ".join(failed),
        )

    # Bug #17: commit the last_sent updates ourselves. Otherwise a caller
    # rollback (or a later exception in the same transaction) silently
    # erases the audit trail of "we did send these".
    #
    # Caveat worth knowing: this commits the CALLER's session, so any pending
    # state the caller has not finalised is persisted here too. Left as is
    # because removing it reintroduces bug #17, but callers must not rely on
    # being able to roll back after calling this.
    committed = True
    if any_success:
        try:
            await db.commit()
        except Exception as exc:
            committed = False
            logger.warning(f"notify_event: commit of last_sent updates failed: {exc}")

    return {
        "delivered": delivered,
        "failed": failed,
        "any_success": any_success,
        "committed": committed,
    }


def _format_event_message(event: str, data: dict) -> str:
    """Format a notification message based on event type."""
    if event == "run.success":
        return f"✅ Backup completed\nJob: {data.get('job_name', 'N/A')}\nServer: {data.get('server_name', 'N/A')}\nSize: {data.get('size_bytes', 0):,} bytes\nDuration: {data.get('duration', 'N/A')}"
    elif event == "run.failed":
        return f"❌ Backup failed\nJob: {data.get('job_name', 'N/A')}\nServer: {data.get('server_name', 'N/A')}\nError: {data.get('error', 'Unknown')}"
    elif event == "storage.warning":
        return f"⚠️ Storage warning\nDestination: {data.get('name', 'N/A')}\nUsage: {data.get('percent_used', 0)}%"
    elif event == "storage.critical":
        return f"🔴 Storage critical\nDestination: {data.get('name', 'N/A')}\nUsage: {data.get('percent_used', 0)}%"
    elif event == "validation.passed":
        dur = data.get("duration")
        return (f"✅ Restore-validation passed\nJob: {data.get('job_name', 'N/A')}\n"
                f"Server: {data.get('server_name', 'N/A')}"
                + (f"\nDuration: {dur}s" if dur else ""))
    elif event == "validation.failed":
        return (f"❌ Restore-validation FAILED — backup is not restorable!\n"
                f"Job: {data.get('job_name', 'N/A')}\n"
                f"Server: {data.get('server_name', 'N/A')}\n"
                f"Error: {data.get('error', 'Unknown')}")
    elif event == "validation.skipped":
        return (f"ℹ️ Restore-validation skipped\nJob: {data.get('job_name', 'N/A')}\n"
                f"Reason: {data.get('error', 'no artifact')}")
    elif event == "credential.expiring":
        return (f"⏳ Credential expiring soon\n"
                f"Name: {data.get('name', 'N/A')}\n"
                f"Type: {data.get('credential_type', 'N/A')}\n"
                f"Expires: {data.get('expires_at', 'N/A')}\n"
                f"Days left: {data.get('days_left', '?')}")
    elif event == "credential.expired":
        return (f"⛔ Credential EXPIRED\n"
                f"Name: {data.get('name', 'N/A')}\n"
                f"Type: {data.get('credential_type', 'N/A')}\n"
                f"Expired: {data.get('expires_at', 'N/A')}")
    elif event == "backup.anomaly":
        return (f"🤖 Backup anomaly detected\n"
                f"Job: {data.get('job_name', 'N/A')}\n"
                f"Type: {data.get('anomaly', 'unknown')}\n"
                f"Latest size: {data.get('latest_size', 0):,} bytes\n"
                f"Mean over last {data.get('window', 7)} runs: {data.get('mean_size', 0):,.0f} bytes\n"
                f"Δ: {data.get('delta_pct', 0):+.1f}%  ({data.get('z_score', 0):+.2f}σ)\n"
                f"Possible cause: {data.get('hypothesis', 'investigate manually')}")
    elif event == "security.report":
        vulns = data.get("python_vulns", []) or []
        ce = data.get("credential_expiry", {}) or {}
        orphans = data.get("mcp_orphans", []) or []
        mcp_exp = data.get("mcp_expired", []) or []
        lines = ["🛡️ Weekly security scan"]
        if vulns:
            lines.append(f"⚠️  Python CVEs: {len(vulns)}")
            for v in vulns[:5]:
                fix = ",".join(v.get("fix_versions") or []) or "no fix"
                lines.append(f"   · {v.get('package')} {v.get('version')} → {v.get('id')}  fix:{fix}")
            if len(vulns) > 5:
                lines.append(f"   …and {len(vulns) - 5} more")
        else:
            lines.append("✅ Python CVEs: none detected")
        lines.append(f"Credentials: {ce.get('expired', 0)} expired, "
                     f"{ce.get('expiring_30d', 0)} expiring <30d, "
                     f"{ce.get('unbounded', 0)}/{ce.get('total', 0)} unbounded")
        lines.append(f"MCP clients: {len(orphans)} orphaned (>90d unused), {len(mcp_exp)} expired")
        return "\n".join(lines)
    else:
        return str(data)
