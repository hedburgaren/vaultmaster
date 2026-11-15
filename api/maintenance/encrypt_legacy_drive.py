"""Encrypt, in place, the plaintext backups that still sit on Google Drive.

Run inside the worker container (it mounts ./api, the rclone config, the work
area and the age identity):

    python -m api.maintenance.encrypt_legacy_drive            # dry run
    python -m api.maintenance.encrypt_legacy_drive --apply    # do it
    python -m api.maintenance.encrypt_legacy_drive --check-one

Why: policy (2026-07-19) says nothing unencrypted may sit on Google Drive, and
the monthly retention copies from before that date still do. They are restore
points, so they are converted, not removed.

What is plaintext is decided by the Drive listing, never by the database: every
file under the Drive root that does not end in .age. The is_encrypted flag on
the rows is not trusted (34 rows claimed encryption for plaintext files), and
the stored path is normalised first (about 8300 rows carry rclone's message,
"Copied to :drive:/...", as their path).

The result must be indistinguishable from what the backup executor writes
today, so every field follows it:

- the file is `age -r <AGE_PUBLIC_KEY>` of the existing file (the executor's
  `... | gzip | age`), named `<old filename>.age` (age_crypto.AGE_SUFFIX), in
  the same remote directory (server/job/filename layout);
- `remote_path` is the path the upload returns, in today's format;
- `checksum_sha256` and `size_bytes` describe the ENCRYPTED file on disk (the
  executor runs sha256sum and stat on the file it produced, after age);
- `is_encrypted` is set only after the uploaded copy was downloaded again,
  decrypted with the identity, and its sha256 equals that of the downloaded
  plaintext. Bytes, not intent, which is the rule age_crypto.py exists for.

Per file, one at a time: download, encrypt, upload, download the uploaded copy
and decrypt it, compare, and only then update the rows (with an audit entry, in
one transaction) and remove the plaintext. Any failure before that point leaves
the plaintext and the rows untouched and removes the ciphertext that was
uploaded. A stored checksum that does not match the Drive file does not stop
the conversion (the Drive file is the backup we have); it is recorded in the
audit entry and the summary. Files with no artifact row (orphans) are
encrypted the same way, audit-logged, and no row is created. A second run skips
what is done. Local (hedburgaren archive) copies are never touched: local
plaintext is exempt by policy.
"""

import argparse
import asyncio
import gzip
import hashlib
import logging
import os
import shutil
import sys
import tarfile
import tempfile
from dataclasses import dataclass, field

logger = logging.getLogger("encrypt_legacy_drive")

# The whole Drive root, so that nothing plaintext hides outside one folder.
DEFAULT_DRIVE_DIR = ""
WORK_BASE = os.environ.get("VM_WORK_DIR", "/tmp/vaultmaster")

# Statuses of one Drive file
DONE = "converted"
DONE_MISMATCH = "converted (stored checksum did not match)"
DONE_ORPHAN = "converted (no artifact row)"
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
        """Permanent removal: NOT moved to the Drive trash (a plaintext copy
        left in the trash is still a plaintext copy on Drive). Only this tool
        uses the flag; the rest of VaultMaster deletes as before."""
        from api.services.rclone_client import (
            _build_backend, _run_rclone, listing_says_absent, normalize_stored_path)

        path = normalize_stored_path(remote_path)
        remote, flags = _build_backend(dest)
        target = path if ":" in path else f"{remote}/{path}"
        code, _, err = await _run_rclone(
            ["deletefile", "--drive-use-trash=false", target] + flags, timeout=300)
        if code == 0:
            return True, f"removed permanently (not in the Drive trash): {target}"
        parent, _, name = target.rpartition("/")
        lcode, listing, _ = await _run_rclone(["lsf", parent, "--files-only"] + flags, timeout=120)
        if lcode == 0 and listing_says_absent(listing, name):
            return True, f"already absent: {target}"
        return False, f"permanent removal failed: {err.strip()[:200]}"

    async def exists(self, dest, remote_path):
        """True, False, or None when it cannot be told (treated as 'exists')."""
        from api.services.rclone_client import (
            _build_backend, _run_rclone, listing_says_absent, normalize_stored_path)

        path = normalize_stored_path(remote_path)
        remote, flags = _build_backend(dest)
        target = path if ":" in path else f"{remote}/{path}"
        parent, _, name = target.rpartition("/")
        code, listing, _ = await _run_rclone(["lsf", parent, "--files-only"] + flags, timeout=120)
        if code == 3:  # directory not found: nothing there
            return False
        if code != 0:
            return None
        return not listing_says_absent(listing, name)

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


