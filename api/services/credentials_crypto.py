"""Credential vault encryption.

Owns symmetric encryption for the Credential vault — strictly separate
from JWT signing.

Why separate from settings.secret_key:
- JWT key compromise rotates tokens but isn't supposed to expose secrets.
- Credentials key compromise is catastrophic — must be stored differently
  (env or KMS), rotated more carefully, and never logged.

Configuration:
    CREDENTIALS_MASTER_KEYS env var (comma-separated, version-prefixed):
        v1:<base64-Fernet-key>,v2:<base64-Fernet-key>

    The highest version is used for NEW encryptions. ALL versions are
    tried on decrypt. To rotate:
      1. Generate v2: python -c "from cryptography.fernet import Fernet;
         print(Fernet.generate_key().decode())"
      2. Set CREDENTIALS_MASTER_KEYS="v2:<new>,v1:<old>"
      3. Restart API. New encryptions use v2; v1 still readable.
      4. Periodically run rotate_to_latest() to re-encrypt v1 rows as v2.
      5. Once 0 rows reference v1, drop it from env.

The HKDF-derivation step (per-credential subkey) is OPTIONAL and not
applied here — we use MultiFernet directly, which is sufficient for our
threat model (single-tenant, server-side encryption). HKDF would matter
only if we had per-tenant keys.
"""

from __future__ import annotations

import base64
import os
import re
import threading
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken, MultiFernet


_KEY_LINE_RE = re.compile(r"^v(\d+):(.+)$")


class CredentialCryptoError(Exception):
    """Raised when crypto config is missing or malformed."""


class CredentialCrypto:
    """Encrypt/decrypt strings with versioned Fernet keys."""

    def __init__(self, raw_keys: str):
        if not raw_keys or not raw_keys.strip():
            raise CredentialCryptoError(
                "CREDENTIALS_MASTER_KEYS not set. "
                "Format: v1:<base64-Fernet-key>[,v2:<key>...]"
            )

        self._versions: dict[int, Fernet] = {}
        for part in raw_keys.split(","):
            part = part.strip()
            if not part:
                continue
            m = _KEY_LINE_RE.match(part)
            if not m:
                raise CredentialCryptoError(
                    f"Malformed key entry {part[:8]!r}; "
                    "expected 'vN:<base64-Fernet-key>'"
                )
            ver = int(m.group(1))
            key_b64 = m.group(2).strip()
            try:
                # Validate by constructing Fernet — raises if not 32 base64 bytes.
                f = Fernet(key_b64.encode())
            except (ValueError, base64.binascii.Error) as exc:
                raise CredentialCryptoError(
                    f"Key v{ver} is not a valid Fernet key: {exc}"
                )
            if ver in self._versions:
                raise CredentialCryptoError(f"Duplicate key version v{ver}")
            self._versions[ver] = f

        if not self._versions:
            raise CredentialCryptoError("CREDENTIALS_MASTER_KEYS parsed to empty set")

        self._latest_version = max(self._versions.keys())
        # MultiFernet tries keys in order; put latest first so encryption
        # picks it up too (it always uses the first key for encrypt).
        ordered = sorted(self._versions.items(), key=lambda kv: -kv[0])
        self._multi = MultiFernet([f for _, f in ordered])

    @property
    def latest_version(self) -> int:
        return self._latest_version

    def encrypt(self, plaintext: str) -> tuple[bytes, int]:
        """Encrypt plaintext with the latest version key.

        Returns (token_bytes, version). token_bytes is suitable for storing
        in a BYTEA column; version is what to write to key_version.
        """
        if plaintext is None:
            plaintext = ""
        token = self._multi.encrypt(plaintext.encode("utf-8"))
        return token, self._latest_version

    def decrypt(self, token: bytes | str) -> str:
        """Decrypt a token. Raises InvalidToken if all keys fail."""
        if isinstance(token, str):
            token = token.encode("utf-8")
        plaintext = self._multi.decrypt(token)
        return plaintext.decode("utf-8")

    def rotate(self, token: bytes | str) -> tuple[bytes, int]:
        """Re-encrypt a token under the latest key.

        Used by background rotation jobs to migrate v(N-1) → vN data
        after a key rotation. Returns (new_token, latest_version).
        """
        plaintext = self.decrypt(token)
        return self.encrypt(plaintext)


