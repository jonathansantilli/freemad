"""Toy module for the evolve runtime proving ground.

`slow_sum` is deliberately inefficient: an O(n) accumulation loop. An optimization
candidate should replace it with the closed-form arithmetic series without changing
behavior, which is worth roughly 4000x.

The slowness is CPU-bound on purpose. An earlier version slept for a microsecond per
iteration, which made the benchmark measure the host's timer granularity instead of the
code: the unmodified seed scored anywhere from 8 to 5022 ops/sec, straddling its own
target, so whether a run ended instantly or optimized for ten iterations was a coin
flip. A judge has to be quiet enough that the comparator's epsilon means something.
"""

from __future__ import annotations


def slow_sum(n: int) -> int:
    if n < 0:
        raise ValueError("n must be non-negative")
    total = 0
    for i in range(n + 1):
        total += i
    return total
