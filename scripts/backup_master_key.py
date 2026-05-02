#!/usr/bin/env python3
"""GPG-encrypt the VaultMaster CREDENTIALS_MASTER_KEYS for off-host backup.

Run with a passphrase you keep separately (NOT in any backup that goes
on the same disk). The output is a base64-armored .gpg.asc file that's
safe to email, copy to a USB stick, or print on paper as a QR code.

Usage:
    python -m scripts.backup_master_key \
        --output /srv/archive/master-key-2026-05-02.asc \
        --passphrase-env BACKUP_PASSPHRASE

Or interactively:
    BACKUP_PASSPHRASE='my-strong-recovery-passphrase' \
        python -m scripts.backup_master_key --output -

Recovery (when host is gone):
    gpg -d master-key-2026-05-02.asc > restored-keys.txt
    # Restored line goes into new VaultMaster .env as
    # CREDENTIALS_MASTER_KEYS=v1:...

Recommended placement of the encrypted file (REDUNDANCY > CONVENIENCE):
    1. Bank safe-deposit box (printed QR + USB stick)
    2. A trusted person's password manager (1Password / Bitwarden)
    3. A second physical location (home safe, parent's house)

NEVER place an UNencrypted master key off-host. NEVER place the
encrypted file together with the recovery passphrase.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def read_master_keys(env_file: str) -> str:
    if not os.path.isfile(env_file):
        raise SystemExit(f"env file not found: {env_file}")
    line_re = re.compile(r"^CREDENTIALS_MASTER_KEYS=(.+)$")
    with open(env_file, encoding="utf-8") as f:
        for raw in f:
            m = line_re.match(raw.strip())
            if m:
                return m.group(1)
    raise SystemExit(f"CREDENTIALS_MASTER_KEYS not in {env_file}")


def gpg_encrypt(plaintext: str, passphrase: str) -> bytes:
    cmd = [
        "gpg",
        "--batch", "--yes",
        "--armor",
        "--pinentry-mode", "loopback",
        "--passphrase-fd", "0",
        "--symmetric",
        "--cipher-algo", "AES256",
    ]
    payload = passphrase + "\n" + plaintext
    proc = subprocess.run(cmd, input=payload, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"gpg failed (exit {proc.returncode}): {proc.stderr.strip()}")
    return proc.stdout.encode("utf-8")


def main() -> int:
    p = argparse.ArgumentParser(description="GPG-encrypt CREDENTIALS_MASTER_KEYS for off-host backup")
    p.add_argument("--env-file", default="/srv/containers/vm.example.com/.env")
    p.add_argument("--output", required=True, help="Path to write the .asc file (or '-' for stdout)")
    p.add_argument("--passphrase-env", default="BACKUP_PASSPHRASE", help="Env var holding the passphrase")
    args = p.parse_args()

    passphrase = os.environ.get(args.passphrase_env, "")
    if not passphrase:
        raise SystemExit(f"set ${args.passphrase_env} (>= 16 chars recommended)")
    if len(passphrase) < 16:
        print("warning: passphrase is shorter than 16 chars", file=sys.stderr)

    keys = read_master_keys(args.env_file)
    payload = (
        f"# VaultMaster CREDENTIALS_MASTER_KEYS\n"
        f"# Generated: {datetime.now(timezone.utc).isoformat()}\n"
        f"# Source: {args.env_file}\n"
        f"# Recovery: paste the line below into the new host's .env\n"
        f"# WITHOUT the leading hashes; restart api/worker/beat afterward.\n"
        f"CREDENTIALS_MASTER_KEYS={keys}\n"
    )

    encrypted = gpg_encrypt(payload, passphrase)

    if args.output == "-":
        sys.stdout.buffer.write(encrypted)
    else:
        out = Path(args.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(encrypted)
        os.chmod(args.output, 0o600)
        print(f"[ok] wrote {len(encrypted)} bytes to {args.output} (mode 0600)")
        print(f"[next] copy this file to:")
        print(f"       1. Bank safe-deposit box (print + USB)")
        print(f"       2. Trusted person's password manager")
        print(f"       3. Second physical location")
        print(f"[next] verify recoverability:")
        print(f"       echo $YOUR_PASSPHRASE | gpg --batch --yes --pinentry-mode loopback "
              f"--passphrase-fd 0 -d {args.output}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
