import asyncio
import json
import logging
import os
import shutil
import subprocess

logger = logging.getLogger(__name__)


async def _run_rclone(args: list[str], timeout: int = 60) -> tuple[int, str, str]:
    """Run an rclone command and return (exit_code, stdout, stderr)."""
    proc = await asyncio.create_subprocess_exec(
        "rclone", *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        return proc.returncode, stdout.decode(), stderr.decode()
    except asyncio.TimeoutError:
        proc.kill()
        return -1, "", "Timeout"


def _obscure_password(plaintext: str) -> str | None:
    """Obscure a password using rclone obscure (synchronous, fast)."""
    try:
        result = subprocess.run(
            ["rclone", "obscure", plaintext],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
        logger.warning(f"rclone obscure failed: {result.stderr}")
        return None
    except Exception as e:
        logger.warning(f"rclone obscure error: {e}")
        return None


def _build_backend(dest) -> tuple[str, list[str]]:
    """Build (remote_path, extra_rclone_flags) from storage destination config.

    Uses inline backend flags so no rclone.conf is needed.
    Returns the remote spec (e.g. ':s3:bucket/path') and a list of
    --backend-flag=value arguments.
    """
    backend = dest.backend
    cfg = dest.config or {}

    if backend == "local":
        return cfg.get("path", "/mnt/backup"), []

    flags: list[str] = []

    if backend == "s3":
        remote = f":s3:{cfg.get('bucket', 'backups')}"
        if cfg.get("endpoint"):
            flags.append(f"--s3-endpoint={cfg['endpoint']}")
        if cfg.get("region"):
            flags.append(f"--s3-region={cfg['region']}")
        if cfg.get("access_key"):
            flags.append(f"--s3-access-key-id={cfg['access_key']}")
        if cfg.get("secret_key"):
            flags.append(f"--s3-secret-access-key={cfg['secret_key']}")
        flags.append("--s3-provider=Other")
        flags.append("--s3-env-auth=false")
        return remote, flags

    if backend == "sftp":
        host = cfg.get("host", "localhost")
        port = cfg.get("port", 22)
        path = cfg.get("path", "/backups")
        remote = f":sftp:{path}"
        flags.append(f"--sftp-host={host}")
        flags.append(f"--sftp-port={port}")
        if cfg.get("user"):
            flags.append(f"--sftp-user={cfg['user']}")
        if cfg.get("password"):
            # rclone requires obscured passwords for --sftp-pass
            obscured = _obscure_password(cfg["password"])
            if obscured:
                flags.append(f"--sftp-pass={obscured}")
        return remote, flags

    if backend == "b2":
        remote = f":b2:{cfg.get('bucket', 'backups')}"
        if cfg.get("key_id"):
            flags.append(f"--b2-account={cfg['key_id']}")
        app_key = cfg.get("app_key") or cfg.get("application_key")
        if app_key:
            flags.append(f"--b2-key={app_key}")
        return remote, flags

    if backend == "gdrive":
        remote = ":drive:"
        if cfg.get("client_id"):
            flags.append(f"--drive-client-id={cfg['client_id']}")
        if cfg.get("client_secret"):
            flags.append(f"--drive-client-secret={cfg['client_secret']}")
        if cfg.get("token"):
            flags.append(f"--drive-token={cfg['token']}")
        if cfg.get("folder_id"):
            flags.append(f"--drive-root-folder-id={cfg['folder_id']}")
        return remote, flags

    if backend == "onedrive":
        folder = cfg.get("folder_path", "/Backups")
        remote = f":onedrive:{folder}"
        if cfg.get("client_id"):
            flags.append(f"--onedrive-client-id={cfg['client_id']}")
        if cfg.get("client_secret"):
            flags.append(f"--onedrive-client-secret={cfg['client_secret']}")
        if cfg.get("drive_id"):
            flags.append(f"--onedrive-drive-id={cfg['drive_id']}")
        if cfg.get("token"):
            flags.append(f"--onedrive-token={cfg['token']}")
        return remote, flags

    # Fallback
    return cfg.get("path", "/mnt/backup"), []


async def test_storage_connection(dest) -> tuple[bool, str]:
    """Test connectivity to a storage destination."""
    try:
        remote, flags = _build_backend(dest)
        if dest.backend == "local":
            if os.path.isdir(remote):
                return True, f"Local path {remote} exists and is accessible"
            # Try to create it
            try:
                os.makedirs(remote, exist_ok=True)
                return True, f"Local path {remote} created successfully"
            except OSError as e:
                return False, f"Local path {remote} does not exist and could not be created: {e}"

        exit_code, stdout, stderr = await _run_rclone(["lsd", remote, "--max-depth", "1"] + flags)
        if exit_code == 0:
            return True, f"Connected to {dest.backend} storage"
        return False, f"Failed: {stderr.strip()}"

    except Exception as e:
        return False, str(e)


async def get_storage_usage(dest) -> dict:
    """Get storage usage information."""
    remote, flags = _build_backend(dest)

    if dest.backend == "local":
        try:
            usage = shutil.disk_usage(remote)
            return {
                "total_bytes": usage.total,
                "used_bytes": usage.used,
                "free_bytes": usage.free,
                "percent_used": round(usage.used / usage.total * 100, 1),
            }
        except Exception as e:
            return {"error": str(e)}

    exit_code, stdout, stderr = await _run_rclone(["about", remote, "--json"] + flags)
    if exit_code == 0:
        try:
            data = json.loads(stdout)
            return {
                "total_bytes": data.get("total"),
                "used_bytes": data.get("used"),
                "free_bytes": data.get("free"),
                "percent_used": round(data.get("used", 0) / data.get("total", 1) * 100, 1) if data.get("total") else None,
            }
        except json.JSONDecodeError:
            return {"error": "Failed to parse rclone output"}
    return {"error": stderr}


async def list_storage_directory(dest, path: str = "/") -> list[dict]:
    """List files in a storage destination directory."""
    remote, flags = _build_backend(dest)
    full_path = f"{remote}/{path.lstrip('/')}" if path != "/" else remote

    if dest.backend == "local":
        try:
            entries = []
            for entry in os.scandir(full_path):
                stat = entry.stat()
                entries.append({
                    "name": entry.name,
                    "type": "directory" if entry.is_dir() else "file",
                    "size": stat.st_size if entry.is_file() else None,
                    "modified": stat.st_mtime,
                })
            return sorted(entries, key=lambda x: (x["type"] != "directory", x["name"]))
        except Exception as e:
            return [{"error": str(e)}]

    exit_code, stdout, stderr = await _run_rclone(["lsjson", full_path] + flags)
    if exit_code == 0:
        try:
            items = json.loads(stdout)
            return [
                {
                    "name": item["Name"],
                    "type": "directory" if item.get("IsDir") else "file",
                    "size": item.get("Size"),
                    "modified": item.get("ModTime"),
                }
                for item in items
            ]
        except json.JSONDecodeError:
            return [{"error": "Failed to parse rclone output"}]
    return [{"error": stderr}]


async def copy_file_to_storage(dest, local_path: str, remote_subpath: str) -> tuple[bool, str]:
    """Copy a file to a storage destination."""
    remote, flags = _build_backend(dest)
    target = f"{remote}/{remote_subpath}"

    if dest.backend == "local":
        target_dir = os.path.dirname(f"{remote}/{remote_subpath}")
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(local_path, f"{remote}/{remote_subpath}")
        return True, f"Copied to {remote}/{remote_subpath}"

    exit_code, stdout, stderr = await _run_rclone(["copyto", local_path, target] + flags, timeout=3600)
    if exit_code == 0:
        return True, f"Copied to {target}"
    return False, f"Failed: {stderr}"
