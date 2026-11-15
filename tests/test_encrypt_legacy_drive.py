"""Encrypting the legacy plaintext Google Drive backups in place.

Run: python -m tests.test_encrypt_legacy_drive

No database, rclone or age binary: the Drive is a dict, the crypto is a
reversible stand-in that writes a real age header, and the session is a fake.
The code under test is the real api/maintenance/encrypt_legacy_drive.py.
"""

import asyncio
import hashlib
import os
import sys
import tempfile
import uuid
from types import SimpleNamespace

from api.maintenance import encrypt_legacy_drive as m

FAILURES = []
PREFIX = ":drive:"
HEADER = b"age-encryption.org/v1\n"


def check(cond, msg):
    if cond:
        print(f"  ok   {msg}")
    else:
        print(f"  FAIL {msg}")
        FAILURES.append(msg)


def sha(b):
    return hashlib.sha256(b).hexdigest()


class Drive:
    """The Google Drive: stored path -> bytes."""
    def __init__(self):
        self.files = {}


class StubOps:
    def __init__(self, drive, break_decrypt=False, fail_upload=False, fail_remove_plain=False):
        self.d = drive
        self.break_decrypt = break_decrypt
        self.fail_upload = fail_upload
        self.fail_remove_plain = fail_remove_plain
        self.removed = []
        self.uploaded = []

    async def download(self, dest, path, local):
        if path not in self.d.files:
            return False, "not found"
        with open(local, "wb") as fh:
            fh.write(self.d.files[path])
        return True, "ok"

    async def upload(self, dest, local, sub):
        if self.fail_upload:
            return False, "Failed: quota"
        target = f"{PREFIX}/{sub}"
        with open(local, "rb") as fh:
            self.d.files[target] = fh.read()
        self.uploaded.append(target)
        return True, target

    async def remove(self, dest, path):
        self.removed.append(path)
        if self.fail_remove_plain and not path.endswith(".age"):
            return False, "denied"
        self.d.files.pop(path, None)
        return True, "removed"

    async def encrypt(self, src, dst, recipient):
        with open(src, "rb") as fh:
            data = fh.read()
        with open(dst, "wb") as fh:
            fh.write(HEADER + data[::-1])

    async def decrypt(self, src, dst):
        with open(src, "rb") as fh:
            data = fh.read()
        out = data[len(HEADER):][::-1]
        if self.break_decrypt:
            out = out + b"x"
        with open(dst, "wb") as fh:
            fh.write(out)

    def is_age_file(self, path):
        with open(path, "rb") as fh:
            return fh.read(4).hex() == "6167652d"


class FakeDb:
    def __init__(self, fail_commit=False, artifacts=()):
        self.added, self.commits, self.rollbacks = [], 0, 0
        self.fail_commit = fail_commit
        self.artifacts = {a.id: a for a in artifacts}

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        if self.fail_commit:
            raise RuntimeError("db down")
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def execute(self, stmt):
        ids = [v for v in stmt.compile().params.values() if isinstance(v, uuid.UUID)]
        art = self.artifacts.get(ids[0]) if ids else None
        return SimpleNamespace(scalar_one_or_none=lambda: art)


def make_artifact(drive, name="vaultmaster_20260630_041549.dump.gz", content=b"plaintext dump bytes",
                  checksum=None, job="VaultMaster DB"):
    path = f"{PREFIX}/hedburgaren/{job}/{name}"
    drive.files[path] = content
    return SimpleNamespace(id=uuid.uuid4(), filename=name, remote_path=path, size_bytes=len(content),
                           checksum_sha256=checksum if checksum is not None else sha(content),
                           is_encrypted=False, is_deleted=False, purged_at=None)


DEST = SimpleNamespace(name="Google Drive", backend="gdrive", id=uuid.uuid4())


def convert(artifact, ops, db):
    with tempfile.TemporaryDirectory() as wd:
        return asyncio.run(m.convert_one(artifact, DEST, db, ops, wd, "age1recipient", PREFIX))


def test_mismatch_is_skipped_and_nothing_changes():
    d = Drive()
    a = make_artifact(d, checksum="0" * 64)
    before = dict(vars(a))
    ops, db = StubOps(d), FakeDb()
    r = convert(a, ops, db)
    check(r.status == m.SKIP_MISMATCH, f"a checksum mismatch is skipped and reported ({r.status})")
    check(vars(a) == before and not ops.uploaded and not db.commits, "mismatch: row untouched, nothing uploaded, no commit")
    check(a.remote_path in d.files, "mismatch: the plaintext is still on the Drive")
    r2 = convert(make_artifact(d, "x.gz", checksum="pending"), StubOps(d), FakeDb())
    check(r2.status == m.SKIP_UNVERIFIABLE, "a row with no usable checksum is skipped, not guessed at")


