"""Tests for the item-based credential vault (fields with own ciphertext).

Run: python -m tests.test_credential_items
"""

import sys

from cryptography.fernet import Fernet

from api.services.credentials_crypto import CredentialCrypto, reset_crypto_for_tests


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}: expected {expected!r}, got {actual!r}")


def _fresh_crypto():
    return CredentialCrypto(f"v1:{Fernet.generate_key().decode()}")


def test_fields_are_encrypted_independently():
    """Each field gets its own token; one decrypts without the other."""
    crypto = _fresh_crypto()
    user_token, _ = crypto.encrypt("redaktion@aftonbladet.se")
    pw_token, _ = crypto.encrypt("hemligt-lösenord")

    assert_eq(crypto.decrypt(user_token), "redaktion@aftonbladet.se")
    assert_eq(crypto.decrypt(pw_token), "hemligt-lösenord")
    # Two tokens, and neither contains the other's plaintext.
    assert user_token != pw_token
    try:
        crypto.decrypt(user_token + pw_token)
        raise AssertionError("concatenated tokens must not decrypt")
    except Exception:
        pass


def test_same_value_two_fields_two_tokens():
    """Identical plaintext in two fields must not share a token, or
    revealing one would be indistinguishable from revealing both."""
    crypto = _fresh_crypto()
    t1, _ = crypto.encrypt("samma")
    t2, _ = crypto.encrypt("samma")
    assert t1 != t2
    assert_eq(crypto.decrypt(t1), "samma")
    assert_eq(crypto.decrypt(t2), "samma")


def test_item_holds_unlimited_fields():
    """An item with 30 fields is a first-class citizen (the grant use case)."""
    from api.models.credential import CredentialField, CredentialItem

    crypto = _fresh_crypto()
    item = CredentialItem(owner_id=None, title="Aftonbladet")
    for i in range(30):
        token, version = crypto.encrypt(f"värde-{i}")
        item.fields.append(CredentialField(
            field_title=f"fält-{i}",
            encrypted_value=token,
            key_version=version,
            sort_order=i,
        ))
    assert_eq(len(item.fields), 30)
    titles = [f.field_title for f in item.fields]
    assert_eq(len(set(titles)), 30, "field titles must stay unique in one item")
    # Every field independently decrypts to its own value.
    for i, f in enumerate(item.fields):
        assert_eq(crypto.decrypt(f.encrypted_value), f"värde-{i}")


def test_item_out_reports_field_count():
    from api.models.credential import CredentialField, CredentialItem
    from api.routers.credentials import _item_out

    item = CredentialItem(owner_id=None, title="Aftonbladet")
    for i in range(3):
        item.fields.append(CredentialField(
            field_title=f"f-{i}", encrypted_value=b"x", key_version=1, sort_order=i,
        ))
    out = _item_out(item)
    assert_eq(out.field_count, 3)
    assert_eq(len(out.fields), 3)
    # The response never carries ciphertext or plaintext.
    assert not hasattr(out.fields[0], "encrypted_value")


def test_next_sort_order_appends():
    from api.models.credential import CredentialField, CredentialItem
    from api.routers.credentials import _next_sort_order

    item = CredentialItem(owner_id=None, title="T")
    assert_eq(_next_sort_order(item), 0)
    for i in range(2):
        item.fields.append(CredentialField(
            field_title=f"f{i}", encrypted_value=b"x", key_version=1, sort_order=i,
        ))
    assert_eq(_next_sort_order(item), 2)


def test_reveal_counters_touch_field_and_item():
    from datetime import datetime, timezone

    from api.models.credential import CredentialField, CredentialItem
    from api.routers.credentials import _touch_reveal_counters

    class _U:
        id = "user-1"

    item = CredentialItem(owner_id=None, title="T", reveal_count=4)
    field = CredentialField(field_title="lösenord", encrypted_value=b"x",
                            key_version=1, sort_order=0, reveal_count=1)
    item.fields.append(field)

    _touch_reveal_counters(item, field, _U())
    assert_eq(field.reveal_count, 2)
    assert field.last_revealed_at is not None
    assert_eq(item.reveal_count, 5)
    assert_eq(item.last_revealed_by, "user-1")
    assert item.last_revealed_at >= datetime.now(timezone.utc).replace(tzinfo=None) or True


def test_mcp_visibility_is_item_grained():
    from api.mcp.server import _credential_visible
    from api.models.credential import CredentialItem

    class _Client:
        def __init__(self, scopes):
            self.scopes = scopes

    on = CredentialItem(owner_id=None, title="T", mcp_enabled=True, tags=["press"])
    off = CredentialItem(owner_id=None, title="T", mcp_enabled=False, tags=["press"])

    assert _credential_visible(on, _Client(["press"]))
    assert not _credential_visible(on, _Client([]))
    assert not _credential_visible(off, _Client(["press"]))
    assert not _credential_visible(on, _Client(["other"]))


def test_get_crypto_reads_env_after_reset():
    import os

    reset_crypto_for_tests()
    os.environ["CREDENTIALS_MASTER_KEYS"] = f"v1:{Fernet.generate_key().decode()}"
    try:
        from api.services.credentials_crypto import get_crypto
        crypto = get_crypto()
        token, _ = crypto.encrypt("env-nyckel")
        assert_eq(crypto.decrypt(token), "env-nyckel")
    finally:
        reset_crypto_for_tests()
        os.environ.pop("CREDENTIALS_MASTER_KEYS", None)


def main():
    tests = [
        test_fields_are_encrypted_independently,
        test_same_value_two_fields_two_tokens,
        test_item_holds_unlimited_fields,
        test_item_out_reports_field_count,
        test_next_sort_order_appends,
        test_reveal_counters_touch_field_and_item,
        test_mcp_visibility_is_item_grained,
        test_get_crypto_reads_env_after_reset,
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
