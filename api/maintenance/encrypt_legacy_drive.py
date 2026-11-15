"""Encrypt, in place, the plaintext backups that still sit on Google Drive.

Run inside the worker container (it mounts ./api, the rclone config, the work
area and the age identity):

    python -m api.maintenance.encrypt_legacy_drive            # dry run
    python -m api.maintenance.encrypt_legacy_drive --apply    # do it
    python -m api.maintenance.encrypt_legacy_drive --check-one

Why: policy (2026-07-19) says nothing unencrypted may sit on Google Drive, and
56 monthly retention copies from before that date still do. They are restore
points, so they are converted, not removed.

The result must be indistinguishable from what the backup executor writes
today, so every field follows it:

- the file is `age -r <AGE_PUBLIC_KEY>` of the existing file (the executor's
  `... | gzip | age`), named `<old filename>.age` (age_crypto.AGE_SUFFIX), in
  the same remote directory (server/job/filename layout);
- `checksum_sha256` and `size_bytes` describe the ENCRYPTED file on disk (the
  executor runs sha256sum and stat on the file it produced, after age);
- `is_encrypted` is set only after the uploaded copy was downloaded again,
  decrypted with the identity, and its sha256 equals the original's. Bytes, not
  intent, which is the rule age_crypto.py exists for.

Per artifact, one at a time: download, verify the stored checksum, encrypt,
upload, download the uploaded copy and decrypt it, compare, and only then
update the row (with an audit entry, in one transaction) and remove the
plaintext. Any failure before that point leaves the plaintext and the row
untouched and removes the ciphertext that was uploaded. A second run skips
what is done. Local (hedburgaren archive) copies are never touched: local
plaintext is exempt by policy. Drive files with no artifact row are reported
and never touched.
"""

import argparse
import asyncio
import gzip
import hashlib
import logging
import os
import re
import shutil
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field

logger = logging.getLogger("encrypt_legacy_drive")

DEFAULT_DRIVE_DIR = "hedburgaren"
WORK_BASE = os.environ.get("VM_WORK_DIR", "/tmp/vaultmaster")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

# Statuses of one artifact
DONE = "converted"
SKIP_MISMATCH = "skipped: checksum mismatch"
SKIP_UNVERIFIABLE = "skipped: no usable stored checksum"
SKIP_NAME = "skipped: filename already ends in .age"
FAILED = "FAILED"


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


# ── operations the conversion depends on (replaced in tests) ─────────────────

class Ops:
    """The real rclone client and age, exactly as the executor uses them."""

    async def download(self, dest, remote_path, local):
        from api.services.rclone_client import download_file_from_storage
        return await download_file_from_storage(dest, remote_path, local)

    async def upload(self, dest, local, sub_path):
        from api.services.rclone_client import copy_file_to_storage
        return await copy_file_to_storage(dest, local, sub_path)

    async def remove(self, dest, remote_path):
        from api.services.rclone_client import delete_file_from_storage
        return await delete_file_from_storage(dest, remote_path)

    async def encrypt(self, src, dst, recipient):
        from api.services.restore_validator import _run
        code, _, err = await _run(["age", "-r", recipient, "-o", dst, src], timeout=3600)
        if code != 0:
            raise Exception(f"age encrypt failed (exit {code}): {err.strip()[:200]}")

    async def decrypt(self, src, dst):
        from api.services import age_crypto
        from api.services.restore_validator import _run
        await age_crypto.decrypt_local_file(src, dst, _run)

    def is_age_file(self, path):
        from api.services import age_crypto
        return age_crypto.file_is_age_encrypted(path)


@dataclass
class Result:
    artifact_id: str
    name: str
    status: str
    detail: str = ""


@dataclass
class Summary:
    results: list = field(default_factory=list)

    def add(self, r):
        self.results.append(r)

    @property
    def failed(self):
        return [r for r in self.results if r.status == FAILED]


# ── the conversion of one artifact ───────────────────────────────────────────

def new_names(artifact, remote_prefix: str):
    """(new filename, new stored path, sub path for the upload), by the
    executor's layout: the same directory, the same name plus .age."""
    from api.services.age_crypto import AGE_SUFFIX
    from api.services.rclone_client import normalize_stored_path

    old_path = normalize_stored_path(artifact.remote_path)
    new_filename = artifact.filename + AGE_SUFFIX
    new_path = old_path + AGE_SUFFIX
    prefix = remote_prefix.rstrip("/") + "/"
    if old_path.startswith(prefix):
        sub = old_path[len(prefix):]
    else:
        sub = old_path.lstrip("/")
    return new_filename, new_path, sub + AGE_SUFFIX