# ── paths ────────────────────────────────────────────────────────────────────

def rel_path(stored: str, remote_prefix: str) -> str:
    """A stored path or a Drive path as the path under the remote root, with
    the broken "Copied to " prefix removed."""
    from api.services.rclone_client import normalize_stored_path

    p = normalize_stored_path(stored)
    prefix = remote_prefix.rstrip("/") + "/"
    return p[len(prefix):] if p.startswith(prefix) else p.lstrip("/")


def full_path(rel: str, remote_prefix: str) -> str:
    """The path in today's stored format: <remote>/<rel>."""
    return f"{remote_prefix.rstrip('/')}/{rel}"


# ── the conversion of one file ───────────────────────────────────────────────

async def convert_file(rel: str, rows, dest, db, ops, workdir: str, recipient: str, remote_prefix: str) -> Result:
    """Encrypt one plaintext Drive file in place. `rows` are the artifact rows
    that point at it (none for an orphan). Never raises; returns what happened.

    The Drive file is the backup we have: a stored checksum that does not match
    is recorded, not a reason to leave the file in plaintext. The round trip is
    checked against the sha of the downloaded file itself."""
    from api.services.age_crypto import AGE_SUFFIX

    name = rel.rsplit("/", 1)[-1]
    old_path = full_path(rel, remote_prefix)
    new_rel = rel + AGE_SUFFIX
    plain = os.path.join(workdir, "plain")
    cipher = os.path.join(workdir, "cipher.age")
    check_in = os.path.join(workdir, "check.age")
    check_out = os.path.join(workdir, "check.plain")
    uploaded = None
    aid = str(rows[0].id) if rows else "-"

    original = [{k: getattr(r, k) for k in
                 ("filename", "remote_path", "size_bytes", "checksum_sha256", "is_encrypted")} for r in rows]

    async def drop_upload():
        if uploaded:
            ok, msg = await ops.remove(dest, uploaded)
            if not ok:
                logger.error("could not remove uploaded ciphertext %s: %s", uploaded, msg)
                return f" (ALSO could not remove the uploaded ciphertext {uploaded}: {msg})"
        return ""

    notes = []
    try:
        # Never overwrite a file we did not write: a <file>.age that is already
        # there is either a verified leftover (handled by verify_twin, not here)
        # or something unknown, and the copy step would silently replace it.
        # Unknown (the check itself failed) counts as present.
        if await ops.exists(dest, full_path(new_rel, remote_prefix)) is not False:
            return Result(aid, name, FAILED,
                          f"{new_rel} already exists on the Drive (or its existence could not be "
                          "checked): refusing to overwrite it; nothing was uploaded or removed")
        ok, msg = await ops.download(dest, old_path, plain)
        if not ok:
            return Result(aid, name, FAILED, f"download: {msg}")
        actual = sha256_file(plain)
        for r in rows:
            stored = (r.checksum_sha256 or "").strip().lower()
            if stored != actual:
                notes.append(f"stored checksum did not match (stored {stored[:16]!r}, file {actual[:16]})")
                break
        if any(r.is_encrypted for r in rows):
            notes.append("row claimed is_encrypted=true but the Drive file was plaintext")

        await ops.encrypt(plain, cipher, recipient)
        if not ops.is_age_file(cipher) or os.path.getsize(cipher) == 0:
            return Result(aid, name, FAILED, "encryption produced no age file")
        new_size = os.path.getsize(cipher)
        new_sum = sha256_file(cipher)

        ok, msg = await ops.upload(dest, cipher, new_rel)
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

        # Only now does anything change: rows and audit entry in one transaction.
        for r in rows:
            r.filename = name + AGE_SUFFIX
            r.remote_path = uploaded
            r.size_bytes = new_size
            r.checksum_sha256 = new_sum
            r.is_encrypted = True
        try:
            from api.routers.audit import log_action
            detail = f"Legacy plaintext Drive file encrypted in place: {name} -> {name + AGE_SUFFIX}"
            if notes:
                detail += "; " + "; ".join(notes)
            if not rows:
                detail += "; no artifact row exists for this file (orphan), none was created"
            await log_action(
                db, action="artifact.encrypt_legacy",
                resource_type="backup_artifact" if rows else "drive_file",
                resource_id=aid if rows else rel,
                detail=detail,
                meta={"old_path": old_path, "new_path": uploaded,
                      "old_size": original[0]["size_bytes"] if original else None,
                      "new_size": new_size, "plaintext_sha256": actual, "ciphertext_sha256": new_sum,
                      "rows": [str(r.id) for r in rows], "orphan": not rows,
                      "checksum_mismatch": any("checksum" in n for n in notes),
                      "flag_was_wrong": any("is_encrypted" in n for n in notes)},
            )
            await db.commit()
        except Exception as exc:
            try:
                await db.rollback()
            except Exception:
                pass
            for r, o in zip(rows, original):
                for k, v in o.items():
                    setattr(r, k, v)
            return Result(aid, name, FAILED, f"row update: {exc}" + await drop_upload())
    except Exception as exc:  # noqa: BLE001
        return Result(aid, name, FAILED, f"{type(exc).__name__}: {exc}" + await drop_upload())

    # Rows (if any) point at the verified ciphertext now. Remove the plaintext.
    status = DONE_ORPHAN if not rows else (DONE_MISMATCH if any("checksum" in n for n in notes) else DONE)
    ok, msg = await ops.remove(dest, old_path)
    if not ok:
        return Result(aid, name, FAILED,
                      f"converted, but the plaintext {old_path} could not be removed: {msg}. "
                      "A re-run removes it as a leftover.")
    return Result(aid, name, status,
                  f"{old_path} -> {uploaded}" + (f" [{'; '.join(notes)}]" if notes else ""))


