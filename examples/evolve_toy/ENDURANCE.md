# Endurance run (M2 manual sign-off)

One 8-hour unattended run with real agents. Purpose: prove the runtime ends on a
declared stop reason — never a crash — across a real day cycle (worktree churn,
store growth, supervision, budget enforcement).

The goal is deliberately unreachable (`ops_per_sec >= 1e9` vs a ~2.9k baseline; even
the closed form only reaches ~9M), so the terminator is `max_wall_clock_minutes: 480`.

## One-time setup

Run from the repository root:

    cp -R examples/evolve_toy /tmp/evolve_toy && cd /tmp/evolve_toy   # never init in place
    git init -q && git add -A && git -c user.name=you -c user.email=you@x commit -qm "toy seed"

    # shell env; run the two exports from the freemad repo root
    export REPO=$(git -C /path/to/freemad rev-parse --show-toplevel)
    export PATH="$(cd "$REPO" && poetry env info -p)/bin:$PATH"
    export PYTHONPATH="$REPO"
    alias fm=freemad   # the installed console script; `python -m freemad.cli` also works but warns

## Pre-flight (seconds)

    fm evolve validate --config endurance.yaml
    # expect: {"ok": true, "problems": [], "warnings": []}

## Launch (overnight)

    nohup fm evolve start --config endurance.yaml \
      "make slow_sum as fast as possible" > endurance.log 2>&1 &
    echo $! > endurance.pid

`run_id: <uuid>` appears immediately at the top of `endurance.log`. Save it:

    export RUN_ID=$(head -1 endurance.log | cut -d' ' -f2)

## Check-ins (any time, read-only, safe while running)

    fm evolve status  "$RUN_ID" --config endurance.yaml
    fm evolve report  "$RUN_ID" --config endurance.yaml   # byte-stable trajectory
    git tag --list "evolve/$RUN_ID/*"                       # accepted versions
    git log --oneline "evolve/$RUN_ID" | head               # lineage branch

Emergency stop (still a *declared* reason):

    fm evolve stop "$RUN_ID" --config endurance.yaml

## Morning checklist — record these in the M2 sign-off PR

1. Final line of `endurance.log` is JSON with `"status": "stopped"` and
   `"stop_reason": "wall_clock"` (not an exception/traceback).
2. `fm evolve report "$RUN_ID" --config endurance.yaml` renders cleanly and is
   byte-identical when re-run (deterministic rendering).
3. `git tag --list "evolve/$RUN_ID/*"` — every accepted version tagged;
   worktrees cleaned up (`ls .freemad/evolve/worktrees/$RUN_ID` empty).
4. Note: total iterations, commits vs rejections split, any
   `supervisor_triggered` / `human_escalated` events:
   `fm evolve inspect "$RUN_ID" --config endurance.yaml | grep -c supervisor_triggered`
5. If it parked in `waiting_for_human` overnight (6 interventions without a new
   best): that is correct behavior — either answer with guidance or decline:
       fm evolve answer "$RUN_ID" "focus on algorithmic complexity, not micro-opt"
       # or: fm evolve answer "$RUN_ID" no --decline
   then record the resulting terminal status instead.

Cost note: each iteration spends one Claude API call for variation plus local
pytest/bench. With `worker_budget.max_minutes: 10` worst case is ~48 iterations.
