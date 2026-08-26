"""Container isolation for judge stages and worker commands.

Env scrubbing covers variables. It cannot cover this project's actual credentials, which
are the agent CLI's on-disk session under `~/.claude/` and `~/.codex/` — reachable by any
judge stage as long as `HOME` names the operator's home directory. The container removes
the directory from the stage's world rather than trying to make it unreadable.

The argv tests always run. The tests that actually start a container are skipped when no
runtime is reachable, so CI without Docker stays green.
"""

from __future__ import annotations

import sys

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from freemad.config import ConfigError, ContainerConfig, load_config
from freemad.evolve.container import (
    ContainerUnavailable,
    build_argv,
    container_name,
    require_runtime,
    runtime_available,
)
from freemad.evolve.judge import Judge
from tests.pkg_mad.evolve.test_orchestrator import _git

IMAGE = "python:3.13-slim"


def _docker_ready() -> bool:
    return shutil.which("docker") is not None and runtime_available("docker") is None


docker_required = pytest.mark.skipif(
    not _docker_ready(), reason="no reachable container runtime"
)


class TestArgvConstruction:
    """What the isolation actually consists of, asserted flag by flag."""

    def _argv(self, **overrides):
        cfg = ContainerConfig(enabled=True, image=IMAGE, **overrides)
        return build_argv(
            cfg,
            ["python", "bench.py"],
            Path("/tmp/wt"),
            {"PATH": "/usr/bin", "HOME": "/Users/someone"},
            network=False,
            name="freemad-test",
            uid_gid="501:20",
        )

    def test_only_the_worktree_is_mounted(self):
        argv = self._argv()
        mounts = [argv[i + 1] for i, a in enumerate(argv) if a == "--mount"]
        assert len(mounts) == 1
        assert mounts[0].endswith("target=/workspace")
        assert "/tmp/wt" in mounts[0]

    def test_home_never_names_a_host_path(self):
        """The whole point: `~/.claude` must not be reachable from inside."""
        argv = self._argv()
        envs = [argv[i + 1] for i, a in enumerate(argv) if a == "-e"]
        assert "HOME=/tmp" in envs
        assert not any(e.startswith("HOME=/Users") for e in envs)

    def test_network_false_means_no_network_interface(self):
        argv = self._argv()
        assert "--network" in argv and argv[argv.index("--network") + 1] == "none"

    def test_network_true_leaves_the_default_network(self):
        cfg = ContainerConfig(enabled=True, image=IMAGE)
        argv = build_argv(
            cfg, ["true"], Path("/tmp/wt"), {}, network=True, name="n", uid_gid=None
        )
        assert "--network" not in argv

    def test_privileges_are_dropped(self):
        argv = self._argv()
        assert "--cap-drop=ALL" in argv
        assert "--security-opt=no-new-privileges" in argv
        assert "--read-only" in argv

    def test_runs_as_the_operator_so_git_can_still_read_what_it_wrote(self):
        assert "--user" in self._argv()

    def test_limits_are_passed_through_when_set(self):
        argv = self._argv(memory="2g", cpus="1.5")
        assert argv[argv.index("--memory") + 1] == "2g"
        assert argv[argv.index("--cpus") + 1] == "1.5"

    def test_the_command_is_last_and_intact(self):
        argv = self._argv()
        assert argv[-2:] == ["python", "bench.py"]
        assert argv[-3] == IMAGE

    def test_names_are_unique_so_a_timeout_can_kill_the_right_one(self):
        assert container_name() != container_name()


class TestMissingRuntimeIsFatal:
    """A security control that silently falls back is worse than none."""

    def test_require_runtime_raises_rather_than_degrading(self):
        cfg = ContainerConfig(enabled=True, runtime="definitely-not-a-runtime")
        with pytest.raises(ContainerUnavailable, match="not on PATH"):
            require_runtime(cfg)

    def test_the_message_names_the_opt_out(self):
        cfg = ContainerConfig(enabled=True, runtime="definitely-not-a-runtime")
        with pytest.raises(ContainerUnavailable, match="container.enabled: false"):
            require_runtime(cfg)


