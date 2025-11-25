from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from freemad.cli import main


def _make_config(tmpdir: Path) -> Path:
    cfg_path = tmpdir / "cfg.yaml"
    cfg_path.write_text(
        """
agents:
  - id: a
    type: claude_code
    cli_command: "python"
    timeout: 1
    config:
      temperature: 0.0
  - id: b
    type: claude_code
    cli_command: "python"
    timeout: 1
    config:
      temperature: 0.0
security:
  cli_allowed_commands: ["python"]
""",
        encoding="utf-8",
    )
    return cfg_path


def test_version_flag_exits_zero(capsys):
    rc = main(["--version"])
    assert rc == 0
    out = capsys.readouterr().out
    assert out.strip()


def test_missing_requirement_returns_error(capsys):
    with tempfile.TemporaryDirectory() as td:
        cfg = _make_config(Path(td))
        rc = main(["--config", str(cfg)])
        assert rc == 2
        err = capsys.readouterr().err
        assert "requirement is required" in err


def test_invalid_config_path_returns_error(capsys):
    rc = main(["--config", "nonexistent.yaml", "task"])
    assert rc == 2
    err = capsys.readouterr().err
    assert "config error" in err
