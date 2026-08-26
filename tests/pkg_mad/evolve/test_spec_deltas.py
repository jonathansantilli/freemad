"""Regressions for the `evolve.md` semantics that were decided but never implemented.

Section references are to `evolve.md` rev. 2.
"""

from __future__ import annotations

import sys

import json
from pathlib import Path

import pytest
import yaml

from freemad.config import ConfigError, load_config
from freemad.evolve.context import ContextInput, generate_context
from freemad.evolve.lineage import Lineage
from freemad.evolve.models import IterationRecord, ScoreVector
from freemad.evolve.orchestrator import EvolveOrchestrator
from freemad.evolve.supervisor import Supervisor, SupervisorFinding
from freemad.evolve.variation import (
    scope_debate_agents,
    scope_debate_budget,
    scope_worker_budget,
    transcript_dir,
)
from freemad.prompts.evolve import (
    SELF_REPORT_MARKER,
    build_implementation_mandate,
    build_worker_requirement,
    extract_self_report,
)
from freemad.types import IterationOutcome, SupervisorCause, VariationKind
from tests.pkg_mad.evolve.test_orchestrator import (
    ScriptedAgent,
    build_orchestrator,
    make_config,
)

JUDGE = {
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
    "comparator": [
        {"component": "ops_per_sec", "direction": "maximize", "epsilon": 1.0}
    ],
    "protected_paths": ["bench.py", "tests/"],
}


# --------------------------------------------------------------------------------
# S1 - section 2.2: the outer worker budget always wins
# --------------------------------------------------------------------------------


def _generous_cfg(toy_repo, tmp_path, minutes: int = 2):
    """Timeouts deliberately far ABOVE the budget.

    The config defaults (`timeout=60.0`, `cli_timeout_ms=60000`) already satisfy a
    one-minute cap, so a test written against them passes with `scope_worker_budget`
    replaced by `return cfg` — it asserts the defaults, not the scoping.
    """
    from dataclasses import replace as dc_replace

    cfg = make_config(toy_repo, tmp_path, worker_budget={"max_minutes": minutes})
    return dc_replace(
        cfg,
        agents=[dc_replace(a, timeout=3600.0) for a in cfg.agents],
        security=dc_replace(cfg.security, cli_timeout_ms=3_600_000),
    )


class TestS1WorkerBudget:
    def test_worker_timeouts_are_capped_at_the_iteration_budget(
        self, toy_repo, tmp_path
    ):
        cfg = _generous_cfg(toy_repo, tmp_path, minutes=2)
        assert all(a.timeout == 3600.0 for a in cfg.agents), "must start above the cap"

        scoped = scope_worker_budget(cfg)

        # The CLI adapter takes the *max* of the two, so both have to come down.
        assert [a.timeout for a in scoped.agents] == [120.0] * len(cfg.agents)
        assert scoped.security.cli_timeout_ms == 120_000

    def test_timeouts_already_under_the_budget_are_untouched(self, toy_repo, tmp_path):
        cfg = make_config(toy_repo, tmp_path, worker_budget={"max_minutes": 30})
        scoped = scope_worker_budget(cfg)
        assert [a.timeout for a in scoped.agents] == [a.timeout for a in cfg.agents]
        assert scoped.security.cli_timeout_ms == cfg.security.cli_timeout_ms

    def test_judge_stage_timeouts_are_left_alone(self, toy_repo, tmp_path):
        """The judge is not the worker; its stages keep their own timeouts."""
        cfg = _generous_cfg(toy_repo, tmp_path, minutes=1)
        scoped = scope_worker_budget(cfg)
        assert [s.timeout_sec for s in scoped.evolve.judge.stages] == [
            s.timeout_sec for s in cfg.evolve.judge.stages
        ]

    def test_inner_debate_guard_is_scoped_to_what_is_left(self, toy_repo, tmp_path):
        cfg = make_config(toy_repo, tmp_path, worker_budget={"max_minutes": 10})
        scoped = scope_debate_budget(cfg, elapsed_sec=540.0)
        assert scoped.budget.max_total_time_sec == pytest.approx(60.0)

    def test_scoping_never_raises_the_debate_budget(self, toy_repo, tmp_path):
        cfg = make_config(toy_repo, tmp_path, worker_budget={"max_minutes": 60})
        scoped = scope_debate_budget(cfg, elapsed_sec=0.0)
        assert scoped.budget.max_total_time_sec == cfg.budget.max_total_time_sec

    def test_a_spent_budget_still_leaves_a_positive_guard(self, toy_repo, tmp_path):
        cfg = make_config(toy_repo, tmp_path, worker_budget={"max_minutes": 1})
        scoped = scope_debate_budget(cfg, elapsed_sec=9_999.0)
        assert scoped.budget.max_total_time_sec == pytest.approx(1.0)


