"""Encrypting the legacy plaintext Google Drive backups in place.

Run: python -m tests.test_encrypt_legacy_drive

No database, rclone or age binary: the Drive is a dict, the crypto is a
reversible stand-in that writes a real age header, and the session is a fake.
The code under test is the real api/maintenance/encrypt_legacy_drive.py.

The data it was shaped by (2026-11): 56 plaintext files on the Drive, 49 with a
live artifact row whose remote_path is rclone's message ("Copied to
:drive:/hedburgaren/<job>/<file>"), 34 of those rows claiming is_encrypted=true
for a plaintext file, stored checksums that may not match, and 7 files with no
row at all.
"""

import asyncio
import gzip
import hashlib
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

    async def exists(self, dest, path):
        return path in self.d.files

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


def put(drive, job, name, content):
    rel = f"hedburgaren/{job}/{name}"
    drive.files[f"{PREFIX}/{rel}"] = content
    return rel


def make_row(drive, name="vaultmaster_20260630_041549.dump.gz", content=b"plaintext dump bytes",
             checksum=None, job="VaultMaster DB", encrypted=False, legacy_prefix=True):
    """An artifact row as production has them: the stored path is rclone's
    message, and is_encrypted may lie."""
    rel = put(drive, job, name, content)
    stored = f"{PREFIX}/{rel}"
    return SimpleNamespace(id=uuid.uuid4(), filename=name,
                           remote_path=("Copied to " + stored) if legacy_prefix else stored,
                           size_bytes=len(content),
                           checksum_sha256=checksum if checksum is not None else sha(content),
                           is_encrypted=encrypted, is_deleted=False, purged_at=None)


DEST = SimpleNamespace(name="Google Drive", backend="gdrive", id=uuid.uuid4())


def convert(rel, rows, ops, db):
    with tempfile.TemporaryDirectory() as wd:
        return asyncio.run(m.convert_file(rel, rows, DEST, db, ops, wd, "age1recipient", PREFIX))


def rel_of(row):
    return m.rel_path(row.remote_path, PREFIX)


def test_prefix_normalisation():
    legacy = "Copied to :drive:/hedburgaren/NocoDB DB/nocodb_20260630_183049.dump.gz"
    today = ":drive:/hedburgaren/NocoDB DB/nocodb_20260630_183049.dump.gz"
    want = "hedburgaren/NocoDB DB/nocodb_20260630_183049.dump.gz"
    check(m.rel_path(legacy, PREFIX) == want, "the 'Copied to :drive:/' prefix is stripped to the Drive path")
    check(m.rel_path(today, PREFIX) == want, "today's stored format maps to the same path")
    check(m.rel_path(" Copied to " + today, PREFIX) == want, "stray whitespace around the prefix is tolerated")
    check(m.full_path(want, PREFIX) == today, "and back: the path used for rclone is today's format")

    # A listing entry matches its legacy row by directory and file name.
    d = Drive()
    row = make_row(d)
    targets, leftovers = m.plan([(rel_of(row), 20)], [row], PREFIX)
    check(len(targets) == 1 and targets[0][2] == [row] and not leftovers, "a legacy-path row is matched to its Drive file")


def test_the_flag_is_not_trusted_for_selection():
    d = Drive()
    liar = make_row(d, "liar.dump.gz", b"lie", job="A", encrypted=True)
    honest = make_row(d, "honest.dump.gz", b"yes", job="B", encrypted=False)
    files = [(rel_of(liar), 3), (rel_of(honest), 3)]
    targets, _ = m.plan(files, [liar, honest], PREFIX)
    check({t[0] for t in targets} == {rel_of(liar), rel_of(honest)},
          "selection comes from the listing: a row saying is_encrypted=true is still converted when its file is plaintext")
    # An .age file in the listing is never a target, whatever any row says.
    targets, _ = m.plan([("hedburgaren/A/x.gz.age", 9)], [], PREFIX)
    check(not targets, "a file ending in .age is not plaintext")


