from __future__ import annotations

import subprocess
from dataclasses import replace
from pathlib import Path
from typing import List, Optional


from freemad.agents.base import Agent
from freemad.config import Config, load_config
from freemad.evolve.orchestrator import EvolveOrchestrator
from freemad.tasks.models import TaskRequest, TaskResponse
from freemad.types import EvolveRunStatus, EvolveStopReason, IterationOutcome

SLOW_IMPL = """\
import time


def total(n: int) -> int:
    s = 0
    for i in range(n + 1):
        s += i
        time.sleep(0.000005)
    return s
"""

FAST_IMPL = """\
def total(n: int) -> int:
    return n * (n + 1) // 2
"""

BROKEN_IMPL = """\
def total(n: int) -> int:
    return n * (n + 1  # syntax error
"""

TESTS_FILE = """\
from impl import total


def test_known_values():
    assert total(0) == 0
    assert total(10) == 55
"""

BENCH_FILE = """\
import json
import time

from impl import total


def ops_per_sec() -> float:
    calls = 0
    start = time.perf_counter()
    deadline = start + 0.2
    while time.perf_counter() < deadline:
        total(30)
        calls += 1
    elapsed = time.perf_counter() - start
    return calls / elapsed if elapsed > 0 else 0.0


if __name__ == "__main__":
    print(json.dumps({"components": {"ops_per_sec": round(ops_per_sec(), 2)}}))
"""


class ScriptedAgent(Agent):
    """Fake worker: pops a scripted file write per act() call."""

    def __init__(
        self, cfg: Config, agent_cfg, scripts: Optional[List[Optional[str]]] = None
    ):
        super().__init__(cfg, agent_cfg)
        self._scripts = list(scripts or [])
        self.calls = 0
        self.last_context_len = 0

    def generate(self, requirement: str):  # pragma: no cover - not used by evolve
        raise NotImplementedError

    def critique_and_refine(self, requirement: str, own_response: str, peer_responses):  # noqa: D102
        raise NotImplementedError  # pragma: no cover - not used by evolve

    def act(self, request: TaskRequest) -> TaskResponse:
        self.calls += 1
        self.last_context_len = len(request.goal)
        script = self._scripts.pop(0) if self._scripts else None
        writes = []
        if script is not None:
            path = "impl.py"
            from freemad.tasks.models import FileWrite

            writes.append(FileWrite(path=path, content=script))
        return TaskResponse(
            agent_id=self.agent_cfg.id,
            stage=request.stage,
            role=request.role,
            content="tried the change" if script else "no changes",
            writes=tuple(writes),
        )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def make_config(repo: Path, tmp_path: Path, **overrides) -> Config:
    evolve = {
        "repo_path": str(repo),
        "store_path": str(tmp_path / "evolve.db"),
        "variation": {"kind": "single_agent", "agent_id": "w"},
        "judge": {
            "stages": [
                {
                    "name": "tests",
                    "command": "python -m pytest tests -q",
                    "timeout_sec": 60,
                },
                {
                    "name": "bench",
                    "command": "python bench.py",
                    "timeout_sec": 60,
                    "parse": "json_stdout",
                    "provides": ["ops_per_sec"],
                },
            ],
            "gate": [{"component": "ops_per_sec", "op": ">", "value": 0}],
            "comparator": [
                {"component": "ops_per_sec", "direction": "maximize", "epsilon": 1.0}
            ],
            "protected_paths": ["bench.py", "tests/"],
        },
        "stop": {
            "max_iterations": 5,
            "max_wall_clock_minutes": 10,
            "target": [{"component": "ops_per_sec", "op": ">=", "value": 5000}],
        },
        "context_budget_chars": 8000,
    }
    evolve.update(overrides)
    cfg = load_config(
        overrides={
            "agents": [
                {"id": "w", "type": "fake_worker"},
                {"id": "x", "type": "claude_code"},
            ],
            "evolve": evolve,
        }
    )
    from freemad.agents.registry import register_agent

    register_agent("fake_worker", ScriptedAgent)
    return cfg


def build_orchestrator(cfg: Config, scripts: List[Optional[str]]):
    orch = EvolveOrchestrator(cfg)
    agent = ScriptedAgent(cfg, cfg.agents[0], scripts)
    orch._resolve_agent = lambda: agent  # type: ignore[method-assign]
    orch._agent_ref = agent
    return orch


