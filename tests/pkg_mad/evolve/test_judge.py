from __future__ import annotations

import pytest

from freemad.config import ComparatorTermConfig, GatePredicateConfig
from freemad.evolve.judge import (
    compare_scores,
    evaluate_gate,
    parse_stage_stdout,
    target_met,
    within_regress_bounds,
)
from freemad.evolve.models import ScoreVector
from freemad.types import CompareDirection, GateOp


def sv(**components: float) -> ScoreVector:
    return ScoreVector(components=dict(components))


MAX_TERM = ComparatorTermConfig(
    component="ops", direction=CompareDirection.MAXIMIZE, epsilon=2.0
)
MIN_TERM = ComparatorTermConfig(
    component="latency", direction=CompareDirection.MINIMIZE, epsilon=0.5
)
BOTH = (MAX_TERM, MIN_TERM)


class TestEvaluateGate:
    def test_pass_when_all_predicates_hold(self) -> None:
        gate = (
            GatePredicateConfig(component="ops", op=GateOp.GT, value=10),
            GatePredicateConfig(component="mem", op=GateOp.LTE, value=100),
        )
        ok, failures = evaluate_gate(sv(ops=11, mem=99), gate)
        assert ok and failures == ()

    @pytest.mark.parametrize(
        "op,value,actual,expected",
        [
            (">=", 10, 10, True),
            (">=", 10, 9.999, False),
            (">", 10, 10, False),
            (">", 10, 10.001, True),
            ("<=", 5, 5, True),
            ("<=", 5, 5.1, False),
            ("<", 5, 4.999, True),
            ("==", 3, 3.0, True),
            ("==", 3, 3.1, False),
        ],
    )
    def test_ops(self, op: str, value: float, actual: float, expected: bool) -> None:
        gate = (GatePredicateConfig(component="x", op=GateOp(op), value=value),)
        ok, _ = evaluate_gate(sv(x=actual), gate)
        assert ok is expected

    def test_missing_component_fails_closed(self) -> None:
        gate = (GatePredicateConfig(component="absent", op=GateOp.GT, value=0),)
        ok, failures = evaluate_gate(sv(other=1), gate)
        assert not ok
        assert failures[0].actual is None
        assert failures[0].component == "absent"

    def test_empty_gate_passes(self) -> None:
        ok, failures = evaluate_gate(sv(), ())
        assert ok and failures == ()

    def test_failure_describe_includes_actual(self) -> None:
        gate = (GatePredicateConfig(component="ops", op=GateOp.GTE, value=10),)
        _, failures = evaluate_gate(sv(ops=4), gate)
        assert "ops" in failures[0].describe()
        assert "4" in failures[0].describe()


class TestCompareScores:
    def test_strict_better_maximize(self) -> None:
        assert compare_scores(sv(ops=102.1), sv(ops=100), (MAX_TERM,))

    def test_within_epsilon_is_not_better(self) -> None:
        assert not compare_scores(
            sv(ops=101), sv(ops=100), (MAX_TERM,)
        )  # diff 1 <= eps 2
        assert not compare_scores(sv(ops=100), sv(ops=100), (MAX_TERM,))
        assert not compare_scores(
            sv(ops=98), sv(ops=100), (MAX_TERM,)
        )  # diff -2 within eps
        assert not compare_scores(
            sv(ops=102), sv(ops=100), (MAX_TERM,)
        )  # diff == eps is a tie

    def test_worse_is_not_better(self) -> None:
        assert not compare_scores(sv(ops=90), sv(ops=100), (MAX_TERM,))

    def test_lexicographic_first_term_decides(self) -> None:
        a = sv(ops=200, latency=99)
        b = sv(ops=100, latency=1)
        assert compare_scores(a, b, BOTH)

    def test_second_term_breaks_ties(self) -> None:
        a = sv(ops=101, latency=1.0)
        b = sv(ops=100, latency=2.0)
        assert compare_scores(a, b, BOTH)

    def test_minimize_direction(self) -> None:
        a = sv(latency=1.0)
        b = sv(latency=2.0)
        assert compare_scores(a, b, (MIN_TERM,))
        assert not compare_scores(b, a, (MIN_TERM,))

    def test_all_terms_within_epsilon_not_better(self) -> None:
        assert not compare_scores(
            sv(ops=101, latency=1.4), sv(ops=100, latency=1.0), BOTH
        )

    def test_last_term_tie_is_not_better(self) -> None:
        assert not compare_scores(
            sv(ops=100, latency=1.0), sv(ops=100, latency=1.0), BOTH
        )

    def test_missing_component_fails_closed(self) -> None:
        # A missing component only matters when it must decide: all terms tied.
        assert not compare_scores(sv(ops=101), sv(ops=100), BOTH)
        # If an earlier term decides, later missing components cannot flip it.
        assert compare_scores(sv(ops=500), sv(ops=1, latency=1.0), BOTH)
        assert not compare_scores(sv(ops=1), sv(ops=500, latency=1.0), BOTH)

    def test_epsilon_zero_requires_exact_improvement(self) -> None:
        zero = ComparatorTermConfig(
            component="ops", direction=CompareDirection.MAXIMIZE, epsilon=0.0
        )
        assert compare_scores(sv(ops=100.001), sv(ops=100), (zero,))
        assert not compare_scores(sv(ops=100.0), sv(ops=100), (zero,))
        assert not compare_scores(sv(ops=99.999), sv(ops=100), (zero,))


