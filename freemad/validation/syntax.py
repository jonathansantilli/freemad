from __future__ import annotations

from .base import ValidationResult
from freemad import ValidatorName


class SyntaxValidator:
    name = ValidatorName.SYNTAX

    def validate(self, answer_id: str, text: str) -> ValidationResult:
        # Hard-fail on empty or whitespace-only content
        if not (text or "").strip():
            return ValidationResult(passed=False, confidence=0.0, errors=["empty solution"], metrics={"length": 0.0})
        # Minimal heuristic: flag if an explicit marker suggests syntax issues
        if "SYNTAX_ERROR" in text:
            return ValidationResult(passed=False, confidence=0.2, errors=["syntax marker present"])
        # Otherwise neutral-positive
        return ValidationResult(passed=True, confidence=0.7, metrics={"length": float(len(text))})
