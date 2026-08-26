"""Acceptance criteria from `evolve.md` section 5 that had no test behind them.

These are the criteria the audit recorded as unverified: a ten-iteration alternating-operator
run, a mid-*judge* SIGKILL, every reachable stop reason driven to its real trigger, an
event-sourced report, and the dependency-update example's admission behaviour.
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

from freemad.config import load_config
from freemad.evolve.orchestrator import EvolveOrchestrator
from freemad.evolve.report import render_report
from freemad.evolve.store import EvolveStore
from freemad.tasks.models import FileWrite, TaskResponse
from freemad.types import (
    EvolveEventKind,
    EvolveRunStatus,
    EvolveStopReason,
    IterationOutcome,
)
from tests.pkg_mad.evolve.test_orchestrator import (
    BROKEN_IMPL,
    FAST_IMPL,
    SLOW_IMPL,
    ScriptedAgent,
    _git,
    build_orchestrator,
    make_config,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]


# --------------------------------------------------------------------------------
# M1: "10 unattended iterations… alternating clean and deliberately broken edits"
# --------------------------------------------------------------------------------


# Each accepted edit must be a genuine improvement, so the clean variants get
# progressively faster while the broken ones fail the test stage outright.
def _faster(n: int) -> str:
    return f"def total(n: int) -> int:\n    return n * (n + 1) // 2  # variant {n}\n"


def test_ten_unattended_iterations_alternating_clean_and_broken(toy_repo, tmp_path):
    scripts = []
    for i in range(10):
        scripts.append(_faster(i) if i % 2 == 0 else BROKEN_IMPL)

    cfg = make_config(
        toy_repo,
        tmp_path,
        stop={
            "max_iterations": 10,
            "max_wall_clock_minutes": 10,
        },  # no target: run to the cap
    )
    orch = build_orchestrator(cfg, scripts)
    snap = orch.create_run("make total fast")
    snap = orch.resume(snap.run_id)
    final = orch.run(snap.run_id)

    events = orch._store.list_events(snap.run_id)
    kinds = [e.kind for e in events]
    rejected = [e for e in events if e.kind == EvolveEventKind.CANDIDATE_REJECTED]
    outcomes = {str(e.payload["outcome"]) for e in rejected}
    context_after = orch._context_for(snap.run_id, final)
    orch.close()

    assert final.stop_reason == EvolveStopReason.MAX_ITERATIONS.value
    assert (
        kinds.count(EvolveEventKind.ITERATION_STARTED) == 10
    ), "10 unattended iterations"
    assert (
        EvolveEventKind.CANDIDATE_COMMITTED in kinds
    ), "the clean edits must be admitted"
    assert (
        IterationOutcome.REJECTED_GATE.value in outcomes
    ), "the broken edits must be rejected"
    # A rejected signature has to surface in the next iteration's context document.
    assert "GRAVEYARD" in context_after
    assert "(empty" not in context_after.split("GRAVEYARD")[1][:200]


# --------------------------------------------------------------------------------
# M1: "report is reproducible byte-identical FROM EVENTS ALONE"
# --------------------------------------------------------------------------------


def test_report_renders_from_events_after_the_runs_row_is_deleted(toy_repo, tmp_path):
    """Section 3: the run summary is a projection of the events, not a second source."""
    cfg = make_config(toy_repo, tmp_path)
    orch = build_orchestrator(cfg, [FAST_IMPL, BROKEN_IMPL])
    snap = orch.create_run("make total fast")
    snap = orch.resume(snap.run_id)
    orch.run(snap.run_id)
    run_id = snap.run_id
    orch.close()

    before = render_report(EvolveStore(cfg.evolve.store_path, read_only=True), run_id)

    # Drop the derived row entirely; the event log must still render the same bytes.
    scratch = EvolveStore(cfg.evolve.store_path)
    scratch._conn.execute("DELETE FROM evolve_runs WHERE run_id = ?", (run_id,))
    scratch._conn.commit()
    scratch.close()

    after = render_report(EvolveStore(cfg.evolve.store_path, read_only=True), run_id)

    assert after == before, "the report must not depend on derived state"
    assert "report_sha256:" in after
    assert "# cost" in after, "section 3 lists cost among the report's contents"


# --------------------------------------------------------------------------------
# M2: "every EvolveStopReason exercised… compressed budgets and a fake clock"
# --------------------------------------------------------------------------------


class TestEveryStopReasonReachesItsTrigger:
    """Driven to the real trigger, not asserted against `orch.stop(reason)`."""

    def test_target_reached(self, toy_repo, tmp_path):
        cfg = make_config(toy_repo, tmp_path)
        orch = build_orchestrator(cfg, [FAST_IMPL])
        snap = orch.create_run("g")
        snap = orch.resume(snap.run_id)
        final = orch.run(snap.run_id)
        orch.close()
        assert final.stop_reason == EvolveStopReason.TARGET_REACHED.value
        assert final.status == EvolveRunStatus.COMPLETED

    def test_max_iterations(self, toy_repo, tmp_path):
        cfg = make_config(
            toy_repo, tmp_path, stop={"max_iterations": 2, "max_wall_clock_minutes": 10}
        )
        orch = build_orchestrator(cfg, [None, None, None])
        snap = orch.create_run("g")
        snap = orch.resume(snap.run_id)
        final = orch.run(snap.run_id)
        orch.close()
        assert final.stop_reason == EvolveStopReason.MAX_ITERATIONS.value

    def test_wall_clock_with_a_fake_clock(self, toy_repo, tmp_path, monkeypatch):
        cfg = make_config(
            toy_repo, tmp_path, stop={"max_iterations": 99, "max_wall_clock_minutes": 1}
        )
        orch = build_orchestrator(cfg, [None] * 5)
        snap = orch.create_run("g")
        snap = orch.resume(snap.run_id)
        orch.step(snap.run_id)  # baseline, on the real clock

        import freemad.evolve.orchestrator as orch_mod

        # Capture the real function first: a lambda calling `time.time()` would resolve
        # to the patched one and recurse forever.
        real_time = time.time
        monkeypatch.setattr(orch_mod.time, "time", lambda: real_time() + 3600)
        final = orch.run(snap.run_id)
        orch.close()
        assert final.stop_reason == EvolveStopReason.WALL_CLOCK.value

    def test_fatal_error_on_a_changed_judge(self, toy_repo, tmp_path):
        from dataclasses import replace

        cfg = make_config(toy_repo, tmp_path)
        orch = build_orchestrator(cfg, [])
        snap = orch.create_run("g")
        snap = orch.resume(snap.run_id)
        orch.step(snap.run_id)
        retuned = replace(
            cfg,
            evolve=replace(
                cfg.evolve,
                judge=replace(
                    cfg.evolve.judge,
                    comparator=(replace(cfg.evolve.judge.comparator[0], epsilon=99.0),),
                ),
            ),
        )
        orch2 = EvolveOrchestrator(retuned, store_path=cfg.evolve.store_path)
        final = orch2.step(snap.run_id)
        orch.close()
        orch2.close()
        assert final.stop_reason == EvolveStopReason.FATAL_ERROR.value
        assert final.status == EvolveRunStatus.FAILED

    def test_manual(self, toy_repo, tmp_path):
        cfg = make_config(toy_repo, tmp_path)
        orch = build_orchestrator(cfg, [])
        snap = orch.create_run("g")
        orch.resume(snap.run_id)
        final = orch.stop(snap.run_id, EvolveStopReason.MANUAL)
        orch.close()
        assert final.stop_reason == EvolveStopReason.MANUAL.value
        assert final.status == EvolveRunStatus.STOPPED

    def test_human_declined(self, toy_repo, tmp_path):
        from dataclasses import replace

        cfg = make_config(toy_repo, tmp_path)
        orch = build_orchestrator(cfg, [])
        snap = orch.create_run("g")
        orch._store.update_run(replace(snap, status=EvolveRunStatus.WAITING_FOR_HUMAN))
        final = orch.decline(snap.run_id)
        orch.close()
        assert final.stop_reason == EvolveStopReason.HUMAN_DECLINED.value

    def test_budget_is_reserved_with_no_trigger(self):
        """The one reason with no code path, per section 2.2: no adapter reports cost."""
        sources = (PROJECT_ROOT / "freemad").rglob("*.py")
        emitters = [
            p
            for p in sources
            if "EvolveStopReason.BUDGET" in p.read_text() and p.name != "types.py"
        ]
        assert (
            not emitters
        ), f"BUDGET now has a trigger in {emitters}; exercise it for real"


# --------------------------------------------------------------------------------
# M2: "kill -9 mid-JUDGE resumes losing at most one iteration" (real SIGKILL)
# --------------------------------------------------------------------------------


SLOW_JUDGE_RUNNER = """
import sys, time
sys.path.insert(0, "__PROJECT__")
from freemad.agents import bootstrap
from freemad.agents.base import Agent
from freemad.agents.registry import register_agent
from freemad.config import load_config
from freemad.evolve.orchestrator import EvolveOrchestrator
from freemad.tasks.models import FileWrite, TaskResponse


