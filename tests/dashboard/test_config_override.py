from __future__ import annotations

from pathlib import Path
import tempfile

from fastapi.testclient import TestClient

import sys
ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from freemad.dashboard.app import create_app, DashboardConfig


BASE_YAML = """
agents:
  - id: mock1
    type: claude_code
    cli_command: "python"
    cli_args: {}
    cli_flags: []
    cli_positional: []
    timeout: 1
    config:
      temperature: 0.1
  - id: mock2
    type: claude_code
    cli_command: "python"
    cli_args: {}
    cli_flags: []
    cli_positional: []
    timeout: 1
    config:
      temperature: 0.1
transcripts_dir: transcripts
"""


def make_app(tmpdir: Path) -> tuple[TestClient, Path]:
    override_base = tmpdir / "base.yaml"
    override_path = tmpdir / "override.yaml"
    override_base.write_text(BASE_YAML, encoding="utf-8")
    cfg = DashboardConfig(
        transcripts_dir=str(tmpdir / "t"),
        override_base=override_base,
        override_path=override_path,
    )
    app = create_app(cfg)
    return TestClient(app), override_path


def test_get_override_creates_file_and_returns_yaml() -> None:
    with tempfile.TemporaryDirectory() as td:
        client, override_path = make_app(Path(td))
        resp = client.get("/api/config/override")
        assert resp.status_code == 200
        data = resp.json()
        assert "yaml" in data
        assert override_path.exists()
        assert "agents:" in data["yaml"]


def test_save_override_validates_and_persists() -> None:
    with tempfile.TemporaryDirectory() as td:
        client, override_path = make_app(Path(td))
        new_yaml = BASE_YAML + "rounds: 2\n"
        resp = client.post("/api/config/override", json={"yaml": new_yaml})
        assert resp.status_code == 200, resp.text
        assert "saved" in resp.text or resp.json().get("message")
        assert override_path.read_text(encoding="utf-8").strip().endswith("rounds: 2")


def test_save_override_rejects_invalid_yaml() -> None:
    with tempfile.TemporaryDirectory() as td:
        client, override_path = make_app(Path(td))
        resp = client.post("/api/config/override", json={"yaml": "agents: ["})
        assert resp.status_code == 400
        # file should remain previous valid content
        assert "agents" in override_path.read_text(encoding="utf-8")


def test_save_override_rolls_back_on_validation_error(monkeypatch) -> None:
    with tempfile.TemporaryDirectory() as td:
        client, override_path = make_app(Path(td))

        def bad_load_config(*args, **kwargs):  # noqa: ANN001
            raise RuntimeError("boom")

        from freemad import dashboard

        monkeypatch.setattr(dashboard.app, "load_config", bad_load_config)  # type: ignore[attr-defined]
        prev = override_path.read_text(encoding="utf-8")
        resp = client.post("/api/config/override", json={"yaml": prev + "\nrounds: 3"})
        assert resp.status_code == 400
        # rollback should restore previous contents
        assert override_path.read_text(encoding="utf-8") == prev
