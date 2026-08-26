"""Benchmark for the evolve toy: prints {"components": {"ops_per_sec": N}}.

Protected judge file: candidates may not alter this script; the runtime
restores it from the seed before every judging phase.
"""

from __future__ import annotations

import json
import time

from toy import slow_sum


# Large enough that the O(n) loop dominates interpreter overhead, so the score
# reflects the algorithm rather than the noise floor.
N = 20_000


def ops_per_sec() -> float:
    calls = 0
    start = time.perf_counter()
    deadline = start + 0.5
    while time.perf_counter() < deadline:
        slow_sum(N)
        calls += 1
    elapsed = time.perf_counter() - start
    if elapsed <= 0:
        return 0.0
    return calls / elapsed


if __name__ == "__main__":
    print(json.dumps({"components": {"ops_per_sec": round(ops_per_sec(), 2)}}))
