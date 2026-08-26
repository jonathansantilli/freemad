"""Regressions for the defects found in the 2026-08-24 audit (docs/evolve-audit.md).

Each test pins one clause of the self-regulation contract in `evolve.md` section 4 that
the implementation was violating.
"""

from __future__ import annotations

import sys

import json
from pathlib import Path
from typing import List

import pytest

from freemad.agents.base import Agent
from freemad.config import load_config
from freemad.evolve.lineage import Lineage
from freemad.evolve.orchestrator import EvolveOrchestrator
from freemad.tasks.models import FileWrite, TaskRequest, TaskResponse
from freemad.types import (
    EvolveEventKind,
    EvolveRunStatus,
    EvolveStopReason,
    IterationOutcome,
    SupervisorCause,
)
from tests.pkg_mad.evolve.test_orchestrator import (
    BENCH_FILE,
    FAST_IMPL,
    SLOW_IMPL,
    TESTS_FILE,
    ScriptedAgent,
    _git,
    build_orchestrator,
    make_config,
)

# A benchmark whose score is read straight from a worker-editable knob file, so a test
# can dictate an exact score vector without racing a real timing loop.
KNOB_BENCH = """\
import json
from pathlib import Path

knobs = json.loads(Path("knobs.json").read_text())
print(json.dumps({"components": {
    "correctness": float(knobs["correctness"]),
    "ops_per_sec": float(knobs["ops_per_sec"]),
}}))
"""

BROKEN_TESTS_IMPL = """\
def total(n: int) -> int:
    return 0          # wrong answer, but instant
"""


def _commit(repo: Path, message: str) -> None:
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", message)


class _WritesAgent(Agent):
    """Worker that applies a scripted list of file writes, one dict per iteration."""

    def __init__(self, cfg, agent_cfg, scripts: List[dict]):
        super().__init__(cfg, agent_cfg)
        self._scripts = list(scripts)

    def generate(self, requirement: str):  # pragma: no cover - unused by evolve
        raise NotImplementedError

    def critique_and_refine(
        self, requirement, own_response, peer_responses
    ):  # pragma: no cover
        raise NotImplementedError

    def act(self, request: TaskRequest) -> TaskResponse:
        files = self._scripts.pop(0) if self._scripts else {}
        return TaskResponse(
            agent_id=self.agent_cfg.id,
            stage=request.stage,
            role=request.role,
            content="scripted edit",
            writes=tuple(FileWrite(path=p, content=c) for p, c in files.items()),
        )


def _events(orch: EvolveOrchestrator, run_id: str, kind: EvolveEventKind) -> list:
    return [e for e in orch._store.list_events(run_id) if e.kind == kind]


# --------------------------------------------------------------------------------
# B1 - evolve.md section 4.1: progress is proven, not claimed
# --------------------------------------------------------------------------------


def _late_stage_config(repo: Path, tmp_path: Path):
    """Scoring stage first, correctness stage last: the fail-open ordering."""
    return make_config(
        repo,
        tmp_path,
        judge={
            "stages": [
                {
                    "name": "bench",
                    "command": f"{sys.executable} bench.py",
                    "timeout_sec": 60,
                    "parse": "json_stdout",
                    "provides": ["ops_per_sec"],
                },
                {
                    "name": "tests",
                    "command": f"{sys.executable} -m pytest tests -q",
                    "timeout_sec": 60,
                },
            ],
            "gate": [{"component": "ops_per_sec", "op": ">", "value": 0}],
            "comparator": [
                {"component": "ops_per_sec", "direction": "maximize", "epsilon": 1.0}
            ],
            "protected_paths": ["bench.py", "tests/"],
        },
    )