async def convert_one(artifact, dest, db, ops, workdir: str, recipient: str, remote_prefix: str) -> Result:
    """Convert one artifact. Never raises; returns what happened."""
    from api.services.rclone_client import normalize_stored_path

    aid = str(artifact.id)
    name = artifact.filename
    if name.endswith(".age"):
        return Result(aid, name, SKIP_NAME)
    stored = (artifact.checksum_sha256 or "").strip().lower()
    if not _SHA256_RE.match(stored):
        return Result(aid, name, SKIP_UNVERIFIABLE, f"stored checksum {stored[:16]!r}")

    old_path = normalize_stored_path(artifact.remote_path)
    new_filename, _, sub_path = new_names(artifact, remote_prefix)
    plain = os.path.join(workdir, "plain")
    cipher = os.path.join(workdir, "cipher.age")
    check_in = os.path.join(workdir, "check.age")
    check_out = os.path.join(workdir, "check.plain")
    uploaded = None

    original = {k: getattr(artifact, k) for k in
                ("filename", "remote_path", "size_bytes", "checksum_sha256", "is_encrypted")}

    async def drop_upload():
        if uploaded:
            ok, msg = await ops.remove(dest, uploaded)
            if not ok:
                logger.error("could not remove uploaded ciphertext %s: %s", uploaded, msg)
                return f" (ALSO could not remove the uploaded ciphertext {uploaded}: {msg})"
        return ""

    try:
        ok, msg = await ops.download(dest, old_path, plain)
        if not ok:
            return Result(aid, name, FAILED, f"download: {msg}")
        actual = sha256_file(plain)
        if actual != stored:
            return Result(aid, name, SKIP_MISMATCH, f"stored {stored[:16]}.. actual {actual[:16]}..")

        await ops.encrypt(plain, cipher, recipient)
        if not ops.is_age_file(cipher) or os.path.getsize(cipher) == 0:
            return Result(aid, name, FAILED, "encryption produced no age file")
        new_size = os.path.getsize(cipher)
        new_sum = sha256_file(cipher)

        ok, msg = await ops.upload(dest, cipher, sub_path)
        if not ok:
            return Result(aid, name, FAILED, f"upload: {msg}")
        uploaded = msg  # the stored path, as the executor records it

        ok, msg = await ops.download(dest, uploaded, check_in)
        if not ok:
            return Result(aid, name, FAILED, f"readback download: {msg}" + await drop_upload())
        if sha256_file(check_in) != new_sum:
            return Result(aid, name, FAILED, "uploaded copy differs from what was sent" + await drop_upload())
        await ops.decrypt(check_in, check_out)
        if sha256_file(check_out) != actual:
            return Result(aid, name, FAILED, "decrypted readback does not equal the original" + await drop_upload())

        # Only now does the row change: one transaction with the audit entry.
        artifact.filename = new_filename
        artifact.remote_path = uploaded
        artifact.size_bytes = new_size
        artifact.checksum_sha256 = new_sum
        artifact.is_encrypted = True
        try:
            from api.routers.audit import log_action
            await log_action(
                db, action="artifact.encrypt_legacy", resource_type="backup_artifact",
                resource_id=aid,
                detail=f"Legacy plaintext Drive artifact encrypted in place: {name} -> {new_filename}",
                meta={"old_path": old_path, "new_path": uploaded, "old_size": original["size_bytes"],
                      "new_size": new_size, "plaintext_sha256": actual, "ciphertext_sha256": new_sum},
            )
            await db.commit()
        except Exception as exc:
            try:
                await db.rollback()
            except Exception:
                pass
            for k, v in original.items():
                setattr(artifact, k, v)
            return Result(aid, name, FAILED, f"row update: {exc}" + await drop_upload())
    except Exception as exc:  # noqa: BLE001
        return Result(aid, name, FAILED, f"{type(exc).__name__}: {exc}" + await drop_upload())

    # The row points at the verified ciphertext now. Remove the plaintext.
    ok, msg = await ops.remove(dest, old_path)
    if not ok:
        return Result(aid, name, FAILED,
                      f"converted, but the plaintext {old_path} could not be removed: {msg}. "
                      "A re-run removes it as a leftover.")
    return Result(aid, name, DONE, f"{old_path} -> {uploaded}")


# ── discovery ────────────────────────────────────────────────────────────────

async def find_drive_dest(db):
    from sqlalchemy import select
    from api.models.storage_destination import StorageDestination

    dests = (await db.execute(
        select(StorageDestination).where(StorageDestination.backend == "gdrive")
    )).scalars().all()
    return list(dests)