class TestConfigValidation:
    def _cfg(self, **container):
        return load_config(
            overrides={
                "agents": [
                    {"id": "w", "type": "claude_code"},
                    {"id": "x", "type": "codex"},
                ],
                "evolve": {
                    "variation": {"kind": "single_agent", "agent_id": "w"},
                    "judge": {
                        "stages": [
                            {
                                "name": "b",
                                "command": f"{sys.executable} b.py",
                                "parse": "json_stdout",
                                "provides": ["s"],
                            }
                        ],
                        "gate": [{"component": "s", "op": ">", "value": 0}],
                        "comparator": [
                            {"component": "s", "direction": "maximize", "epsilon": 0.0}
                        ],
                        "protected_paths": ["b.py"],
                        "container": container,
                    },
                },
            }
        )

    def test_defaults_are_off_and_valid(self):
        assert self._cfg().evolve.judge.container.enabled is False

    def test_a_relative_workdir_is_rejected(self):
        with pytest.raises(ConfigError, match="absolute container path"):
            self._cfg(enabled=True, workdir="workspace")

    def test_an_empty_image_is_rejected(self):
        with pytest.raises(ConfigError, match="image must be non-empty"):
            self._cfg(enabled=True, image="   ")

    def test_settings_round_trip(self):
        c = self._cfg(
            enabled=True, image=IMAGE, memory="1g", cpus="2"
        ).evolve.judge.container
        assert (c.enabled, c.image, c.memory, c.cpus) == (True, IMAGE, "1g", "2")


PROBE = (
    "import json, os, pathlib\n"
    'home = pathlib.Path(os.path.expanduser("~"))\n'
    'print(json.dumps({"components": {\n'
    '    "home_has_claude": 1.0 if (home / ".claude").exists() else 0.0,\n'
    '    "sees_host_root": 1.0 if pathlib.Path("/Users").exists() else 0.0,\n'
    "}}))\n"
)


@docker_required
class TestRealContainerIsolation:
    """Actually starts a container. Skipped when no runtime is reachable."""

    @pytest.fixture()
    def probe_repo(self, tmp_path):
        repo = tmp_path / "probe"
        repo.mkdir()
        (repo / "probe.py").write_text(PROBE)
        _git(repo, "init", "-q")
        _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
        _git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "seed")
        return repo

    def _judge(self, repo: Path, tmp_path: Path, containerised: bool):
        # Containerised, the stage runs the image's own python. On the host it must run
        # *this* interpreter: a bare `python` resolves only when a venv is on PATH.
        command = "python probe.py" if containerised else f"{sys.executable} probe.py"
        cfg = load_config(
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
                                "name": "probe",
                                "command": command,
                                "timeout_sec": 180,
                                "parse": "json_stdout",
                                "provides": ["home_has_claude", "sees_host_root"],
                            }
                        ],
                        "gate": [
                            {"component": "home_has_claude", "op": ">=", "value": 0}
                        ],
                        "comparator": [
                            {
                                "component": "home_has_claude",
                                "direction": "maximize",
                                "epsilon": 0.0,
                            }
                        ],
                        "protected_paths": ["probe.py"],
                        "container": {"enabled": containerised, "image": IMAGE},
                    },
                },
            }
        )
        return Judge(cfg).judge_worktree(repo)

    def test_the_container_removes_the_operator_home(self, probe_repo, tmp_path):
        verdict = self._judge(probe_repo, tmp_path, containerised=True)
        assert verdict.failed_stage is None, verdict.failure_detail
        score = verdict.score.to_dict()
        assert (
            score["home_has_claude"] == 0.0
        ), "the agent CLI's on-disk session must not be reachable from a judge stage"
        assert score["sees_host_root"] == 0.0, "the host filesystem must not be mounted"

    @pytest.mark.skipif(
        not Path(os.path.expanduser("~/.claude")).exists(),
        reason="no ~/.claude on this machine to contrast against",
    )
    def test_and_that_it_is_visible_without_one(self, probe_repo, tmp_path):
        """The contrast that makes the assertion above mean something."""
        verdict = self._judge(probe_repo, tmp_path, containerised=False)
        assert verdict.failed_stage is None, verdict.failure_detail
        assert verdict.score.to_dict()["home_has_claude"] == 1.0

    def test_files_written_inside_stay_usable_by_git_outside(
        self, probe_repo, tmp_path
    ):
        """Without `--user`, the stage writes root-owned files and the next `git add` fails."""
        (probe_repo / "probe.py").write_text(
            "import json, pathlib\n"
            'pathlib.Path("made_inside.txt").write_text("hello")\n'
            'print(json.dumps({"components": {"home_has_claude": 0.0, "sees_host_root": 0.0}}))\n'
        )
        _git(
            probe_repo,
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@t",
            "commit",
            "-aqm",
            "writer",
        )

        verdict = self._judge(probe_repo, tmp_path, containerised=True)
        assert verdict.failed_stage is None, verdict.failure_detail

        made = probe_repo / "made_inside.txt"
        assert made.exists() and made.read_text() == "hello"
        assert (
            made.stat().st_uid == os.getuid()
        ), "a root-owned file would break git on the host"
        subprocess.run(
            ["git", "add", "-A"], cwd=str(probe_repo), check=True, capture_output=True
        )