def test_failing_late_stage_rejects_even_when_the_gate_passes(toy_repo, tmp_path):
    """A stage failure short-circuits the pipeline, leaving a partial score vector.

    When the gate only covers components an *earlier* stage provided, it passes on that
    partial vector -- so a candidate that broke the test suite used to be committed.
    """
    cfg = _late_stage_config(toy_repo, tmp_path)
    orch = build_orchestrator(cfg, [BROKEN_TESTS_IMPL])
    snap = orch.create_run("make total fast")
    snap = orch.resume(snap.run_id)
    orch.step(snap.run_id)  # baseline
    orch.step(snap.run_id)  # iteration 1

    verdict = _events(orch, snap.run_id, EvolveEventKind.CANDIDATE_JUDGED)[-1].payload[
        "verdict"
    ]
    rejected = _events(orch, snap.run_id, EvolveEventKind.CANDIDATE_REJECTED)
    orch.close()

    assert verdict["failed_stage"] == "tests"
    assert (
        verdict["gate_passed"] is True
    ), "the gate really does pass on the partial vector"
    assert rejected, "a candidate whose judge stage failed must never be admitted"
    assert rejected[-1].payload["outcome"] == IterationOutcome.REJECTED_GATE.value


def test_committed_candidate_never_has_a_failed_stage(toy_repo, tmp_path):
    cfg = _late_stage_config(toy_repo, tmp_path)
    orch = build_orchestrator(cfg, [FAST_IMPL])
    snap = orch.create_run("make total fast")
    snap = orch.resume(snap.run_id)
    orch.step(snap.run_id)
    orch.step(snap.run_id)

    judged = _events(orch, snap.run_id, EvolveEventKind.CANDIDATE_JUDGED)
    committed = _events(orch, snap.run_id, EvolveEventKind.CANDIDATE_COMMITTED)
    orch.close()

    assert committed, "a clean speedup must still be admitted"
    assert judged[-1].payload["verdict"]["failed_stage"] is None


def test_seed_with_a_failing_late_stage_is_fatal(toy_repo, tmp_path):
    """The baseline has the same hole: a seed whose stage fails is not a baseline."""
    (toy_repo / "impl.py").write_text(BROKEN_TESTS_IMPL)
    _commit(toy_repo, "seed that fails its own tests")

    cfg = _late_stage_config(toy_repo, tmp_path)
    orch = build_orchestrator(cfg, [])
    snap = orch.create_run("goal")
    snap = orch.resume(snap.run_id)
    final = orch.step(snap.run_id)
    orch.close()

    assert final.status == EvolveRunStatus.FAILED
    assert final.stop_reason == EvolveStopReason.FATAL_ERROR.value
    assert "tests" in (final.error or "")


# --------------------------------------------------------------------------------
# B2 - evolve.md section 8.3: comparator drift is bounded against best-ever
# --------------------------------------------------------------------------------


def _two_component_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "knobrepo"
    repo.mkdir()
    (repo / "bench.py").write_text(KNOB_BENCH)
    (repo / "knobs.json").write_text(
        json.dumps({"correctness": 0.5, "ops_per_sec": 100.0})
    )
    _git(repo, "init", "-q")
    _commit(repo, "seed")
    return repo


def _two_component_config(repo: Path, tmp_path: Path):
    return load_config(
        overrides={
            "agents": [
                {"id": "w", "type": "writes_agent"},
                {"id": "x", "type": "claude_code"},
            ],
            "evolve": {
                "repo_path": str(repo),
                "store_path": str(tmp_path / "evolve.db"),
                "variation": {"kind": "single_agent", "agent_id": "w"},
                "judge": {
                    "stages": [
                        {
                            "name": "bench",
                            "command": f"{sys.executable} bench.py",
                            "timeout_sec": 60,
                            "parse": "json_stdout",
                            "provides": ["correctness", "ops_per_sec"],
                        }
                    ],
                    "gate": [{"component": "correctness", "op": ">", "value": 0}],
                    # Lexicographic: correctness decides first, so a candidate can improve
                    # it while torching throughput.
                    "comparator": [
                        {
                            "component": "correctness",
                            "direction": "maximize",
                            "epsilon": 0.0,
                        },
                        {
                            "component": "ops_per_sec",
                            "direction": "maximize",
                            "epsilon": 1.0,
                        },
                    ],
                    "protected_paths": ["bench.py"],
                },
                "stop": {"max_iterations": 5, "max_wall_clock_minutes": 10},
                "context_budget_chars": 8000,
            },
        }
    )


