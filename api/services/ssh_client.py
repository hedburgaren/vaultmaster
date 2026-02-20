import asyncio
import logging
from datetime import datetime, timezone

import asyncssh

logger = logging.getLogger(__name__)

LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1", "0.0.0.0"}


def _resolve_host(host: str) -> str:
    """Rewrite localhost addresses to host.docker.internal so the container can reach the host."""
    if host.lower() in LOCAL_HOSTS:
        return "host.docker.internal"
    return host


def _build_connect_kwargs(server) -> dict:
    """Build asyncssh connection kwargs from a server object.

    Handles ssh_key, ssh_password, and fallback auth types.
    """
    resolved = _resolve_host(server.host)
    kwargs: dict = {
        "host": resolved,
        "port": getattr(server, 'port', 22) or 22,
        "username": getattr(server, 'ssh_user', None) or "root",
        "known_hosts": None,
    }

    auth_type = getattr(server, 'auth_type', 'ssh_key')
    meta = getattr(server, 'meta', None) or {}

    key_path = getattr(server, 'ssh_key_path', None)

    if auth_type == 'ssh_password':
        password = meta.get('ssh_password')
        if password:
            kwargs["password"] = password
            if key_path:
                kwargs["client_keys"] = [key_path]
            else:
                kwargs["client_keys"] = []
    elif key_path:
        kwargs["client_keys"] = [key_path]

    return kwargs


async def test_ssh_connection(server) -> tuple[bool, str]:
    """Test SSH connectivity to a server."""
    try:
        if getattr(server, 'auth_type', '') == "local":
            return True, "Local server — always reachable"

        if getattr(server, 'auth_type', '') == "api":
            return True, "API-based server — use provider API to test"

        kwargs = _build_connect_kwargs(server)
        async with asyncssh.connect(**kwargs) as conn:
            result = await conn.run("hostname", check=True)
            hostname = result.stdout.strip()
            return True, f"Connected to {hostname}"

    except Exception as e:
        err = str(e)
        if "Permission denied" in err:
            user = getattr(server, 'ssh_user', None) or 'root'
            host = getattr(server, 'host', '?')
            err = f"Permission denied for user {user} on host {host}"
        logger.error(f"SSH connection test failed for {getattr(server, 'name', '?')}: {e}")
        return False, err


async def list_remote_directory(server, path: str = "/") -> list[dict]:
    """List files in a remote directory via SSH."""
    try:
        if getattr(server, 'auth_type', '') in ("api",):
            return [{"error": "File browsing not supported for API-based servers"}]

        kwargs = _build_connect_kwargs(server)
        async with asyncssh.connect(**kwargs) as conn:
            result = await conn.run(f"ls -la --time-style=long-iso {path}", check=True)
            entries = []
            for line in result.stdout.strip().split("\n")[1:]:
                parts = line.split(None, 7)
                if len(parts) >= 8:
                    entries.append({
                        "permissions": parts[0],
                        "type": "directory" if parts[0].startswith("d") else "file",
                        "owner": parts[2],
                        "group": parts[3],
                        "size": int(parts[4]) if not parts[0].startswith("d") else None,
                        "modified": f"{parts[5]} {parts[6]}",
                        "name": parts[7],
                    })
            return entries

    except Exception as e:
        logger.error(f"Failed to list directory {path} on {getattr(server, 'name', '?')}: {e}")
        return [{"error": str(e)}]


async def run_remote_command(server, command: str, timeout: int = 300) -> tuple[int, str, str]:
    """Execute a command on a remote server via SSH. Prepends sudo if use_sudo is set."""
    kwargs = _build_connect_kwargs(server)

    meta = getattr(server, 'meta', None) or {}
    use_sudo = getattr(server, 'use_sudo', False) or meta.get('use_sudo', False)
    if use_sudo and (getattr(server, 'ssh_user', None) or "root") != "root":
        command = f"sudo -n {command}"

    async with asyncssh.connect(**kwargs) as conn:
        result = await conn.run(command, check=False, timeout=timeout)
        return result.exit_status, result.stdout, result.stderr
