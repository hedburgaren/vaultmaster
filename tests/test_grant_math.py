"""Tests for the granular grant math (what an agent may read).

Run: python -m tests.test_grant_math

The point under test is Chrille's use case: an LLM holds the right to read
2 of 30 keys, read backup status, and write nothing. Visibility is
computed from explicit grant rows, never guessed from names or tags.
"""

import sys
from types import SimpleNamespace

from api.mcp.server import (
    client_api_scopes,
    client_may,
    fields_visible_to,
    granted_field_ids,
    granted_item_ids,
    item_visible_to,
)


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}: expected {expected!r}, got {actual!r}")


def make_item(n_fields=30, mcp_enabled=False, tags=None, mcp_scopes=None, item_id="item-1"):
    fields = [
        SimpleNamespace(id=f"field-{i}", field_title=f"fält-{i}", sort_order=i)
        for i in range(n_fields)
    ]
    return SimpleNamespace(
        id=item_id, mcp_enabled=mcp_enabled, tags=tags or [], mcp_scopes=mcp_scopes or [],
        fields=fields,
    )


def make_client(scopes=None, items=(), fields=(), api=()):
    grants = (
        [SimpleNamespace(resource_type="credential_item", resource_id=i) for i in items]
        + [SimpleNamespace(resource_type="credential_field", resource_id=f) for f in fields]
        + [SimpleNamespace(resource_type="api", resource_id=a) for a in api]
    )
    return SimpleNamespace(scopes=scopes or [], grants=grants)


def test_two_of_thirty_fields():
    """The headline case: exactly two granted fields of thirty are readable."""
    item = make_item(30)
    client = make_client(fields=["field-3", "field-17"])
    visible = fields_visible_to(item, client)
    assert_eq([f.id for f in visible], ["field-3", "field-17"])
    assert_eq(item_visible_to(item, client), True)


def test_no_grants_no_visibility():
    item = make_item(30, mcp_enabled=True, tags=["prod"])
    client = make_client()  # no scopes, no grants
    assert_eq(fields_visible_to(item, client), [])
    assert_eq(item_visible_to(item, client), False)


def test_item_grant_unlocks_every_field():
    item = make_item(30)
    client = make_client(items=["item-1"])
    assert_eq(len(fields_visible_to(item, client)), 30)


def test_grant_beats_mcp_enabled_off():
    """A grant is this client's own opt-in; the coarse flag cannot veto it."""
    item = make_item(5, mcp_enabled=False)
    client = make_client(fields=["field-0"])
    assert_eq([f.id for f in fields_visible_to(item, client)], ["field-0"])


def test_tag_visibility_still_works_alongside():
    item = make_item(5, mcp_enabled=True, tags=["press"])
    client = make_client(scopes=["press"], fields=["field-2"])
    # Coarse layer exposes everything; the field grant adds nothing.
    assert_eq(len(fields_visible_to(item, client)), 5)


def test_other_items_fields_do_not_leak():
    """Grants on one item's fields must not open another item's same-titled fields."""
    item_a = make_item(3, item_id="item-a")
    item_b = make_item(3, item_id="item-b")
    client = make_client(items=["item-a"])
    assert_eq(len(fields_visible_to(item_a, client)), 3)
    assert_eq(fields_visible_to(item_b, client), [])
    assert_eq(item_visible_to(item_b, client), False)


def test_api_scopes_are_explicit():
    client = make_client(api=["backup.read"])
    assert_eq(client_api_scopes(client), {"backup.read"})
    assert_eq(client_may(client, "backup.read"), True)
    assert_eq(client_may(client, "credentials.read"), False)
    assert_eq(client_may(make_client(), "backup.read"), False)
    # Coarse tag scopes must never satisfy an api surface.
    tagged = SimpleNamespace(scopes=["backup.read"], grants=[])
    assert_eq(client_may(tagged, "backup.read"), False)


def test_grant_id_helpers_partition_by_type():
    client = make_client(items=["i1"], fields=["f1", "f2"], api=["backup.read"])
    assert_eq(granted_item_ids(client), {"i1"})
    assert_eq(granted_field_ids(client), {"f1", "f2"})
    assert_eq(client_api_scopes(client), {"backup.read"})


def test_visibility_respects_sort_order():
    item = make_item(6)
    client = make_client(fields=["field-4", "field-1"])
    assert_eq([f.id for f in fields_visible_to(item, client)], ["field-1", "field-4"])


def main():
    tests = [
        test_two_of_thirty_fields,
        test_no_grants_no_visibility,
        test_item_grant_unlocks_every_field,
        test_grant_beats_mcp_enabled_off,
        test_tag_visibility_still_works_alongside,
        test_other_items_fields_do_not_leak,
        test_api_scopes_are_explicit,
        test_grant_id_helpers_partition_by_type,
        test_visibility_respects_sort_order,
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
