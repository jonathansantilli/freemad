"""Regressions for defects found by adversarially reviewing the audit fixes themselves.

Two of these were introduced *by* the fixes: the destructive `restore_protected` opened
a path-escape, and epsilon-50 made measurement noise look like progress.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from freemad.config import ConfigError, load_config
from freemad.evolve.lineage import Lineage, NoChangesToCommit, ProtectedPathTampering
from freemad.evolve.orchestrator import EvolveOrchestrator
from freemad.types import EvolveEventKind, EvolveRunStatus
from tests.pkg_mad.evolve.test_orchestrator import (
    ScriptedAgent,
    _git,
    build_orchestrator,
    make_config,
)

BENCH = 'import json\nprint(json.dumps({"components": {"s": 1.0}}))\n'


def _repo_with_nested_protected(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "tests" / "perf").mkdir(parents=True)
    (repo / "tests" / "perf" / "test_bench.py").write_text(
        "def test_x(): assert True\n"
    )
    (repo / "bench.py").write_text(BENCH)
    _git(repo, "init", "-q")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
    return repo


def _cfg(repo: Path, tmp_path: Path, protected):
    return load_config(
        overrides={
            "agents": [
                {"id": "w", "type": "claude_code"},
                {"id": "x", "type": "codex"},
            ],
            "evolve": {
                "repo_path": str(repo),
                "store_path": str(tmp_path / "e.db"),
                "variation": {"kind": "single_agent", "agent_id": "w"},
                "judge": {
                    "stages": [
                        {
                            "name": "b",
                            "command": "python3 bench.py",
                            "parse": "json_stdout",
                            "provides": ["s"],
                        }
                    ],
                    "gate": [{"component": "s", "op": ">", "value": 0}],
                    "comparator": [
                        {"component": "s", "direction": "maximize", "epsilon": 0.0}
                    ],
                    # deliberately NOT list()-wrapped: a bare string must be rejected
                    "protected_paths": protected,
                },
            },
        }
    )


class TestProtectedPathCannotEscapeTheWorktree:
    """`restore_protected` deletes before restoring; the delete must stay inside.

    `Path.is_symlink()` lstats only the FINAL component and `shutil.rmtree` refuses only
    when the path *itself* is a link, so a worker that turns a PARENT component into a
    symlink made `is_dir()` follow it and handed `rmtree` a directory outside the
    worktree — operator data, deleted silently, with the run carrying on.
    """

    def test_symlinked_parent_is_refused_and_the_target_survives(self, tmp_path):
        victim = tmp_path / "victim"
        (victim / "perf").mkdir(parents=True)
        (victim / "perf" / "data.txt").write_text("IRREPLACEABLE")

        repo = _repo_with_nested_protected(tmp_path)
        cfg = _cfg(repo, tmp_path, ["tests/perf"])
        lineage = Lineage(cfg, "escape")
        lineage.init_run_branch(lineage.resolve_ref("HEAD"))
        worktree = lineage.create_worktree(1)
        try:
            # exactly what an allowlisted `python -c` can do during VARIATION
            subprocess.run(
                [
                    "python3",
                    "-c",
                    "import os,sys; os.rename('tests','t2'); os.symlink(sys.argv[1],'tests')",
                    str(victim),
                ],
                cwd=worktree,
                check=True,
            )

            with pytest.raises(ProtectedPathTampering, match="traverses a symlink"):
                lineage.restore_protected(worktree, "HEAD")

            assert (victim / "perf" / "data.txt").read_text() == "IRREPLACEABLE"
        finally:
            lineage.remove_worktree(1)
            lineage.delete_run_branch()

    def test_tampering_fails_the_iteration_not_the_run(self, tmp_path):
        repo = _repo_with_nested_protected(tmp_path)
        cfg = _cfg(repo, tmp_path, ["tests/perf"])

        class SymlinkAgent(ScriptedAgent):
            def act(self, request):
                root = Path(request.workspace_root)
                (root / "extra.py").write_text("# a real change too\n")
                subprocess.run(
                    [
                        "python3",
                        "-c",
                        "import os; os.rename('tests','t2'); os.symlink('/tmp','tests')",
                    ],
                    cwd=root,
                    check=True,
                )
                return super().act(request)

        orch = EvolveOrchestrator(cfg)
        orch._resolve_agent = lambda: SymlinkAgent(cfg, cfg.agents[0], [])  # type: ignore
        snap = orch.create_run("goal")
        snap = orch.resume(snap.run_id)
        orch.step(snap.run_id)  # baseline
        final = orch.step(snap.run_id)  # iteration 1
        events = orch._store.list_events(snap.run_id)
        rejected = [e for e in events if e.kind == EvolveEventKind.CANDIDATE_REJECTED]
        orch.close()

        assert (
            final.status == EvolveRunStatus.RUNNING
        ), "the run must survive the attempt"
        assert rejected[-1].payload["failure_signature"] == "protected path tampering"


class TestProtectedHashesAreActuallyCompared:
    """Stamping a hash and never comparing it is provenance, not tamper detection."""

    def test_a_change_after_restoration_is_caught(self, tmp_path):
        repo = _repo_with_nested_protected(tmp_path)
        cfg = _cfg(repo, tmp_path, ["bench.py"])
        lineage = Lineage(cfg, "toctou")
        lineage.init_run_branch(lineage.resolve_ref("HEAD"))
        worktree = lineage.create_worktree(1)
        try:
            lineage.restore_protected(worktree, "HEAD")
            lineage.verify_protected(worktree, "HEAD")  # clean right after restoration

            # what a daemonised grandchild does between restoration and judging
            (worktree / "bench.py").write_text(
                'import json\nprint(json.dumps({"components": {"s": 999999.0}}))\n'
            )
            with pytest.raises(ProtectedPathTampering, match="changed between"):
                lineage.verify_protected(worktree, "HEAD")
        finally:
            lineage.remove_worktree(1)
            lineage.delete_run_branch()

    def test_build_artifacts_do_not_trip_it(self, tmp_path):
        """The judge creates __pycache__ inside the protected tree while running."""
        repo = _repo_with_nested_protected(tmp_path)
        cfg = _cfg(repo, tmp_path, ["tests/perf"])
        lineage = Lineage(cfg, "artifacts")
        lineage.init_run_branch(lineage.resolve_ref("HEAD"))
        worktree = lineage.create_worktree(1)
        try:
            lineage.restore_protected(worktree, "HEAD")
            cache = worktree / "tests" / "perf" / "__pycache__"
            cache.mkdir()
            (cache / "test_bench.cpython-313.pyc").write_bytes(b"\x00compiled")
            lineage.verify_protected(worktree, "HEAD")  # must not raise
        finally:
            lineage.remove_worktree(1)
            lineage.delete_run_branch()

    def test_an_added_conftest_is_still_caught(self, tmp_path):
        """The artifact filter must not become a hole for a real steering file."""
        repo = _repo_with_nested_protected(tmp_path)
        cfg = _cfg(repo, tmp_path, ["tests/perf"])
        lineage = Lineage(cfg, "added")
        lineage.init_run_branch(lineage.resolve_ref("HEAD"))
        worktree = lineage.create_worktree(1)
        try:
            lineage.restore_protected(worktree, "HEAD")
            (worktree / "tests" / "perf" / "conftest.py").write_text(
                "def pytest_collection_modifyitems(items):\n    items.clear()\n"
            )
            with pytest.raises(ProtectedPathTampering, match="untracked file"):
                lineage.verify_protected(worktree, "HEAD")
        finally:
            lineage.remove_worktree(1)
            lineage.delete_run_branch()

    def test_hash_tree_is_length_delimited(self, tmp_path):
        """("ab", b"c") and ("a", b"bc") must not collide."""
        repo = _repo_with_nested_protected(tmp_path)
        lineage = Lineage(_cfg(repo, tmp_path, ["bench.py"]), "hash")
        one = tmp_path / "one"
        two = tmp_path / "two"
        (one).mkdir()
        (two).mkdir()
        (one / "ab").write_bytes(b"c")
        (two / "a").write_bytes(b"bc")
        assert lineage._hash_tree(one) != lineage._hash_tree(two)


class TestNoOpCandidateIsRejectedNotFatal:
    """A candidate judged "better" on noise leaves nothing staged; `git commit` exits 1."""

    def test_empty_commit_raises_a_typed_error(self, tmp_path):
        repo = _repo_with_nested_protected(tmp_path)
        cfg = _cfg(repo, tmp_path, ["bench.py"])
        lineage = Lineage(cfg, "noop")
        lineage.init_run_branch(lineage.resolve_ref("HEAD"))
        worktree = lineage.create_worktree(1)
        try:
            with pytest.raises(NoChangesToCommit):
                lineage.commit_candidate(worktree, 1, "{}")
        finally:
            lineage.remove_worktree(1)
            lineage.delete_run_branch()

    def test_the_run_survives_it(self, toy_repo, tmp_path):
        cfg = make_config(toy_repo, tmp_path)

        class TouchesOnlyProtected(ScriptedAgent):
            def act(self, request):
                # every edit lands in a protected path, so restoration undoes all of it
                (Path(request.workspace_root) / "bench.py").write_text("# noop\n")
                return super().act(request)

        orch = EvolveOrchestrator(cfg)
        orch._resolve_agent = lambda: TouchesOnlyProtected(cfg, cfg.agents[0], [])  # type: ignore
        snap = orch.create_run("goal")
        snap = orch.resume(snap.run_id)
        orch.step(snap.run_id)
        final = orch.step(snap.run_id)
        orch.close()
        assert final.status == EvolveRunStatus.RUNNING


class TestScalarConfigIsRejected:
    def test_protected_paths_as_a_bare_string(self, tmp_path):
        repo = _repo_with_nested_protected(tmp_path)
        with pytest.raises(ConfigError, match="single value"):
            _cfg(repo, tmp_path, "bench.py")


class TestEscalationMessageIsNotDoubled:
    def test_cause_prefix_appears_once(self, toy_repo, tmp_path):
        from freemad.evolve.supervisor import SupervisorFinding
        from freemad.types import SupervisorCause

        cfg = make_config(toy_repo, tmp_path)
        orch = build_orchestrator(cfg, [])
        snap = orch.create_run("goal")
        finding = SupervisorFinding(
            cause=SupervisorCause.STALL,
            detail="stall: no commit in the last 2 iterations",
        )
        parked = orch._escalate(snap, finding)
        orch.close()
        assert parked.error is not None
        assert parked.error.count("stall:") == 1, parked.error


class TestReportOnARealTrajectory:
    """The only report coverage was a run with one event and no iterations.

    M1 requires the report to be reproducible byte-identical *from events alone*; a
    degenerate run cannot demonstrate that, because there is nothing to render.
    """

    def test_render_is_byte_identical_across_processes(self, toy_repo, tmp_path):
        from freemad.evolve.report import render_report
        from freemad.evolve.store import EvolveStore
        from tests.pkg_mad.evolve.test_orchestrator import BROKEN_IMPL, FAST_IMPL

        cfg = make_config(toy_repo, tmp_path)
        # a real trajectory: one accepted, one rejected, one that produced nothing
        orch = build_orchestrator(cfg, [FAST_IMPL, BROKEN_IMPL, None])
        snap = orch.create_run("make total fast")
        snap = orch.resume(snap.run_id)
        final = orch.run(snap.run_id)
        run_id = snap.run_id
        orch.close()

        committed = [
            e
            for e in EvolveStore(cfg.evolve.store_path, read_only=True).list_events(
                run_id
            )
            if e.kind == EvolveEventKind.CANDIDATE_COMMITTED
        ]
        assert (
            committed
        ), "the fixture must actually commit something to be worth rendering"

        # two independent stores, as `evolve report` would open on a later invocation
        first = render_report(
            EvolveStore(cfg.evolve.store_path, read_only=True), run_id
        )
        second = render_report(
            EvolveStore(cfg.evolve.store_path, read_only=True), run_id
        )

        assert first == second
        assert f"it{committed[0].iteration} COMMITTED" in first
        assert "# trajectory" in first and "report_sha256:" in first
        assert final.stop_reason is not None


class TestDebateArtefactsStayOutOfTheLineage:
    """A live run on a real repository committed the debate runtime's own transcripts.

    The worker ran the freemad CLI inside the worktree to check its work; the CLI wrote
    `transcripts/*.json`; `git add -A` swept them into the accepted candidate. Whatever
    produces them, the run's artefacts are not part of the code being evolved.
    """

    def test_transcripts_and_runtime_state_are_not_committed(self, toy_repo, tmp_path):
        cfg = make_config(toy_repo, tmp_path)
        lineage = Lineage(cfg, "artefacts")
        lineage.init_run_branch(lineage.resolve_ref("HEAD"))
        worktree = lineage.create_worktree(1)
        try:
            (worktree / "impl.py").write_text(
                "def total(n):\n    return n * (n + 1) // 2\n"
            )
            (worktree / "transcripts").mkdir()
            (worktree / "transcripts" / "transcript-20260101-000000.json").write_text(
                "{}"
            )
            (worktree / ".freemad" / "evolve").mkdir(parents=True)
            (worktree / ".freemad" / "evolve" / "junk.db").write_bytes(b"x")

            sha = lineage.commit_candidate(worktree, 1, "{}")

            files = subprocess.run(
                ["git", "ls-tree", "-r", "--name-only", sha],
                cwd=str(toy_repo),
                capture_output=True,
                text=True,
                check=True,
            ).stdout.split()
            assert "impl.py" in files, "the real change must be committed"
            assert not any(f.startswith("transcripts/") for f in files)
            assert not any(f.startswith(".freemad/") for f in files)
        finally:
            lineage.remove_worktree(1)
            lineage.delete_run_branch()
