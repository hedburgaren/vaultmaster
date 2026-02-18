import base64
import os

from cryptography.fernet import Fernet

from api.config import get_settings


def _get_fernet() -> Fernet:
    settings = get_settings()
    key = settings.secret_key.encode()
    # Derive a 32-byte key from the secret, padded/truncated
    key_bytes = key.ljust(32, b"\0")[:32]
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt_secret(plaintext: str) -> str:
    """Encrypt a secret string using Fernet (AES-128-CBC)."""
    f = _get_fernet()
    return f.encrypt(plaintext.encode()).decode()


def decrypt_secret(ciphertext: str) -> str:
    """Decrypt a Fernet-encrypted string."""
    f = _get_fernet()
    return f.decrypt(ciphertext.encode()).decode()
