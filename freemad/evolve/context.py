from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from freemad.evolve.models import IterationRecord, JudgeVerdict, ScoreVector
from freemad.types import IterationOutcome
from freemad.utils.budget import enforce_size


@dataclass(frozen=True)
class ContextInput:
    goal: str
    iteration: int
    best_iteration: Optional[int]
    best_sha: Optional[str]
    best_score: Optional[ScoreVector]
    baseline_score: Optional[ScoreVector]
    records: Sequence[IterationRecord]
    directives: Sequence[str] = ()


def failure_signature(verdict: JudgeVerdict) -> str:
    """Stable normalized string for loop detection and the graveyard.

    Stage failures (root cause, short-circuit) come first; gate failures next
    as failed predicate names. Digits stripped; lowercase; whitespace collapsed.
    """
    if verdict.failed_stage:
        first_line = ""
        detail = verdict.failure_detail.strip()
        if detail:
            for line in detail.splitlines():
                if line.strip():
                    first_line = line.strip()
                    break
        return _normalize(f"{verdict.failed_stage}: {first_line}")
    if verdict.gate_failures:
        raw = "; ".join(f.component for f in verdict.gate_failures)
        return _normalize(raw)
    return _normalize(verdict.failure_detail or "unknown")


def _normalize(text: str) -> str:
    no_digits = re.sub(r"\d+", "", text)
    collapsed = re.sub(r"\s+", " ", no_digits).strip().lower()
    return collapsed[:200]


def _fmt_score(score: Optional[ScoreVector]) -> str:
    if score is None:
        return "(none)"
    parts = [f"{k}={v:.6g}" for k, v in sorted(score.components.items())]
    return "{" + ", ".join(parts) + "}" if parts else "{}"


def generate_context(data: ContextInput, budget_chars: int) -> str:
    """Deterministic context document. Priority order fixed; only the graveyard
    (last section) may shrink to fit the budget."""
    sections: List[str] = []

    sections.append(f"# GOAL\n{data.goal}")

    best_line = (
        f"iteration {data.best_iteration}, sha {data.best_sha}, score {_fmt_score(data.best_score)}"
        if data.best_iteration is not None
        else "none yet (baseline only)"
    )
    sections.append(
        f"# CURRENT BEST\n{best_line}\nBaseline score: {_fmt_score(data.baseline_score)}"
    )

    trajectory = _trajectory_table(data.records)
    sections.append(f"# SCORE TRAJECTORY\n{trajectory or '(no iterations yet)'}")

    accepted = [
        f"- it{r.iteration}: {r.self_report.splitlines()[0][:160]}"
        for r in data.records
        if r.outcome == IterationOutcome.COMMITTED and r.self_report
    ]
    sections.append(
        "# ACCEPTED APPROACHES\n" + ("\n".join(accepted) if accepted else "(none yet)")
    )

    graveyard = _graveyard(data.records)

    directive_lines = [f"- {d}" for d in data.directives]
    directive_block = "\n".join(directive_lines)
    sections.append(
        f"# ACTIVE DIRECTIVES\n{directive_block if directive_block else '(none)'}"
    )
    sections.append(f"# THE GRAVEYARD (do not repeat these)\n{graveyard}")

    doc = "\n\n".join(sections)
    over = len(doc) - budget_chars
    if over > 0 and graveyard:
        header = "# THE GRAVEYARD (do not repeat these)\n"
        lines = graveyard.splitlines()
        while over > 0 and len(lines) > 1:
            lines = lines[: max(1, len(lines) // 2)]
            sections[-1] = header + "\n".join(lines).rstrip() + "\n... (truncated)"
            doc = "\n\n".join(sections)
            over = len(doc) - budget_chars
        if over > 0:
            sections[-1] = header + "... (truncated)"
            doc = "\n\n".join(sections)
    # The trajectory table grows with the run, so shrinking the graveyard alone does
    # not bound the document on a long one.
    return enforce_size(doc, budget_chars, "evolve_context")[0]


# The table grows with the run; past this it crowds out the sections below it,
# ACTIVE DIRECTIVES included — which is what the supervisor steers with.
TRAJECTORY_MAX_ROWS = 40


def _trajectory_table(records: Sequence[IterationRecord]) -> str:
    if not records:
        return ""
    lines = ["iter | outcome | score | signature"]
    lines.append("--- | --- | --- | ---")
    ordered = sorted(records, key=lambda x: x.iteration)
    if len(ordered) > TRAJECTORY_MAX_ROWS:
        lines.append(
            f"... ({len(ordered) - TRAJECTORY_MAX_ROWS} earlier iterations elided)"
        )
        ordered = ordered[-TRAJECTORY_MAX_ROWS:]
    for r in ordered:
        sig = r.failure_signature or "-"
        score = _fmt_score(r.score) if r.score else "-"
        tag = f" ({r.tag})" if r.tag else ""
        lines.append(f"{r.iteration} | {r.outcome.value}{tag} | {score} | {sig[:60]}")
    return "\n".join(lines)


def _graveyard(records: Sequence[IterationRecord]) -> str:
    groups: Dict[str, Tuple[int, List[str]]] = {}
    for r in records:
        if r.outcome != IterationOutcome.COMMITTED:
            sig = r.failure_signature or "unknown"
            count, examples = groups.get(sig, (0, []))
            example = r.self_report.splitlines()[0][:120] if r.self_report else ""
            new_examples = examples + (
                [example] if example and len(examples) < 2 else []
            )
            groups[sig] = (count + 1, new_examples)
    if not groups:
        return "(empty — nothing has been rejected yet)"
    lines: List[str] = []
    for sig, (count, examples) in sorted(
        groups.items(), key=lambda kv: (-kv[1][0], kv[0])
    ):
        lines.append(f"[x{count}] {sig}")
        for ex in examples:
            lines.append(f"    e.g. {ex}")
    return "\n".join(lines)


__all__ = [
    "ContextInput",
    "failure_signature",
    "generate_context",
]