def test_lying_row_is_converted_and_corrected():
    d = Drive()
    content = b"PlastShop dump \x00\x01 bytes" * 50
    a = make_row(d, "utv.plastshop.se_20260630_180049.dump.gz", content, job="PlastShop Odoo DB", encrypted=True)
    old = f"{PREFIX}/{rel_of(a)}"
    ops, db = StubOps(d), FakeDb()
    r = convert(rel_of(a), [a], ops, db)
    new_path = old + ".age"
    cipher = d.files.get(new_path, b"")
    check(r.status == m.DONE, f"converted ({r.status} {r.detail})")
    check(a.filename == "utv.plastshop.se_20260630_180049.dump.gz.age", "filename gets the executor's .age suffix")
    check(a.remote_path == new_path and not a.remote_path.startswith("Copied to"),
          "remote_path is today's format (the stored path the upload returns), without the broken prefix")
    check(a.size_bytes == len(cipher) and a.size_bytes != len(content), "size_bytes is the size of the encrypted file")
    check(a.checksum_sha256 == sha(cipher), "checksum_sha256 is the sha256 of the encrypted file")
    check(a.is_encrypted is True and cipher.startswith(HEADER), "is_encrypted is true, and now it is true")
    check(old not in d.files, "the plaintext is gone from the Drive")
    check(db.commits == 1 and len(db.added) == 1 and db.added[0].action == "artifact.encrypt_legacy",
          "one transaction with one audit entry")
    check("is_encrypted=true but the Drive file was plaintext" in db.added[0].detail,
          "the audit entry records that the flag was wrong")
    check(sha(d.files[new_path][len(HEADER):][::-1]) == sha(content), "the ciphertext decrypts to the original")


def test_checksum_mismatch_still_converts_and_is_recorded():
    d = Drive()
    a = make_row(d, checksum="0" * 64)
    old = f"{PREFIX}/{rel_of(a)}"
    plain = d.files[old]
    db = FakeDb()
    r = convert(rel_of(a), [a], StubOps(d), db)
    check(r.status == m.DONE_MISMATCH, f"a stored checksum that does not match does not stop the conversion ({r.status})")
    check("stored checksum did not match" in db.added[0].detail and "stored checksum did not match" in r.detail,
          "the mismatch is in the audit detail and in the summary line")
    check(a.is_encrypted and a.checksum_sha256 == sha(d.files[old + ".age"]),
          "the row gets the checksum of the ciphertext, replacing the wrong one")
    check(sha(d.files[old + ".age"][len(HEADER):][::-1]) == sha(plain),
          "the round trip was checked against the sha of the downloaded file")
    check(old not in d.files, "plaintext removed after verification")


def test_failure_after_upload_leaves_rows_and_plaintext_and_removes_ciphertext():
    d = Drive()
    a = make_row(d)
    before = dict(vars(a))
    old = f"{PREFIX}/{rel_of(a)}"
    plain_before = d.files[old]
    ops = StubOps(d, break_decrypt=True)
    r = convert(rel_of(a), [a], ops, FakeDb())
    check(r.status == m.FAILED and "decrypted readback" in r.detail, f"a bad readback fails ({r.detail})")
    check(ops.uploaded and ops.uploaded[0] not in d.files, "the uploaded ciphertext is removed again")
    check(vars(a) == before and d.files.get(old) == plain_before, "row and plaintext untouched")

    d2 = Drive()
    a2 = make_row(d2)
    before2 = dict(vars(a2))
    ops2, db2 = StubOps(d2), FakeDb(fail_commit=True)
    r2 = convert(rel_of(a2), [a2], ops2, db2)
    check(r2.status == m.FAILED and vars(a2) == before2 and db2.rollbacks == 1, "a failing commit restores the row and rolls back")
    check(ops2.uploaded[0] not in d2.files and f"{PREFIX}/{rel_of(a2)}" in d2.files,
          "commit failure: ciphertext removed, plaintext kept")

    d3 = Drive()
    a3 = make_row(d3)
    r3 = convert(rel_of(a3), [a3], StubOps(d3, fail_upload=True), FakeDb())
    check(r3.status == m.FAILED and a3.is_encrypted is False and f"{PREFIX}/{rel_of(a3)}" in d3.files, "a failed upload changes nothing")


