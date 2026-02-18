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
    else:
        return str(data)
