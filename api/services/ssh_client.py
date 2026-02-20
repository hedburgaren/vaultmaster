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


async def list_remote_databases(server, db_type: str = "postgresql") -> list[dict]:
    """List databases on a remote server via SSH.

    Uses the server's meta.db_* fields for connection info.
    For PostgreSQL on localhost, uses 'sudo -u $db_user psql' for peer auth
    which is the standard approach for native PostgreSQL installs.
    """
    meta = getattr(server, 'meta', None) or {}
    db_host = meta.get('db_host', '127.0.0.1')
    db_port = meta.get('db_port', 5432 if db_type == 'postgresql' else 3306)
    db_user = meta.get('db_user', 'postgres' if db_type == 'postgresql' else 'root')
    db_password = meta.get('db_password', '')

    try:
        kwargs = _build_connect_kwargs(server)
        async with asyncssh.connect(**kwargs) as conn:
            sql_query = "SELECT datname, pg_database_size(datname) FROM pg_database WHERE datistemplate = false ORDER BY datname;"

            if db_type == 'postgresql':
                is_local = db_host in ('127.0.0.1', 'localhost', '::1', '')
                if is_local and not db_password:
                    # Peer auth: switch to the OS user that owns the DB (e.g. postgres, odoo18)
                    cmd = f"sudo -n -u {db_user} psql -d postgres -p {db_port} -t -A -c \"{sql_query}\""
                elif db_password:
                    # Password auth via PGPASSWORD
                    cmd = f"PGPASSWORD='{db_password}' psql -h {db_host} -p {db_port} -U {db_user} -d postgres -w -t -A -c \"{sql_query}\""
                else:
                    # No password, remote host — try direct connection
                    cmd = f"psql -h {db_host} -p {db_port} -U {db_user} -d postgres -t -A -c \"{sql_query}\""
            elif db_type in ('mysql', 'mariadb'):
                pw_flag = f"-p'{db_password}'" if db_password else ""
                cmd = f"mysql -h {db_host} -P {db_port} -u {db_user} {pw_flag} -N -e \"SELECT schema_name, IFNULL(SUM(data_length + index_length), 0) FROM information_schema.schemata LEFT JOIN information_schema.tables ON schema_name = table_schema WHERE schema_name NOT IN ('information_schema','performance_schema','mysql','sys') GROUP BY schema_name ORDER BY schema_name;\""
                use_sudo = meta.get('use_sudo', False)
                ssh_user = getattr(server, 'ssh_user', None) or "root"
                if use_sudo and ssh_user != "root":
                    cmd = f"sudo -n sh -c '{cmd}'"
            else:
                return [{"error": f"Unsupported database type: {db_type}"}]

            result = await conn.run(cmd, check=False, timeout=30)
            if result.exit_status != 0:
                stderr = result.stderr.strip()
                # Provide helpful error context
                if "peer" in stderr.lower() or "ident" in stderr.lower():
                    stderr += " (Hint: try leaving DB password empty for peer/ident auth)"
                elif "password authentication failed" in stderr.lower():
                    stderr += " (Hint: check DB password)"
                elif "sudo" in stderr.lower():
                    stderr += " (Hint: SSH user needs passwordless sudo — add to sudoers with NOPASSWD)"
                return [{"error": stderr or "Command failed"}]

            databases = []
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                sep = "|" if db_type == "postgresql" else "\t"
                parts = line.split(sep)
                name = parts[0].strip()
                size = int(parts[1].strip()) if len(parts) > 1 and parts[1].strip().isdigit() else 0
                if name:
                    databases.append({"name": name, "size_bytes": size})
            return databases

    except Exception as e:
        logger.error(f"Failed to list databases on {getattr(server, 'name', '?')}: {e}")
        return [{"error": str(e)}]


