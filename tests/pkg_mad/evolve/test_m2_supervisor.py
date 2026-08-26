from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable, List, Optional

import pytest

from freemad.config import load_config
from freemad.evolve.orchestrator import EvolveOrchestrator
from freemad.evolve.store import EvolveStore
from freemad.types import (
    EvolveEventKind,
    EvolveRunStatus,
    EvolveStopReason,
)
from tests.pkg_mad.evolve.test_orchestrator import (
    BENCH_FILE,
    SLOW_IMPL,
    TESTS_FILE,
    ScriptedAgent,
    _git,
)


DIRECTIONS_JSON = json.dumps(
    {"directions": ["vectorize the loop", "cache partial sums", "use numpy dot"]}
)


class SupervisedAgent(ScriptedAgent):
    """Worker that never improves; debate agents answer with canned directions."""

    def generate(self, requirement: str):
        from freemad.agents.base import AgentResponse, Metadata

        marked = f"SOLUTION: {DIRECTIONS_JSON}\nREASONING: canned directions"
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution=marked,
            reasoning="canned",
            answer_id=None,
            metadata=Metadata(),
        )

    def critique_and_refine(
        self, requirement: str, own_response: str, peer_responses: List[str]
    ):
        from freemad.agents.base import CritiqueResponse, Metadata
        from freemad.types import Decision

        return CritiqueResponse(
            agent_id=self.agent_cfg.id,
            decision=Decision.KEEP,
            changed=False,
            solution="SOLUTION: keep\nREASONING: unchanged",
            reasoning="keep",
            answer_id=None,
            metadata=Metadata(),
        )


