from __future__ import annotations

import hashlib
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from freemad.evolve.models import EvolveEvent, ScoreVector
from freemad.evolve.store import EvolveStore
from freemad.types import EvolveEventKind, EvolveRunStatus, EvolveStopReason


def render_report(store: EvolveStore, run_id: str) -> str:
    """Deterministic trajectory report rendered purely from persisted events.

    `evolve.md` section 3: "purely from `evolve_events`; deleting derived output and
    re-rendering must be byte-identical." Reading the `evolve_runs` row would make the
    report depend on derived state — the run summary is itself a projection of these
    events, so it is reconstructed here rather than trusted. Wall-clock timestamps are
    excluded for the same reason.
    """
    events: Sequence[EvolveEvent] = store.list_events(run_id)
    if not events:
        raise ValueError(f"unknown evolve run id: {run_id}")

    created = _first_payload(events, EvolveEventKind.RUN_CREATED)
    stopped = _last_payload(events, EvolveEventKind.RUN_STOPPED)
    escalated = _last_payload(events, EvolveEventKind.HUMAN_ESCALATED)
    baseline = _first_payload(events, EvolveEventKind.BASELINE_JUDGED)
    committed = [e for e in events if e.kind == EvolveEventKind.CANDIDATE_COMMITTED]

    status = _status(stopped, escalated)
    stop_reason = str(stopped.get("reason")) if stopped else "(none)"
    error = stopped.get("error") if stopped else None

    lines: List[str] = []
    lines.append(f"# evolve report {run_id}")
    lines.append("")
    lines.append(f"goal: {created.get('goal', '(unknown)')}")
    lines.append(f"seed_ref: {created.get('seed_sha', '(unknown)')}")
    lines.append(f"manifest_hash: {created.get('manifest_hash', '(unknown)')}")
    lines.append(f"status: {status}")
    lines.append(f"stop_reason: {stop_reason}")
    if error:
        lines.append(f"error: {error}")
    lines.append("")

    baseline_score = (baseline.get("verdict") or {}).get("score") if baseline else None
    if committed:
        last = committed[-1].payload
        best_line = (
            f"it{committed[-1].iteration} sha {last.get('sha')} "
            f"score {_fmt_dict(last.get('score'))}"
        )
    elif baseline_score and stop_reason == EvolveStopReason.TARGET_REACHED.value:
        best_line = f"baseline score {_fmt_dict(baseline_score)} (target met at seed)"
    else:
        best_line = "(none)"
    lines.append(f"best: {best_line}")
    lines.append("")

    lines.append("# baseline")
    if baseline:
        verdict = baseline.get("verdict") or {}
        lines.append(
            f"- gate_passed={verdict.get('gate_passed')} score={_fmt_dict(verdict.get('score'))}"
        )
    lines.append("")

    lines.append("# trajectory")
    for event in committed:
        payload = event.payload
        lines.append(
            f"- it{event.iteration} COMMITTED {payload.get('tag')} "
            f"{payload.get('sha')} score {_fmt_dict(payload.get('score'))}"
        )
    counts: Dict[str, int] = {}
    for event in events:
        if event.kind != EvolveEventKind.CANDIDATE_REJECTED:
            continue
        outcome = str(event.payload.get("outcome", "unknown"))
        sig = str(event.payload.get("failure_signature", "unknown"))
        key = f"{outcome}:{sig}"
        counts[key] = counts.get(key, 0) + 1
    for key in sorted(counts):
        lines.append(f"- x{counts[key]} {key}")
    lines.append("")

    interventions: List[Tuple[int, str]] = []
    escalations: List[Tuple[int, str]] = []
    directions_given = 0
    for event in events:
        if event.kind == EvolveEventKind.SUPERVISOR_TRIGGERED:
            interventions.append((event.iteration, str(event.payload.get("cause", ""))))
        elif event.kind == EvolveEventKind.SUPERVISOR_DIRECTIONS:
            directions_given += len(event.payload.get("directions") or [])
        elif event.kind == EvolveEventKind.HUMAN_ESCALATED:
            escalations.append((event.iteration, str(event.payload.get("cause", ""))))
        elif event.kind == EvolveEventKind.HUMAN_INPUT_RECEIVED:
            escalations.append((event.iteration, "answered"))
    lines.append("# interventions")
    if interventions:
        for iteration, cause in interventions:
            lines.append(f"- it{iteration} supervisor ({cause})")
        lines.append(f"- directions issued: {directions_given}")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("# human escalations")
    if escalations:
        for iteration, what in escalations:
            lines.append(f"- it{iteration} {what}")
    else:
        lines.append("- none")

    lines.append("")
    lines.append("# cost")
    lines.append(
        "- not reported: no adapter reports cost, so wall clock is the effective budget"
    )

    digest = _content_digest(lines)
    lines.append("")
    lines.append(f"report_sha256: {digest}")
    return "\n".join(lines) + "\n"


def _first_payload(
    events: Sequence[EvolveEvent], kind: EvolveEventKind
) -> Dict[str, Any]:
    for event in events:
        if event.kind == kind:
            return dict(event.payload)
    return {}


def _last_payload(
    events: Sequence[EvolveEvent], kind: EvolveEventKind
) -> Dict[str, Any]:
    for event in reversed(events):
        if event.kind == kind:
            return dict(event.payload)
    return {}


def _status(stopped: Mapping[str, Any], escalated: Mapping[str, Any]) -> str:
    """Reconstructed rather than read from the runs row."""
    if stopped:
        recorded = stopped.get("status")
        if recorded:
            return str(recorded)
        reason = str(stopped.get("reason", ""))
        if reason == EvolveStopReason.FATAL_ERROR.value:
            return EvolveRunStatus.FAILED.value
        if reason == EvolveStopReason.TARGET_REACHED.value:
            return EvolveRunStatus.COMPLETED.value
        return EvolveRunStatus.STOPPED.value
    if escalated:
        return EvolveRunStatus.WAITING_FOR_HUMAN.value
    return EvolveRunStatus.RUNNING.value


def _fmt(score: Optional[ScoreVector]) -> str:
    if score is None:
        return "{}"
    return (
        "{"
        + ", ".join(f"{k}={v:.6g}" for k, v in sorted(score.components.items()))
        + "}"
    )


def _fmt_dict(raw: Optional[Mapping[str, float]]) -> str:
    if not raw:
        return "{}"
    items = sorted((str(k), float(v)) for k, v in dict(raw).items())
    return "{" + ", ".join(f"{k}={v:.6g}" for k, v in items) + "}"


def _content_digest(lines: Sequence[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()