# --------------------------------------------------------------------------------
# S2 - section 2.2: the *judge* is immutable mid-run, not the whole section
# --------------------------------------------------------------------------------


class TestS2ManifestScope:
    def test_budget_knobs_do_not_change_the_fitness_hash(self, toy_repo, tmp_path):
        """Resuming with a longer budget must not be a FATAL_ERROR."""
        base = make_config(toy_repo, tmp_path)
        loosened = make_config(
            toy_repo,
            tmp_path,
            # same target: only the budget knobs move
            stop={
                "max_iterations": 99,
                "max_wall_clock_minutes": 999,
                "target": [{"component": "ops_per_sec", "op": ">=", "value": 5000}],
            },
            context_budget_chars=12345,
        )
        a, b = EvolveOrchestrator(base), EvolveOrchestrator(loosened)
        try:
            assert a.fitness_hash() == b.fitness_hash()
        finally:
            a.close()
            b.close()

    def test_weakening_the_target_does_change_it(self, toy_repo, tmp_path):
        """`stop.target` decides when the run declares success, so it is immutable too."""
        base = make_config(toy_repo, tmp_path)
        easier = make_config(
            toy_repo,
            tmp_path,
            stop={
                "max_iterations": 5,
                "max_wall_clock_minutes": 10,
                "target": [{"component": "ops_per_sec", "op": ">=", "value": 1}],
            },
        )
        a, b = EvolveOrchestrator(base), EvolveOrchestrator(easier)
        try:
            assert a.fitness_hash() != b.fitness_hash()
        finally:
            a.close()
            b.close()

    def test_changing_the_judge_does_change_the_manifest(self, toy_repo, tmp_path):
        base = make_config(toy_repo, tmp_path)
        retuned = make_config(
            toy_repo,
            tmp_path,
            judge={
                **JUDGE,
                "gate": [{"component": "ops_per_sec", "op": ">", "value": 999}],
            },
        )
        a, b = EvolveOrchestrator(base), EvolveOrchestrator(retuned)
        try:
            assert a.fitness_hash() != b.fitness_hash()
        finally:
            a.close()
            b.close()

    def test_the_goal_is_part_of_the_manifest(self, toy_repo, tmp_path):
        orch = EvolveOrchestrator(make_config(toy_repo, tmp_path))
        try:
            assert orch.manifest_hash("goal a") != orch.manifest_hash("goal b")
        finally:
            orch.close()


# --------------------------------------------------------------------------------
# S3 - section 2.2: iteration 0 tags the measured seed v0
# --------------------------------------------------------------------------------


def test_baseline_tags_the_seed_as_v0(toy_repo, tmp_path):
    cfg = make_config(toy_repo, tmp_path)
    orch = build_orchestrator(cfg, [])
    snap = orch.create_run("make total fast")
    snap = orch.resume(snap.run_id)
    orch.step(snap.run_id)
    orch.close()

    lineage = Lineage(cfg, snap.run_id)
    tag = lineage.tag_name(0)
    assert lineage.resolve_ref(tag) == lineage.resolve_ref(
        "HEAD"
    ), "v0 must point at the unmodified seed"


# --------------------------------------------------------------------------------
# S4 - section 3: operators produce a self-report, falling back to final output
# --------------------------------------------------------------------------------


class TestS4SelfReport:
    def test_the_marker_is_asked_for(self):
        assert SELF_REPORT_MARKER in build_worker_requirement("goal", "# GOAL", ())

    def test_only_the_report_is_kept(self):
        reply = (
            "Here is a long rambling explanation of my change.\n"
            "```python\nprint('lots of code')\n```\n"
            f"{SELF_REPORT_MARKER} memoised the inner loop; the bound check still costs 10%."
        )
        report = extract_self_report(reply, 2200)
        assert report == "memoised the inner loop; the bound check still costs 10%."
        assert "rambling" not in report

    def test_the_last_marker_wins(self):
        reply = (
            f"{SELF_REPORT_MARKER} quoting the instruction\nwork\n"
            f"{SELF_REPORT_MARKER} the real one"
        )
        assert extract_self_report(reply, 2200) == "the real one"

    def test_absent_report_falls_back_to_the_output(self):
        assert extract_self_report("no marker anywhere", 2200) == "no marker anywhere"

    def test_empty_report_falls_back_too(self):
        assert extract_self_report(
            f"did a thing\n{SELF_REPORT_MARKER}   ", 2200
        ).startswith("did a thing")

    def test_nothing_at_all_stays_empty(self):
        assert extract_self_report("", 2200) == ""


