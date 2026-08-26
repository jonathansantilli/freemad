from __future__ import annotations

import sys
from pathlib import Path

from freemad.config import load_config
from freemad.evolve.orchestrator import EvolveOrchestrator
from freemad.types import EvolveEventKind, EvolveRunStatus, IterationOutcome
from tests.pkg_mad.evolve.test_m2_supervisor import SupervisedAgent, fresh_repo


def debate_config(repo: Path, tmp_path: Path):
    from freemad.agents.registry import register_agent

    register_agent("fake_worker", SupervisedAgent)
    return load_config(
        overrides={
            "agents": [
                {"id": "w", "type": "fake_worker"},
                {"id": "d1", "type": "fake_worker"},
                {"id": "d2", "type": "fake_worker"},
            ],
            "evolve": {
                "repo_path": str(repo),
                "store_path": str(tmp_path / "evolve.db"),
                "variation": {"kind": "debate", "debate_rounds": 1},
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


FAST_IMPL = "def total(n: int) -> int:\n    return n * (n + 1) // 2\n"


class DebaterImplementer(SupervisedAgent):
    """Debaters propose the plan; the origin agent implements it on mandate."""

    def act(self, request):  # type: ignore[no-untyped-def]
        from freemad.tasks.models import FileWrite

        if "Implement EXACTLY your winning proposal" in request.goal:
            writes: tuple[FileWrite, ...] = (
                FileWrite(path="impl.py", content=FAST_IMPL),
            )
        else:
            writes = ()
        response = super().act(request)
        return type(response)(
            agent_id=response.agent_id,
            stage=response.stage,
            role=response.role,
            content="implemented the winning plan",
            commands=response.commands,
            findings=response.findings,
            artifact_ids=response.artifact_ids,
            work_items=response.work_items,
            writes=writes,
            sources=response.sources,
        )


def test_debate_variation_end_to_end_reaches_target(tmp_path, monkeypatch):
    repo = fresh_repo(tmp_path)
    cfg = debate_config(repo, tmp_path)

    from freemad.agents.factory import AgentFactory

    agents = {a.id: DebaterImplementer(cfg, a, []) for a in cfg.agents}
    monkeypatch.setattr(AgentFactory, "build_all", lambda self: dict(agents))

    orch = EvolveOrchestrator(cfg)
    snap = orch.create_run("make total fast via debate")
    orch.resume(snap.run_id)
    final = orch.run(snap.run_id)

    assert final.status == EvolveRunStatus.COMPLETED
    assert final.stop_reason == "target_reached"

    events = orch._store.list_events(final.run_id)
    produced = [e for e in events if e.kind == EvolveEventKind.VARIATION_PRODUCED]
    assert produced, "debate variation must emit VARIATION_PRODUCED"
    assert produced[0].payload["kind"] == "debate"
    transcript_ref = produced[0].payload.get("transcript_ref")
    assert transcript_ref and Path(transcript_ref).exists()

    committed = [e for e in events if e.kind == EvolveEventKind.CANDIDATE_COMMITTED]
    assert committed and committed[0].iteration == 1
    record = orch._state_for(final.run_id).records[0]
    assert record.outcome == IterationOutcome.COMMITTED
    assert record.kind.value == "debate"


def test_comparison_harness_produces_table(tmp_path):
    harness_dir = Path(__file__).resolve().parents[3] / "examples" / "evolve_toy"
    sys.path.insert(0, str(harness_dir))
    try:
        import compare_operators as harness

        rows = harness.run_comparison(trials=1)
    finally:
        sys.path.remove(str(harness_dir))

    kinds = {r["operator"] for r in rows}
    assert kinds == {"single_agent", "debate"}
    for row in rows:
        assert row["status"] in {"completed", "stopped"}
        assert row["events"] > 0
    table = harness.render_table(rows)
    assert "| operator |" in table
    # The measurement must be reproducible byte-identically from the rows alone.
    assert table == harness.render_table(rows)
