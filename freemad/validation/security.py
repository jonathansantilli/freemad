from __future__ import annotations

import re
from typing import List

from freemad import SecurityConfig
from freemad import ValidatorName
from .base import ValidationResult


class SecurityValidator:
    name = ValidatorName.SECURITY

    def __init__(self, sec: SecurityConfig):
        self._patterns: List[re.Pattern] = []
        for p in sec.redact_patterns:
            try:
                self._patterns.append(re.compile(p))
            except re.error:
                # ignore invalid patterns; config validator should catch
                pass

    def validate(self, answer_id: str, text: str) -> ValidationResult:
        hits = []
        for rp in self._patterns:
            if rp.search(text or ""):
                hits.append(rp.pattern)
        if hits:
            return ValidationResult(passed=False, confidence=0.3, warnings=[f"secret-like content matched: {len(hits)} pattern(s)"])
        return ValidationResult(passed=True, confidence=0.8)
