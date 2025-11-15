from __future__ import annotations

import hashlib
import re
from typing import List


_FENCE_RE = re.compile(r"```[a-zA-Z0-9_\-]*\n(.*?)\n```", re.DOTALL)


def _normalize_eol(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def canonicalize_solution(solution: str) -> str:
    if solution is None:
        return ""
    s = _normalize_eol(solution).strip()
    # If fenced code blocks exist, extract their bodies
    blocks: List[str] = [m.group(1) for m in _FENCE_RE.finditer(s)]
    if blocks:
        s = "\n\n".join(b.strip() for b in blocks).strip()
    return s


def compute_answer_id(solution: str) -> str:
    canon = canonicalize_solution(solution)
    h = hashlib.sha256(canon.encode("utf-8")).hexdigest()
    return h[:16]

