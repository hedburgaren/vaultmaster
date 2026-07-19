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

    Decrypts any `enc:vN:...` values in config in-flight; secrets only
    exist in plaintext for the duration of this call.
    """
    backend = dest.backend
    # Work on a copy so we don't mutate the SQLAlchemy attribute (which
    # would mark the row dirty and round-trip the plaintext to DB).
    try:
        from api.services.credentials_crypto import decrypt_dict_secrets
        cfg = decrypt_dict_secrets(dict(dest.config or {})) or {}
    except Exception:  # crypto not configured — fall back to raw config
        cfg = dict(dest.config or {})

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
    """Copy a file to a storage destination.

    On success the second element is the STORED PATH, not a human message.
    It used to be f"Copied to {target}", and the caller wrote that sentence
    straight into BackupArtifact.remote_path. Every artifact ever recorded
    therefore had a path of the form "Copied to /srv/archive/..." which
    download_file_from_storage could not resolve, so restore and restore
    validation could never locate a file. Callers that want a log line should
    format one from the returned path.
    """
    remote, flags = _build_backend(dest)
    target = f"{remote}/{remote_subpath}"

    if dest.backend == "local":
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.copy2(local_path, target)
        return True, target

    exit_code, stdout, stderr = await _run_rclone(["copyto", local_path, target] + flags, timeout=3600)
    if exit_code == 0:
        return True, target
    return False, f"Failed: {stderr}"


# Legacy artifacts stored the copy_file_to_storage *message* as their path.
_LEGACY_PATH_PREFIX = "Copied to "


def normalize_stored_path(remote_path: str) -> str:
    """Strip the legacy "Copied to " prefix from a stored artifact path.

    Roughly 8300 artifacts predate the fix above and carry the prefix. Handling
    it on read makes those backups locatable again instead of requiring a bulk
    rewrite of historical rows.
    """
    p = (remote_path or "").strip()
    if p.startswith(_LEGACY_PATH_PREFIX):
        return p[len(_LEGACY_PATH_PREFIX):].strip()
    return p


async def delete_file_from_storage(dest, remote_path: str) -> tuple[bool, str]:
    """Delete a single artifact file from a storage destination.

    This did not exist until 2026-07-19, which is why nothing ever reclaimed
    space: rotation only ever set a database flag. Retention was enforced on
    paper and nowhere else.

    A missing file counts as success. Purge is expected to be re-runnable and
    an already-gone file is the desired end state, not an error.
    """
    path = normalize_stored_path(remote_path)
    if not path:
        return False, "empty remote_path"

    if dest.backend == "local":
        if not os.path.isfile(path):
            return True, f"already absent: {path}"
        try:
            os.remove(path)
            return True, f"deleted {path}"
        except OSError as e:
            return False, f"delete failed: {e}"

    remote, flags = _build_backend(dest)
    target = path if ":" in path else f"{remote}/{path}"
    exit_code, _stdout, stderr = await _run_rclone(["deletefile", target] + flags, timeout=300)
    if exit_code == 0:
        return True, f"deleted {target}"

    # Do not infer the outcome from the error text. The first version matched
    # "not found" and "does not exist", and rclone actually says "is a directory
    # or doesn't exist" (contraction), so every already-deleted file was
    # reported as a failure. Its row then never got flagged and the next run
    # retried the same delete forever.
    #
    # String matching is the wrong tool anyway: the same phrases appear for
    # bucket-not-found and permission problems, which are real failures. Check
    # the actual state instead: if the file is not there, the desired end state
    # is reached, whatever rclone said on the way.
    check_code, check_out, _ = await _run_rclone(
        ["lsf", target] + flags, timeout=120
    )
    if check_code != 0 or not (check_out or "").strip():
        return True, f"already absent: {target}"

    return False, f"delete failed, file still present: {stderr.strip()[:200]}"


async def download_file_from_storage(dest, remote_path: str, local_path: str) -> tuple[bool, str]:
    """Download an artifact from a storage destination to a local file.

    `remote_path` is what was stored on `BackupArtifact.remote_path` —
    typically the full backend-prefixed path returned by copy_file_to_storage.
    For local backends it's a filesystem path; for cloud backends it's a
    backend:bucket/path string that rclone understands.
    """
    remote_path = normalize_stored_path(remote_path)

    if dest.backend == "local":
        if not os.path.isfile(remote_path):
            return False, f"local file not found: {remote_path}"
        os.makedirs(os.path.dirname(local_path), exist_ok=True)
        shutil.copy2(remote_path, local_path)
        return True, f"Copied {remote_path} -> {local_path}"

    remote, flags = _build_backend(dest)
    # remote_path typically already contains the backend prefix; rclone
    # handles `backend:bucket/path` directly.
    source = remote_path if ":" in remote_path else f"{remote}/{remote_path}"
    exit_code, _stdout, stderr = await _run_rclone(["copyto", source, local_path] + flags, timeout=3600)
    if exit_code == 0:
        return True, f"Downloaded {source} -> {local_path}"
    return False, f"Download failed: {stderr.strip()[:200]}"