async def plaintext_artifacts(db, dest):
    from sqlalchemy import select
    from api.models.backup_artifact import BackupArtifact

    rows = (await db.execute(
        select(BackupArtifact)
        .where(BackupArtifact.storage_id == dest.id,
               BackupArtifact.is_encrypted == False,  # noqa: E712
               BackupArtifact.is_deleted == False,  # noqa: E712
               BackupArtifact.purged_at.is_(None))
        .order_by(BackupArtifact.created_at)
    )).scalars().all()
    return list(rows)


async def encrypted_artifact_paths(db, dest):
    from sqlalchemy import select
    from api.models.backup_artifact import BackupArtifact
    from api.services.rclone_client import normalize_stored_path

    rows = (await db.execute(
        select(BackupArtifact.remote_path).where(BackupArtifact.storage_id == dest.id,
                                                 BackupArtifact.is_encrypted == True,  # noqa: E712
                                                 BackupArtifact.is_deleted == False)  # noqa: E712
    )).all()
    return {normalize_stored_path(r[0]) for r in rows}


async def list_drive_files(dest, drive_dir: str):
    """(relative path, size) of every file under drive_dir on the Drive."""
    import json
    from api.services.rclone_client import _build_backend, _run_rclone

    remote, flags = _build_backend(dest)
    code, out, err = await _run_rclone(
        ["lsjson", "-R", "--files-only", f"{remote}/{drive_dir.strip('/')}"] + flags, timeout=900)
    if code != 0:
        raise RuntimeError(f"could not list the Drive path {drive_dir}: {err.strip()[:200]}")
    items = json.loads(out or "[]")
    base = drive_dir.strip("/")
    return [(f"{base}/{i['Path']}", i.get("Size")) for i in items]


def classify_files(files, rows, encrypted_paths, remote_prefix):
    """Split the plaintext files on the Drive into those with a row to convert,
    leftovers of an already converted artifact, and true orphans."""
    from api.services.rclone_client import normalize_stored_path

    prefix = remote_prefix.rstrip("/") + "/"

    def rel(p):
        p = normalize_stored_path(p)
        return p[len(prefix):] if p.startswith(prefix) else p.lstrip("/")

    row_paths = {rel(r.remote_path) for r in rows}
    enc_rel = {rel(p) for p in encrypted_paths}
    present = {p for p, _ in files}
    with_row, leftovers, orphans = [], [], []
    for path, size in files:
        if path.endswith(".age"):
            continue
        if path in row_paths:
            with_row.append(path)
        elif path + ".age" in enc_rel and path + ".age" in present:
            leftovers.append(path)
        else:
            orphans.append((path, size))
    return with_row, leftovers, orphans


# ── the run ──────────────────────────────────────────────────────────────────

