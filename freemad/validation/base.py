from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Protocol
from freemad import ValidatorName


@dataclass(frozen=True)
class ValidationResult:
    passed: bool
    confidence: float  # [0..1]
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    metrics: Dict[str, float] = field(default_factory=dict)


class Validator(Protocol):
    name: ValidatorName

    def validate(self, answer_id: str, text: str) -> ValidationResult:
        ...
