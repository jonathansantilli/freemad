"""CLI surface for `freemad evolve`, which the audit found had no tests at all."""

from __future__ import annotations

import sys

import json
from pathlib import Path

import pytest
import yaml

from freemad.cli import _evolve_main
from freemad.evolve.models import EvolveRunSnapshot
from freemad.evolve.store import EvolveStore
from freemad.types import EvolveEventKind, EvolveRunStatus
from tests.pkg_mad.evolve.test_orchestrator import (
    BENCH_FILE,
    SLOW_IMPL,
    TESTS_FILE,
    _git,
)

GOOD_BENCH = BENCH_FILE
CRASHING_TESTS = "def test_broken():\n    raise SystemExit(3)\n"


def _write_repo(root: Path, tests_file: str = TESTS_FILE) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "impl.py").write_text(SLOW_IMPL)
    (root / "tests").mkdir(exist_ok=True)
    (root / "tests" / "test_impl.py").write_text(tests_file)
    (root / "bench.py").write_text(GOOD_BENCH)
    _git(root, "init", "-q")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")


def _write_config(cfg_path: Path, repo: Path, store: Path, **judge_extra) -> Path:
    judge = {
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
    }
    judge.update(judge_extra)
    cfg_path.write_text(
        yaml.safe_dump(
            {
                "evolve": {
                    "repo_path": str(repo),
                    "store_path": str(store),
                    "variation": {"kind": "single_agent", "agent_id": "claude"},
                    "judge": judge,
                    "stop": {"max_iterations": 2, "max_wall_clock_minutes": 10},
                }
            }
        )
    )
    return cfg_path


def _json_out(capsys) -> dict:
    return json.loads(capsys.readouterr().out.strip().splitlines()[-1])


@pytest.fixture()
def cli_repo(tmp_path):
    repo = tmp_path / "repo"
    _write_repo(repo)
    store = tmp_path / "state" / "evolve.db"
    cfg = _write_config(tmp_path / "evolve.yaml", repo, store)
    return repo, store, cfg