async def run(apply: bool, drive_dir: str, ops=None, session_factory=None, out=print, workbase=None) -> int:
    from api.services import age_crypto
    from api.services.rclone_client import _build_backend, normalize_stored_path

    if session_factory is None:
        from api.tasks.backup_tasks import get_task_session as session_factory
    ops = ops or Ops()
    summary = Summary()

    recipient = None
    if apply:
        recipient = age_crypto.validate_public_key(age_crypto.get_public_key())
        age_crypto.assert_keypair_roundtrips()  # the identity must open what we seal

    async with session_factory() as db:
        dests = await find_drive_dest(db)
        if len(dests) != 1:
            out(f"expected exactly one gdrive storage destination, found {len(dests)}: refusing")
            return 2
        dest = dests[0]
        rows = await plaintext_artifacts(db, dest)
        enc_paths = await encrypted_artifact_paths(db, dest)
        row_ids = [r.id for r in rows]
    remote_prefix, _ = _build_backend(dest)

    files = await list_drive_files(dest, drive_dir)
    _, leftovers, orphans = classify_files(files, rows, enc_paths, remote_prefix)

    out(f"Drive destination: {dest.name}")
    out(f"plaintext artifacts with a row: {len(rows)} ({sum(r.size_bytes or 0 for r in rows)} bytes)")
    for r in rows:
        out(f"  convert  {normalize_stored_path(r.remote_path)}  ({r.size_bytes} bytes)")
    out(f"leftover plaintext of already converted artifacts: {len(leftovers)}")
    for p in leftovers:
        out(f"  leftover {p}")
    out(f"orphans (plaintext on Drive, no artifact row; report only, never touched): {len(orphans)}")
    for p, size in orphans:
        out(f"  orphan   {p}  ({size} bytes)")

    if not apply:
        out("dry run: nothing changed. Re-run with --apply to convert.")
        return 0

    base = workbase or (WORK_BASE if os.path.isdir(WORK_BASE) else None)
    for artifact_id in row_ids:
        workdir = tempfile.mkdtemp(prefix="vm-encrypt-legacy-", dir=base)
        res = None
        try:
            async with session_factory() as db:
                from sqlalchemy import select
                from api.models.backup_artifact import BackupArtifact
                artifact = (await db.execute(
                    select(BackupArtifact).where(BackupArtifact.id == artifact_id)
                )).scalar_one_or_none()
                if artifact is None or artifact.is_encrypted or artifact.is_deleted:
                    continue  # done by someone else since the listing
                res = await convert_one(artifact, dest, db, ops, workdir, recipient, remote_prefix)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        if res is not None:
            summary.add(res)
            out(f"  {res.status}: {res.name} {res.detail}")

    # Leftovers: the encrypted twin exists on Drive and has a verified row.
    for p in leftovers:
        ok, msg = await ops.remove(dest, f"{remote_prefix.rstrip('/')}/{p}")
        summary.add(Result("-", p, DONE if ok else FAILED, f"leftover plaintext: {msg}"))
        out(f"  {'removed leftover' if ok else 'FAILED leftover'}: {p} {msg}")

    counts = {}
    for r in summary.results:
        counts[r.status] = counts.get(r.status, 0) + 1
    out("summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())) + f"; orphans untouched={len(orphans)}")
    skipped = [r for r in summary.results if r.status.startswith("skipped")]
    if skipped or summary.failed:
        out("NOT everything is encrypted: look at the skipped and FAILED lines above.")
    return 1 if (summary.failed or skipped) else 0


async def check_one(ops=None, session_factory=None, out=print, workbase=None, artifact_id=None) -> int:
    """Download one already-encrypted Drive artifact and show it is unreadable
    without the key: an age header, and neither gzip nor tar."""
    from sqlalchemy import select
    from api.models.backup_artifact import BackupArtifact
    from api.services import age_crypto

    if session_factory is None:
        from api.tasks.backup_tasks import get_task_session as session_factory
    ops = ops or Ops()
    async with session_factory() as db:
        dests = await find_drive_dest(db)
        if len(dests) != 1:
            out(f"expected exactly one gdrive storage destination, found {len(dests)}")
            return 2
        dest = dests[0]
        q = select(BackupArtifact).where(BackupArtifact.storage_id == dest.id,
                                         BackupArtifact.is_encrypted == True,  # noqa: E712
                                         BackupArtifact.is_deleted == False,  # noqa: E712
                                         BackupArtifact.purged_at.is_(None))
        if artifact_id:
            q = q.where(BackupArtifact.id == artifact_id)
        else:
            q = q.order_by(BackupArtifact.size_bytes)
        artifact = (await db.execute(q.limit(1))).scalars().first()
    if artifact is None:
        out("no encrypted artifact on the Drive to check")
        return 2

    base = workbase or (WORK_BASE if os.path.isdir(WORK_BASE) else None)
    workdir = tempfile.mkdtemp(prefix="vm-encrypt-check-", dir=base)
    try:
        local = os.path.join(workdir, "file")
        ok, msg = await ops.download(dest, artifact.remote_path, local)
        if not ok:
            out(f"download failed: {msg}")
            return 1
        with open(local, "rb") as fh:
            head = fh.read(len(age_crypto.AGE_HEADER))
        is_age = head == age_crypto.AGE_HEADER.encode()
        try:
            with gzip.open(local, "rb") as g:
                g.read(16)
            gz_readable = True
        except Exception:
            gz_readable = False
        tar_readable = tarfile.is_tarfile(local)
        out(f"artifact: {artifact.remote_path}")
        out(f"first bytes: {head!r}  age header: {is_age}")
        out(f"readable as gzip without the key: {gz_readable}")
        out(f"readable as tar without the key: {tar_readable}")
        good = is_age and not gz_readable and not tar_readable
        out("RESULT: " + ("encrypted, unreadable without the key" if good else "NOT PROTECTED"))
        return 0 if good else 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Encrypt legacy plaintext Google Drive backups in place")
    p.add_argument("--apply", action="store_true", help="convert (default is a dry run)")
    p.add_argument("--check-one", action="store_true", help="download one encrypted Drive artifact and show it is unreadable")
    p.add_argument("--artifact-id", help="with --check-one: a specific artifact")
    p.add_argument("--drive-dir", default=DEFAULT_DRIVE_DIR, help="Drive path to scan for orphans (default hedburgaren)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.check_one:
        import uuid
        aid = uuid.UUID(args.artifact_id) if args.artifact_id else None
        return asyncio.run(check_one(artifact_id=aid))
    return asyncio.run(run(args.apply, args.drive_dir))


if __name__ == "__main__":
    sys.exit(main())