class TestBaseline:
    def test_baseline_measured_and_tagged_v0_not_counted(self, toy_repo, tmp_path):
        cfg = make_config(toy_repo, tmp_path)
        orch = build_orchestrator(cfg, [None])
        snap = orch.create_run("make total fast")
        snap = orch.resume(snap.run_id)
        final = orch.step(snap.run_id)
        assert final.baseline_score is not None
        assert final.baseline_score.get("ops_per_sec", 0) > 0
        assert final.iteration == 1
        events = orch._store.list_events(final.run_id)
        kinds = [e.kind.value for e in events]
        assert "baseline_judged" in kinds

    def test_seed_failing_own_gate_stops_fatal(self, toy_repo, tmp_path):
        (toy_repo / "impl.py").write_text(BROKEN_IMPL)
        _git(
            toy_repo,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-aqm",
            "broken seed",
        )
        cfg = make_config(toy_repo, tmp_path)
        orch = build_orchestrator(cfg, [])
        snap = orch.create_run("goal")
        snap = orch.resume(snap.run_id)
        final = orch.step(snap.run_id)
        assert final.status == EvolveRunStatus.FAILED
        assert final.stop_reason == EvolveStopReason.FATAL_ERROR.value
        assert "baseline_gate_failed" in (final.error or "")

    def test_manifest_change_midrun_is_fatal(self, toy_repo, tmp_path):
        cfg = make_config(toy_repo, tmp_path)
        orch = build_orchestrator(cfg, [])
        snap = orch.create_run("g")
        snap = orch.resume(snap.run_id)
        baseline = orch.step(snap.run_id)
        assert baseline.status == EvolveRunStatus.RUNNING
        cfg2 = replace(
            cfg,
            evolve=replace(
                cfg.evolve,
                judge=replace(
                    cfg.evolve.judge,
                    comparator=(replace(cfg.evolve.judge.comparator[0], epsilon=99.0),),
                ),
            ),
        )
        orch2 = EvolveOrchestrator(cfg2, store_path=cfg.evolve.store_path)
        final = orch2.step(snap.run_id)
        assert final.status == EvolveRunStatus.FAILED
        assert "fitness definition changed mid-run" in (final.error or "")


