from __future__ import annotations

import concurrent.futures
from typing import Dict

from .base import ValidationResult
from freemad import ValidatorName
from freemad import canonicalize_solution


SAFE_BUILTINS: Dict[str, object] = {
    "print": print,
    "len": len,
    "range": range,
    "min": min,
    "max": max,
    "sum": sum,
    "enumerate": enumerate,
    "list": list,
    "dict": dict,
    "set": set,
    "tuple": tuple,
    "int": int,
    "float": float,
    "str": str,
    "bool": bool,
    "abs": abs,
    "zip": zip,
    "map": map,
    "filter": filter,
    "any": any,
    "all": all,
    "sorted": sorted,
}
UNSAFE_TOKENS = ("import", "__")


class SandboxValidator:
    def __init__(self, enabled: bool = False, timeout_ms: int = 500) -> None:
        self.enabled = enabled
        self.timeout_ms = timeout_ms

    name = ValidatorName.SANDBOX

    def _run_code(self, code: str) -> ValidationResult:
        # Restricted exec environment (no __import__, limited builtins)
        glb = {"__builtins__": SAFE_BUILTINS}
        loc: Dict[str, object] = {}
        try:
            exec(code, glb, loc)
            return ValidationResult(passed=True, confidence=0.8)
        except Exception as e:  # pragma: no cover - error path unit-tested
            return ValidationResult(passed=False, confidence=0.4, errors=[f"runtime: {e.__class__.__name__}: {e}"])

    def validate(self, answer_id: str, text: str) -> ValidationResult:
        if not self.enabled:
            # Present but neutral if disabled
            return ValidationResult(passed=True, confidence=0.5)
        code = canonicalize_solution(text)
        if not code:
            return ValidationResult(passed=False, confidence=0.3, errors=["empty solution"])
        if any(tok in code for tok in UNSAFE_TOKENS):
            return ValidationResult(passed=False, confidence=0.2, errors=["unsafe code patterns detected"])
        # Run with a hard timeout via thread executor
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            fut = ex.submit(self._run_code, code)
            try:
                return fut.result(timeout=max(0.001, self.timeout_ms / 1000.0))
            except concurrent.futures.TimeoutError:
                return ValidationResult(passed=False, confidence=0.2, errors=["sandbox timeout"])