# ── discovery ────────────────────────────────────────────────────────────────

async def find_drive_dest(db):
    from sqlalchemy import select
    from api.models.storage_destination import StorageDestination

    dests = (await db.execute(
        select(StorageDestination).where(StorageDestination.backend == "gdrive")
    )).scalars().all()
    return list(dests)


async def live_artifacts(db, dest):
    """Every artifact row on this destination that purge has not finished with,
    whatever its is_encrypted says: the flag is not trusted, the Drive listing
    decides what is plaintext. Rows flagged is_deleted but not yet purged are
    included on purpose: a later purge must remove the .age file, not leave it
    orphaned because the row still pointed at the old plaintext name."""
    from sqlalchemy import select
    from api.models.backup_artifact import BackupArtifact

    rows = (await db.execute(
        select(BackupArtifact)
        .where(BackupArtifact.storage_id == dest.id,
               BackupArtifact.purged_at.is_(None))
        .order_by(BackupArtifact.created_at)
    )).scalars().all()
    return list(rows)


async def list_drive_files(dest, drive_dir: str):
    """(path under the remote root, size) of every file under drive_dir."""
    import json
    from api.services.rclone_client import _build_backend, _run_rclone

    remote, flags = _build_backend(dest)
    base = drive_dir.strip("/")
    target = f"{remote}/{base}" if base else remote
    code, out, err = await _run_rclone(["lsjson", "-R", "--files-only", target] + flags, timeout=900)
    if code != 0:
        raise RuntimeError(f"could not list the Drive path {drive_dir!r}: {err.strip()[:200]}")
    items = json.loads(out or "[]")
    return [((f"{base}/" if base else "") + i["Path"], i.get("Size")) for i in items]


