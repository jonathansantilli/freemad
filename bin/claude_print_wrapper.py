#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run Claude Code in plain print mode for FREE-MAD."
    )
    parser.add_argument(
        "--model", default="opus", help="Claude model alias or full model name."
    )
    # `store_true` with `default=True` can never be turned off. Evolve workers do need
    # to run unattended, so the default stays -- but it has to be switchable.
    permissions = parser.add_mutually_exclusive_group()
    permissions.add_argument(
        "--dangerously-skip-permissions",
        dest="skip_permissions",
        action="store_true",
        default=True,
        help="Run without interactive permission prompts (default).",
    )
    permissions.add_argument(
        "--require-permissions",
        dest="skip_permissions",
        action="store_false",
        help="Keep interactive permission prompts.",
    )
    args = parser.parse_args()

    prompt = sys.stdin.read()
    cmd = ["claude", "-p", "--model", args.model]
    if args.skip_permissions:
        cmd.append("--dangerously-skip-permissions")

    result = subprocess.run(
        cmd, input=prompt, text=True, capture_output=True, check=False
    )
    if result.returncode != 0:
        sys.stderr.write(result.stderr or result.stdout)
        return result.returncode

    output = (result.stdout or "").strip()
    if not output:
        sys.stderr.write(result.stderr)
        return 1
    sys.stdout.write(output)
    if not output.endswith("\n"):
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