def test_failure_after_upload_leaves_row_and_plaintext_and_removes_ciphertext():
    d = Drive()
    a = make_artifact(d)
    before = dict(vars(a))
    plain_before = d.files[a.remote_path]
    ops = StubOps(d, break_decrypt=True)
    r = convert(a, ops, FakeDb())
    check(r.status == m.FAILED and "decrypted readback" in r.detail, f"a bad readback fails ({r.detail})")
    check(ops.uploaded and ops.uploaded[0] not in d.files, "the uploaded ciphertext is removed again")
    check(vars(a) == before, "the row is untouched")
    check(d.files.get(a.remote_path) == plain_before, "the plaintext is untouched")

    # A database failure at the very end behaves the same.
    d2 = Drive()
    a2 = make_artifact(d2)
    before2 = dict(vars(a2))
    ops2, db2 = StubOps(d2), FakeDb(fail_commit=True)
    r2 = convert(a2, ops2, db2)
    check(r2.status == m.FAILED and "row update" in r2.detail, f"a failing commit fails the artifact ({r2.detail})")
    check(vars(a2) == before2 and db2.rollbacks == 1, "commit failure: row restored, rolled back")
    check(ops2.uploaded[0] not in d2.files and a2.remote_path in d2.files,
          "commit failure: ciphertext removed, plaintext kept")

    d3 = Drive()
    a3 = make_artifact(d3)
    r3 = convert(a3, StubOps(d3, fail_upload=True), FakeDb())
    check(r3.status == m.FAILED and a3.is_encrypted is False and a3.remote_path in d3.files, "a failed upload changes nothing")


def test_success_updates_the_row_like_the_executor():
    d = Drive()
    content = b"PlastShop dump \x00\x01 bytes" * 50
    a = make_artifact(d, "utv.plastshop.se_20260630_180049.dump.gz", content, job="PlastShop Odoo DB")
    old_path = a.remote_path
    ops, db = StubOps(d), FakeDb()
    r = convert(a, ops, db)
    new_path = old_path + ".age"
    cipher = d.files.get(new_path, b"")
    check(r.status == m.DONE, f"converted ({r.status} {r.detail})")
    check(a.filename == "utv.plastshop.se_20260630_180049.dump.gz.age", "filename gets the executor's .age suffix")
    check(a.remote_path == new_path == f"{PREFIX}/hedburgaren/PlastShop Odoo DB/{a.filename}",
          "remote path: same directory, the stored path returned by the upload")
    check(a.size_bytes == len(cipher) and a.size_bytes != len(content), "size_bytes is the size of the encrypted file")
    check(a.checksum_sha256 == sha(cipher), "checksum_sha256 is the sha256 of the encrypted file")
    check(a.is_encrypted is True and cipher.startswith(HEADER), "is_encrypted is true, and the Drive holds an age file")
    check(old_path not in d.files, "the plaintext is gone from the Drive")
    check(db.commits == 1 and len(db.added) == 1 and db.added[0].action == "artifact.encrypt_legacy",
          "one transaction with one audit entry")
    check(sha(StubOps(d).d.files[new_path][len(HEADER):][::-1]) == sha(content), "the ciphertext decrypts to the original")


def patch_run(drive, rows, enc_paths=(), orphans=(), extra_files=()):
    """Patch discovery so run() works without a database or rclone."""
    db = FakeDb(artifacts=rows)

    class Sess:
        async def __aenter__(self_inner):
            return db

        async def __aexit__(self_inner, *a):
            return False

    async def dests(_db):
        return [DEST]

    async def plain_rows(_db, _dest):
        return [r for r in rows if not r.is_encrypted]

    async def enc(_db, _dest):
        return set(enc_paths)

    async def listing(_dest, _dir):
        files = [(p.split(":drive:/", 1)[1], len(b)) for p, b in drive.files.items()]
        return files

    from api.services import rclone_client
    saved = [(m, "find_drive_dest", m.find_drive_dest), (m, "plaintext_artifacts", m.plaintext_artifacts),
             (m, "encrypted_artifact_paths", m.encrypted_artifact_paths), (m, "list_drive_files", m.list_drive_files),
             (rclone_client, "_build_backend", rclone_client._build_backend)]
    m.find_drive_dest, m.plaintext_artifacts, m.encrypted_artifact_paths = dests, plain_rows, enc
    m.list_drive_files = listing
    rclone_client._build_backend = lambda dest: (PREFIX, [])

    def restore():
        for obj, name, old in saved:
            setattr(obj, name, old)
    return (lambda: Sess()), db, restore


def run_apply(drive, rows, ops, apply=True, **kw):
    from api.services import age_crypto
    saved = (age_crypto.validate_public_key, age_crypto.assert_keypair_roundtrips)
    age_crypto.validate_public_key = lambda k: "age1recipient"
    age_crypto.assert_keypair_roundtrips = lambda: None
    sess, db, restore = patch_run(drive, rows, **kw)
    lines = []
    try:
        with tempfile.TemporaryDirectory() as base:
            rc = asyncio.run(m.run(apply, "hedburgaren", ops=ops, session_factory=sess, out=lines.append, workbase=base))
    finally:
        restore()
        age_crypto.validate_public_key, age_crypto.assert_keypair_roundtrips = saved
    return rc, lines


