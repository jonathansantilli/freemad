from __future__ import annotations

import re
from typing import Iterable, List


class Redactor:
    def __init__(self, patterns: Iterable[str]):
        self._regexes: List[re.Pattern] = []
        for p in patterns:
            try:
                self._regexes.append(re.compile(p))
            except re.error:
                continue

    def redact(self, text: str) -> str:
        s = text
        for rx in self._regexes:
            s = rx.sub("[REDACTED]", s)
        return s

