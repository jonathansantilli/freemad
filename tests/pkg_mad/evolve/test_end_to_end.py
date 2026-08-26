"""End-to-end evolve runs through the REAL agent adapter — no substituted Python class.

Every other evolve test replaces the agent with a Python object (`register_agent` plus a
`_resolve_agent` monkeypatch). That skips everything between the orchestrator and the
worker: `AgentFactory`, `_ensure_allowed`, the subprocess spawn, the task prompt, and the
JSON response parse. Config wiring is therefore invisible to those tests — which is how
all three shipped examples came to be unrunnable with a real agent while the suite was
green.

These tests drive the loop from a config file on disk, through `CLIAdapter`, into a stub
*executable* (`bin/evolve_stub_agent.py`). The only thing not real is the model.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from freemad.config import ConfigError, load_config
from freemad.evolve.orchestrator import EvolveOrchestrator
from freemad.types import EvolveEventKind, EvolveRunStatus, EvolveStopReason

PROJECT_ROOT = Path(__file__).resolve().parents[3]
STUB = PROJECT_ROOT / "bin" / "evolve_stub_agent.py"

SLOW = "def total(n: int) -> int:\n    s = 0\n    for i in range(n + 1):\n        s += i\n    return s\n"
FAST = "def total(n: int) -> int:\n    return n * (n + 1) // 2\n"
BROKEN = "def total(n: int) -> int:\n    return n * (n + 1  # syntax error\n"

TESTS = (
    "from impl import total\n\n\n"
    "def test_known_values():\n"
    "    assert total(0) == 0\n"
    "    assert total(10) == 55\n"
)

BENCH = (
    "import json, time\n"
    "from impl import total\n\n"
    "calls, start = 0, time.perf_counter()\n"
    "while time.perf_counter() < start + 0.15:\n"
    "    total(2000)\n"
    "    calls += 1\n"
    "elapsed = time.perf_counter() - start\n"
    'print(json.dumps({"components": {"ops_per_sec": round(calls / elapsed, 2)}}))\n'
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


@pytest.fixture()
def wired(tmp_path):
    """A seed repo plus a real config file wired to the stub executable."""
    repo = tmp_path / "repo"
    (repo / "tests").mkdir(parents=True)
    (repo / "impl.py").write_text(SLOW)
    (repo / "tests" / "test_impl.py").write_text(TESTS)
    (repo / "bench.py").write_text(BENCH)
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")

    cfg_path = tmp_path / "evolve.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "agents": [
                    {
                        "id": "worker",
                        "type": "claude_code",
                        # A real executable, resolved and spawned by CLIAdapter.
                        "cli_command": f"{sys.executable} {STUB}",
                        "timeout": 60,
                    },
                    {
                        "id": "peer",
                        "type": "openai_codex",
                        "cli_command": f"{sys.executable} {STUB}",
                        "enabled": False,
                    },
                ],
                # The stub is python, so the allowlist has to say so — the check that
                # `endurance.yaml` was silently failing.
                "security": {
                    "cli_allowed_commands": [sys.executable],
                    "cli_timeout_ms": 60000,
                },
                "evolve": {
                    "repo_path": str(repo),
                    "store_path": str(tmp_path / "state" / "evolve.db"),
                    "variation": {"kind": "single_agent", "agent_id": "worker"},
                    "judge": {
                        "stages": [
                            {
                                "name": "tests",
                                "command": f"{sys.executable} -m pytest tests -q",
                                "timeout_sec": 120,
                            },
                            {
                                "name": "bench",
                                "command": f"{sys.executable} bench.py",
                                "timeout_sec": 120,
                                "parse": "json_stdout",
                                "provides": ["ops_per_sec"],
                            },
                        ],
                        "gate": [{"component": "ops_per_sec", "op": ">", "value": 0}],
                        "comparator": [
                            {
                                "component": "ops_per_sec",
                                "direction": "maximize",
                                "epsilon": 5.0,
                            }
                        ],
                        "protected_paths": ["bench.py", "tests/"],
                    },
                    "stop": {"max_iterations": 4, "max_wall_clock_minutes": 10},
                },
            }
        )
    )
    return repo, cfg_path, tmp_path


def _script(tmp_path: Path, steps: list[dict]) -> None:
    """Point the stub at a per-iteration plan."""
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"steps": steps}))
    os.environ["EVOLVE_STUB_PLAN"] = str(plan)
    os.environ["EVOLVE_STUB_STATE"] = str(tmp_path / "stub.count")


@pytest.fixture(autouse=True)
def _clean_stub_env():
    yield
    for key in ("EVOLVE_STUB_PLAN", "EVOLVE_STUB_STATE", "EVOLVE_STUB_AGENT_ID"):
        os.environ.pop(key, None)


class TestRealAdapterEndToEnd:
    def test_a_full_run_commits_through_the_real_adapter(self, wired):
        repo, cfg_path, tmp_path = wired
        _script(tmp_path, [{"impl.py": FAST}])

        cfg = load_config(path=cfg_path)
        orch = EvolveOrchestrator(cfg)
        try:
            snap = orch.create_run("make total fast")
            snap = orch.resume(snap.run_id)
            final = orch.run(snap.run_id)
            events = orch._store.list_events(snap.run_id)
        finally:
            orch.close()

        committed = [e for e in events if e.kind == EvolveEventKind.CANDIDATE_COMMITTED]
        assert committed, "the stub's edit must reach the lineage through CLIAdapter"
        assert final.best_sha == committed[-1].payload["sha"]

        # The commit is real: the accepted content is in git, under the run branch.
        blob = subprocess.run(
            ["git", "show", f"{final.best_sha}:impl.py"],
            cwd=str(repo),
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        assert "n * (n + 1) // 2" in blob

    def test_the_worker_actually_ran_as_a_subprocess(self, wired):
        """Proven by state only the stub process could have written."""
        repo, cfg_path, tmp_path = wired
        _script(tmp_path, [{"impl.py": FAST}])

        cfg = load_config(path=cfg_path)
        orch = EvolveOrchestrator(cfg)
        try:
            snap = orch.create_run("g")
            snap = orch.resume(snap.run_id)
            orch.step(snap.run_id)  # baseline — no agent call
            assert not (
                tmp_path / "stub.count"
            ).exists(), "baseline must not call the worker"
            orch.step(snap.run_id)  # iteration 1 — spawns the stub
        finally:
            orch.close()

        assert (
            tmp_path / "stub.count"
        ).read_text() == "1", "exactly one act() subprocess"

    def test_the_self_report_survives_the_round_trip(self, wired):
        """Prompt -> subprocess -> JSON -> parse -> extraction, end to end."""
        repo, cfg_path, tmp_path = wired
        _script(tmp_path, [{"impl.py": FAST}])

        cfg = load_config(path=cfg_path)
        orch = EvolveOrchestrator(cfg)
        try:
            snap = orch.create_run("g")
            snap = orch.resume(snap.run_id)
            orch.step(snap.run_id)
            orch.step(snap.run_id)
            produced = [
                e
                for e in orch._store.list_events(snap.run_id)
                if e.kind == EvolveEventKind.VARIATION_PRODUCED
            ][-1]
        finally:
            orch.close()

        assert produced.payload["produced_changes"] is True
        # Only the trailing SELF-REPORT survives, not the whole reply.
        assert produced.payload["self_report"].startswith("wrote impl.py")
        assert produced.payload["agent_ids"] == ["worker"]

    def test_a_broken_edit_is_rejected_and_the_run_continues(self, wired):
        repo, cfg_path, tmp_path = wired
        _script(tmp_path, [{"impl.py": BROKEN}, {"impl.py": FAST}])

        cfg = load_config(path=cfg_path)
        orch = EvolveOrchestrator(cfg)
        try:
            snap = orch.create_run("g")
            snap = orch.resume(snap.run_id)
            final = orch.run(snap.run_id)
            events = orch._store.list_events(snap.run_id)
        finally:
            orch.close()

        rejected = [e for e in events if e.kind == EvolveEventKind.CANDIDATE_REJECTED]
        committed = [e for e in events if e.kind == EvolveEventKind.CANDIDATE_COMMITTED]
        assert rejected, "the syntax error must fail the tests stage"
        assert committed, "and the run must carry on to the good edit"
        assert final.status in {EvolveRunStatus.STOPPED, EvolveRunStatus.COMPLETED}

    def test_a_silent_worker_is_reported_as_no_changes(self, wired):
        """The stub runs out of plan, so it writes nothing — a real empty act()."""
        repo, cfg_path, tmp_path = wired
        _script(tmp_path, [])

        cfg = load_config(path=cfg_path)
        orch = EvolveOrchestrator(cfg)
        try:
            snap = orch.create_run("g")
            snap = orch.resume(snap.run_id)
            final = orch.run(snap.run_id)
            events = orch._store.list_events(snap.run_id)
        finally:
            orch.close()

        rejected = [e for e in events if e.kind == EvolveEventKind.CANDIDATE_REJECTED]
        assert rejected and all(
            e.payload["failure_signature"] == "no changes produced" for e in rejected
        )
        assert final.stop_reason == EvolveStopReason.MAX_ITERATIONS.value


class TestConfigWiringIsEnforcedAtRunCreation:
    """The two failures that shipped, caught where they would actually bite."""

    def _broken(self, wired, mutate):
        _repo, cfg_path, _tmp = wired
        raw = yaml.safe_load(cfg_path.read_text())
        mutate(raw)
        cfg_path.write_text(yaml.safe_dump(raw))
        return load_config(path=cfg_path)

    def test_missing_cli_command_fails_the_run_not_every_iteration(self, wired):
        def drop(raw):
            raw["agents"][0].pop("cli_command")

        cfg = self._broken(wired, drop)
        orch = EvolveOrchestrator(cfg)
        try:
            with pytest.raises(ConfigError):
                orch.create_run("g")
        finally:
            orch.close()

    def test_a_non_allowlisted_executable_is_caught(self, wired):
        """`endurance.yaml` named `python`, which the default allowlist refuses."""

        def narrow(raw):
            raw["security"]["cli_allowed_commands"] = ["claude", "codex"]

        cfg = self._broken(wired, narrow)
        orch = EvolveOrchestrator(cfg)
        try:
            with pytest.raises(ConfigError, match="cli_allowed_commands refuses"):
                orch.create_run("g")
        finally:
            orch.close()