def test_orphan_is_encrypted_in_place_without_a_row():
    d = Drive()
    rel = put(d, "ARC Gruppen Odoo DB", "arcgruppen.se_20260502_135352.dump.gz", b"orphan dump")
    old = f"{PREFIX}/{rel}"
    ops, db = StubOps(d), FakeDb()
    r = convert(rel, [], ops, db)
    cipher = d.files.get(old + ".age", b"")
    check(r.status == m.DONE_ORPHAN, f"an orphan is converted ({r.status})")
    check(cipher.startswith(HEADER) and sha(cipher[len(HEADER):][::-1]) == sha(b"orphan dump"),
          "the age file is on the Drive and round-trips to the original")
    check(old not in d.files, "the plaintext is removed only after verification")
    check(len(db.added) == 1 and db.added[0].resource_type == "drive_file" and db.added[0].resource_id == rel
          and "orphan" in db.added[0].detail, "the orphan is audit-logged, with its path")

    d2 = Drive()
    rel2 = put(d2, "J", "o.gz", b"orphan")
    ops2 = StubOps(d2, break_decrypt=True)
    r2 = convert(rel2, [], ops2, FakeDb())
    check(r2.status == m.FAILED and f"{PREFIX}/{rel2}" in d2.files and not any(p.endswith(".age") for p in d2.files),
          "a failed orphan round trip leaves the plaintext and no ciphertext")


def patch_run(drive, rows):
    """Patch discovery so run() works without a database or rclone."""
    db = FakeDb(artifacts=rows)

    class Sess:
        async def __aenter__(self_inner):
            return db

        async def __aexit__(self_inner, *a):
            return False

    async def dests(_db):
        return [DEST]

    async def live(_db, _dest):
        return list(rows)

    async def listing(_dest, _dir):
        return [(p.split(":drive:/", 1)[1], len(b)) for p, b in drive.files.items()]

    from api.services import rclone_client
    saved = [(m, "find_drive_dest", m.find_drive_dest), (m, "live_artifacts", m.live_artifacts),
             (m, "list_drive_files", m.list_drive_files),
             (rclone_client, "_build_backend", rclone_client._build_backend)]
    m.find_drive_dest, m.live_artifacts, m.list_drive_files = dests, live, listing
    rclone_client._build_backend = lambda dest: (PREFIX, [])

    def restore():
        for obj, name, old in saved:
            setattr(obj, name, old)
    return (lambda: Sess()), db, restore


def run_tool(drive, rows, ops, apply=True):
    from api.services import age_crypto
    saved = (age_crypto.validate_public_key, age_crypto.assert_keypair_roundtrips)
    age_crypto.validate_public_key = lambda k: "age1recipient"
    age_crypto.assert_keypair_roundtrips = lambda: None
    sess, db, restore = patch_run(drive, rows)
    lines = []
    try:
        with tempfile.TemporaryDirectory() as base:
            rc = asyncio.run(m.run(apply, "", ops=ops, session_factory=sess, out=lines.append, workbase=base))
    finally:
        restore()
        age_crypto.validate_public_key, age_crypto.assert_keypair_roundtrips = saved
    return rc, lines