# ── Module-level singleton with lazy init + lock ──
_lock = threading.Lock()
_instance: Optional[CredentialCrypto] = None


def get_crypto() -> CredentialCrypto:
    """Return the process-wide CredentialCrypto, building it lazily.

    Reads CREDENTIALS_MASTER_KEYS from settings or environment. Cached for
    the lifetime of the process; restart to pick up rotation.
    """
    global _instance
    if _instance is not None:
        return _instance
    with _lock:
        if _instance is not None:
            return _instance
        from api.config import get_settings
        raw = (get_settings().credentials_master_keys or "").strip()
        if not raw:
            raw = os.environ.get("CREDENTIALS_MASTER_KEYS", "").strip()
        _instance = CredentialCrypto(raw)
        return _instance


def reset_crypto_for_tests() -> None:
    """Reset the singleton — only for tests."""
    global _instance
    with _lock:
        _instance = None


# ── Helpers for in-place dict encryption (e.g. StorageDestination.config) ──
SECRET_FIELD_NAMES = {
    "password",
    "secret_access_key",
    "secret_key",
    "access_key_secret",
    "oauth_token",
    "refresh_token",
    "client_secret",
    "api_secret",
    "private_key",
    "smtp_password",
    # Notification-channel secrets (Bug #22). webhook_url is included because
    # Slack/Discord webhook URLs embed an unauthenticated bearer-equivalent
    # token in the path — leaking one is functionally identical to leaking
    # bot_token. chat_id is sensitive only as routing metadata, but treating
    # it as a secret keeps the surface clean.
    "bot_token",
    "bridge_token",
    "webhook_url",
    "chat_id",
}

_ENC_PREFIX = "enc:v"


def encrypt_dict_secrets(d: dict | None, extra_keys: set[str] | None = None) -> dict | None:
    """Encrypt sensitive values in a config dict in place.

    Sensitive values become "enc:v<N>:<base64-token>". Already-encrypted
    values are passed through. Non-sensitive fields are untouched.
    """
    if not d:
        return d
    crypto = get_crypto()
    keys = SECRET_FIELD_NAMES | (extra_keys or set())
    for k, v in list(d.items()):
        if k.lower() not in keys:
            continue
        if not isinstance(v, str):
            continue
        if v.startswith(_ENC_PREFIX):
            continue
        token, ver = crypto.encrypt(v)
        d[k] = f"{_ENC_PREFIX}{ver}:{token.decode('ascii')}"
    return d


def decrypt_dict_secrets(d: dict | None) -> dict | None:
    """Decrypt any 'enc:vN:...'-prefixed string values in a dict in place."""
    if not d:
        return d
    crypto = get_crypto()
    for k, v in list(d.items()):
        if not isinstance(v, str) or not v.startswith(_ENC_PREFIX):
            continue
        # Strip "enc:vN:" prefix
        try:
            _, _vN, token = v.split(":", 2)
            d[k] = crypto.decrypt(token.encode("ascii"))
        except Exception:
            # Best-effort: leave malformed value alone rather than blow up
            pass
    return d


def mask_dict_secrets(d: dict | None) -> dict | None:
    """Return a copy of the dict where encrypted values are masked as '****'.

    Used by GET endpoints so secrets never leave the server even in the
    base64-encrypted form.
    """
    if not d:
        return d
    out = dict(d)
    for k, v in out.items():
        if isinstance(v, str) and v.startswith(_ENC_PREFIX):
            out[k] = "********"
        elif k.lower() in SECRET_FIELD_NAMES and isinstance(v, str) and v:
            # Plaintext sensitive value (legacy / not yet migrated) — also mask.
            out[k] = "********"
    return out
