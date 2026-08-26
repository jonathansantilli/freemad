"""Comparison harness: single-agent vs debate variation on the toy problem.

Runs the toy optimization N times per operator with deterministic scripted
agents (no LLMs, no network) and reports iterations-to-target, commit rate,
and wall time purely from the persisted event logs.

Usage:
    python compare_operators.py [--trials N]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from freemad.agents.base import Agent, AgentResponse, CritiqueResponse  # noqa: E402
from freemad.agents.registry import register_agent  # noqa: E402
from freemad.config import load_config  # noqa: E402
from freemad.evolve.orchestrator import EvolveOrchestrator  # noqa: E402
from freemad.tasks.models import TaskRequest, TaskResponse  # noqa: E402
from freemad.types import Decision, EvolveEventKind  # noqa: E402


SLOW_IMPL = (
    "import time\n\n\ndef total(n: int) -> int:\n"
    "    s = 0\n    for i in range(n + 1):\n        s += i\n"
    "        time.sleep(0.000005)\n    return s\n"
)
FAST_IMPL = "def total(n: int) -> int:\n    return n * (n + 1) // 2\n"
TESTS_FILE = (
    "from impl import total\n\n\ndef test_known():\n    assert total(10) == 55\n"
)
BENCH_FILE = (
    "import json, time\nfrom impl import total\n\n\n"
    "def ops_per_sec() -> float:\n"
    "    calls = 0\n    start = time.perf_counter()\n"
    "    deadline = start + 0.15\n    while time.perf_counter() < deadline:\n"
    "        total(30)\n        calls += 1\n"
    "    elapsed = time.perf_counter() - start\n"
    "    return calls / elapsed if elapsed > 0 else 0.0\n\n\n"
    'if __name__ == "__main__":\n'
    '    print(json.dumps({"components": {"ops_per_sec": round(ops_per_sec(), 2)}}))\n'
)

PLAN_TEXT = (
    "SOLUTION: Replace the loop in impl.py with the closed-form arithmetic "
    "series n*(n+1)//2. Keep the signature identical.\nREASONING: obvious win"
)


class HarnessWorker(Agent):
    """Deterministic stand-in for both debaters and implementers."""

    def generate(self, requirement: str) -> AgentResponse:
        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution=PLAN_TEXT,
            reasoning="canned",
            answer_id=None,
        )

    def critique_and_refine(
        self, requirement: str, own_response: str, peer_responses: List[str]
    ) -> CritiqueResponse:
        return CritiqueResponse(
            agent_id=self.agent_cfg.id,
            decision=Decision.KEEP,
            changed=False,
            solution="SOLUTION: keep\nREASONING: unchanged",
            reasoning="keep",
            answer_id=None,
        )

    def act(self, request: TaskRequest) -> TaskResponse:
        from freemad.tasks.models import FileWrite

        mandate = "Implement EXACTLY your winning proposal"
        single_mode = "evolutionary optimization loop" in request.goal
        if mandate in request.goal or single_mode:
            writes = (FileWrite(path="impl.py", content=FAST_IMPL),)
        else:
            writes = ()
        return TaskResponse(
            agent_id=self.agent_cfg.id,
            stage=request.stage,
            role=request.role,
            content="applied closed-form sum",
            writes=writes,
        )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=str(repo), check=True, capture_output=True)


def make_repo(root: Path) -> Path:
    repo = root / f"repo-{uuid.uuid4().hex[:8]}"
    repo.mkdir(parents=True)
    (repo / "impl.py").write_text(SLOW_IMPL)
    (repo / "tests").mkdir()
    (repo / "tests" / "test_impl.py").write_text(TESTS_FILE)
    (repo / "bench.py").write_text(BENCH_FILE)
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=h", "-c", "user.email=h@h", "add", "-A")
    _git(repo, "-c", "user.name=h", "-c", "user.email=h@h", "commit", "-qm", "seed")
    return repo


def make_config(repo: Path, store_path: Path, kind: str):
    return load_config(
        overrides={
            "agents": [
                {"id": "w", "type": "harness_worker"},
                {"id": "d1", "type": "harness_worker"},
                {"id": "d2", "type": "harness_worker"},
            ],
            "evolve": {
                "repo_path": str(repo),
                "store_path": str(store_path),
                "variation": {"kind": kind, "agent_id": "w"},
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
                        {
                            "component": "ops_per_sec",
                            "direction": "maximize",
                            "epsilon": 1.0,
                        }
                    ],
                    "protected_paths": ["bench.py", "tests/"],
                },
                "stop": {
                    "max_iterations": 5,
                    "max_wall_clock_minutes": 10,
                    "target": [{"component": "ops_per_sec", "op": ">=", "value": 5000}],
                },
            },
        }
    )


def run_trial(kind: str, workspace: Path) -> Dict[str, object]:
    repo = make_repo(workspace)
    store_path = workspace / f"{kind}-{uuid.uuid4().hex[:8]}.db"
    cfg = make_config(repo, store_path, kind)
    orch = EvolveOrchestrator(cfg)
    started = time.perf_counter()
    snap = orch.create_run("make total as fast as possible")
    snap = orch.resume(snap.run_id)
    final = orch.run(snap.run_id)
    elapsed = time.perf_counter() - started

    events = orch._store.list_events(snap.run_id)
    commits = [e for e in events if e.kind == EvolveEventKind.CANDIDATE_COMMITTED]
    rejections = [e for e in events if e.kind == EvolveEventKind.CANDIDATE_REJECTED]
    iters_to_target = commits[0].iteration if commits else None
    result = {
        "operator": kind,
        "status": final.status.value,
        "iterations_to_target": iters_to_target,
        "commits": len(commits),
        "rejections": len(rejections),
        "wall_seconds": round(elapsed, 2),
        # evolve.md section 5 asks the harness to report cost. No adapter reports it
        # (section 2.2 says so too), so the column is present and honestly empty rather
        # than silently absent -- wall clock is the effective budget.
        "cost_usd": None,
        "events": len(events),
    }
    orch.close()
    return result


def run_comparison(
    trials: int = 2, workspace: Optional[Path] = None
) -> List[Dict[str, object]]:
    register_agent("harness_worker", HarnessWorker)
    own_workspace = False
    if workspace is None:
        workspace = Path(tempfile.mkdtemp(prefix="evolve-compare-"))
        own_workspace = True
    rows: List[Dict[str, object]] = []
    try:
        for kind in ("single_agent", "debate"):
            for _ in range(trials):
                rows.append(run_trial(kind, workspace))
    finally:
        if own_workspace:
            import shutil

            shutil.rmtree(workspace, ignore_errors=True)
    return rows


def render_table(rows: List[Dict[str, object]]) -> str:
    header = (
        "| operator | status | iters_to_target | commits | rejections "
        "| wall_s | cost_usd | events |"
    )
    sep = "|---|---|---|---|---|---|---|"
    lines = [header, sep]
    for r in rows:
        lines.append(
            f"| {r['operator']} | {r['status']} | {r['iterations_to_target']} "
            f"| {r['commits']} | {r['rejections']} | {r['wall_seconds']} "
            f"| {r['cost_usd'] if r['cost_usd'] is not None else 'n/a'} | {r['events']} |"
        )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Compare evolve variation operators")
    parser.add_argument("--trials", type=int, default=2)
    args = parser.parse_args(argv)
    rows = run_comparison(trials=args.trials)
    print(render_table(rows))
    print(json.dumps(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