def m2_config(repo: Path, tmp_path: Path, **evolve_overrides):
    evolve = {
        "repo_path": str(repo),
        "store_path": str(tmp_path / "evolve.db"),
        "variation": {"kind": "single_agent", "agent_id": "w"},
        "judge": {
            "stages": [
                {
                    "name": "tests",
                    "command": f"{sys.executable} -m pytest tests -q",
                    "timeout_sec": 60,
                },
                {
                    "name": "bench",
                    "command": f"{sys.executable} bench.py",
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
            "max_iterations": 50,
            "max_wall_clock_minutes": 10,
            "target": [{"component": "ops_per_sec", "op": ">=", "value": 10**12}],
        },
        "supervisor": {
            "stall_window": 2,
            "loop_threshold": 2,
            "directions_ttl_iterations": 1,
            "max_interventions_before_human": 2,
        },
    }
    evolve.update(evolve_overrides)
    cfg = load_config(
        overrides={
            "agents": [
                {"id": "w", "type": "fake_worker"},
                {"id": "d1", "type": "fake_worker"},
                {"id": "d2", "type": "fake_worker"},
            ],
            "evolve": evolve,
        }
    )
    from freemad.agents.registry import register_agent

    register_agent("fake_worker", SupervisedAgent)
    return cfg


def fresh_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "impl.py").write_text(SLOW_IMPL)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_impl.py").write_text(TESTS_FILE)
    (repo / "bench.py").write_text(BENCH_FILE)
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
    return repo


def build(cfg, scripts: List[Optional[str]], agent_cls=SupervisedAgent):
    orch = EvolveOrchestrator(cfg)
    orch._resolve_agent = (  # type: ignore[method-assign]
        lambda: agent_cls(cfg, cfg.agents[0], scripts)
    )
    return orch


RUNNER = """
import os, sys, time, json
sys.path.insert(0, "__PROJECT__")
from freemad.config import load_config
from freemad.agents import bootstrap
from freemad.agents.base import Agent, AgentResponse, CritiqueResponse
from freemad.agents.registry import register_agent
from freemad.tasks.models import TaskRequest, TaskResponse
from freemad.types import Decision
from freemad.evolve.orchestrator import EvolveOrchestrator


class RunnerWorker(Agent):
    def generate(self, requirement):
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution='SOLUTION: {"directions": ["a", "b", "c"]}\\nREASONING: canned',
            reasoning="canned",
            answer_id=None,
        )

    def critique_and_refine(self, requirement, own_response, peer_responses):
        return CritiqueResponse(
            agent_id=self.agent_cfg.id,
            decision=Decision.KEEP,
            changed=False,
            solution="SOLUTION: keep\\nREASONING: unchanged",
            reasoning="keep",
            answer_id=None,
        )

    def act(self, request):
        # Hold the iteration open so the test can kill the run *during* variation. An
        # instant worker leaves the worktree in place for ~65 ms, a window a 50 ms poll
        # on a loaded CI runner can miss outright — which is what happened on 3.11.
        time.sleep(float(os.environ.get("FREEMAD_TEST_ACT_SLEEP", "0")))
        return TaskResponse(
            agent_id=self.agent_cfg.id,
            stage=request.stage,
            role=request.role,
            content="no changes this round",
        )


bootstrap.register_builtin_agents()
register_agent("fake_worker", RunnerWorker)

cfg = load_config(path="__CFG__")
orch = EvolveOrchestrator(cfg)
snap = orch.create_run("__GOAL__")
print(snap.run_id, flush=True)
snap = orch.resume(snap.run_id)
final = orch.run(snap.run_id)
print(final.status.value, flush=True)
"""


class TestSupervisorLoop:
    def test_loop_triggers_debate_directions_and_escalation_then_decline(
        self, tmp_path
    ):
        repo = fresh_repo(tmp_path)
        cfg = m2_config(
            repo,
            tmp_path,
            stop={
                "max_iterations": 30,
                "max_wall_clock_minutes": 10,
                "target": [{"component": "ops_per_sec", "op": ">=", "value": 10**12}],
            },
        )
        orch = build(cfg, [])
        snap = orch.create_run("impossible")
        snap = orch.resume(snap.run_id)
        snap = orch.step(snap.run_id)  # baseline -> iteration 1

        # Worker produces no changes each round: WORKER_FAILED, stable signature.
        # Detection ignores evidence from before the last intervention (evolve.md
        # section 3, "reset counters after intervention"), so each escalation step needs
        # a fresh window rather than re-firing on the same records.
        for _ in range(20):
            snap = orch.step(snap.run_id)
            if snap.status == EvolveRunStatus.WAITING_FOR_HUMAN:
                break

        events = orch._store.list_events(snap.run_id)
        kinds = [e.kind for e in events]
        assert EvolveEventKind.SUPERVISOR_TRIGGERED in kinds, [k.value for k in kinds]
        assert EvolveEventKind.SUPERVISOR_DIRECTIONS in kinds
        dirs_event = next(
            e for e in events if e.kind == EvolveEventKind.SUPERVISOR_DIRECTIONS
        )
        assert len(dirs_event.payload["directions"]) == 3
        assert snap.status == EvolveRunStatus.WAITING_FOR_HUMAN
        escalated = next(e for e in events if e.kind == EvolveEventKind.HUMAN_ESCALATED)
        question = escalated.payload["question"]
        assert "Current best" in question and "interventions failed" in question

        final = orch.decline(snap.run_id)
        assert final.status == EvolveRunStatus.STOPPED
        assert final.stop_reason == EvolveStopReason.HUMAN_DECLINED.value

    def test_human_answer_injects_directive_and_resumes(self, tmp_path):
        repo = fresh_repo(tmp_path)
        cfg = m2_config(repo, tmp_path)
        orch = build(cfg, [])
        snap = orch.create_run("g")
        orch.resume(snap.run_id)
        snap = orch.step(snap.run_id)
        for _ in range(20):
            snap = orch.step(snap.run_id)
            if snap.status == EvolveRunStatus.WAITING_FOR_HUMAN:
                break
        assert snap.status == EvolveRunStatus.WAITING_FOR_HUMAN
        answered = orch.answer(snap.run_id, "try closed form via arithmetic series")
        assert answered.status == EvolveRunStatus.RUNNING
        state = orch._state_for(snap.run_id)
        assert any(d.source_ref == "human" for d in state.directives)

    def test_intervention_failure_does_not_halt_run(self, tmp_path, monkeypatch):
        from freemad.evolve import supervisor as sup_mod

        repo = fresh_repo(tmp_path)
        cfg = m2_config(repo, tmp_path)
        orch = build(cfg, [])
        snap = orch.create_run("g")
        orch.resume(snap.run_id)
        orch.step(snap.run_id)
        monkeypatch.setattr(
            sup_mod.Supervisor,
            "intervene",
            lambda self, **kw: sup_mod.InterventionResult(
                directives=(),
                transcript_ref=None,
                error="debate exploded",
            ),
        )
        for _ in range(4):
            snap = orch.step(snap.run_id)
            assert snap.status != EvolveRunStatus.FAILED


class TestPauseResume:
    def test_pause_from_within_act_stops_between_iterations(self, tmp_path):
        repo = fresh_repo(tmp_path)
        cfg = m2_config(repo, tmp_path)
        fast_impl = "def total(n: int) -> int:\n    return n * (n + 1) // 2\n"
        orch = EvolveOrchestrator(cfg)
        holder: dict = {}

        class PausingAgent(SupervisedAgent):
            def act(self, request):  # type: ignore[no-untyped-def]
                response = super().act(request)
                orch.pause(holder["run_id"])
                return response

        orch._resolve_agent = (  # type: ignore[method-assign]
            lambda: PausingAgent(cfg, cfg.agents[0], [fast_impl])
        )
        snap = orch.create_run("pause me")
        holder["run_id"] = snap.run_id
        orch.resume(snap.run_id)
        orch.step(snap.run_id)  # baseline
        final = orch.run(snap.run_id)
        assert final.status == EvolveRunStatus.PAUSED
        resumed = orch.resume(snap.run_id)
        final2 = orch.run(resumed.run_id)
        assert final2.status in {EvolveRunStatus.COMPLETED, EvolveRunStatus.PAUSED}

    def test_readonly_store_accessible_while_writer_live(self, tmp_path):
        repo = fresh_repo(tmp_path)
        db = str(tmp_path / "evolve.db")
        cfg = m2_config(repo, tmp_path)
        cfg = replace(cfg, evolve=replace(cfg.evolve, store_path=db))
        orch = EvolveOrchestrator(cfg)
        seen = {"read": False}

        class ReadingAgent(SupervisedAgent):
            def act(self, request):  # type: ignore[no-untyped-def]
                reader = EvolveStore(db, read_only=True)
                live = reader.get_run(holder["run_id"])
                events = reader.list_events(holder["run_id"])
                reader.close()
                seen["read"] = live is not None and len(events) > 0
                return super().act(request)

        holder: dict = {}
        orch._resolve_agent = (  # type: ignore[method-assign]
            lambda: ReadingAgent(cfg, cfg.agents[0], [None])
        )
        snap = orch.create_run("concurrent")
        holder["run_id"] = snap.run_id
        orch.resume(snap.run_id)
        orch.step(snap.run_id)
        orch.step(snap.run_id)
        assert seen["read"]


class TestStopReasons:
    """Note what this proves: the *mapping* from reason to status, not the trigger.

    `EvolveStopReason.BUDGET` has no trigger at all. Per `evolve.md` section 2.2 cost is
    enforced "only when all variation agents report cost"; no adapter reports cost, so
    `evolve validate` warns and wall clock is the effective budget. BUDGET stays in the
    enum as reserved, and is listed here only so the mapping stays total.
    """

    @pytest.mark.parametrize(
        "reason",
        [
            EvolveStopReason.MANUAL,
            EvolveStopReason.BUDGET,
            EvolveStopReason.WALL_CLOCK,
            EvolveStopReason.MAX_ITERATIONS,
            EvolveStopReason.HUMAN_DECLINED,
            EvolveStopReason.FATAL_ERROR,
        ],
    )
    def test_every_stop_reason_maps_to_stopped_or_failed(self, tmp_path, reason):
        repo = fresh_repo(tmp_path)
        cfg = m2_config(repo, tmp_path)
        orch = build(cfg, [])
        snap = orch.create_run(f"g-{reason.value}")
        final = orch.stop(snap.run_id, reason)
        expected_status = (
            EvolveRunStatus.FAILED
            if reason == EvolveStopReason.FATAL_ERROR
            else EvolveRunStatus.STOPPED
        )
        assert final.status == expected_status
        assert final.stop_reason == reason.value

    def test_budget_is_reserved_and_never_produced(self):
        """If something starts emitting BUDGET, this test should be replaced by a real one."""
        sources = [
            Path("freemad/evolve/orchestrator.py").read_text(),
            Path("freemad/cli.py").read_text(),
        ]
        assert not any(
            "EvolveStopReason.BUDGET" in text for text in sources
        ), "BUDGET now has a trigger; exercise it end to end instead of asserting the mapping"

    def test_target_reached_is_completed(self) -> None:
        pytest.skip(
            "covered by M1: test_improvement_committed_tagged_branch_advanced_target_reached"
        )


class TestSigkillResume:
    def _run_runner(
        self, script_text: str, project_root: Path, log_dir: Path, env_extra: dict
    ):
        env = dict(os.environ)
        env["PYTHONPATH"] = str(project_root) + os.pathsep + env.get("PYTHONPATH", "")
        env.update(env_extra)
        # Files, not pipes. A pipe nobody drains stalls the runner once it fills, and a
        # pipe nobody reads leaves no trace of why the runner stopped where it did — CI
        # produced exactly that: "worktree never appeared" and nothing else to go on.
        with (
            open(log_dir / "runner.stdout", "w") as out,
            open(log_dir / "runner.stderr", "w") as err,
        ):
            return subprocess.Popen(
                [sys.executable, "-u", "-c", script_text],
                stdout=out,
                stderr=err,
                env=env,
            )

    @staticmethod
    def _wait_for(predicate: Callable[[], bool], timeout: float) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return predicate()

    @staticmethod
    def _diagnosis(
        proc: subprocess.Popen[bytes], log_dir: Path, store_path: str, run_id: str
    ) -> str:
        """What the runner was doing when the test gave up on it."""
        state = "still running" if proc.poll() is None else f"exited {proc.returncode}"
        parts = [f"runner {state}"]
        for name in ("runner.stdout", "runner.stderr"):
            text = (log_dir / name).read_text().strip()
            parts.append(f"{name}: {text[-1500:] or '<empty>'}")
        if run_id:
            store = EvolveStore(Path(store_path))
            try:
                trail = [
                    f"{e.iteration}:{e.kind.value}" for e in store.list_events(run_id)
                ]
            finally:
                store.close()
            parts.append("events: " + (", ".join(trail) or "<none>"))
        return "\n".join(parts)

    def test_kill9_mid_variation_costs_at_most_one_iteration(self, tmp_path):
        project_root = Path(__file__).resolve().parents[3]
        repo = fresh_repo(tmp_path)
        cfg = m2_config(
            repo,
            tmp_path,
            stop={
                "max_iterations": 5,
                "max_wall_clock_minutes": 10,
                "target": [{"component": "ops_per_sec", "op": ">=", "value": 10**12}],
            },
        )

        slow_cfg = replace(
            cfg, agents=[replace(cfg.agents[0], timeout=120.0)] + list(cfg.agents[1:])
        )

        runner_cfg = str(tmp_path / "runner.json")
        from freemad.config import to_dict

        (tmp_path / "runner.json").write_text(json.dumps(to_dict(slow_cfg)))

        script = (
            RUNNER.replace("__PROJECT__", str(project_root))
            .replace("__CFG__", runner_cfg)
            .replace("__GOAL__", "kill test goal")
        )
        log_dir = tmp_path / "runner_logs"
        log_dir.mkdir()
        # The worker holds each variation open for a minute (the agent timeout is two), so
        # the kill below lands inside iteration 1, not after it.
        proc = self._run_runner(
            script, project_root, log_dir, {"FREEMAD_TEST_ACT_SLEEP": "60"}
        )
        store_path = slow_cfg.evolve.store_path

        def first_line() -> str:
            lines = (log_dir / "runner.stdout").read_text().splitlines()
            return lines[0].strip() if lines else ""

        try:
            # Bounded: a readline() on the pipe blocked for as long as the runner stayed
            # silent, which is forever if it never got as far as printing.
            assert self._wait_for(lambda: bool(first_line()), 30), (
                "runner did not report run id\n"
                + self._diagnosis(proc, log_dir, store_path, "")
            )
            run_id_line = first_line()

            # Wait until the worker's variation phase started (iteration worktree
            # exists). The baseline is judged first — two stages, 60s timeout each — so
            # the bound covers a slow CI runner doing that, not just a quick local one.
            wt = repo / ".freemad" / "evolve" / "worktrees" / run_id_line / "it1"
            assert self._wait_for(wt.exists, 180), (
                "variation worktree never appeared\n"
                + self._diagnosis(proc, log_dir, store_path, run_id_line)
            )
        finally:
            # The point of the test when the waits succeed; cleanup when they do not.
            if proc.poll() is None:
                os.kill(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)

        # Fresh orchestrator resumes from persisted events only.
        orch2 = EvolveOrchestrator(load_config(path=runner_cfg))
        records_before = orch2._rebuild_records(run_id_line)
        snap = orch2.resume(run_id_line)
        assert snap.status == EvolveRunStatus.RUNNING
        final = orch2.run(run_id_line)
        records_after = orch2._rebuild_records(run_id_line)
        # Terminal-or-parked: never a crash; the killed iteration is redone.
        assert final.status in {
            EvolveRunStatus.STOPPED,
            EvolveRunStatus.COMPLETED,
            EvolveRunStatus.WAITING_FOR_HUMAN,
        }
        iterations = sorted(r.iteration for r in records_after)
        assert iterations == list(
            range(min(iterations), max(iterations) + 1)
        ), "no iteration gap may remain after resume"
        assert max(iterations) <= len(records_before) + 1 + 6