class TestWithinRegressBounds:
    def test_default_bound_is_epsilon(self) -> None:
        best = sv(ops=100)
        ok, detail = within_regress_bounds(sv(ops=97), best, (MAX_TERM,))
        assert not ok
        assert detail is not None and "regressed" in detail

    def test_explicit_max_regress_overrides(self) -> None:
        term = ComparatorTermConfig(
            component="ops",
            direction=CompareDirection.MAXIMIZE,
            epsilon=2.0,
            max_regress=20.0,
        )
        ok, _ = within_regress_bounds(sv(ops=85), sv(ops=100), (term,))
        assert ok
        ok, _ = within_regress_bounds(sv(ops=79), sv(ops=100), (term,))
        assert not ok

    def test_minimize_bound(self) -> None:
        term = ComparatorTermConfig(
            component="lat", direction=CompareDirection.MINIMIZE, epsilon=1.0
        )
        best = sv(lat=1.0)
        # 3.0 is a full unit worse than the allowed worst (best + epsilon = 2.0).
        ok, _ = within_regress_bounds(sv(lat=3.0), best, (term,))
        assert not ok
        # 1.5 is within the tolerated band.
        ok, _ = within_regress_bounds(sv(lat=1.5), best, (term,))
        assert ok

    def test_drift_is_not_cumulative_across_generations(self) -> None:
        term = ComparatorTermConfig(
            component="ops", direction=CompareDirection.MAXIMIZE, epsilon=2.0
        )
        best_ever = sv(ops=100)
        gen1 = sv(ops=99)
        gen2 = sv(ops=98)
        ok1, _ = within_regress_bounds(gen1, best_ever, (term,))
        ok2, _ = within_regress_bounds(gen2, best_ever, (term,))
        assert ok1 and ok2
        ok3, _ = within_regress_bounds(sv(ops=96), best_ever, (term,))
        assert not ok3

    def test_missing_component_violates(self) -> None:
        ok, detail = within_regress_bounds(sv(), sv(ops=100), (MAX_TERM,))
        assert not ok and detail is not None


class TestParseStageStdout:
    def test_valid_output(self) -> None:
        parsed = parse_stage_stdout(
            '{"components": {"ops": 12.5, "mem": 3}}', ["ops", "mem"]
        )
        assert parsed == {"ops": 12.5, "mem": 3.0}

    def test_extra_components_ignored(self) -> None:
        parsed = parse_stage_stdout('{"components": {"a": 1, "b": 2}}', ["a"])
        assert parsed == {"a": 1.0}

    def test_malformed_json_raises(self) -> None:
        with pytest.raises(Exception):
            parse_stage_stdout("not json", ["x"])

    def test_non_object_root_raises(self) -> None:
        with pytest.raises(ValueError, match="JSON object"):
            parse_stage_stdout("[1, 2]", ["x"])

    def test_missing_components_key_raises(self) -> None:
        with pytest.raises(ValueError, match="components"):
            parse_stage_stdout('{"result": {}}', ["x"])

    def test_components_not_object_raises(self) -> None:
        with pytest.raises(ValueError, match="components"):
            parse_stage_stdout('{"components": [1]}', ["x"])

    def test_declared_component_missing_raises(self) -> None:
        with pytest.raises(ValueError, match="missing"):
            parse_stage_stdout('{"components": {"other": 1}}', ["needed"])

    def test_string_component_raises(self) -> None:
        with pytest.raises(ValueError, match="number"):
            parse_stage_stdout('{"components": {"x": "fast"}}', ["x"])

    def test_bool_component_raises(self) -> None:
        with pytest.raises(ValueError, match="number"):
            parse_stage_stdout('{"components": {"x": true}}', ["x"])

    def test_nan_component_raises(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            parse_stage_stdout('{"components": {"x": NaN}}', ["x"])

    def test_inf_component_raises(self) -> None:
        with pytest.raises(ValueError, match="finite"):
            parse_stage_stdout('{"components": {"x": Infinity}}', ["x"])


class TestTargetMet:
    def test_target_met_true_and_false(self) -> None:
        target = (GatePredicateConfig(component="ops", op=GateOp.GTE, value=100),)
        assert target_met(sv(ops=150), target)
        assert not target_met(sv(ops=50), target)
        assert not target_met(sv(), target)