# --------------------------------------------------------------------------------
# Config surface that used to be validated but never read
# --------------------------------------------------------------------------------


class TestKnowledgePaths:
    def test_contents_are_inlined_when_a_root_is_given(self, tmp_path):
        """Listing paths alone made a real-repo plan debate explore for 300s+ per call.

        The debaters need the code in front of them, size-capped, still marked untrusted.
        """
        (tmp_path / "pkg").mkdir()
        (tmp_path / "pkg" / "hot.py").write_text("def hot():\n    return 42\n")
        (tmp_path / "pkg" / "big.py").write_text(
            "x = 1\n" * 20000
        )  # over the per-file cap
        req = build_worker_requirement("goal", "# GOAL", (), ("pkg",), root=tmp_path)
        assert (
            "def hot():" in req
        ), "the source must be in the prompt, not just its name"
        assert "--- pkg/hot.py ---" in req
        assert (
            "TRUNCATED" in req
        ), "the oversized file must be capped, not dropped or inlined whole"
        assert "untrusted" in req

    def test_names_only_without_a_root(self):
        req = build_worker_requirement("goal", "# GOAL", (), ("pkg/hot.py",))
        assert "pkg/hot.py" in req and "def hot" not in req

    def test_knowledge_paths_reach_the_worker_flagged_as_untrusted(self):
        requirement = build_worker_requirement(
            "goal", "# GOAL", (), knowledge_paths=("docs/api.md", "notes/")
        )
        assert "docs/api.md" in requirement
        assert "notes/" in requirement
        assert "untrusted" in requirement

    def test_the_worker_is_told_not_to_run_git(self):
        """A live run lost two of three iterations to the agent trying to commit.

        `git` is deliberately not allowlisted — a worker with it could rewrite the
        lineage it is being judged on — so the prompt has to say the runtime owns
        version control, or the agent works it out by burning iterations.
        """
        for requirement in (
            build_worker_requirement("goal", "# GOAL", ()),
            build_implementation_mandate("the plan"),
        ):
            assert "Do not run git" in requirement
            assert "runtime" in requirement

    def test_no_knowledge_block_when_none_configured(self):
        """Pinned to the real header, so rewording it cannot make this vacuous."""
        from freemad.prompts.evolve import _knowledge_block

        header = _knowledge_block(("x",)).splitlines()[0]
        assert header not in build_worker_requirement("goal", "# GOAL", ())
        assert header in build_worker_requirement("goal", "# GOAL", (), ("x",))


class TestDebateAgentIds:
    def test_empty_means_every_configured_agent(self, toy_repo, tmp_path):
        cfg = make_config(toy_repo, tmp_path)
        assert scope_debate_agents(cfg).agents == cfg.agents

    def test_named_ids_restrict_the_debate(self, toy_repo, tmp_path):
        cfg = make_config(
            toy_repo,
            tmp_path,
            variation={
                "kind": "debate",
                "agent_id": "w",
                "debate_agent_ids": ["w", "x"],
                "debate_rounds": 1,
            },
        )
        assert [a.id for a in scope_debate_agents(cfg).agents] == ["w", "x"]

    def test_a_single_debater_is_rejected_at_load(self, toy_repo, tmp_path):
        with pytest.raises(ConfigError, match="at least 2 agents"):
            make_config(
                toy_repo,
                tmp_path,
                variation={
                    "kind": "debate",
                    "debate_agent_ids": ["w"],
                    "debate_rounds": 1,
                },
            )

    def test_duplicates_are_rejected_at_load(self, toy_repo, tmp_path):
        with pytest.raises(ConfigError, match="unique"):
            make_config(
                toy_repo,
                tmp_path,
                variation={
                    "kind": "debate",
                    "debate_agent_ids": ["w", "w"],
                    "debate_rounds": 1,
                },
            )


DIRECTIONS = json.dumps(
    {"directions": ["vectorize the loop", "cache partial sums", "use a lookup table"]}
)


class _DirectionsAgent(ScriptedAgent):
    """Answers a supervisor prompt with canned directions."""

    def generate(self, requirement: str):
        from freemad.agents.base import AgentResponse, Metadata

        return AgentResponse(
            agent_id=self.agent_cfg.id,
            solution=f"SOLUTION: {DIRECTIONS}\nREASONING: canned",
            reasoning="canned",
            answer_id=None,
            metadata=Metadata(),
        )