def test_regression_is_bounded_against_the_peak_not_the_seed(tmp_path):
    """A hard-won secondary metric may not be ratcheted back down to the seed floor."""
    repo = _two_component_repo(tmp_path)
    cfg = _two_component_config(repo, tmp_path)

    from freemad.agents.registry import register_agent

    register_agent("writes_agent", _WritesAgent)
    scripts = [
        {"knobs.json": json.dumps({"correctness": 0.6, "ops_per_sec": 5000.0})},
        # Better on the deciding term, catastrophic on the second -- but still above the
        # *baseline* floor of 100 - 1.0, which is what the bound used to be measured against.
        {"knobs.json": json.dumps({"correctness": 0.7, "ops_per_sec": 99.5})},
    ]
    agent = _WritesAgent(cfg, cfg.agents[0], scripts)
    orch = EvolveOrchestrator(cfg)
    orch._resolve_agent = lambda: agent  # type: ignore[method-assign]

    snap = orch.create_run("raise correctness")
    snap = orch.resume(snap.run_id)
    orch.step(snap.run_id)  # baseline {0.5, 100}
    orch.step(snap.run_id)  # it1 -> accepted, best becomes {0.6, 5000}
    final = orch.step(snap.run_id)  # it2 -> must be rejected

    committed = _events(orch, snap.run_id, EvolveEventKind.CANDIDATE_COMMITTED)
    rejected = _events(orch, snap.run_id, EvolveEventKind.CANDIDATE_REJECTED)
    orch.close()

    assert len(committed) == 1, "only the genuine improvement is admitted"
    assert final.best_score is not None
    assert final.best_score.get("ops_per_sec") == pytest.approx(5000.0)
    assert rejected, "the peak-then-drop candidate must be rejected"
    assert "regress" in rejected[-1].payload["detail"].lower()


def test_a_run_without_a_target_does_not_complete_at_the_baseline(toy_repo, tmp_path):
    """`stop.target` is optional (evolve.md section 2.2); empty means no goal-met test.

    Gate evaluation is vacuously true on an empty predicate list, so an unset target
    used to read as "already met" and end every such run at iteration 0.
    """
    cfg = make_config(
        toy_repo, tmp_path, stop={"max_iterations": 2, "max_wall_clock_minutes": 10}
    )
    assert cfg.evolve.stop.target == ()
    orch = build_orchestrator(cfg, [FAST_IMPL, SLOW_IMPL])
    snap = orch.create_run("make total fast")
    snap = orch.resume(snap.run_id)
    after_baseline = orch.step(snap.run_id)

    assert after_baseline.status == EvolveRunStatus.RUNNING
    assert after_baseline.stop_reason is None

    final = orch.run(snap.run_id)
    orch.close()
    assert final.stop_reason == EvolveStopReason.MAX_ITERATIONS.value


# --------------------------------------------------------------------------------
# B3 - evolve.md section 4.7: the measurement cannot be gamed by the measured
# --------------------------------------------------------------------------------


