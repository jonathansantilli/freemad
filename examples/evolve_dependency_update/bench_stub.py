"""Protected compatibility benchmark: prints {"components": {"compat_score": N}}.

compat_score is 100 iff vendored_lib reports a 2.x version AND all golden
behaviors still hold; otherwise it reflects partial credit so the comparator
can observe progress. This file is judge-owned (protected_paths)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "vendor"))

GOLDEN = [
    ("Hello World", "hello-world"),
    ("  Fast, Reliable & True!  ", "fast-reliable-true"),
    ("multiple   spaces", "multiple-spaces"),
    ("under_scored-title", "under-scored-title"),
    ("", ""),
]


def main() -> int:
    import vendored_lib
    from app import normalize_title

    major = int(vendored_lib.VERSION.split(".")[0])
    passing = sum(1 for g, e in GOLDEN if normalize_title(g) == e)
    compat = round(100.0 * (passing / len(GOLDEN)) * (1.0 if major >= 2 else 0.5), 2)
    print(json.dumps({"components": {"compat_score": compat}}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
