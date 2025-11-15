from __future__ import annotations

from statistics import mean
from typing import Dict, Iterable, List, Tuple

from freemad.config import Config
from .base import ValidationResult, Validator
from .coverage import CoverageValidator
from .sandbox import SandboxValidator
from .security import SecurityValidator
from .syntax import SyntaxValidator


class ValidationManager:
    def __init__(self, cfg: Config, validators: Iterable[Validator] | None = None):
        if validators is None:
            validators = [
                SyntaxValidator(),
                SandboxValidator(enabled=cfg.validation.enable_sandbox, timeout_ms=cfg.validation.sandbox_timeout_ms),
                SecurityValidator(cfg.security),
                CoverageValidator(),
            ]
        self.validators: List[Validator] = list(validators)

    def validate_many(self, answers: Dict[str, str]) -> Tuple[Dict[str, Dict[str, ValidationResult]], Dict[str, float]]:
        """Validate answers; returns (results per validator, mean confidence per answer)."""
        per_answer: Dict[str, Dict[str, ValidationResult]] = {}
        confidence: Dict[str, float] = {}
        for ans_id, text in answers.items():
            vres: Dict[str, ValidationResult] = {}
            confs: List[float] = []
            for v in self.validators:
                res = v.validate(ans_id, text)
                vres[v.name.value] = res
                confs.append(max(0.0, min(1.0, res.confidence)))
            per_answer[ans_id] = vres
            confidence[ans_id] = mean(confs) if confs else 0.0
        return per_answer, confidence