def test_dry_run_prints_the_three_groups_and_changes_nothing():
    d = Drive()
    ok = make_row(d, "ok.dump.gz", b"okay", job="A")
    lie = make_row(d, "lie.dump.gz", b"liar", job="B", encrypted=True)
    sized = make_row(d, "size.dump.gz", b"sized", job="C")
    sized.size_bytes = 999999  # the row's size disagrees with the Drive file
    put(d, "D", "orphan1.gz", b"o1")
    put(d, "D", "orphan2.gz", b"o2o2")
    snapshot = dict(d.files)
    total = sum(len(b) for b in d.files.values())
    rc, lines = run_tool(d, [ok, lie, sized], StubOps(d), apply=False)
    text = "\n".join(lines)
    check(rc == 0 and d.files == snapshot and lie.remote_path.startswith("Copied to") and lie.filename == "lie.dump.gz", "dry run: exit 0, Drive and rows unchanged")
    check("plaintext files on the Drive: 5 (" + str(total) + " bytes)" in text, "dry run: total count and bytes")
    check("looks consistent: 1 " in text, "dry run: one row that looks fine")
    check("wrong flag or size differs (checksum is verified when applying): 2 " in text, "dry run: two rows with wrong flag or size")
    check("orphans, no artifact row (encrypted in place too, no row is created): 2 " in text, "dry run: two orphans")
    check("is_encrypted=true, file is plaintext" in text and "orphan1.gz" in text, "dry run: lists the lying row and the orphans")


def test_apply_converts_all_three_groups_and_resumes():
    d = Drive()
    ok = make_row(d, "ok.dump.gz", b"okay", job="A")
    lie = make_row(d, "lie.dump.gz", b"liar", job="B", encrypted=True)
    bad = make_row(d, "bad.dump.gz", b"badsum", job="C", checksum="2" * 64)
    orphan_rel = put(d, "D", "orphan.gz", b"orph")
    rc, lines = run_tool(d, [ok, lie, bad], StubOps(d))
    plain_left = [p for p in d.files if not p.endswith(".age")]
    check(rc == 0 and not plain_left, f"apply: no plaintext is left on the Drive (rc={rc}, left={plain_left})")
    check(ok.is_encrypted and lie.is_encrypted and bad.is_encrypted, "apply: every row is encrypted")
    check(f"{PREFIX}/{orphan_rel}.age" in d.files, "apply: the orphan is encrypted too")
    check(any("converted (stored checksum did not match)=1" in l for l in lines)
          and any("converted (no artifact row)=1" in l for l in lines), "apply: the summary counts mismatch and orphan")
    ops = StubOps(d)
    rc, lines = run_tool(d, [ok, lie, bad], ops)
    check(rc == 0 and not ops.uploaded and not ops.removed, "a second run does nothing: resumable")


def test_leftover_plaintext_is_removed_on_rerun_and_failure_exits_non_zero():
    d = Drive()
    c = make_row(d, "c.dump.gz", b"ccc")
    old = f"{PREFIX}/{rel_of(c)}"
    rc, _ = run_tool(d, [c], StubOps(d, fail_remove_plain=True))
    check(rc == 1 and c.is_encrypted and old in d.files, "plaintext removal failed: exit non-zero, row already encrypted")
    ops = StubOps(d)
    rc, _ = run_tool(d, [c], ops)
    check(rc == 0 and old not in d.files and c.remote_path in d.files,
          "the re-run removes the leftover plaintext, never the ciphertext")

    d2 = Drive()
    bad = make_row(d2, "z.dump.gz", b"z")
    rc, lines = run_tool(d2, [bad], StubOps(d2, break_decrypt=True))
    check(rc == 1 and any("NOT everything" in l for l in lines) and not bad.is_encrypted, "a failing file: exit non-zero and a final warning")


def test_existing_age_file_is_never_overwritten():
    d = Drive()
    a = make_row(d)
    old = f"{PREFIX}/{rel_of(a)}"
    foreign = old + ".age"
    d.files[foreign] = HEADER + b"someone else's file"
    before = dict(vars(a))
    ops, db = StubOps(d), FakeDb()
    r = convert(rel_of(a), [a], ops, db)
    check(r.status == m.FAILED and "refusing to overwrite" in r.detail, f"a name collision fails the file ({r.detail})")
    check(d.files[foreign] == HEADER + b"someone else's file", "the existing .age is untouched")
    check(not ops.uploaded and not ops.removed and vars(a) == before and old in d.files,
          "nothing uploaded, nothing removed (a file the tool did not create is never deleted), row and plaintext kept")

    class Unknown(StubOps):
        async def exists(self, dest, path):
            return None
    d2 = Drive()
    a2 = make_row(d2)
    r2 = convert(rel_of(a2), [a2], Unknown(d2), FakeDb())
    check(r2.status == m.FAILED and not a2.is_encrypted, "if existence cannot be checked, it counts as present")


