"""Tests for the CredentialCrypto service.

Run: python -m tests.test_credentials_crypto
"""

import sys

from cryptography.fernet import Fernet, InvalidToken

from api.services.credentials_crypto import (
    CredentialCrypto,
    CredentialCryptoError,
)


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}: expected {expected!r}, got {actual!r}")


def test_roundtrip_v1_only():
    k1 = Fernet.generate_key().decode()
    cc = CredentialCrypto(f"v1:{k1}")
    token, ver = cc.encrypt("hello")
    assert_eq(ver, 1)
    assert_eq(cc.decrypt(token), "hello")


def test_unicode_payload():
    k1 = Fernet.generate_key().decode()
    cc = CredentialCrypto(f"v1:{k1}")
    payload = "ÅÄÖ — råttbajs! 🔐 emoji"
    token, _ = cc.encrypt(payload)
    assert_eq(cc.decrypt(token), payload)


def test_rotation_v2_can_read_v1_data():
    k1 = Fernet.generate_key().decode()
    k2 = Fernet.generate_key().decode()

    cc_v1 = CredentialCrypto(f"v1:{k1}")
    token_old, ver_old = cc_v1.encrypt("legacy secret")
    assert_eq(ver_old, 1)

    cc_v2 = CredentialCrypto(f"v2:{k2},v1:{k1}")
    # Old token still decrypts
    assert_eq(cc_v2.decrypt(token_old), "legacy secret")
    # New encryptions use v2
    token_new, ver_new = cc_v2.encrypt("new secret")
    assert_eq(ver_new, 2)
    assert_eq(cc_v2.decrypt(token_new), "new secret")


def test_rotate_re_encrypts_with_latest_key():
    k1 = Fernet.generate_key().decode()
    k2 = Fernet.generate_key().decode()

    cc_v1 = CredentialCrypto(f"v1:{k1}")
    old_token, _ = cc_v1.encrypt("rotate me")

    cc = CredentialCrypto(f"v2:{k2},v1:{k1}")
    new_token, ver = cc.rotate(old_token)
    assert_eq(ver, 2)
    assert_eq(cc.decrypt(new_token), "rotate me")
    # New token is different from old (re-encrypted with new key)
    if new_token == old_token:
        raise AssertionError("rotate produced identical token — key rotation did nothing")


def test_v1_key_dropped_after_rotation_breaks_old_data():
    k1 = Fernet.generate_key().decode()
    k2 = Fernet.generate_key().decode()

    cc_v1 = CredentialCrypto(f"v1:{k1}")
    old_token, _ = cc_v1.encrypt("legacy secret")

    cc_v2_only = CredentialCrypto(f"v2:{k2}")
    try:
        cc_v2_only.decrypt(old_token)
    except InvalidToken:
        return
    raise AssertionError("decrypt with mismatched key should have raised InvalidToken")


def test_malformed_config_rejected():
    bad_inputs = [
        "",
        "no-version-prefix",
        "v1:not-a-real-fernet-key",
        "v1:" + Fernet.generate_key().decode() + ",v1:" + Fernet.generate_key().decode(),  # dup version
    ]
    for raw in bad_inputs:
        try:
            CredentialCrypto(raw)
        except CredentialCryptoError:
            continue
        raise AssertionError(f"accepted malformed config: {raw[:30]!r}")


def test_empty_plaintext_roundtrip():
    k1 = Fernet.generate_key().decode()
    cc = CredentialCrypto(f"v1:{k1}")
    token, _ = cc.encrypt("")
    assert_eq(cc.decrypt(token), "")


def test_token_is_bytes_for_db():
    k1 = Fernet.generate_key().decode()
    cc = CredentialCrypto(f"v1:{k1}")
    token, _ = cc.encrypt("for-bytea-column")
    if not isinstance(token, bytes):
        raise AssertionError(f"encrypt returned {type(token)}, expected bytes")


def main():
    tests = [
        test_roundtrip_v1_only,
        test_unicode_payload,
        test_rotation_v2_can_read_v1_data,
        test_rotate_re_encrypts_with_latest_key,
        test_v1_key_dropped_after_rotation_breaks_old_data,
        test_malformed_config_rejected,
        test_empty_plaintext_roundtrip,
        test_token_is_bytes_for_db,
    ]
    failures = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {t.__name__}: {type(e).__name__}: {e}")
    if failures:
        sys.exit(1)
    print(f"\n{len(tests)} passed.")


if __name__ == "__main__":
    main()
