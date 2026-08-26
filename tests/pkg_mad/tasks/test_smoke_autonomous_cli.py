"""The README's autonomous quick start, executed: canned agents, no credentials.

Gated like the debate smoke test (set SMOKE=1). It goes through `freemad.cli.main` and the
real CLI adapter, spawning `bin/structured_human_task_mock.py` under this interpreter.
"""

from __future__ import annotations

import io
import json
import os
import shlex
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from freemad.cli import main

ROOT = Path(__file__).resolve().parents[3]
MOCK = ROOT / "bin" / "structured_human_task_mock.py"


@unittest.skipUnless(
    os.getenv("SMOKE") == "1", "smoke test disabled; set SMOKE=1 to enable"
)
class TestAutonomousQuickStart(unittest.TestCase):
    def _cli(self, argv: list[str]) -> dict:
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(argv)
        self.assertEqual(code, 0, buf.getvalue())
        return json.loads(buf.getvalue().strip().splitlines()[-1])

    def test_waits_for_the_human_then_completes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            exe = shlex.quote(sys.executable)
            cfg = Path(tmp) / "smoke.json"
            cfg.write_text(
                json.dumps(
                    {
                        "agents": [
                            {
                                "id": "researcher",
                                "type": "claude_code",
                                "cli_command": f"{exe} {MOCK}",
                                "roles": ["researcher", "arbiter"],
                            },
                            {
                                "id": "planner",
                                "type": "openai_codex",
                                "cli_command": f"{exe} {MOCK}",
                                "roles": ["planner"],
                            },
                            {
                                "id": "reviewer",
                                "type": "claude_code",
                                "cli_command": f"{exe} {MOCK}",
                                "roles": ["reviewer", "verifier"],
                            },
                        ],
                        "security": {"cli_allowed_commands": [sys.executable]},
                        "task": {
                            "store_path": str(Path(tmp) / "tasks.db"),
                            "artifacts_dir": str(Path(tmp) / "artifacts"),
                            "max_stage_retries": 1,
                            "tool_policy": {
                                "allow_workspace_write": False,
                                "allow_local_commands": False,
                            },
                        },
                    }
                )
            )
            common = ["--config", str(cfg)]
            started = self._cli(
                [
                    "task",
                    "start",
                    *common,
                    "--task-type",
                    "plan",
                    "--workspace-root",
                    tmp,
                    "Critique this architecture until the agents approve an implementation-ready plan.",
                ]
            )
            task_id = started["task_id"]
            self.assertEqual(started["status"], "waiting_for_human")
            self.assertEqual(started["current_stage"], "plan_review")
            self.assertIn("storage backend", started["error"])

            status = self._cli(["task", "status", task_id, *common])
            self.assertEqual(status["status"], "waiting_for_human")

            self._cli(["task", "answer", task_id, "Use SQLite.", *common])
            resumed = self._cli(["task", "resume", task_id, *common])
            self.assertEqual(resumed["status"], "completed")
            self.assertEqual(resumed["current_stage"], "finalize")
            self.assertNotIn("error", resumed, "the answered question must not linger")

            inspected = self._cli(["task", "inspect", task_id, *common])
            kinds = [event["kind"] for event in inspected["events"]]
            self.assertIn("arbiter_requested", kinds)
            self.assertIn("human_input_received", kinds)
            self.assertEqual(kinds[-1], "task_completed")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
