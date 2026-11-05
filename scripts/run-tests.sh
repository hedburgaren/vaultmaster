#!/usr/bin/env bash
# Runs every test module in tests/ with the given Python (default: python3)
# and prints one line per module plus a total. Exit 1 if any module failed.
set -u
PY="${1:-python3}"
cd "$(dirname "$0")/.."
fail=0
for t in tests/test_*.py; do
  m=$(basename "$t" .py)
  out=$("$PY" -m "tests.$m" 2>&1)
  rc=$?
  echo "$m exit=$rc $(printf '%s\n' "$out" | tail -1)"
  [ "$rc" -eq 0 ] || fail=1
done
exit $fail
