#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from typing import Any


def _extract_final_message(stdout: str) -> str | None:
    last_message: str | None = None
    for line in stdout.splitlines():
        line = line.strip()
        if not line or not line.startswith("{"):
            continue
        try:
            payload: dict[str, Any] = json.loads(line)
        except json.JSONDecodeError:
            continue
        if payload.get("type") != "item.completed":
            continue
        item = payload.get("item")
        if not isinstance(item, dict):
            continue
        if item.get("type") != "agent_message":
            continue
        text = item.get("text")
        if isinstance(text, str) and text.strip():
            last_message = text.strip()
    return last_message


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Codex exec in JSON event mode for FREE-MAD."
    )
    parser.add_argument("--model", default="gpt-5.3-codex", help="Codex model name.")
    args = parser.parse_args()

    prompt = sys.stdin.read()
    cmd = [
        "codex",
        "exec",
        "--model",
        args.model,
        "--skip-git-repo-check",
        "--json",
        "-",
    ]
    result = subprocess.run(
        cmd, input=prompt, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr or result.stdout)
        return result.returncode

    message = _extract_final_message(result.stdout or "")
    if message is None:
        sys.stderr.write(
            result.stderr or "Codex exec did not emit a final agent message.\n"
        )
        return 1
    sys.stdout.write(message)
    if not message.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
