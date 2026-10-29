"""Tests for the dirsize parser backing the tree picker's size column.

Run: python -m tests.test_dirsize
"""

import sys

from api.routers.servers import _parse_du_output


def assert_eq(actual, expected, msg=""):
    if actual != expected:
        raise AssertionError(f"{msg}: expected {expected!r}, got {actual!r}")


def test_plain_output():
    assert_eq(_parse_du_output("42139521\t/srv/agents\n", "/srv/agents"), 42139521)


def test_path_with_spaces():
    assert_eq(_parse_du_output("123\t/mnt/My Folder/data\n", "/mnt/My Folder/data"), 123)


def test_empty_output_raises():
    try:
        _parse_du_output("", "/x")
        raise AssertionError("must raise on empty output")
    except ValueError as e:
        assert "no output" in str(e), str(e)


def test_nonnumeric_raises():
    try:
        _parse_du_output("not-a-number\t/x\n", "/x")
        raise AssertionError("must raise on non-numeric first field")
    except ValueError as e:
        assert "not parseable" in str(e), str(e)


def test_only_first_line_counts():
    # du -sb prints one line, but a trailing warning line must not break it.
    assert_eq(_parse_du_output("99\t/x\ndu: cannot access something\n", "/x"), 99)


def main():
    tests = [
        test_plain_output,
        test_path_with_spaces,
        test_empty_output_raises,
        test_nonnumeric_raises,
        test_only_first_line_counts,
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