class TestIterations:
    def test_improvement_committed_tagged_branch_advanced_target_reached(
        self, toy_repo, tmp_path
    ):
        cfg = make_config(toy_repo, tmp_path)
        orch = build_orchestrator(cfg, [FAST_IMPL])
        snap = orch.create_run("make total fast")
        snap = orch.resume(snap.run_id)
        final = orch.run(snap.run_id)
        assert final.status == EvolveRunStatus.COMPLETED
        assert final.stop_reason == EvolveStopReason.TARGET_REACHED.value
        assert final.best_iteration == 1
        assert final.best_sha is not None

        tip = subprocess.run(
            ["git", "rev-parse", f"evolve/{final.run_id}"],
            cwd=str(toy_repo),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert tip == final.best_sha

        tag_exists = subprocess.run(
            ["git", "tag", "--list", f"evolve/{final.run_id}/v1"],
            cwd=str(toy_repo),
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        assert tag_exists

        trailer = subprocess.run(
            ["git", "log", "-1", "--format=%b", tip],
            cwd=str(toy_repo),
            capture_output=True,
            text=True,
            check=True,
        )
        assert "Evolve-Score:" in trailer.stdout

        committed_worktree_clean = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(toy_repo),
            capture_output=True,
            text=True,
        ).stdout.strip()
        assert committed_worktree_clean == ""

    def test_breaking_change_rejected_gate_signature_in_context(
        self, toy_repo, tmp_path
    ):
        cfg = make_config(toy_repo, tmp_path)
        orch = build_orchestrator(cfg, [BROKEN_IMPL, FAST_IMPL])
        snap = orch.create_run("make total fast")
        orch.resume(snap.run_id)
        after_baseline = orch.step(snap.run_id)
        it1 = orch.step(after_baseline.run_id)
        records = orch._state_for(snap.run_id).records
        assert records[-1].outcome == IterationOutcome.REJECTED_GATE
        assert (
            records[-1].failure_signature and "tests" in records[-1].failure_signature
        )
        context = orch._context_for(snap.run_id, it1)
        assert "GRAVEYARD" in context
        assert records[-1].failure_signature in context

    def test_no_changes_counts_as_worker_failed(self, toy_repo, tmp_path):
        cfg = make_config(toy_repo, tmp_path)
        orch = build_orchestrator(cfg, [None])
        snap = orch.create_run("g")
        orch.resume(snap.run_id)
        orch.step(snap.run_id)  # baseline
        it1 = orch.step(snap.run_id)
        record = orch._state_for(snap.run_id).records[-1]
        assert record.outcome == IterationOutcome.WORKER_FAILED
        assert record.failure_signature == "no changes produced"
        assert it1.iteration == 2
        assert it1.best_iteration is None

    def test_tampered_bench_cannot_move_score(self, toy_repo, tmp_path):
        hacked_bench = BENCH_FILE.replace(
            "return calls / elapsed if elapsed > 0 else 0.0",
            "return 999999.0",
        )

        class TamperAgent(ScriptedAgent):
            def act(self, request: TaskRequest) -> TaskResponse:
                response = super().act(request)
                bench = request.workspace_root + "/bench.py"
                with open(bench, "w") as fh:
                    fh.write(hacked_bench)
                return response

        from freemad.agents.registry import register_agent

        register_agent("tamper_worker", TamperAgent)
        cfg = make_config(toy_repo, tmp_path)
        cfg = replace(
            cfg, agents=[replace(cfg.agents[0], type="tamper_worker"), cfg.agents[1]]
        )
        orch = build_orchestrator(cfg, [FAST_IMPL])
        orch._resolve_agent = lambda: TamperAgent(cfg, cfg.agents[0], [FAST_IMPL])  # type: ignore[method-assign]
        snap = orch.create_run("g")
        orch.resume(snap.run_id)
        orch.step(snap.run_id)  # baseline honest score
        orch.step(snap.run_id)
        events = orch._store.list_events(snap.run_id)
        judged = [e for e in events if e.kind.value == "candidate_judged"]
        assert judged, "candidate must be judged"
        hashes = judged[-1].payload["verdict"]["protected_hashes"]
        assert hashes.get("bench.py") and hashes["bench.py"] != "absent"
        record = orch._state_for(snap.run_id).records[-1]
        # The candidate hacked bench.py to print a constant 999999.0. The judge
        # must have measured with the seed copy instead: the recorded score is
        # an honest measurement of the (fast) implementation, never the hack.
        assert record.outcome == IterationOutcome.COMMITTED
        assert record.score is not None
        assert record.score.get("ops_per_sec") != 999999.0
        assert abs(record.score.get("ops_per_sec", 0) - 999999.0) > 1.0

    def test_max_iterations_stop(self, toy_repo, tmp_path):
        from freemad.config import GatePredicateConfig

        cfg = make_config(toy_repo, tmp_path)
        cfg = replace(
            cfg,
            evolve=replace(
                cfg.evolve,
                stop=replace(
                    cfg.evolve.stop,
                    max_iterations=1,
                    target=(
                        GatePredicateConfig(
                            component="ops_per_sec", op=">=", value=10**12
                        ),
                    ),
                ),
            ),
        )
        orch = build_orchestrator(cfg, [None, None])
        snap = orch.create_run("g")
        orch.resume(snap.run_id)
        orch.step(snap.run_id)  # baseline -> iteration becomes 1
        it1 = orch.step(snap.run_id)  # worker failed -> iteration becomes 2
        final = orch.step(it1.run_id)  # iteration 2 > max_iterations=1
        assert final.status == EvolveRunStatus.STOPPED
        assert final.stop_reason == EvolveStopReason.MAX_ITERATIONS.value


class TestResume:
    def test_resume_rebuilds_records_from_events(self, toy_repo, tmp_path):
        cfg = make_config(toy_repo, tmp_path)
        orch = build_orchestrator(cfg, [BROKEN_IMPL])
        snap = orch.create_run("g")
        orch.resume(snap.run_id)
        orch.step(snap.run_id)
        orch.step(snap.run_id)
        fresh = EvolveOrchestrator(cfg, store_path=str(tmp_path / "evolve.db"))
        records = fresh._rebuild_records(snap.run_id)
        assert len(records) == 1
        assert records[0].outcome == IterationOutcome.REJECTED_GATE
        assert records[0].failure_signature
