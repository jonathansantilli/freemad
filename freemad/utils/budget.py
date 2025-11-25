from __future__ import annotations

import time


class BudgetExceeded(RuntimeError):
    pass


class BudgetGuard:
    def __init__(self, max_total_time_sec: float | None, max_round_time_sec: float | None) -> None:
        self.max_total_time_sec = max_total_time_sec
        self.max_round_time_sec = max_round_time_sec
        self._start = time.perf_counter()

    def check_total(self) -> None:
        if self.max_total_time_sec is None:
            return
        if time.perf_counter() - self._start > self.max_total_time_sec:
            raise BudgetExceeded(f"max_total_time_sec exceeded: {self.max_total_time_sec}")

    def round_start(self) -> float:
        return time.perf_counter()

    def check_round(self, round_started_at: float) -> None:
        if self.max_round_time_sec is None:
            return
        if time.perf_counter() - round_started_at > self.max_round_time_sec:
            raise BudgetExceeded("max_round_time_sec exceeded")


def enforce_size(text: str, max_size: int, label: str) -> tuple[str, bool]:
    s = text or ""
    if len(s) <= max_size:
        return s, False
    marker = f"\n\n[TRUNCATED at {max_size} chars: {label}]"
    return s[:max_size] + marker, True


def approx_tokens(text: str) -> int:
    """Very rough token approximation: 1 token ~= 4 chars."""
    s = text or ""
    return max(0, (len(s) + 3) // 4)


def truncate_to_tokens(text: str, max_tokens: int, label: str) -> tuple[str, bool]:
    if max_tokens is None:
        return text, False
    if approx_tokens(text) <= max_tokens:
        return text, False
    approx_chars = max_tokens * 4
    marker = f"\n\n[TRUNCATED at ~{max_tokens} tokens: {label}]"
    if approx_chars <= 0:
        return marker, True
    return text[:approx_chars] + marker, True


class TokenBudget:
    def __init__(self, max_total_tokens: int | None, enforce: bool = False) -> None:
        self.max_total_tokens = max_total_tokens
        self.enforce = enforce
        self.used = 0

    def add(self, n: int) -> None:
        if n <= 0:
            return
        self.used += n
        if self.enforce and self.max_total_tokens is not None and self.used > self.max_total_tokens:
            raise BudgetExceeded("max_total_tokens exceeded")
