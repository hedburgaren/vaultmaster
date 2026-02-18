import asyncio
import json
import logging

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


def _build_remote_name(dest) -> str:
    """Build rclone remote spec from storage destination config."""
    backend = dest.backend
    config = dest.config

    if backend == "local":
        return config.get("path", "/mnt/backup")
    elif backend == "s3":
        # Assumes rclone config already set up, or use env-based config
        return f"{config.get('remote_name', 's3')}:{config.get('bucket', 'backups')}"
    elif backend == "gdrive":
        return f"{config.get('remote_name', 'gdrive')}:{config.get('folder', 'backups')}"
    elif backend == "sftp":
        return f"{config.get('remote_name', 'sftp')}:{config.get('path', '/backups')}"
    elif backend == "b2":
        return f"{config.get('remote_name', 'b2')}:{config.get('bucket', 'backups')}"
    else:
        return config.get("path", "/mnt/backup")


async def test_storage_connection(dest) -> tuple[bool, str]:
    """Test connectivity to a storage destination."""
    try:
        remote = _build_remote_name(dest)
        if dest.backend == "local":
            import os
            if os.path.isdir(remote):
                return True, f"Local path {remote} exists and is accessible"
            return False, f"Local path {remote} does not exist"

        exit_code, stdout, stderr = await _run_rclone(["lsd", remote, "--max-depth", "1"])
        if exit_code == 0:
            return True, f"Connected to {remote}"
        return False, f"Failed: {stderr}"

    except Exception as e:
        return False, str(e)


async def get_storage_usage(dest) -> dict:
    """Get storage usage information."""
    remote = _build_remote_name(dest)

    if dest.backend == "local":
        import shutil
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

    exit_code, stdout, stderr = await _run_rclone(["about", remote, "--json"])
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
    remote = _build_remote_name(dest)
    full_path = f"{remote}/{path.lstrip('/')}" if path != "/" else remote

    if dest.backend == "local":
        import os
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

    exit_code, stdout, stderr = await _run_rclone(["lsjson", full_path])
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
    remote = _build_remote_name(dest)
    target = f"{remote}/{remote_subpath}"

    if dest.backend == "local":
        import shutil
        import os
        target_dir = os.path.dirname(f"{remote}/{remote_subpath}")
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(local_path, f"{remote}/{remote_subpath}")
        return True, f"Copied to {remote}/{remote_subpath}"

    exit_code, stdout, stderr = await _run_rclone(["copyto", local_path, target], timeout=3600)
    if exit_code == 0:
        return True, f"Copied to {target}"
    return False, f"Failed: {stderr}"