class TestValidate:
    def test_clean_repo_validates(self, cli_repo, capsys):
        _, _, cfg = cli_repo
        assert _evolve_main(["validate", "--config", str(cfg)]) == 0
        result = _json_out(capsys)
        assert result["ok"] is True
        assert result["problems"] == []

    def test_seed_whose_stage_fails_is_a_problem(self, tmp_path, capsys):
        """B1 at the validate boundary: the gate can pass on a partial score vector."""
        repo = tmp_path / "repo"
        _write_repo(repo, tests_file=CRASHING_TESTS)
        cfg = _write_config(
            tmp_path / "evolve.yaml",
            repo,
            tmp_path / "evolve.db",
            stages=[
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
        )
        assert _evolve_main(["validate", "--config", str(cfg)]) == 2
        result = _json_out(capsys)
        assert result["ok"] is False
        assert any("tests" in p for p in result["problems"])

    def test_warns_when_a_scored_stage_touches_nothing_protected(
        self, tmp_path, capsys
    ):
        """S5: a component the worker can rewrite carries no measurement trust."""
        repo = tmp_path / "repo"
        _write_repo(repo)
        cfg = _write_config(
            tmp_path / "evolve.yaml",
            repo,
            tmp_path / "evolve.db",
            protected_paths=["tests/"],  # bench.py deliberately left editable
        )
        assert _evolve_main(["validate", "--config", str(cfg)]) == 0
        result = _json_out(capsys)
        assert result["ok"] is True
        assert any("bench" in w and "protected" in w for w in result["warnings"])

    def test_dirty_repo_is_a_problem(self, cli_repo, capsys):
        repo, _, cfg = cli_repo
        (repo / "impl.py").write_text("# uncommitted edit\n")
        assert _evolve_main(["validate", "--config", str(cfg)]) == 2
        assert any("clean" in p for p in _json_out(capsys)["problems"])


def _seed_store(
    store: Path,
    run_id: str = "run-1",
    status: EvolveRunStatus = EvolveRunStatus.STOPPED,
) -> None:
    store.parent.mkdir(parents=True, exist_ok=True)
    s = EvolveStore(store)
    s.create_run(
        EvolveRunSnapshot(
            run_id=run_id,
            goal="make it fast",
            manifest_hash="deadbeef",
            status=status,
            seed_ref="HEAD",
            run_branch="evolve/run-1",
            repo_path="/tmp/repo",
        )
    )
    s.append_event(run_id, EvolveEventKind.RUN_CREATED, 0, {"goal": "make it fast"})
    s.close()


class TestStatusAndInspect:
    def test_status_reads_the_store_named_by_the_config(self, cli_repo, capsys):
        """These two used to load the *default* config and read the wrong database."""
        _, store, cfg = cli_repo
        _seed_store(store)
        assert _evolve_main(["status", "run-1", "--config", str(cfg)]) == 0
        assert _json_out(capsys)["run_id"] == "run-1"

    def test_inspect_includes_events(self, cli_repo, capsys):
        _, store, cfg = cli_repo
        _seed_store(store)
        assert _evolve_main(["inspect", "run-1", "--config", str(cfg)]) == 0
        payload = _json_out(capsys)
        assert [e["kind"] for e in payload["events"]] == [
            EvolveEventKind.RUN_CREATED.value
        ]

    def test_unknown_run_id_is_an_error(self, cli_repo, capsys):
        _, store, cfg = cli_repo
        _seed_store(store)
        assert _evolve_main(["status", "nope", "--config", str(cfg)]) == 2

    def test_config_is_required(self, cli_repo):
        with pytest.raises(SystemExit) as exc:
            _evolve_main(["status", "run-1"])
        assert exc.value.code == 2


class TestAnswer:
    def test_decline_needs_no_guidance_text(self, cli_repo, capsys):
        """S7: you should not have to invent text you are declining to give."""
        _, store, cfg = cli_repo
        _seed_store(store, status=EvolveRunStatus.WAITING_FOR_HUMAN)
        assert _evolve_main(["answer", "run-1", "--decline", "--config", str(cfg)]) == 0
        assert _json_out(capsys)["stop_reason"] == "human_declined"

    def test_missing_guidance_is_rejected_not_crashed(self, cli_repo):
        """Guards the `parser.error`; the sibling above guards `nargs="?"`.

        Reverting `nargs` alone also exits 2, for an unrelated argparse reason, so
        neither test covers both halves — the pair does.
        """
        _, store, cfg = cli_repo
        _seed_store(store, status=EvolveRunStatus.WAITING_FOR_HUMAN)
        with pytest.raises(SystemExit) as exc:
            _evolve_main(["answer", "run-1", "--config", str(cfg)])
        assert exc.value.code == 2


class TestAnswerGuard:
    """Neither verb may overwrite a run that already finished."""

    def test_decline_refuses_a_completed_run(self, cli_repo, capsys):
        _, store, cfg = cli_repo
        _seed_store(store, status=EvolveRunStatus.COMPLETED)
        assert _evolve_main(["answer", "run-1", "--decline", "--config", str(cfg)]) == 2
        assert "not waiting for human input" in capsys.readouterr().err

    def test_answer_refuses_a_completed_run(self, cli_repo, capsys):
        _, store, cfg = cli_repo
        _seed_store(store, status=EvolveRunStatus.COMPLETED)
        assert _evolve_main(["answer", "run-1", "go on", "--config", str(cfg)]) == 2
        assert "not waiting for human input" in capsys.readouterr().err


class TestPauseAndStop:
    """Both read `args.config`; neither subparser used to define it."""

    def test_pause_runs(self, cli_repo, capsys):
        _, store, cfg = cli_repo
        _seed_store(store, status=EvolveRunStatus.RUNNING)
        assert _evolve_main(["pause", "run-1", "--config", str(cfg)]) == 0
        assert _json_out(capsys)["status"] == EvolveRunStatus.PAUSED.value

    def test_stop_runs(self, cli_repo, capsys):
        _, store, cfg = cli_repo
        _seed_store(store, status=EvolveRunStatus.RUNNING)
        assert _evolve_main(["stop", "run-1", "--config", str(cfg)]) == 0
        assert _json_out(capsys)["stop_reason"] == "manual"


class TestMissingStore:
    def test_status_names_the_missing_store(self, cli_repo, capsys):
        _, _, cfg = cli_repo  # store never created
        assert _evolve_main(["status", "run-1", "--config", str(cfg)]) == 2
        assert "no evolve store at" in capsys.readouterr().err

    def test_report_does_not_create_a_store(self, cli_repo):
        _, store, cfg = cli_repo
        assert _evolve_main(["report", "run-1", "--config", str(cfg)]) == 2
        assert not store.exists(), "a read-only verb must not create the store"


class TestReport:
    def test_report_renders_and_is_reproducible(self, cli_repo, capsys):
        """M1 acceptance: re-rendering from events alone must be byte-identical."""
        _, store, cfg = cli_repo
        _seed_store(store)
        assert _evolve_main(["report", "run-1", "--config", str(cfg)]) == 0
        first = capsys.readouterr().out
        assert _evolve_main(["report", "run-1", "--config", str(cfg)]) == 0
        assert capsys.readouterr().out == first
        assert "report_sha256:" in first