def test_files_added_inside_a_protected_directory_do_not_survive_restore(
    toy_repo, tmp_path
):
    """`git checkout <ref> -- <dir>` only overwrites paths present in <ref>.

    Adding beats editing: a conftest.py dropped into a protected `tests/` would neutralise
    the suite and outlive restoration.
    """
    cfg = make_config(toy_repo, tmp_path)
    lineage = Lineage(cfg, "protect-test")
    lineage.init_run_branch(lineage.resolve_ref("HEAD"))
    worktree = lineage.create_worktree(1)
    try:
        (worktree / "tests" / "conftest.py").write_text(
            "def pytest_collection_modifyitems(items):\n    items.clear()\n"
        )
        (worktree / "tests" / "test_extra.py").write_text(
            "def test_free_pass(): assert True\n"
        )
        (worktree / "bench.py").write_text(
            'print(\'{"components": {"ops_per_sec": 1e9}}\')'
        )

        hashes = lineage.restore_protected(worktree, "HEAD")

        assert not (worktree / "tests" / "conftest.py").exists()
        assert not (worktree / "tests" / "test_extra.py").exists()
        assert (worktree / "bench.py").read_text() == BENCH_FILE
        assert (worktree / "tests" / "test_impl.py").read_text() == TESTS_FILE
        # Independently computed, not a second call to the thing under test.
        import hashlib

        assert (
            hashes["bench.py"] == hashlib.sha256(BENCH_FILE.encode()).hexdigest()
        ), "the stamped hash must be the seed's own content hash"
    finally:
        lineage.remove_worktree(1)
        lineage.delete_run_branch()


# --------------------------------------------------------------------------------
# B4 - evolve.md section 4.6: death is cheap
# --------------------------------------------------------------------------------


def test_crash_between_tag_and_branch_advance_is_recoverable(
    toy_repo, tmp_path, monkeypatch
):
    """The tag outlives the crash; resume redoes the iteration and must re-tag over it."""
    cfg = make_config(toy_repo, tmp_path)
    orch = build_orchestrator(cfg, [FAST_IMPL, FAST_IMPL])
    snap = orch.create_run("make total fast")
    snap = orch.resume(snap.run_id)
    orch.step(snap.run_id)  # baseline

    def boom(self, new_sha, expected_old_sha):
        raise RuntimeError("simulated kill -9 after tag, before branch advance")

    monkeypatch.setattr(Lineage, "advance_run_branch", boom)
    with pytest.raises(RuntimeError):
        orch.step(snap.run_id)
    monkeypatch.undo()

    # The worktree must not leak either, or resume starts from a dirty tree.
    assert not (
        toy_repo / ".freemad" / "evolve" / "worktrees" / snap.run_id / "it1"
    ).exists()

    orch.resume(snap.run_id)
    final = orch.step(snap.run_id)
    committed = _events(orch, snap.run_id, EvolveEventKind.CANDIDATE_COMMITTED)
    orch.close()

    assert (
        committed
    ), "the redone iteration must be admitted, not wedged on the orphan tag"
    assert final.best_sha == committed[-1].payload["sha"]


# --------------------------------------------------------------------------------
# H1 - an agent that only adds files has not done nothing
# --------------------------------------------------------------------------------


class _AddsOnlyNewFiles(ScriptedAgent):
    def act(self, request: TaskRequest) -> TaskResponse:
        root = Path(request.workspace_root)
        (root / "memo.py").write_text("CACHE: dict = {}\n")
        return TaskResponse(
            agent_id=self.agent_cfg.id,
            stage=request.stage,
            role=request.role,
            content="added a memo module",
            writes=(),
        )


def test_addition_only_edit_counts_as_a_change(toy_repo, tmp_path):
    """`git status -uno` hides untracked files, but `commit_candidate` stages them."""
    cfg = make_config(toy_repo, tmp_path)
    orch = EvolveOrchestrator(cfg)
    orch._resolve_agent = lambda: _AddsOnlyNewFiles(cfg, cfg.agents[0], [])  # type: ignore
    snap = orch.create_run("make total fast")
    snap = orch.resume(snap.run_id)
    orch.step(snap.run_id)
    orch.step(snap.run_id)

    produced = _events(orch, snap.run_id, EvolveEventKind.VARIATION_PRODUCED)[
        -1
    ].payload
    orch.close()

    assert produced["produced_changes"] is True
    assert (
        "memo.py" in produced["diff_stat"]
    ), "the stat must show what would be committed"


