from __future__ import annotations

from .base import ValidationResult
from freemad import ValidatorName


class CoverageValidator:
    name = ValidatorName.COVERAGE

    def validate(self, answer_id: str, text: str) -> ValidationResult:
        # Placeholder; in CI we could run tests against solution.
        return ValidationResult(passed=True, confidence=0.5)
