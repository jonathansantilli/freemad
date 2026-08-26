"""Protected characterization suite: golden behavior checks for the public API.

Judge-owned (protected_paths): exits non-zero on any behavioral regression.
Runs against the CURRENT worktree, so it verifies the upgrade preserved
behavior without trusting worker-edited unit tests."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

GOLDEN = [
    ("Hello World", "hello-world"),
    ("  Fast, Reliable & True!  ", "fast-reliable-true"),
    ("multiple   spaces", "multiple-spaces"),
    ("under_scored-title", "under-scored-title"),
    ("", ""),
]


def main() -> int:
    from app import normalize_title

    failures = [
        (given, normalize_title(given), expected)
        for given, expected in GOLDEN
        if normalize_title(given) != expected
    ]
    for given, actual, expected in failures:
        print(f"FAIL: {given!r} -> {actual!r}, expected {expected!r}", file=sys.stderr)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