# --------------------------------------------------------------------------------
# H2 / H3 - the escalation budget survives resume and is restored by human guidance
# --------------------------------------------------------------------------------


def test_rebuilt_intervention_counter_resets_on_a_new_best(toy_repo, tmp_path):
    """Resume rebuilds counters from events; a new best must clear them as the live path does."""
    cfg = make_config(toy_repo, tmp_path)
    orch = build_orchestrator(cfg, [])
    snap = orch.create_run("goal")
    run_id = snap.run_id

    for kind, payload in [
        (EvolveEventKind.SUPERVISOR_TRIGGERED, {"cause": SupervisorCause.STALL.value}),
        (EvolveEventKind.SUPERVISOR_TRIGGERED, {"cause": SupervisorCause.STALL.value}),
        (EvolveEventKind.CANDIDATE_COMMITTED, {"sha": "abc", "tag": "v1", "score": {}}),
        (EvolveEventKind.SUPERVISOR_TRIGGERED, {"cause": SupervisorCause.LOOP.value}),
    ]:
        orch._store.append_event(run_id, kind, 1, payload)

    orch._state.pop(run_id, None)
    orch._rebuild_records(run_id)
    counter = orch._state[run_id].interventions_since_best
    orch.close()

    assert counter == 1, "only the intervention after the last new best still counts"


def test_human_guidance_restores_the_autonomous_budget(toy_repo, tmp_path):
    from dataclasses import replace as dc_replace

    cfg = make_config(toy_repo, tmp_path)
    orch = build_orchestrator(cfg, [])
    snap = orch.create_run("goal")
    # `answer` only applies to a run parked on an escalation.
    orch._store.update_run(dc_replace(snap, status=EvolveRunStatus.WAITING_FOR_HUMAN))
    state = orch._state_for(snap.run_id)
    state.interventions_since_best = (
        cfg.evolve.supervisor.max_interventions_before_human
    )

    orch.answer(snap.run_id, "try memoizing partial sums")
    counter = orch._state_for(snap.run_id).interventions_since_best
    orch.close()

    assert counter == 0, "after human input the supervisor gets its attempts back"


# --------------------------------------------------------------------------------
# H5 - a stray path from a worker fails the iteration, not the run
# --------------------------------------------------------------------------------


class _EscapingWriteAgent(ScriptedAgent):
    def act(self, request: TaskRequest) -> TaskResponse:
        return TaskResponse(
            agent_id=self.agent_cfg.id,
            stage=request.stage,
            role=request.role,
            content="writing outside the worktree",
            writes=(FileWrite(path="../../escaped.py", content="pwned = True\n"),),
        )


def test_escaping_write_path_fails_the_iteration_not_the_run(toy_repo, tmp_path):
    cfg = make_config(toy_repo, tmp_path)
    orch = EvolveOrchestrator(cfg)
    orch._resolve_agent = lambda: _EscapingWriteAgent(cfg, cfg.agents[0], [])  # type: ignore
    snap = orch.create_run("make total fast")
    snap = orch.resume(snap.run_id)
    orch.step(snap.run_id)  # baseline
    final = orch.step(snap.run_id)  # iteration 1 - must not raise

    rejected = _events(orch, snap.run_id, EvolveEventKind.CANDIDATE_REJECTED)
    orch.close()

    assert (
        final.status == EvolveRunStatus.RUNNING
    ), "the run survives a misbehaving worker"
    assert rejected[-1].payload["outcome"] == IterationOutcome.WORKER_FAILED.value
    assert "escapes worktree" in rejected[-1].payload["detail"]
    # `../../escaped.py` resolves relative to the worktree, which lives at
    # <repo>/.freemad/evolve/worktrees/<run_id>/it1 — two levels up is the
    # worktrees directory, NOT tmp_path.
    assert not (toy_repo / ".freemad" / "evolve" / "worktrees" / "escaped.py").exists()