class TestSingleAgentIntervention:
    def test_single_agent_mode_never_runs_a_debate(self, toy_repo, tmp_path):
        cfg = make_config(
            toy_repo, tmp_path, supervisor={"intervention": "single_agent"}
        )
        supervisor = Supervisor(cfg)

        def _no_debates(requirement):  # pragma: no cover - asserts it is never reached
            raise AssertionError("single_agent intervention must not run a debate")

        supervisor._run_debate = _no_debates  # type: ignore[method-assign]
        supervisor._ask_one_agent = lambda requirement: {  # type: ignore[method-assign]
            "final_solution": DIRECTIONS,
            "transcript": [],
        }

        result = supervisor.intervene(
            snapshot_goal="make it fast",
            records=(),
            best_score=None,
            baseline_score=None,
            best_sha=None,
            finding=SupervisorFinding(cause=SupervisorCause.STALL, detail="stall"),
            active_directives=(),
            debate_run_id="run-x",
            iteration=3,
        )

        assert result.error is None
        assert [d.text for d in result.directives] == json.loads(DIRECTIONS)[
            "directions"
        ]

    def test_it_really_does_call_an_agent(self, toy_repo, tmp_path):
        from freemad.agents.registry import register_agent

        register_agent("directions_agent", _DirectionsAgent)
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "w", "type": "directions_agent"},
                    {"id": "x", "type": "directions_agent"},
                ],
                "evolve": {
                    "repo_path": str(toy_repo),
                    "store_path": str(tmp_path / "e.db"),
                    "variation": {"kind": "single_agent", "agent_id": "w"},
                    "supervisor": {"intervention": "single_agent"},
                    "judge": JUDGE,
                },
            }
        )
        result = Supervisor(cfg)._ask_one_agent("give me directions")
        assert json.loads(DIRECTIONS)["directions"][0] in result["final_solution"]


def test_intervention_counter_is_persisted(toy_repo, tmp_path):
    """The column existed and was written with its default forever."""
    cfg = make_config(toy_repo, tmp_path)
    orch = build_orchestrator(cfg, [])
    snap = orch.create_run("goal")

    updated = orch._persist_intervention_count(snap, 2)
    reloaded = orch.status(snap.run_id)
    orch.close()

    assert updated.interventions_without_new_best == 2
    assert reloaded.interventions_without_new_best == 2


# --------------------------------------------------------------------------------
# Paths: transcripts and config-relative resolution
# --------------------------------------------------------------------------------


def test_transcripts_are_anchored_to_the_store(toy_repo, tmp_path):
    cfg = make_config(toy_repo, tmp_path)
    where = transcript_dir(cfg, "run-7")
    assert (
        where == Path(cfg.evolve.store_path).resolve().parent / "transcripts" / "run-7"
    )
    assert where.is_absolute(), "must not depend on the process working directory"


def test_relative_evolve_paths_resolve_against_the_config_file(tmp_path):
    project = tmp_path / "project"
    (project / "sub").mkdir(parents=True)
    cfg_path = project / "sub" / "evolve.yaml"
    cfg_path.write_text(
        yaml.safe_dump({"evolve": {"repo_path": "..", "store_path": "state/evolve.db"}})
    )

    cfg = load_config(path=cfg_path)

    assert Path(cfg.evolve.repo_path) == project.resolve()
    assert (
        Path(cfg.evolve.store_path)
        == (project / "sub" / "state" / "evolve.db").resolve()
    )


def test_absolute_evolve_paths_are_left_alone(tmp_path):
    cfg_path = tmp_path / "evolve.yaml"
    cfg_path.write_text(
        yaml.safe_dump(
            {"evolve": {"repo_path": "/somewhere/else", "store_path": "/var/evolve.db"}}
        )
    )
    cfg = load_config(path=cfg_path)
    assert cfg.evolve.repo_path == "/somewhere/else"
    assert cfg.evolve.store_path == "/var/evolve.db"


# --------------------------------------------------------------------------------
# The context document is actually bounded
# --------------------------------------------------------------------------------


def test_context_document_respects_its_budget_on_a_long_run():
    """Shrinking the graveyard alone does not bound a run with 400 iterations."""
    records = tuple(
        IterationRecord(
            iteration=i,
            kind=VariationKind.SINGLE_AGENT,
            outcome=IterationOutcome.COMMITTED,
            score=ScoreVector({"ops_per_sec": float(i)}),
            self_report="x" * 300,
            tag=f"evolve/r/v{i}",
        )
        for i in range(1, 400)
    )
    doc = generate_context(
        ContextInput(
            goal="g",
            iteration=400,
            best_iteration=399,
            best_sha="abc",
            best_score=None,
            baseline_score=None,
            records=records,
            directives=(),
        ),
        budget_chars=2000,
    )
    # enforce_size appends a truncation marker, per the convention used elsewhere.
    assert len(doc) < 2400
    assert doc.startswith("# GOAL")