def test_twin_is_verified_by_decrypting_before_the_plaintext_goes():
    d = Drive()
    content = b"leftover dump"
    a = make_row(d, "t.dump.gz", content, job="T", encrypted=True)  # flag says encrypted, row still on the plaintext
    old = f"{PREFIX}/{rel_of(a)}"
    d.files[old + ".age"] = HEADER + content[::-1]
    ops, db = StubOps(d), FakeDb()
    with tempfile.TemporaryDirectory() as wd:
        r = asyncio.run(m.verify_twin(rel_of(a), [a], DEST, db, ops, wd, PREFIX))
    check(r.status == m.DONE and old not in d.files and old + ".age" in d.files,
          f"a twin that decrypts to the plaintext lets the plaintext go ({r.status})")
    check(a.remote_path == old + ".age" and a.filename.endswith(".age") and a.is_encrypted
          and a.checksum_sha256 == sha(d.files[old + ".age"]), "rows still on the plaintext name are repointed at the twin")

    for label, twin_bytes in (("different content", HEADER + b"something else"[::-1]), ("not an age file", b"\x1f\x8bnot age")):
        d2 = Drive()
        b = make_row(d2, "u.dump.gz", content, job="U", encrypted=True)
        o2 = f"{PREFIX}/{rel_of(b)}"
        d2.files[o2 + ".age"] = twin_bytes
        ops2 = StubOps(d2)
        with tempfile.TemporaryDirectory() as wd:
            r2 = asyncio.run(m.verify_twin(rel_of(b), [b], DEST, FakeDb(), ops2, wd, PREFIX))
        check(r2.status == m.FAILED and o2 in d2.files and not ops2.removed and d2.files[o2 + ".age"] == twin_bytes,
              f"a twin with {label}: plaintext kept, nothing removed or overwritten")

    # Through run(): the row's flag is ignored, the twin must prove itself.
    d3 = Drive()
    c = make_row(d3, "w.dump.gz", content, job="W", encrypted=True)
    d3.files[f"{PREFIX}/{rel_of(c)}.age"] = HEADER + b"garbage"
    rc, lines = run_tool(d3, [c], StubOps(d3))
    check(rc == 1 and f"{PREFIX}/{rel_of(c)}" in d3.files, "run: a row saying encrypted does not make an unverified twin a leftover")


def test_plaintext_removal_is_permanent_not_trash():
    from api.services import rclone_client
    calls = []

    async def fake_rclone(args, timeout=60):
        calls.append(args)
        return 0, "", ""

    saved = (rclone_client._run_rclone, rclone_client._build_backend)
    rclone_client._run_rclone = fake_rclone
    rclone_client._build_backend = lambda dest: (PREFIX, ["--drive-token=x"])
    try:
        ok, msg = asyncio.run(m.Ops().remove(DEST, "Copied to :drive:/hedburgaren/J/f.gz"))
    finally:
        rclone_client._run_rclone, rclone_client._build_backend = saved
    check(ok and calls[0][0] == "deletefile" and "--drive-use-trash=false" in calls[0]
          and ":drive:/hedburgaren/J/f.gz" in calls[0], "the tool's removal passes --drive-use-trash=false, on the normalised path")
    check("permanently" in msg, "and says so")
    d = Drive()
    a = make_row(d)
    rc, lines = run_tool(d, [a], StubOps(d))
    check(any("permanently" in l and "trash" in l for l in lines), "the apply summary says removal was permanent")
    d = Drive()
    a = make_row(d)
    rc, lines = run_tool(d, [a], StubOps(d), apply=False)
    check(any("PERMANENT" in l and "trash" in l for l in lines), "the dry run states that removal bypasses the Drive trash")


