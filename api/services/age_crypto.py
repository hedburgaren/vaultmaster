"""age encryption for backup artifacts.

Context (2026-07-19): this module did not exist. `AGE_PUBLIC_KEY` was declared
in config.py and read nowhere, no code path ever invoked the age binary, and
`is_encrypted` on the artifact row was set from `job.encrypt`, the operator's
*intent*, never the actual outcome. Result: 29 jobs requested encryption, 5336
artifacts claimed to be encrypted, and every one of them was plain gzip. Those
plaintext files were replicated to Google Drive.

Two rules follow from that, and both are load-bearing:

1. **Fail closed.** If a job asks for encryption and we cannot deliver it, the
   run fails. We never silently downgrade to plaintext. A failed backup is a
   visible, fixable problem. A backup that lies about being encrypted is not.

2. **Trust bytes, not flags.** `is_encrypted` is only ever set from a readback
   of the artifact's magic bytes, never from configuration.

Encryption happens in-pipe on the source host (`pg_dump | gzip | age -r ...`)
so plaintext never lands on disk. Only the *public* key is sent to the source
host; it is not secret. The private identity lives solely in the worker
container for restore, and must be stored off-box as well. An encrypted backup
whose only key sits on the machine being backed up is not a backup.
"""

import logging
import re
import shlex

from api.config import get_settings

logger = logging.getLogger(__name__)

# First bytes of an age file: the ASCII header "age-encryption.org/v1".
# 6167652d is "age-". Plain gzip is 1f8b08, which is what we were shipping.
AGE_MAGIC_HEX = "6167652d"
GZIP_MAGIC_HEX = "1f8b08"

# age x25519 recipient: "age1" + 58 bech32 chars. Bech32 excludes 1, b, i, o.
_AGE_PUBKEY_RE = re.compile(r"^age1[02-9ac-hj-np-z]{58}$")

# Extension appended to an artifact once it has been through age.
AGE_SUFFIX = ".age"


class EncryptionUnavailable(Exception):
    """Encryption was requested but cannot be performed.

    Raised during preflight so the run fails before any data is written,
    rather than after we have produced a plaintext file we would then have
    to chase down and delete.
    """


def get_public_key() -> str:
    return (get_settings().age_public_key or "").strip()


def is_configured() -> bool:
    """True when a syntactically valid recipient key is configured."""
    key = get_public_key()
    return bool(key) and bool(_AGE_PUBKEY_RE.match(key))


def validate_public_key(key: str) -> str:
    """Return the key if it is a well-formed age recipient, else raise.

    A malformed key is caught here rather than by the age binary on the
    source host, where the failure would surface as an opaque pipeline error
    partway through a multi-gigabyte dump.
    """
    k = (key or "").strip()
    if not k:
        raise EncryptionUnavailable(
            "AGE_PUBLIC_KEY is empty. Jobs with encrypt=true cannot run. "
            "Generate a keypair with `age-keygen`, put the public key in "
            "AGE_PUBLIC_KEY, and store the private identity off-box."
        )
    if not _AGE_PUBKEY_RE.match(k):
        raise EncryptionUnavailable(
            f"AGE_PUBLIC_KEY is not a valid age recipient (got {k[:12]!r}...). "
            "Expected an 'age1...' x25519 public key from `age-keygen`."
        )
    return k


async def assert_age_available(server, run_command) -> None:
    """Verify the age binary exists on the source host.

    Encryption runs in-pipe where the dump is produced, so age must be present
    there, not merely in the worker image. This is checked before the dump
    starts so a missing binary fails the run cleanly.
    """
    exit_code, stdout, stderr = await run_command(server, "command -v age", timeout=30)
    if exit_code != 0 or not stdout.strip():
        host = getattr(server, "host", "?")
        raise EncryptionUnavailable(
            f"age binary not found on source host {host}. Encryption is "
            "requested but cannot be performed there. Install age on the "
            "source host (apt install age, or drop a static binary in "
            "/usr/local/bin/age)."
        )


async def preflight(server, run_command, encrypt_requested: bool) -> str | None:
    """Gate a run before any data is written.

    Returns the validated recipient key when encryption is on, or None when the
    job does not request encryption. Raises EncryptionUnavailable when the job
    wants encryption we cannot deliver, which is the fail-closed path.
    """
    if not encrypt_requested:
        return None
    key = validate_public_key(get_public_key())
    await assert_age_available(server, run_command)
    return key


def wrap_pipeline(pipeline: str, recipient: str | None, output_path: str) -> str:
    """Build the shell command that writes the artifact.

    `pipeline` is the data-producing stage(s) without any redirect, e.g.
    "pg_dump -U u -Fc db | gzip". When a recipient is given, age is appended as
    the final stage so plaintext never touches disk.

    The whole thing runs under `bash -o pipefail` because the default is to
    report only the *last* stage's exit status. Without it a failing pg_dump
    piped into a succeeding age produces exit 0 and a perfectly valid age file
    wrapped around a truncated dump, a corrupt backup that reports success.
    Note that sudo wraps commands in `sh -c` (dash on Ubuntu), which has no
    pipefail, hence the explicit bash.
    """
    stages = pipeline
    if recipient:
        stages = f"{stages} | age -r {shlex.quote(recipient)}"
    full = f"{stages} > {shlex.quote(output_path)}"
    return f"bash -o pipefail -c {shlex.quote(full)}"


async def read_magic_hex(server, run_command, remote_path: str, nbytes: int = 4) -> str:
    """Read the first bytes of a remote file as lowercase hex."""
    cmd = f"head -c {int(nbytes)} {shlex.quote(remote_path)} | od -An -tx1 | tr -d ' \\n'"
    exit_code, stdout, stderr = await run_command(server, cmd, timeout=60)
    if exit_code != 0:
        raise Exception(f"Could not read magic bytes from {remote_path}: {stderr}")
    return stdout.strip().lower()


async def verify_encrypted(server, run_command, remote_path: str) -> None:
    """Confirm on-disk bytes are actually age-encrypted, or raise.

    This is the check that would have caught the original problem. It reads the
    artifact back rather than trusting anything we believe about the pipeline.
    """
    magic = await read_magic_hex(server, run_command, remote_path)
    if magic.startswith(AGE_MAGIC_HEX):
        return
    if magic.startswith(GZIP_MAGIC_HEX):
        raise Exception(
            f"Encryption verification FAILED for {remote_path}: file begins "
            f"{magic} (gzip), expected {AGE_MAGIC_HEX} (age). The artifact is "
            "plaintext and must not be recorded as encrypted."
        )
    raise Exception(
        f"Encryption verification FAILED for {remote_path}: unexpected magic "
        f"bytes {magic!r}, expected {AGE_MAGIC_HEX} (age)."
    )


async def detect_is_encrypted(server, run_command, remote_path: str) -> bool:
    """Best-effort readback used to stamp the artifact row.

    Deliberately returns False when the bytes cannot be read: an artifact whose
    encryption we cannot confirm is recorded as not encrypted. Under-claiming is
    recoverable. Over-claiming is what put plaintext on Google Drive.
    """
    try:
        magic = await read_magic_hex(server, run_command, remote_path)
    except Exception as exc:
        logger.warning(
            "Could not read magic bytes from %s (%s), recording is_encrypted=False",
            remote_path, exc,
        )
        return False
    return magic.startswith(AGE_MAGIC_HEX)
