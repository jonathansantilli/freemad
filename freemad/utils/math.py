from __future__ import annotations

from typing import List


def fibonacci(n: int) -> int:
    """
    Compute the nth Fibonacci number (0-indexed).
    Raises ValueError for negative n.
    """
    if n < 0:
        raise ValueError("n must be non-negative")
    if n == 0:
        return 0
    if n == 1:
        return 1
    a, b = 0, 1
    for _ in range(2, n + 1):
        a, b = b, a + b
    return b