def test_orphans_are_never_touched_and_dry_run_changes_nothing():
    d = Drive()
    a = make_artifact(d)
    orphan = f"{PREFIX}/hedburgaren/Old Job/orphan_20260414_010101.tar.gz"
    d.files[orphan] = b"nobody knows this one"
    snapshot = dict(d.files)
    rc, lines = run_apply(d, [a], StubOps(d), apply=False)
    check(rc == 0 and d.files == snapshot and not a.is_encrypted, "dry run: exit 0 and nothing changed")
    check(any("orphan" in l and "orphan_20260414" in l for l in lines), "dry run: the orphan is reported")
    check(any("convert" in l and a.filename in l for l in lines), "dry run: the artifact to convert is listed")
    ops = StubOps(d)
    rc, lines = run_apply(d, [a], ops)
    check(rc == 0 and a.is_encrypted, f"apply: the artifact is converted (rc={rc})")
    check(d.files.get(orphan) == b"nobody knows this one" and orphan not in ops.removed, "apply: the orphan is untouched")


def test_resume_skips_done_and_a_failure_exits_non_zero():
    d = Drive()
    a, b = make_artifact(d, "a.dump.gz", b"aaa"), make_artifact(d, "b.dump.gz", b"bbb", job="n8n Data")
    rc, _ = run_apply(d, [a, b], StubOps(d))
    check(rc == 0 and a.is_encrypted and b.is_encrypted, "first run converts both")
    ops = StubOps(d)
    rc, lines = run_apply(d, [a, b], ops)
    check(rc == 0 and not ops.uploaded and not ops.removed, "second run: nothing to do, nothing uploaded or removed")

    d2 = Drive()
    good, bad = make_artifact(d2, "g.dump.gz", b"g"), make_artifact(d2, "z.dump.gz", b"z", checksum="1" * 64, job="Other")
    rc, lines = run_apply(d2, [good, bad], StubOps(d2))
    check(rc == 1 and good.is_encrypted and not bad.is_encrypted, "one skipped artifact: the other still converts, exit is non-zero")
    check(any("summary:" in l for l in lines) and any("NOT everything" in l for l in lines), "a final summary is printed")

    # The plaintext could not be removed after the row changed: a re-run cleans the leftover.
    d3 = Drive()
    c = make_artifact(d3, "c.dump.gz", b"ccc")
    old = c.remote_path
    rc, _ = run_apply(d3, [c], StubOps(d3, fail_remove_plain=True))
    check(rc == 1 and c.is_encrypted and old in d3.files, "plaintext removal failed: exit non-zero, row already encrypted")
    ops = StubOps(d3)
    rc, lines = run_apply(d3, [c], ops, enc_paths=[c.remote_path])
    check(rc == 0 and old not in d3.files and c.remote_path in d3.files, "the re-run removes the leftover plaintext, never the ciphertext")


def test_only_the_drive_and_only_live_plaintext_rows_are_selected():
    from sqlalchemy.dialects import postgresql

    class Cap:
        def __init__(self):
            self.stmt = None

        async def execute(self, stmt):
            self.stmt = stmt
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    cap = Cap()
    asyncio.run(m.plaintext_artifacts(cap, DEST))
    sql = str(cap.stmt.compile(dialect=postgresql.dialect()))
    check("storage_id" in sql and "is_encrypted" in sql and "is_deleted" in sql and "purged_at IS NULL" in sql,
          "the query is limited to the Drive destination, unencrypted, not deleted, not purged (local copies never selected)")


def test_check_one():
    d = Drive()
    enc_art = SimpleNamespace(id=uuid.uuid4(), remote_path=f"{PREFIX}/hedburgaren/J/x.gz.age", size_bytes=5)
    d.files[enc_art.remote_path] = HEADER + b"\x8a\x13binary"

    def sess_for(art):
        class Db:
            async def execute(self, stmt):
                return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: art, all=lambda: []))

        class S:
            async def __aenter__(self):
                return Db()

            async def __aexit__(self, *a):
                return False
        return lambda: S()

    saved = m.find_drive_dest

    async def dests(_db):
        return [DEST]
    m.find_drive_dest = dests
    try:
        lines = []
        with tempfile.TemporaryDirectory() as base:
            rc = asyncio.run(m.check_one(ops=StubOps(d), session_factory=sess_for(enc_art), out=lines.append, workbase=base))
        check(rc == 0 and any("RESULT: encrypted" in l for l in lines), "check-one: an age file passes (header, not gzip, not tar)")
        import gzip
        d.files[enc_art.remote_path] = gzip.compress(b"plain dump")
        lines = []
        with tempfile.TemporaryDirectory() as base:
            rc = asyncio.run(m.check_one(ops=StubOps(d), session_factory=sess_for(enc_art), out=lines.append, workbase=base))
        check(rc == 1 and any("NOT PROTECTED" in l for l in lines), "check-one: a gzip file is reported as not protected")
    finally:
        m.find_drive_dest = saved


def main():
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            print(name)
            fn()
    if FAILURES:
        print(f"{len(FAILURES)} failure(s)")
        sys.exit(1)
    print("all passed")


if __name__ == "__main__":
    main()
