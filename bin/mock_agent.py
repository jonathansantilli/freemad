#!/usr/bin/env python3
import argparse
import sys


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["generate", "critique"])
    ap.add_argument("--force-revise", action="store_true")
    args = ap.parse_args()

    prompt = sys.stdin.read()
    if args.mode == "generate":
        # Simple deterministic output
        print("SOLUTION:\nprint('ok')\n\nREASONING:\nmock agent generation")
        return 0
    else:
        if args.force_revise:
            print("DECISION: REVISE\n\nREVISED_SOLUTION:\nprint('ok')\n\nREASONING:\nrevising as requested")
        else:
            print("DECISION: KEEP\n\nREASONING:\nlooks fine")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