def rows_by_rel(rows, remote_prefix):
    by_rel = {}
    for r in rows:
        by_rel.setdefault(rel_path(r.remote_path, remote_prefix), []).append(r)
    return by_rel


def plan(files, rows, remote_prefix):
    """Group the plaintext files on the Drive.

    Returns (targets, twins). A target is (rel, size, [rows]); rows is empty
    for an orphan. A twin is a plaintext file whose `.age` name already exists on
    the Drive (a previous run died before removing the plaintext, or something
    else put a file there). Whatever any row says, it is only ever removed after
    verify_twin proved the .age decrypts to exactly this plaintext; a conversion
    never overwrites such a file."""
    present = {p for p, _ in files}
    by_rel = rows_by_rel(rows, remote_prefix)
    targets, twins = [], []
    for path, size in files:
        if path.endswith(".age"):
            continue
        if path + ".age" in present:
            twins.append(path)
            continue
        targets.append((path, size, by_rel.get(path, [])))
    return targets, twins


async def verify_twin(rel: str, rows, dest, db, ops, workdir: str, remote_prefix: str) -> Result:
    """A plaintext file with an existing .age twin: prove the twin is the same
    data, then remove the plaintext. Never trusts a row's is_encrypted."""
    from api.services.age_crypto import AGE_SUFFIX

    name = rel.rsplit("/", 1)[-1]
    plain_path, twin_path = full_path(rel, remote_prefix), full_path(rel + AGE_SUFFIX, remote_prefix)
    plain = os.path.join(workdir, "plain")
    twin = os.path.join(workdir, "twin.age")
    twin_out = os.path.join(workdir, "twin.plain")
    aid = str(rows[0].id) if rows else "-"
    try:
        ok, msg = await ops.download(dest, plain_path, plain)
        if not ok:
            return Result(aid, name, FAILED, f"leftover check, download of the plaintext: {msg}")
        ok, msg = await ops.download(dest, twin_path, twin)
        if not ok:
            return Result(aid, name, FAILED, f"leftover check, download of the .age: {msg}")
        if not ops.is_age_file(twin):
            return Result(aid, name, FAILED,
                          f"{rel + AGE_SUFFIX} exists but is not an age file: plaintext kept, nothing overwritten")
        await ops.decrypt(twin, twin_out)
        plain_sha = sha256_file(plain)
        if sha256_file(twin_out) != plain_sha:
            return Result(aid, name, FAILED,
                          f"{rel + AGE_SUFFIX} exists but does not decrypt to this plaintext: plaintext kept, "
                          "nothing overwritten")
        stale = [r for r in rows]  # rows still pointing at the plaintext name
        if stale:
            new_size, new_sum = os.path.getsize(twin), sha256_file(twin)
            for r in stale:
                r.filename, r.remote_path = name + AGE_SUFFIX, twin_path
                r.size_bytes, r.checksum_sha256, r.is_encrypted = new_size, new_sum, True
            from api.routers.audit import log_action
            await log_action(db, action="artifact.encrypt_legacy", resource_type="backup_artifact",
                             resource_id=aid,
                             detail=f"Leftover plaintext {name} verified against its .age and rows repointed",
                             meta={"new_path": twin_path, "plaintext_sha256": plain_sha, "ciphertext_sha256": new_sum,
                                   "rows": [str(r.id) for r in stale]})
            await db.commit()
    except Exception as exc:  # noqa: BLE001
        return Result(aid, name, FAILED, f"leftover check: {type(exc).__name__}: {exc}")
    ok, msg = await ops.remove(dest, plain_path)
    if not ok:
        return Result(aid, name, FAILED, f"verified leftover, but the plaintext could not be removed: {msg}")
    return Result(aid, name, DONE, f"verified leftover: the .age decrypts to this file; plaintext {msg}")


