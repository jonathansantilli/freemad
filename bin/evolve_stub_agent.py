#!/usr/bin/env python3
"""A scriptable stub agent that speaks the real `act()` protocol over stdin/stdout.

`bin/mock_agent.py` only handles the debate runtime's `generate`/`critique` modes, so
nothing exercised the path evolve actually uses: `CLIAdapter.act` builds a task prompt,
spawns this process, and parses a JSON `TaskResponse` off stdout.

Substituting a Python class for the agent — which every other evolve test does — skips
`_ensure_allowed`, the subprocess spawn, the prompt, and the response parse. That is how
three shipped example configs came to be unrunnable (no `cli_command`, and an executable
the allowlist refused) while the whole suite passed.

Driven by two environment variables so a test can script it per iteration:

  EVOLVE_STUB_PLAN   JSON file: {"steps": [{"<path>": "<content>", ...}, ...]}
                     One entry per act() call. Past the end, it writes nothing, which the
                     runtime reports as WORKER_FAILED / "no changes produced".
  EVOLVE_STUB_STATE  A counter file. Created on first use.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def _next_step() -> dict:
    plan_path = os.environ.get("EVOLVE_STUB_PLAN")
    if not plan_path:
        return {}
    steps = json.loads(Path(plan_path).read_text()).get("steps", [])

    state_path = Path(os.environ["EVOLVE_STUB_STATE"])
    index = int(state_path.read_text()) if state_path.exists() else 0
    state_path.write_text(str(index + 1))

    return steps[index] if index < len(steps) else {}


def main() -> int:
    prompt = sys.stdin.read()

    # The request is embedded in the prompt as JSON; an agent has to be able to recover
    # its own identity and stage from it, so parsing it here is part of what is tested.
    request = {}
    start, end = prompt.find("{"), prompt.rfind("}")
    if start != -1 and end > start:
        try:
            request = json.loads(prompt[start : end + 1])
        except json.JSONDecodeError:
            request = {}

    files = _next_step()
    response = {
        "agent_id": os.environ.get("EVOLVE_STUB_AGENT_ID", "worker"),
        "stage": request.get("stage", "execute"),
        "role": request.get("role", "implementer"),
        "content": (
            f"applied {len(files)} file(s)\n"
            f"SELF-REPORT: wrote {', '.join(sorted(files)) or 'nothing'}"
        ),
        "writes": [
            {"path": path, "content": body} for path, body in sorted(files.items())
        ],
    }
    print(json.dumps(response))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
