import logging
from datetime import datetime, timezone

import httpx

logger = logging.getLogger(__name__)


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
    webhook_url = config.get("webhook_url")
    if not webhook_url:
        return False, "No webhook_url configured"
    async with httpx.AsyncClient() as client:
        resp = await client.post(webhook_url, json={"text": f"*{subject}*\n{message}"})
        if resp.status_code == 200:
            return True, "Slack notification sent"
        return False, f"Slack returned {resp.status_code}"


async def _send_ntfy(config: dict, subject: str, message: str) -> tuple[bool, str]:
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
      1. Bridge mode (preferred for hedburgaren) — POST to arc-discord-bridge.
         config = {
             "bridge_url": "http://arc-discord-bridge:8600",
             "bridge_token": "...",
             "channel": "plastshop"
         }
      2. Webhook mode — POST directly to a Discord channel webhook URL.
         config = {"webhook_url": "https://discord.com/api/webhooks/..."}

    Optional:
      "embeds_enabled": bool (default True) — render as Discord embed instead of plain content.
      "username": str — webhook-mode only; overrides bot username for the message.
    """
    bridge_url = config.get("bridge_url")
    bridge_token = config.get("bridge_token")
    channel = config.get("channel")
    webhook_url = config.get("webhook_url")
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
    url = config.get("url")
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

    smtp_host = config.get("smtp_host")
    smtp_port = config.get("smtp_port", 587)
    smtp_user = config.get("smtp_user")
    smtp_password = config.get("smtp_password")
    to_email = config.get("to_email")

    if not all([smtp_host, smtp_user, smtp_password, to_email]):
        return False, "Missing email configuration"

    try:
        msg = MIMEText(message)
        msg["Subject"] = f"[VaultMaster] {subject}"
        msg["From"] = smtp_user
        msg["To"] = to_email

        with smtplib.SMTP(smtp_host, smtp_port) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.send_message(msg)
        return True, "Email sent"
    except Exception as e:
        return False, f"Email failed: {e}"


async def notify_event(db, event: str, data: dict):
    """Send notifications for a specific event trigger to all matching channels."""
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
    }

    subject = subject_map.get(event, event)
    message = _format_event_message(event, data)

    for channel in channels:
        success, msg = await send_notification(channel, subject, message)
        if success:
            channel.last_sent = datetime.now(timezone.utc)
        logger.info(f"Notification {channel.name} ({channel.channel_type}): {msg}")


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
    else:
        return str(data)
