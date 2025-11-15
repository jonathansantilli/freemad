from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional
from freemad.types import Decision, GenMarker, CritMarker


_HEADER_RE_FMT = r"^\s*(%s)\s*:\s*(.*)$"

def _parse_sections(raw: str, markers: List[str]) -> Dict[str, str]:
    """Parse case-insensitive section headers and capture content until next header.

    Supports content on the same line as the header and on subsequent lines.
    Returns mapping of UPPERCASE marker -> stripped content.
    """
    pattern = re.compile(_HEADER_RE_FMT % ("|".join(markers)), re.IGNORECASE | re.MULTILINE)
    results: Dict[str, str] = {}
    matches = list(pattern.finditer(raw or ""))
    for i, m in enumerate(matches):
        name = m.group(1).upper()
        inline = m.group(2) or ""
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(raw)
        tail = (raw[start:end] or "")
        body = (inline + ("\n" if inline and tail else "") + tail).strip()
        results[name] = body
    return results


@dataclass(frozen=True)
class ParseResultGen:
    solution: str
    reasoning: str
    needs_retry: bool
    errors: List[str]


@dataclass(frozen=True)
class ParseResultCrit:
    decision: Decision  # KEEP|REVISE
    solution: Optional[str]
    reasoning: str
    needs_retry: bool
    errors: List[str]


def parse_generation(raw: str) -> ParseResultGen:
    errors: List[str] = []
    if not raw or not raw.strip():
        return ParseResultGen(solution="", reasoning="", needs_retry=True, errors=["empty output"])
    sections = _parse_sections(raw, [GenMarker.SOLUTION.value, GenMarker.REASONING.value])
    if GenMarker.SOLUTION.value not in sections:
        errors.append("missing SOLUTION marker")
    if GenMarker.REASONING.value not in sections:
        errors.append("missing REASONING marker")
    solution = sections.get(GenMarker.SOLUTION.value, "")
    reasoning = sections.get(GenMarker.REASONING.value, "")
    return ParseResultGen(solution=solution, reasoning=reasoning, needs_retry=bool(errors), errors=errors)


def parse_critique(raw: str) -> ParseResultCrit:
    errors: List[str] = []
    if not raw or not raw.strip():
        return ParseResultCrit(decision=Decision.KEEP, solution=None, reasoning="", needs_retry=True, errors=["empty output"])
    sections = _parse_sections(raw, [CritMarker.DECISION.value, CritMarker.REVISED_SOLUTION.value, CritMarker.REASONING.value])
    if CritMarker.DECISION.value not in sections or not sections.get(CritMarker.DECISION.value, "").strip():
        errors.append("missing or invalid DECISION marker")
        return ParseResultCrit(decision=Decision.KEEP, solution=None, reasoning="", needs_retry=True, errors=errors)

    decision_line = sections[CritMarker.DECISION.value].splitlines()[0].strip().upper()
    if decision_line not in (Decision.KEEP.value, Decision.REVISE.value):
        errors.append("missing or invalid DECISION marker")
        return ParseResultCrit(decision=Decision.KEEP, solution=None, reasoning="", needs_retry=True, errors=errors)

    reasoning = sections.get(CritMarker.REASONING.value, "").strip()

    if decision_line == Decision.KEEP.value:
        return ParseResultCrit(decision=Decision.KEEP, solution=None, reasoning=reasoning, needs_retry=False, errors=[])

    if CritMarker.REVISED_SOLUTION.value not in sections or not sections[CritMarker.REVISED_SOLUTION.value].strip():
        errors.append("REVISED_SOLUTION required when DECISION=REVISE")
        return ParseResultCrit(decision=Decision.REVISE, solution=None, reasoning=reasoning, needs_retry=True, errors=errors)

    return ParseResultCrit(decision=Decision.REVISE, solution=sections[CritMarker.REVISED_SOLUTION.value].strip(), reasoning=reasoning, needs_retry=False, errors=[])