# ── the run ──────────────────────────────────────────────────────────────────

async def run(apply: bool, drive_dir: str, ops=None, session_factory=None, out=print, workbase=None) -> int:
    from api.services import age_crypto
    from api.services.rclone_client import _build_backend

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
        rows = await live_artifacts(db, dest)
    remote_prefix, _ = _build_backend(dest)

    files = await list_drive_files(dest, drive_dir)
    targets, leftovers = plan(files, rows, remote_prefix)

    ok_rows, odd_rows, orphans = [], [], []
    for rel, size, trows in targets:
        if not trows:
            orphans.append((rel, size, trows))
        elif any(r.is_encrypted for r in trows) or any(r.size_bytes != size for r in trows):
            odd_rows.append((rel, size, trows))
        else:
            ok_rows.append((rel, size, trows))

    def total(group):
        return sum(sz or 0 for _, sz, _ in group)

    out(f"Drive destination: {dest.name}")
    out(f"plaintext files on the Drive: {len(targets)} ({total(targets)} bytes)")
    out(f"  with an artifact row, looks consistent: {len(ok_rows)} ({total(ok_rows)} bytes)")
    out(f"  with an artifact row, wrong flag or size differs (checksum is verified when applying): "
        f"{len(odd_rows)} ({total(odd_rows)} bytes)")
    out(f"  orphans, no artifact row (encrypted in place too, no row is created): {len(orphans)} ({total(orphans)} bytes)")
    for label, group in (("ok", ok_rows), ("odd", odd_rows), ("orphan", orphans)):
        for rel, size, trows in group:
            flag = ""
            if trows and any(r.is_encrypted for r in trows):
                flag = " [row says is_encrypted=true, file is plaintext]"
            out(f"  {label:6} {rel}  ({size} bytes){flag}")
    out(f"plaintext files whose .age already exists (verified by decrypting before the plaintext is removed): {len(leftovers)}")
    for p in leftovers:
        out(f"  twin     {p}")
    out("plaintext removal is PERMANENT: the Drive trash is bypassed (--drive-use-trash=false), "
        "so no plaintext copy stays recoverable there")

    if not apply:
        out("dry run: nothing changed. Re-run with --apply to convert.")
        return 0

    base = workbase or (WORK_BASE if os.path.isdir(WORK_BASE) else None)
    for rel, _size, trows in ok_rows + odd_rows + orphans:
        workdir = tempfile.mkdtemp(prefix="vm-encrypt-legacy-", dir=base)
        try:
            async with session_factory() as db:
                from sqlalchemy import select
                from api.models.backup_artifact import BackupArtifact
                fresh = []
                for r in trows:
                    row = (await db.execute(
                        select(BackupArtifact).where(BackupArtifact.id == r.id)
                    )).scalar_one_or_none()
                    if row is not None:
                        fresh.append(row)
                res = await convert_file(rel, fresh, dest, db, ops, workdir, recipient, remote_prefix)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        summary.add(res)
        out(f"  {res.status}: {res.name} {res.detail}")

    # Twins: the .age already exists. Removed only after it decrypts to the plaintext.
    by_rel = rows_by_rel(rows, remote_prefix)
    for p in leftovers:
        workdir = tempfile.mkdtemp(prefix="vm-encrypt-legacy-", dir=base)
        try:
            async with session_factory() as db:
                from sqlalchemy import select
                from api.models.backup_artifact import BackupArtifact
                fresh = []
                for r in by_rel.get(p, []):
                    row = (await db.execute(
                        select(BackupArtifact).where(BackupArtifact.id == r.id)
                    )).scalar_one_or_none()
                    if row is not None:
                        fresh.append(row)
                res = await verify_twin(p, fresh, dest, db, ops, workdir, remote_prefix)
        finally:
            shutil.rmtree(workdir, ignore_errors=True)
        summary.add(res)
        out(f"  {res.status}: {res.name} {res.detail}")

    counts = {}
    for r in summary.results:
        counts[r.status] = counts.get(r.status, 0) + 1
    out("summary: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        + "; plaintext was removed permanently, not moved to the Drive trash")
    if summary.failed:
        out("NOT everything is encrypted: look at the FAILED lines above.")
    return 1 if summary.failed else 0


async def expected_plaintext_sha(session_factory, artifact):
    """The plaintext sha256 the conversion recorded in its audit entry, if any."""
    from sqlalchemy import select
    from api.models.audit_log import AuditLog

    async with session_factory() as db:
        entry = (await db.execute(
            select(AuditLog).where(AuditLog.action == "artifact.encrypt_legacy",
                                   AuditLog.resource_id == str(artifact.id))
            .order_by(AuditLog.created_at.desc()).limit(1)
        )).scalars().first()
    return ((entry.meta or {}).get("plaintext_sha256")) if entry else None


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
                                         BackupArtifact.purged_at.is_(None),
                                         BackupArtifact.filename.like("%.age"))
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
        unreadable = is_age and not gz_readable and not tar_readable

        # And with the key: the downloaded bytes are the ones the row records,
        # and they decrypt to the plaintext whose sha the conversion logged.
        downloaded_sha = sha256_file(local)
        sha_matches_row = downloaded_sha == (artifact.checksum_sha256 or "").lower()
        out(f"sha256 of the downloaded file equals the row's checksum: {sha_matches_row}")
        decryptable, plain_ok = False, None
        try:
            await ops.decrypt(local, os.path.join(workdir, "decrypted"))
            decrypted = os.path.join(workdir, "decrypted")
            decrypted_sha = sha256_file(decrypted)
            decryptable = os.path.getsize(decrypted) > 0
            out(f"decrypts with the key: {decryptable}; sha256 of the decrypted file: {decrypted_sha}")
            expected = None
            try:
                expected = await expected_plaintext_sha(session_factory, artifact)
            except Exception as exc:  # noqa: BLE001
                out(f"(no audit entry to compare against: {exc})")
            if expected:
                plain_ok = decrypted_sha == expected
                out(f"equals the plaintext sha recorded at conversion: {plain_ok}")
            else:
                with open(decrypted, "rb") as fh:
                    plain_ok = fh.read(2) == b"\x1f\x8b" or tarfile.is_tarfile(decrypted)
                out(f"no recorded plaintext sha (artifact not converted by this tool); decrypted file is a "
                    f"gzip or tar archive: {plain_ok}")
        except Exception as exc:  # noqa: BLE001
            out(f"could not decrypt with the key: {type(exc).__name__}: {exc}")
        good = unreadable and sha_matches_row and decryptable and plain_ok is True
        out("RESULT: " + ("encrypted: unreadable without the key, decrypts correctly with it"
                          if good else "NOT PROVEN: see the lines above"))
        return 0 if good else 1
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Encrypt legacy plaintext Google Drive backups in place")
    p.add_argument("--apply", action="store_true", help="convert (default is a dry run)")
    p.add_argument("--check-one", action="store_true", help="download one encrypted Drive artifact and show it is unreadable")
    p.add_argument("--artifact-id", help="with --check-one: a specific artifact")
    p.add_argument("--drive-dir", default=DEFAULT_DRIVE_DIR, help="Drive path to scan (default: the whole Drive root)")
    args = p.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if args.check_one:
        import uuid
        aid = uuid.UUID(args.artifact_id) if args.artifact_id else None
        return asyncio.run(check_one(artifact_id=aid))
    return asyncio.run(run(args.apply, args.drive_dir))


if __name__ == "__main__":
    sys.exit(main())