async def list_remote_docker(server) -> dict:
    """List Docker containers and volumes on a remote server via SSH.

    Correlates volumes with the containers that use them using docker inspect
    for accurate (non-truncated) volume names.
    """
    try:
        kwargs = _build_connect_kwargs(server)
        meta = getattr(server, 'meta', None) or {}
        use_sudo = meta.get('use_sudo', False)
        ssh_user = getattr(server, 'ssh_user', None) or "root"
        prefix = "sudo -n " if use_sudo and ssh_user != "root" else ""

        async with asyncssh.connect(**kwargs) as conn:
            # 1. Get containers basic info
            containers_cmd = f'{prefix}docker ps -a --format "{{{{.ID}}}}|{{{{.Names}}}}|{{{{.Image}}}}|{{{{.Status}}}}|{{{{.State}}}}"'
            c_result = await conn.run(containers_cmd, check=False, timeout=15)
            containers = []
            container_ids = []
            if c_result.exit_status == 0:
                for line in c_result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split("|")
                    if len(parts) >= 5:
                        containers.append({
                            "id": parts[0][:12],
                            "name": parts[1],
                            "image": parts[2],
                            "status": parts[3],
                            "state": parts[4],
                        })
                        container_ids.append(parts[0][:12])

            # 2. Get volume→container mapping + bind mounts via docker inspect
            volume_to_containers: dict[str, list[str]] = {}
            container_mounts: dict[str, list[dict]] = {}  # cname -> [{type, source, dest}]
            if container_ids:
                ids_str = " ".join(container_ids)
                # Output: /name|type:name_or_source:destination, ...
                inspect_cmd = (
                    f"{prefix}docker inspect --format "
                    f"'{{{{.Name}}}}|{{{{range .Mounts}}}}{{{{.Type}}}}:{{{{.Name}}}}:{{{{.Source}}}}:{{{{.Destination}}}},{{{{end}}}}' "
                    f"{ids_str}"
                )
                i_result = await conn.run(inspect_cmd, check=False, timeout=20)
                if i_result.exit_status == 0:
                    for line in i_result.stdout.strip().split("\n"):
                        if not line.strip():
                            continue
                        parts = line.split("|", 1)
                        if len(parts) < 2:
                            continue
                        cname = parts[0].strip().lstrip("/")
                        mounts_str = parts[1].strip()
                        binds = []
                        for m in mounts_str.split(","):
                            m = m.strip()
                            if not m:
                                continue
                            mp = m.split(":", 3)
                            mtype = mp[0] if len(mp) > 0 else ""
                            mname = mp[1] if len(mp) > 1 else ""
                            msource = mp[2] if len(mp) > 2 else ""
                            mdest = mp[3] if len(mp) > 3 else ""
                            if mtype == "volume" and mname:
                                volume_to_containers.setdefault(mname, [])
                                if cname not in volume_to_containers[mname]:
                                    volume_to_containers[mname].append(cname)
                            elif mtype == "bind" and msource:
                                binds.append({"source": msource, "dest": mdest})
                        if binds:
                            container_mounts[cname] = binds

            # Enrich containers with bind mount info
            for c in containers:
                c["bind_mounts"] = container_mounts.get(c["name"], [])

            # 3. Get volumes
            volumes_cmd = f'{prefix}docker volume ls --format "{{{{.Name}}}}|{{{{.Driver}}}}"'
            v_result = await conn.run(volumes_cmd, check=False, timeout=15)
            volumes = []
            if v_result.exit_status == 0:
                for line in v_result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split("|")
                    vol_name = parts[0]
                    volumes.append({
                        "name": vol_name,
                        "driver": parts[1] if len(parts) > 1 else "local",
                        "used_by": volume_to_containers.get(vol_name, []),
                    })

            return {"containers": containers, "volumes": volumes, "error": None}

    except Exception as e:
        logger.error(f"Failed to list Docker on {getattr(server, 'name', '?')}: {e}")
        return {"containers": [], "volumes": [], "error": str(e)}


async def prune_docker_volumes(server) -> dict:
    """Remove unused Docker volumes on a remote server via SSH."""
    try:
        kwargs = _build_connect_kwargs(server)
        meta = getattr(server, 'meta', None) or {}
        use_sudo = meta.get('use_sudo', False)
        ssh_user = getattr(server, 'ssh_user', None) or "root"
        prefix = "sudo -n " if use_sudo and ssh_user != "root" else ""

        async with asyncssh.connect(**kwargs) as conn:
            cmd = f'{prefix}docker volume prune -f'
            result = await conn.run(cmd, check=False, timeout=30)
            if result.exit_status != 0:
                return {"success": False, "error": result.stderr.strip() or "Command failed", "removed": []}

            # Parse removed volume names from output
            removed = []
            for line in result.stdout.strip().split("\n"):
                line = line.strip()
                if line and not line.startswith("Total") and not line.startswith("Deleted"):
                    removed.append(line)

            return {"success": True, "removed": removed, "error": None, "output": result.stdout.strip()}

    except Exception as e:
        logger.error(f"Failed to prune Docker volumes on {getattr(server, 'name', '?')}: {e}")
        return {"success": False, "removed": [], "error": str(e)}