def test_a_deleted_but_unpurged_row_is_updated_too():
    d = Drive()
    a = make_row(d, "gone.dump.gz", b"retired", job="R")
    a.is_deleted = True  # flagged by rotation, not yet purged
    rc, _ = run_tool(d, [a], StubOps(d))
    check(rc == 0 and a.is_encrypted and a.filename.endswith(".age") and a.remote_path.endswith(".age"),
          "a row with is_deleted=true and no purged_at is converted too, so a later purge removes the .age")


def test_rows_are_selected_without_looking_at_the_flag():
    from sqlalchemy.dialects import postgresql

    class Cap:
        async def execute(self, stmt):
            self.stmt = stmt
            return SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: []))

    cap = Cap()
    asyncio.run(m.live_artifacts(cap, DEST))
    sql = str(cap.stmt.compile(dialect=postgresql.dialect()))
    where = sql.split("WHERE", 1)[1]
    check("storage_id" in where and "purged_at IS NULL" in where and "is_encrypted" not in where and "is_deleted" not in where,
          "the row query is limited to the Drive destination and unpurged rows; neither is_encrypted nor is_deleted is consulted")


def test_check_one():
    plain = b"the original dump"
    cipher = HEADER + plain[::-1]
    d = Drive()
    art = SimpleNamespace(id=uuid.uuid4(), remote_path=f"{PREFIX}/hedburgaren/J/x.gz.age", size_bytes=len(cipher),
                          checksum_sha256=sha(cipher))
    d.files[art.remote_path] = cipher

    def sess_for(audit_sha):
        class Db:
            async def execute(self, stmt):
                if "audit_log" in str(stmt):
                    entry = SimpleNamespace(meta={"plaintext_sha256": audit_sha}) if audit_sha else None
                    return SimpleNamespace(scalars=lambda: SimpleNamespace(first=lambda: entry))
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

    def go(audit_sha, ops=None):
        lines = []
        with tempfile.TemporaryDirectory() as base:
            rc = asyncio.run(m.check_one(ops=ops or StubOps(d), session_factory=sess_for(audit_sha),
                                         out=lines.append, workbase=base))
        return rc, lines
    try:
        rc, lines = go(sha(plain))
        check(rc == 0 and any("RESULT: encrypted" in l for l in lines), "check-one: age header, no gzip/tar, decrypts, sha equals the recorded plaintext sha")
        check(any("equals the plaintext sha recorded at conversion: True" in l for l in lines), "check-one: shows the decrypted sha against the recorded one")
        rc, lines = go(sha(b"another file"))
        check(rc == 1 and any("recorded at conversion: False" in l for l in lines), "check-one: a decrypted file that differs from the recorded plaintext fails")
        rc, lines = go(sha(plain), StubOps(d, break_decrypt=True))
        check(rc == 1, "check-one: a decryption that does not give the original fails")

        class NoKey(StubOps):
            async def decrypt(self, src, dst):
                raise Exception("no identity")
        rc, lines = go(sha(plain), NoKey(d))
        check(rc == 1 and any("could not decrypt" in l for l in lines), "check-one: without the key it cannot claim decryptability")

        art.checksum_sha256 = "0" * 64
        rc, lines = go(sha(plain))
        check(rc == 1 and any("equals the row's checksum: False" in l for l in lines), "check-one: a file that differs from the row's checksum fails")
        art.checksum_sha256 = sha(cipher)

        d.files[art.remote_path] = gzip.compress(b"plain dump")
        art.checksum_sha256 = sha(d.files[art.remote_path])
        rc, lines = go(None)
        check(rc == 1 and any("NOT PROVEN" in l for l in lines), "check-one: a gzip file is reported as not protected")
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
