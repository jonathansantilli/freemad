"""H4: judge stages and worker commands must not see the run's own credentials."""

from __future__ import annotations

import sys

from pathlib import Path

import pytest

from freemad.config import ConfigError, load_config
from freemad.evolve.judge import Judge
from freemad.evolve.sandbox import BLACKHOLE_PROXY, PROXY_VARS, scrubbed_env
from freemad.evolve.variation import run_commands_policy


SECRETS = {
    "ANTHROPIC_API_KEY": "sk-ant-should-not-be-visible",
    "OPENAI_API_KEY": "sk-should-not-be-visible",
    "AWS_SECRET_ACCESS_KEY": "should-not-be-visible",
    "GITHUB_TOKEN": "ghp_should_not_be_visible",
}


class TestScrubbedEnv:
    def test_secrets_are_stripped(self, monkeypatch):
        for name, value in SECRETS.items():
            monkeypatch.setenv(name, value)
        env = scrubbed_env()
        assert not (set(env) & set(SECRETS))

    def test_process_essentials_survive(self, monkeypatch):
        monkeypatch.setenv("PATH", "/usr/bin")
        monkeypatch.setenv("HOME", "/home/someone")
        env = scrubbed_env()
        assert env["PATH"] == "/usr/bin"
        assert env["HOME"] == "/home/someone"

    def test_passthrough_is_the_escape_hatch(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
        monkeypatch.setenv("MY_JUDGE_FIXTURE_DIR", "/opt/fixtures")
        env = scrubbed_env(passthrough=("MY_JUDGE_FIXTURE_DIR",))
        assert env["MY_JUDGE_FIXTURE_DIR"] == "/opt/fixtures"
        assert "ANTHROPIC_API_KEY" not in env

    def test_absent_passthrough_is_skipped_not_blanked(self):
        """A stage can still tell "unset" from "set to empty"."""
        assert "DEFINITELY_NOT_SET_ANYWHERE" not in scrubbed_env(
            passthrough=("DEFINITELY_NOT_SET_ANYWHERE",)
        )

    def test_network_off_blackholes_proxies_and_clears_no_proxy(self, monkeypatch):
        monkeypatch.setenv("NO_PROXY", "*")
        env = scrubbed_env(network=False)
        for var in PROXY_VARS:
            assert env[var] == BLACKHOLE_PROXY
        # An inherited NO_PROXY would punch straight through the black hole.
        assert env["NO_PROXY"] == ""
        assert env["no_proxy"] == ""

    def test_network_on_keeps_the_route_out(self, monkeypatch):
        """ "Allowed" has to mean reachable: stripping the proxy leaves no route out."""
        monkeypatch.setenv("HTTPS_PROXY", "http://corp:3128")
        monkeypatch.setenv("NO_PROXY", "localhost")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-secret")
        env = scrubbed_env(network=True)
        assert env["HTTPS_PROXY"] == "http://corp:3128"
        assert env["NO_PROXY"] == "localhost"
        assert "ANTHROPIC_API_KEY" not in env, "network on is not scrubbing off"


def _judge_config(tmp_path: Path, command: str, **judge_extra):
    judge = {
        "stages": [
            {
                "name": "probe",
                "command": command,
                "timeout_sec": 60,
                "parse": "json_stdout",
                "provides": ["seen"],
            }
        ],
        "gate": [{"component": "seen", "op": ">=", "value": 0}],
        "comparator": [{"component": "seen", "direction": "maximize", "epsilon": 0.0}],
        # A scoring stage with nothing protected is now a load-time error: the worker
        # could rewrite the scorer.
        "protected_paths": ["probe.py"],
    }
    judge.update(judge_extra)
    return load_config(
        overrides={
            "agents": [
                {"id": "w", "type": "claude_code"},
                {"id": "x", "type": "codex"},
            ],
            "evolve": {
                "repo_path": str(tmp_path),
                "store_path": str(tmp_path / "evolve.db"),
                "variation": {"kind": "single_agent", "agent_id": "w"},
                "judge": judge,
            },
        }
    )


# A stage that reports whether it can see a secret, so the assertion is about the real
# subprocess environment rather than about `scrubbed_env` in isolation.
PROBE = """\
import json
import os

print(json.dumps({"components": {"seen": 1.0 if os.environ.get("ANTHROPIC_API_KEY") else 0.0}}))
"""


class TestJudgeIsScrubbed:
    def test_stage_subprocess_cannot_read_a_secret(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak-me")
        (tmp_path / "probe.py").write_text(PROBE)
        cfg = _judge_config(tmp_path, f"{sys.executable} probe.py")

        verdict = Judge(cfg).judge_worktree(tmp_path)

        assert verdict.failed_stage is None, verdict.failure_detail
        assert verdict.score is not None
        assert verdict.score.get("seen") == 0.0

    def test_env_passthrough_reaches_the_stage(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak-me")
        (tmp_path / "probe.py").write_text(PROBE)
        cfg = _judge_config(
            tmp_path,
            f"{sys.executable} probe.py",
            env_passthrough=["ANTHROPIC_API_KEY"],
        )

        verdict = Judge(cfg).judge_worktree(tmp_path)

        assert verdict.score is not None
        assert verdict.score.get("seen") == 1.0, "the escape hatch must actually work"


class TestStageCommandSplitting:
    def test_quoted_arguments_survive(self, tmp_path):
        """`str.split` would turn `-k "not slow"` into three arguments."""
        (tmp_path / "echo_args.py").write_text(
            "import json, sys\n"
            'print(json.dumps({"components": {"seen": float(len(sys.argv) - 1)}}))\n'
        )
        cfg = _judge_config(tmp_path, f'{sys.executable} echo_args.py -k "not slow"')

        verdict = Judge(cfg).judge_worktree(tmp_path)

        assert verdict.score is not None
        assert (
            verdict.score.get("seen") == 2.0
        ), "-k and 'not slow', not three arguments"


class TestWorkerCommandsAreScrubbed:
    def test_worker_command_cannot_read_a_secret(self, tmp_path, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-leak-me")
        (tmp_path / "leak.py").write_text(
            "import os, pathlib\n"
            'pathlib.Path("leaked.txt").write_text(os.environ.get("ANTHROPIC_API_KEY", ""))\n'
        )
        cfg = load_config(
            overrides={
                "agents": [
                    {"id": "w", "type": "claude_code"},
                    {"id": "x", "type": "codex"},
                ],
                "task": {
                    "tool_policy": {
                        "allow_local_commands": True,
                        "allowed_local_commands": ["python3"],
                    }
                },
            }
        )

        run_commands_policy(cfg, ("python3 leak.py",), tmp_path)

        assert (tmp_path / "leaked.txt").read_text() == ""


class TestEnvPassthroughValidation:
    @pytest.mark.parametrize(
        "bad", ["", "  ", "not a name", "1STARTS_WITH_DIGIT", "has-dash"]
    )
    def test_rejects_names_that_are_not_variables(self, tmp_path, bad):
        with pytest.raises(ConfigError, match="env_passthrough"):
            _judge_config(tmp_path, f"{sys.executable} probe.py", env_passthrough=[bad])

    def test_rejects_duplicates(self, tmp_path):
        with pytest.raises(ConfigError, match="unique"):
            _judge_config(
                tmp_path, f"{sys.executable} probe.py", env_passthrough=["CI", "CI"]
            )


# --------------------------------------------------------------------------------
# Found by adversarial review of the fixes themselves (2026-08-25)
# --------------------------------------------------------------------------------


class TestWorkerCannotKillTheRun:
    """`variation.py` promises a worker cannot end the whole optimization.

    Every one of these used to raise past the `VariationPolicyError` handler, out of
    `_run_iteration`, and terminate the process -- before any `CANDIDATE_REJECTED` event
    was written, so `status` still said RUNNING and `resume` replayed the same iteration
    forever.
    """

    def _policy_cfg(self, allowed=("python3",)):
        return load_config(
            overrides={
                "agents": [
                    {"id": "w", "type": "claude_code"},
                    {"id": "x", "type": "codex"},
                ],
                "task": {
                    "tool_policy": {
                        "allow_workspace_write": True,
                        "allow_local_commands": True,
                        "allowed_local_commands": list(allowed),
                    }
                },
            }
        )

    def test_write_to_the_worktree_root(self, tmp_path):
        from freemad.evolve.variation import VariationPolicyError, apply_writes_policy
        from freemad.tasks.models import FileWrite

        with pytest.raises(VariationPolicyError, match="not the worktree root"):
            apply_writes_policy(
                self._policy_cfg(), (FileWrite(path=".", content="x"),), tmp_path
            )

    def test_write_into_dot_git(self, tmp_path):
        from freemad.evolve.variation import VariationPolicyError, apply_writes_policy
        from freemad.tasks.models import FileWrite

        with pytest.raises(VariationPolicyError, match=r"\.git"):
            apply_writes_policy(
                self._policy_cfg(),
                (FileWrite(path=".git/config", content="x"),),
                tmp_path,
            )

    def test_write_that_fails_on_disk(self, tmp_path):
        from freemad.evolve.variation import VariationPolicyError, apply_writes_policy
        from freemad.tasks.models import FileWrite

        (tmp_path / "adir").mkdir()
        with pytest.raises(VariationPolicyError, match="write failed"):
            apply_writes_policy(
                self._policy_cfg(), (FileWrite(path="adir", content="x"),), tmp_path
            )

    def test_command_with_an_unbalanced_quote(self, tmp_path):
        from freemad.evolve.variation import VariationPolicyError, run_commands_policy

        with pytest.raises(VariationPolicyError, match="unparseable"):
            run_commands_policy(self._policy_cfg(), ('python3 -c "oops',), tmp_path)

    def test_allowlisted_command_that_is_not_installed(self, tmp_path):
        from freemad.evolve.variation import VariationPolicyError, run_commands_policy

        with pytest.raises(VariationPolicyError, match="could not start"):
            run_commands_policy(
                self._policy_cfg(allowed=("nosuchbin-zz",)),
                ("nosuchbin-zz --go",),
                tmp_path,
            )


class TestScalarWhereAListBelongs:
    """`list("bench.py")` is eight one-character entries, all individually valid."""

    @pytest.mark.parametrize("field", ["protected_paths", "env_passthrough"])
    def test_a_bare_string_under_judge_is_rejected(self, tmp_path, field):
        with pytest.raises(ConfigError, match="single value"):
            _judge_config(tmp_path, f"{sys.executable} probe.py", **{field: "bench.py"})

    def test_a_bare_string_for_knowledge_paths_is_rejected(self, tmp_path):
        with pytest.raises(ConfigError, match="single value"):
            load_config(
                overrides={
                    "agents": [
                        {"id": "w", "type": "claude_code"},
                        {"id": "x", "type": "codex"},
                    ],
                    "evolve": {"knowledge_paths": "docs/api.md"},
                }
            )
