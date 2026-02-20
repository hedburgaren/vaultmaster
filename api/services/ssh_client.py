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


async def test_ssh_connection(server) -> tuple[bool, str]:
    """Test SSH connectivity to a server."""
    try:
        if server.auth_type == "local":
            return True, "Local server — always reachable"

        if server.auth_type == "api":
            return True, "API-based server — use provider API to test"

        resolved = _resolve_host(server.host)
        connect_kwargs = {
            "host": resolved,
            "port": server.port,
            "username": server.ssh_user or "root",
            "known_hosts": None,
        }

        if server.ssh_key_path:
            connect_kwargs["client_keys"] = [server.ssh_key_path]

        async with asyncssh.connect(**connect_kwargs) as conn:
            result = await conn.run("hostname", check=True)
            hostname = result.stdout.strip()
            return True, f"Connected to {hostname}"

    except Exception as e:
        logger.error(f"SSH connection test failed for {server.name}: {e}")
        return False, str(e)


async def list_remote_directory(server, path: str = "/") -> list[dict]:
    """List files in a remote directory via SSH."""
    try:
        if server.auth_type in ("api",):
            return [{"error": "File browsing not supported for API-based servers"}]

        resolved = _resolve_host(server.host)
        connect_kwargs = {
            "host": resolved,
            "port": server.port,
            "username": server.ssh_user or "root",
            "known_hosts": None,
        }

        if server.ssh_key_path:
            connect_kwargs["client_keys"] = [server.ssh_key_path]

        async with asyncssh.connect(**connect_kwargs) as conn:
            result = await conn.run(f"ls -la --time-style=long-iso {path}", check=True)
            entries = []
            for line in result.stdout.strip().split("\n")[1:]:  # skip "total" line
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
        logger.error(f"Failed to list directory {path} on {server.name}: {e}")
        return [{"error": str(e)}]


async def run_remote_command(server, command: str, timeout: int = 300) -> tuple[int, str, str]:
    """Execute a command on a remote server via SSH."""
    resolved = _resolve_host(server.host)
    connect_kwargs = {
        "host": resolved,
        "port": server.port,
        "username": server.ssh_user or "root",
        "known_hosts": None,
    }

    if server.ssh_key_path:
        connect_kwargs["client_keys"] = [server.ssh_key_path]

    async with asyncssh.connect(**connect_kwargs) as conn:
        result = await conn.run(command, check=False, timeout=timeout)
        return result.exit_status, result.stdout, result.stderr