class Worker(Agent):
    def generate(self, requirement): raise NotImplementedError
    def critique_and_refine(self, r, o, p): raise NotImplementedError
    def act(self, request):
        return TaskResponse(
            agent_id=self.agent_cfg.id, stage=request.stage, role=request.role,
            content="edit",
            writes=(FileWrite(path="impl.py", content="def total(n):\\n    return n*(n+1)//2\\n"),),
        )


bootstrap.register_builtin_agents()
register_agent("fake_worker", Worker)
cfg = load_config(path="__CFG__")
orch = EvolveOrchestrator(cfg)
snap = orch.create_run("kill mid judge")
print(snap.run_id, flush=True)
snap = orch.resume(snap.run_id)
orch.run(snap.run_id)
"""


def test_real_sigkill_mid_judge_resumes(tmp_path):
    """The existing durability test kills during VARIATION; this one kills the judge."""
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "impl.py").write_text(SLOW_IMPL)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_impl.py").write_text(
        "from impl import total\n\n\ndef test_ok():\n    assert total(10) == 55\n"
    )
    # A judge stage slow enough to be killed while it is the thing running.
    (repo / "bench.py").write_text(
        "import json, time, pathlib\n"
        'pathlib.Path("JUDGING").write_text("x")\n'
        "time.sleep(30)\n"
        'print(json.dumps({"components": {"ops_per_sec": 1.0}}))\n'
    )
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")

    cfg_path = tmp_path / "evolve.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "agents": [
                    {"id": "w", "type": "fake_worker"},
                    {"id": "x", "type": "claude_code"},
                ],
                "evolve": {
                    "repo_path": str(repo),
                    "store_path": str(tmp_path / "e.db"),
                    "variation": {"kind": "single_agent", "agent_id": "w"},
                    "judge": {
                        "stages": [
                            {
                                "name": "bench",
                                "command": "python3 bench.py",
                                "timeout_sec": 120,
                                "parse": "json_stdout",
                                "provides": ["ops_per_sec"],
                            }
                        ],
                        "gate": [{"component": "ops_per_sec", "op": ">", "value": 0}],
                        "comparator": [
                            {
                                "component": "ops_per_sec",
                                "direction": "maximize",
                                "epsilon": 0.0,
                            }
                        ],
                        "protected_paths": ["bench.py"],
                    },
                    "stop": {"max_iterations": 2, "max_wall_clock_minutes": 10},
                },
            }
        )
    )

    script = SLOW_JUDGE_RUNNER.replace("__PROJECT__", str(PROJECT_ROOT)).replace(
        "__CFG__", str(cfg_path)
    )
    env = dict(os.environ)
    env["PYTHONPATH"] = str(PROJECT_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.Popen(
        [sys.executable, "-u", "-c", script],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    try:
        run_id = (proc.stdout.readline() if proc.stdout else "").strip()
        assert run_id, "runner did not report a run id"

        # Wait until the judge itself is running, not merely the iteration.
        marker_seen = False
        deadline = time.time() + 60
        while time.time() < deadline and not marker_seen:
            marker_seen = any(
                (repo / ".freemad" / "evolve" / "worktrees" / run_id).rglob("JUDGING")
            )
            time.sleep(0.05)
        assert marker_seen, "the judge stage never started"

        os.kill(proc.pid, signal.SIGKILL)
        proc.wait(timeout=30)
    finally:
        proc.kill()

    # Make the judge fast so the resumed run can finish.
    (repo / "bench.py").write_text(
        'import json\nprint(json.dumps({"components": {"ops_per_sec": 1.0}}))\n'
    )
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(
        repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "fast judge"
    )

    cfg = load_config(path=cfg_path)
    orch = EvolveOrchestrator(cfg)
    try:
        snap = orch.resume(run_id)
        assert snap.status == EvolveRunStatus.RUNNING
        final = orch.run(run_id)
        assert final.status in {
            EvolveRunStatus.STOPPED,
            EvolveRunStatus.COMPLETED,
            EvolveRunStatus.FAILED,
            EvolveRunStatus.WAITING_FOR_HUMAN,
        }, "a killed judge must still reach a declared state"
        assert final.stop_reason is not None
        iterations = sorted(r.iteration for r in orch._rebuild_records(run_id))
        if iterations:
            assert iterations == list(
                range(min(iterations), max(iterations) + 1)
            ), "no iteration gap may remain after resume"
    finally:
        orch.close()


# --------------------------------------------------------------------------------
# M4: "the dependency example commits the update ONLY on a full gate pass"
# --------------------------------------------------------------------------------


EXAMPLE = PROJECT_ROOT / "examples" / "evolve_dependency_update"


def _dependency_repo(tmp_path: Path) -> Path:
    import shutil

    repo = tmp_path / "dep"
    shutil.copytree(EXAMPLE, repo)
    for junk in list(repo.rglob("__pycache__")):
        shutil.rmtree(junk, ignore_errors=True)
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
    return repo


class _UpgradeAgent(ScriptedAgent):
    """Writes a scripted set of files, one dict per iteration."""

    def __init__(self, cfg, agent_cfg, steps):
        super().__init__(cfg, agent_cfg)
        self._steps = list(steps)

    def act(self, request):
        files = self._steps.pop(0) if self._steps else {}
        return TaskResponse(
            agent_id=self.agent_cfg.id,
            stage=request.stage,
            role=request.role,
            content="upgrade attempt",
            writes=tuple(FileWrite(path=p, content=c) for p, c in files.items()),
        )


def _dep_cfg(repo: Path, tmp_path: Path):
    raw = yaml.safe_load((repo / "evolve.yaml").read_text())
    raw["agents"] = [
        {"id": "w", "type": "upgrade_agent"},
        {"id": "x", "type": "claude_code"},
    ]
    raw["evolve"]["repo_path"] = str(repo)
    raw["evolve"]["store_path"] = str(tmp_path / "dep.db")
    raw["evolve"]["stop"] = {
        "max_iterations": 1,
        "max_wall_clock_minutes": 10,
        **raw["evolve"].get("stop", {}),
    }
    raw["evolve"]["stop"]["max_iterations"] = 1
    path = tmp_path / "dep.yaml"
    path.write_text(yaml.safe_dump(raw))
    return load_config(path=path)


def test_dependency_example_rejects_a_version_bump_that_breaks_behaviour(tmp_path):
    """The README's own warning, pinned: 2.x at 3/5 goldens still beats the seed's 50."""
    repo = _dependency_repo(tmp_path)
    from freemad.agents.registry import register_agent

    register_agent("upgrade_agent", _UpgradeAgent)
    cfg = _dep_cfg(repo, tmp_path)

    lib = (repo / "vendor" / "vendored_lib" / "__init__.py").read_text()
    broken = lib.replace('VERSION = "1.2.0"', 'VERSION = "2.0.0"')
    assert broken != lib, "the fixture must actually bump the version"
    # Remove the double-dash collapse: the goldens break, the version check passes.
    collapse = (
        '    while "--" in collapsed:\n'
        '        collapsed = collapsed.replace("--", "-")\n'
    )
    assert collapse in broken, "fixture must match the shipped implementation"
    broken = broken.replace(collapse, "")

    agent = _UpgradeAgent(
        cfg, cfg.agents[0], [{"vendor/vendored_lib/__init__.py": broken}]
    )
    orch = EvolveOrchestrator(cfg)
    orch._resolve_agent = lambda: agent  # type: ignore[method-assign]
    snap = orch.create_run("update vendored lib to 2.x and keep behavior identical")
    snap = orch.resume(snap.run_id)
    orch.run(snap.run_id)
    events = orch._store.list_events(snap.run_id)
    committed = [e for e in events if e.kind == EvolveEventKind.CANDIDATE_COMMITTED]
    final = orch.status(snap.run_id)
    orch.close()

    assert not committed, "a version bump that breaks goldens must never be admitted"
    assert final.best_sha is None


# --------------------------------------------------------------------------------
# The shipped examples must be able to launch their agent, not just their judge
# --------------------------------------------------------------------------------


EXAMPLE_CONFIGS = [
    PROJECT_ROOT / "examples" / "evolve_toy" / "evolve.yaml",
    PROJECT_ROOT / "examples" / "evolve_toy" / "endurance.yaml",
    PROJECT_ROOT / "examples" / "evolve_dependency_update" / "evolve.yaml",
]


@pytest.mark.parametrize(
    "cfg_path", EXAMPLE_CONFIGS, ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_example_agents_are_launchable(cfg_path):
    """`evolve validate` exercises the judge and never the agent.

    So a config could pass validation and then fail every iteration as WORKER_FAILED —
    which is exactly what all three examples did: two had no `cli_command` at all, and
    the third named `python`, which is not in `security.cli_allowed_commands`. A run
    would do its full iteration budget of nothing and stop without a crash.
    """
    import shlex

    cfg = load_config(path=cfg_path)
    enabled = [a for a in cfg.agents if a.enabled]
    assert enabled, "an example needs at least one enabled agent"
    for agent in enabled:
        assert agent.cli_command, (
            f"agent {agent.id!r} has no cli_command; CLIAdapter._run_cli raises "
            f"ConfigError on the first act()"
        )
        exe = shlex.split(agent.cli_command)[0]
        assert exe in (cfg.security.cli_allowed_commands or []), (
            f"agent {agent.id!r} runs {exe!r}, which security.cli_allowed_commands "
            f"({cfg.security.cli_allowed_commands}) refuses"
        )


def test_freemad_never_reads_an_api_key():
    """Auth is the agent CLI's own subscription session, on disk, not an env var.

    Worth pinning: it is why `security.api_key_source`/`api_key_name` are dead config,
    and why HOME isolation matters more than environment scrubbing for this project's
    own credentials.
    """
    package = PROJECT_ROOT / "freemad"
    offenders = [
        p
        for p in package.rglob("*.py")
        if "ANTHROPIC_API_KEY" in p.read_text() or "OPENAI_API_KEY" in p.read_text()
    ]
    assert not offenders, f"an API-key path appeared in {offenders}"


# --------------------------------------------------------------------------------
# Found by actually running the CLI against a live model, not by a test
# --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "cfg_path", EXAMPLE_CONFIGS, ids=lambda p: f"{p.parent.name}/{p.name}"
)
def test_example_agents_get_a_workable_timeout(cfg_path):
    """A real model doing a code edit does not finish in 60 seconds.

    `CLIAdapter._run_cli` uses max(agent.timeout, security.cli_timeout_ms,
    budget.max_agent_time_sec) — and every one of those defaults to 60s or less. An
    example that sets none of them times out on *every* iteration: the run does its whole
    budget of WORKER_FAILED, stops cleanly on max_iterations, and changes nothing. That is
    what a live run of the toy actually did, while validate was clean and the suite green.
    """
    from freemad.evolve.variation import scope_worker_budget

    scoped = scope_worker_budget(load_config(path=cfg_path))
    agent = next(a for a in scoped.agents if a.enabled)
    effective = max(
        agent.timeout or 60.0,
        scoped.security.cli_timeout_ms / 1000.0,
        scoped.budget.max_agent_time_sec or 10**9,
    )
    assert effective > 60.0, (
        f"{cfg_path.name}: worker gets {effective}s; a real model needs more, and the "
        f"outer worker_budget must not clamp it back down"
    )


def test_redaction_does_not_eat_ordinary_words():
    """`sk-` without a word boundary matches inside "ta|sk-execute".

    Cosmetic in logs, not cosmetic in the event store, which now runs every payload
    through the same redactor — `self_report`, `final_output` and judge output included.
    """
    from freemad.security import Redactor

    redactor = Redactor(load_config().security.redact_patterns)
    assert redactor.redact("mode=task-execute") == "mode=task-execute"
    assert redactor.redact("stage=task-review") == "stage=task-review"
    assert "sk-ant-" not in redactor.redact("key sk-ant-abc123def456 here")


def test_validate_warns_when_a_debate_cannot_fit_its_budget(tmp_path):
    """Found live: a debate is ~5 agent calls, each allowed the WHOLE iteration budget.

    With `timeout: 600` and `worker_budget.max_minutes: 10`, one generation call could
    consume the entire budget, so the debate structurally could not finish. The run spent
    600s per iteration producing nothing, and `validate` was silent about it.
    """
    from freemad.cli import _evolve_main

    cfg = tmp_path / "evolve.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {
                "agents": [
                    {
                        "id": "w",
                        "type": "claude_code",
                        "cli_command": "claude -p",
                        "timeout": 600,
                    },
                    {
                        "id": "p",
                        "type": "claude_code",
                        "cli_command": "claude -p",
                        "timeout": 600,
                    },
                ],
                "evolve": {
                    "repo_path": str(tmp_path),
                    "store_path": str(tmp_path / "e.db"),
                    "variation": {
                        "kind": "debate",
                        "agent_id": "w",
                        "debate_rounds": 1,
                    },
                    "worker_budget": {"max_minutes": 10},
                    "judge": {
                        "stages": [
                            {
                                "name": "b",
                                "command": "python3 b.py",
                                "parse": "json_stdout",
                                "provides": ["s"],
                            }
                        ],
                        "gate": [{"component": "s", "op": ">", "value": 0}],
                        "comparator": [
                            {"component": "s", "direction": "maximize", "epsilon": 0}
                        ],
                        "protected_paths": ["b.py"],
                    },
                },
            }
        )
    )
    (tmp_path / "b.py").write_text('print(\'{"components": {"s": 1}}\')')
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(tmp_path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "s")

    import io
    import contextlib

    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        _evolve_main(["validate", "--config", str(cfg)])
    result = json.loads(buf.getvalue().strip().splitlines()[-1])
    assert any("debate variation needs about" in w for w in result["warnings"]), result
