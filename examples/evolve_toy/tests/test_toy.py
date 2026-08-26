from __future__ import annotations

import pytest

from toy import slow_sum


@pytest.mark.parametrize("n,expected", [(0, 0), (1, 1), (5, 15), (10, 55), (100, 5050)])
def test_slow_sum_known_values(n: int, expected: int) -> None:
    assert slow_sum(n) == expected


def test_slow_sum_rejects_negative() -> None:
    with pytest.raises(ValueError):
        slow_sum(-1)
