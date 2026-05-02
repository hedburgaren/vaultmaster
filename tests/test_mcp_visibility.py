"""Tests for the MCP scope/visibility logic.

Run: python -m tests.test_mcp_visibility
"""

import sys

from api.mcp.server import _credential_visible


class _Cred:
    def __init__(self, mcp_enabled, mcp_scopes=None, tags=None):
        self.mcp_enabled = mcp_enabled
        self.mcp_scopes = mcp_scopes or []
        self.tags = tags or []


class _Client:
    def __init__(self, scopes):
        self.scopes = scopes


def test_disabled_credential_invisible():
    c = _Cred(mcp_enabled=False, tags=["github"])
    assert _credential_visible(c, _Client(["github"])) is False


def test_empty_client_scopes_sees_nothing():
    c = _Cred(mcp_enabled=True, tags=["github"])
    assert _credential_visible(c, _Client([])) is False


def test_client_scope_intersects_credential_tags():
    c = _Cred(mcp_enabled=True, tags=["github", "production"])
    assert _credential_visible(c, _Client(["github"])) is True


def test_client_scope_intersects_mcp_scopes():
    c = _Cred(mcp_enabled=True, mcp_scopes=["deploy"], tags=["production"])
    assert _credential_visible(c, _Client(["deploy"])) is True


def test_client_scope_disjoint_no_access():
    c = _Cred(mcp_enabled=True, mcp_scopes=["deploy"], tags=["production"])
    assert _credential_visible(c, _Client(["staging"])) is False


def test_union_of_mcp_scopes_and_tags():
    c = _Cred(mcp_enabled=True, mcp_scopes=["a"], tags=["b"])
    assert _credential_visible(c, _Client(["a"])) is True
    assert _credential_visible(c, _Client(["b"])) is True
    assert _credential_visible(c, _Client(["c"])) is False


def main():
    tests = [
        test_disabled_credential_invisible,
        test_empty_client_scopes_sees_nothing,
        test_client_scope_intersects_credential_tags,
        test_client_scope_intersects_mcp_scopes,
        test_client_scope_disjoint_no_access,
        test_union_of_mcp_scopes_and_tags,
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
