from __future__ import annotations

from typing import Tuple


from freemad.evolve.context import ContextInput, failure_signature, generate_context
from freemad.evolve.models import (
    GateFailure,
    IterationRecord,
    JudgeVerdict,
    ScoreVector,
)
from freemad.types import IterationOutcome, VariationKind


def verdict(
    gate_passed: bool = False,
    failed_stage: str | None = None,
    detail: str = "",
    failures: Tuple[GateFailure, ...] = (),
) -> JudgeVerdict:
    return JudgeVerdict(
        stage_results=(),
        score=ScoreVector(),
        gate_passed=gate_passed,
        gate_failures=failures,
        failed_stage=failed_stage,
        failure_detail=detail,
    )


class TestFailureSignature:
    def test_gate_failure_uses_component_names(self) -> None:
        f = GateFailure(component="ops_per_sec", op=">=", value=10, actual=None)
        sig = failure_signature(verdict(failures=(f,)))
        assert "ops_per_sec" in sig

    def test_multiple_gate_failures_joined(self) -> None:
        fs = (
            GateFailure(component="ops", op=">", value=1, actual=0),
            GateFailure(component="mem", op="<", value=5, actual=9),
        )
        sig = failure_signature(verdict(failures=fs))
        assert "ops" in sig and "mem" in sig and ";" in sig

    def test_stage_failure_uses_stage_and_stderr_line(self) -> None:
        v = verdict(
            failed_stage="tests", detail="header junk\nAssertionError: bad math\nmore\n"
        )
        sig = failure_signature(v)
        assert sig.startswith("tests:")
        assert "header junk" in sig
        assert "assertionerror" not in sig  # only the first non-empty line
        assert "more" not in sig

    def test_digits_are_stripped(self) -> None:
        a = verdict(failed_stage="s", detail="line one 12345")
        b = verdict(failed_stage="s", detail="line one 999")
        assert failure_signature(a) == failure_signature(b)

    def test_case_and_whitespace_normalized(self) -> None:
        a = verdict(failed_stage="S", detail="Some   Error")
        b = verdict(failed_stage="s", detail="some error")
        assert failure_signature(a) == failure_signature(b)

    def test_empty_falls_back_to_unknown(self) -> None:
        assert "unknown" in failure_signature(verdict())

    def test_truncated_to_stable_length(self) -> None:
        long_a = verdict(failed_stage="s", detail="x" * 500 + "123")
        long_b = verdict(failed_stage="s", detail="x" * 900)
        assert failure_signature(long_a) == failure_signature(long_b)


def _record(
    iteration: int,
    outcome: IterationOutcome,
    signature: str | None = None,
    report: str = "",
    tag: str | None = None,
) -> IterationRecord:
    return IterationRecord(
        iteration=iteration,
        kind=VariationKind.SINGLE_AGENT,
        outcome=outcome,
        score=(
            ScoreVector(components={"ops": float(iteration)})
            if outcome == IterationOutcome.COMMITTED
            else None
        ),
        sha=("sha" + str(iteration)) if outcome == IterationOutcome.COMMITTED else None,
        tag=tag,
        failure_signature=signature,
        self_report=report,
    )


class TestGenerateContext:
    def _input(self, **overrides) -> ContextInput:
        base = dict(
            goal="make it fast",
            iteration=3,
            best_iteration=1,
            best_sha="abc",
            best_score=ScoreVector(components={"ops": 120.0}),
            baseline_score=ScoreVector(components={"ops": 100.0}),
            records=(
                _record(1, IterationOutcome.COMMITTED, report="closed-form sum"),
                _record(
                    2,
                    IterationOutcome.REJECTED_GATE,
                    signature="gate: ops",
                    report="broke tests",
                ),
            ),
        )
        base.update(overrides)
        return ContextInput(**base)

    def test_contains_goal_and_best(self) -> None:
        doc = generate_context(self._input(), budget_chars=8000)
        assert "# GOAL" in doc and "make it fast" in doc
        assert "CURRENT BEST" in doc and "abc" in doc
        assert "Baseline score" in doc

    def test_deterministic_byte_identical(self) -> None:
        a = generate_context(self._input(), budget_chars=4000)
        b = generate_context(self._input(), budget_chars=4000)
        assert a == b

    def test_trajectory_lists_all_records(self) -> None:
        doc = generate_context(self._input(), budget_chars=8000)
        assert "SCORE TRAJECTORY" in doc
        assert "committed" in doc and "rejected_gate" in doc

    def test_graveyard_groups_by_signature_with_counts(self) -> None:
        data = self._input(
            records=(
                _record(
                    1, IterationOutcome.REJECTED_GATE, signature="sig-a", report="r1"
                ),
                _record(
                    2, IterationOutcome.REJECTED_GATE, signature="sig-a", report="r2"
                ),
                _record(
                    3,
                    IterationOutcome.REJECTED_NOT_BETTER,
                    signature="sig-b",
                    report="r3",
                ),
            ),
        )
        doc = generate_context(data, budget_chars=8000)
        assert "[x2] sig-a" in doc
        assert "[x1] sig-b" in doc
        assert "GRAVEYARD" in doc

    def test_accepted_approaches_listed(self) -> None:
        doc = generate_context(self._input(), budget_chars=8000)
        assert "ACCEPTED APPROACHES" in doc and "closed-form sum" in doc

    def test_directives_rendered(self) -> None:
        doc = generate_context(
            self._input(directives=("try memoization",)), budget_chars=8000
        )
        assert "ACTIVE DIRECTIVES" in doc and "- try memoization" in doc

    def test_no_directives_renders_none(self) -> None:
        doc = generate_context(self._input(), budget_chars=8000)
        assert "(none)" in doc

    def test_budget_shrinks_graveyard_only(self) -> None:
        records = tuple(
            _record(
                i,
                IterationOutcome.REJECTED_GATE,
                signature=f"s{i}",
                report=f"report {i}",
            )
            for i in range(20)
        )
        big = generate_context(self._input(records=records), budget_chars=100000)
        # Budget below total size but above the fixed sections' size: only the
        # graveyard shrinks (spec: it is the last section allowed to shrink).
        small = generate_context(self._input(records=records), budget_chars=950)
        assert len(small) < len(big)
        assert "... (truncated)" in small
        assert "# GOAL" in small
        assert "SCORE TRAJECTORY" in small

    def test_extreme_budget_still_keeps_goal(self) -> None:
        doc = generate_context(self._input(), budget_chars=60)
        assert "make it fast" in doc

    def test_committed_records_carry_tags_in_trajectory(self) -> None:
        data = self._input(
            records=(_record(1, IterationOutcome.COMMITTED, tag="evolve/r/v1"),),
        )
        doc = generate_context(data, budget_chars=8000)
        assert "evolve/r/v1" in doc


class TestGraveyardIgnoresCommitted:
    def test_committed_not_in_graveyard(self) -> None:
        data = ContextInput(
            goal="g",
            iteration=2,
            best_iteration=1,
            best_sha="s",
            best_score=ScoreVector(),
            baseline_score=None,
            records=(_record(1, IterationOutcome.COMMITTED, report="ok"),),
        )
        doc = generate_context(data, budget_chars=8000)
        graveyard = doc.split("GRAVEYARD")[1]
        assert "empty" in graveyard.lower()
