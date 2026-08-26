# The Evolve Runtime

The `evolve` runtime drives freemad's agents toward a stated goal over many
generations, measuring every candidate with deterministic judges and keeping only
proven progress. You state the goal once, define success once, and walk away:
the run notices stalls and loops on its own, changes course through debate-driven
interventions, escalates to a human only as a last resort, and stops cleanly when
the goal is met or the budget is spent.

One sentence: **agents propose (alone or by debate), the deterministic judge
disposes, the lineage remembers, the supervisor redirects, the stop conditions
decide when it ends.**

## Division of responsibility

| Question | Answered by | Mechanism |
|---|---|---|
| What is the goal? | Manifest | goal prose + judge definition |
| Is this candidate acceptable? | Judge | deterministic scripts, gate predicates |
| Is this candidate better? | Judge | score-vector comparator |
| Which of several proposals do we try? | Debate (optional) | freemad trajectory scoring |
| Are we off course? | Supervisor detection | pure code over the event history |
| What should change? | Supervisor intervention | a debate over the lineage |
| When do we stop? | Stop conditions | target score, budgets, iteration cap |
| When does a human get involved? | Escalation policy | after N failed interventions |

Debate judges *quality among proposals*. The judge judges *fitness against the
goal*. These are never merged: debate output can choose what to attempt, but only
the deterministic judge admits a candidate into the lineage. If quorum approval
could ever gate a commit, the design is broken.

## Quick start

```bash
# 0. Validate config, repo cleanliness, and dry-run the judge on the seed
python -m freemad.cli evolve validate --config evolve.yaml

# 1. Start an unattended optimization run
python -m freemad.cli evolve start --config evolve.yaml "make slow_sum as fast as possible"

# 2. Observe (every subcommand takes --config: it names the store to read)
python -m freemad.cli evolve status   <run_id> --config evolve.yaml
python -m freemad.cli evolve inspect  <run_id> --config evolve.yaml
python -m freemad.cli evolve report   <run_id> --config evolve.yaml

# 3. Intervene or stop
python -m freemad.cli evolve pause    <run_id> --config evolve.yaml
python -m freemad.cli evolve resume   <run_id> --config evolve.yaml
python -m freemad.cli evolve stop     <run_id> --config evolve.yaml

# 4. If escalated, either guide...
python -m freemad.cli evolve answer <run_id> "try memoizing partial sums" --config evolve.yaml
# ...or decline (a valid clean stop; no guidance text needed)
python -m freemad.cli evolve answer <run_id> --decline --config evolve.yaml
```

A runnable proving ground lives in `examples/evolve_toy/` (with a comparison
harness, `compare_operators.py`, that runs the same toy under both variation
operators). A real-domain example lives in `examples/evolve_dependency_update/`.

## How an iteration works

```
PREPARE -> VARIATION -> JUDGE -> DECIDE -> SUPERVISOR_CHECK -> STOP_CHECK
     ^                                                              |
     +--------------------------------------------------------------+
```

1. **VARIATION** — one agent works directly in a git worktree
   (`variation.kind: single_agent`), or a debate selects a plan whose origin
   agent then implements it (`variation.kind: debate`; never parse patches out
   of debate prose).
2. **JUDGE** — configured stages run in the worktree; `json_stdout` stages must
   print exactly `{"components": {...}}` for their declared components; parsing
   is fail-closed.
3. **DECIDE** — a candidate is committed iff: every judge stage succeeded AND the
   gate passes AND the comparator says strictly better than the incumbent (beyond
   epsilon) AND no component regresses beyond `max_regress` versus best-ever. A failed
   stage is a rejection on its own: it short-circuits the pipeline, so the gate would
   otherwise be judging a partial score vector. Accepted candidates are
   committed with an `Evolve-Score:` trailer, tagged `evolve/<run>/v<K>`, and the
   run branch advances fast-forward-only via compare-and-swap.
4. **SUPERVISOR_CHECK** — stall (no commit in `stall_window` iterations) and loop
   (`loop_threshold` consecutive rejections sharing a failure signature) are
   detected from the event log. On detection, a debate proposes 3-5 new
   directions (schema-validated JSON) that become directives with a TTL. After
   `max_interventions_before_human` interventions without a new best, the run
   parks in `WAITING_FOR_HUMAN` with a concrete question.
5. **STOP_CHECK** — `stop.target` reached, iteration cap, wall clock, budget,
   manual stop, fatal error, or human decline. An *absent* `stop.target` means there is
   no goal-met test, not that the goal is met. Iteration 0 measures the unmodified seed
   as baseline, tags it `v0`, and does not count against `max_iterations`.

The manifest hashed into every run is the goal plus the **judge definition** — the
judge is what is immutable mid-run, so resuming with a different `max_iterations` is
fine while retuning a gate is a `FATAL_ERROR`.

Death is cheap: every event is fsynced (SQLite WAL + `synchronous=FULL`) before
any decision is derived from it, so a `kill -9` anywhere costs at most one
iteration on resume. Orphan worktrees are cleaned up automatically.

## Configuration

```yaml
evolve:
  repo_path: .
  seed_ref: HEAD
  variation:
    kind: single_agent        # or debate
    agent_id: worker          # required for single_agent
    debate_rounds: 2          # used by debate variation and interventions
  judge:
    stages:
      - name: tests
        command: python -m pytest tests -q
        timeout_sec: 120
        parse: exit_code
      - name: bench
        command: python bench.py
        parse: json_stdout
        provides: [ops_per_sec]
    gate:
      - {component: ops_per_sec, op: ">", value: 0}
    comparator:
      - {component: ops_per_sec, direction: maximize, epsilon: 2.0}
    protected_paths: [bench.py, tests/]
    network: false            # black-hole proxies for judge stages and worker commands
    env_passthrough: []       # extra env vars a judge legitimately needs
  supervisor:
    stall_window: 8
    loop_threshold: 3
    directions_ttl_iterations: 4
    max_interventions_before_human: 3
  stop:
    max_iterations: 40
    max_wall_clock_minutes: 480
    target:
      - {component: ops_per_sec, op: ">=", value: 5000}
  worker_budget: {max_minutes: 20}   # caps agent and worker-command timeouts, and
                                     # scopes any inner debate's total-time guard
  knowledge_paths: []                # read-only reference material named to the worker
```

`repo_path` and `store_path` are resolved against the **config file's** directory, like
`output.transcript_dir` and `cache.dir`. Debate transcripts land beside the store.

## Running against a real repository

The toy is a fixture. A real repository is bigger, and two things that cost nothing on
twenty files dominate on two hundred:

**Tell the debaters where the code is.** A plan debate that is only told "produce a
file-by-file plan" has to *find* the code first — a live run showed each debater spending
five minutes on `find`/`grep`/`Read` before writing a word, and every generation call
timing out. `knowledge_paths` inlines the named files into the debate and worker prompts
(size-capped, marked untrusted):

```yaml
evolve:
  knowledge_paths:
    - src/hot_module.py
    - tests/test_hot_module.py
    - bench/bench_hot.py        # let the debaters see what they are scored by
```

**Take tools away from the thinking steps.** Even with the code in front of it, an agent
that *has* tools will explore. A debate's `generating` and `critique` calls are thinking;
only the implementation step (`act()`) needs a filesystem. Per-mode flags do exactly this:

```yaml
agents:
  - id: worker
    type: claude_code
    cli_command: "claude -p --model sonnet --dangerously-skip-permissions"
    timeout: 720
    cli_mode_flags:
      generating: ["--tools", ""]
      critique:   ["--tools", ""]
```

**Budget for what a real call costs.** With tools off, one generation call on a real
optimisation problem measured **451 seconds** — that is how long the model thinks, and it
cannot be prompted away. A one-round, two-agent debate is about five such calls per
iteration, so ~40 minutes; set `agents[].timeout` and `evolve.worker_budget.max_minutes`
to match. `evolve validate` does this arithmetic and tells you what to change when the
numbers cannot fit.

What a real run then looks like: the freemad package itself, goal "make
`freemad.scoring.ScoreTracker` as fast as possible", a protected oracle pinning the
paper's scoring arithmetic exactly, the module's own tests as the editable gate. Two
agents proposed different plans, one won and implemented it — cached weights, incremental
contributor counts, `__slots__`, and the one caller in `orchestrator.py` that `__slots__`
broke, fixed. The oracle confirmed the arithmetic was unchanged, and 26,230 → 28,463
debates/sec went into git as `v1`.

## Watching a run

```bash
python -m freemad.cli evolve start --config evolve.yaml "goal" &   # run_id goes to stderr

freemad-dashboard --evolve-store .freemad/evolve/evolve.db
# /evolve            every run, newest state
# /evolve/<run_id>   score at each accepted version, with supervisor interventions
#                    marked on the chart and human escalations in red
# /api/evolve        the same data as JSON
```

`--evolve-store` is resolved against the **dashboard's** working directory, while the
CLI resolves `store_path` against the **config file's**. If the dashboard shows "No
evolve runs yet", that mismatch is the usual reason — pass the same absolute path the
config resolves to.

The chart's x-axis is iteration number, so an intervention at iteration N lines up with
the accepted versions around it. Each series is normalised against its own observed
range, so a component that is minimised, negative, or missing from some iterations still
plots sensibly.

## Security posture (read this)

- **Container isolation is the boundary. Turn it on.**

  ```yaml
  evolve:
    judge:
      container:
        enabled: true
        image: "python:3.13-slim"   # must carry whatever your stages need
        runtime: docker             # or podman
        memory: "2g"
        cpus: "2"
        read_only_mounts: []        # "host/path" or "host/path:/in/container"
  ```

  The stage runs with **only the worktree mounted**. Your `$HOME` is not mounted, so
  `~/.claude/.credentials.json` and `~/.codex/auth.json` — the sessions this project
  actually authenticates with — are *absent*, not merely unreadable. `judge.network:
  false` becomes `--network=none`, which covers raw sockets, DNS and ssh rather than only
  clients that honour proxy variables. Privileges are dropped (`--cap-drop=ALL`,
  `--security-opt=no-new-privileges`, read-only root with a `/tmp` tmpfs), and the stage
  runs as your uid/gid so the files it writes stay usable by git on the host.

  If the runtime is missing, the run **fails**. It does not fall back to the host: a
  security control that silently degrades is worse than none, because you believe it is
  on. `evolve validate` checks the runtime up front, and warns when isolation is off.

- **Without a container, judge stages execute worker-authored code with full host
  privileges** — reading `$HOME` included. Env scrubbing removes variables; it cannot
  help here, because the credentials are files. Run uncontainerised only against
  repositories you fully trust.
- **Environment scrubbing is real, and it is narrow.** Judge stages and
  worker-proposed commands get an environment built from an allowlist
  (`freemad/evolve/sandbox.py`): enough to start a process and run an interpreter, and
  no variable that carries a secret. Add anything a judge legitimately needs to
  `judge.env_passthrough`.

  Be precise about what that does and does not buy. It covers processes *the runtime*
  launches. It does **not** cover the agent adapter itself (`freemad/agents/cli_adapter.py`),
  which by construction holds the credentials it needs to reach its model — so an agent
  can read its own environment and write a secret into a file it authors. And `HOME` is
  on the allowlist, so anything a judge stage runs can still read `~/.claude/`,
  `~/.aws/`, `~/.netrc` and friends. Scrubbing raises the cost of an accident; it is not
  a boundary against a determined agent. Treat an evolve run as executing untrusted code
  as your user, because it does.
- **`judge.network: false` (the default) black-holes the proxy variables** and clears
  `NO_PROXY`, so well-behaved HTTP clients fail fast. It does not stop raw sockets.
  There is no network sandbox: container-based isolation is documented as the
  production posture and is deliberately not built.
- **Tamper defense**: paths listed in `judge.protected_paths` are *removed and
  restored* from `seed_ref` before every judging phase, and their SHA-256 hashes are
  stamped into `CANDIDATE_JUDGED` events. Removal matters: `git checkout <ref> -- <dir>`
  only overwrites paths that exist in the ref, so without it a worker could drop a
  `conftest.py` into a protected `tests/` and neutralise the suite. After restoration a
  protected path is byte-identical to the seed — editing *and* adding are both defeated.
  Paths *not* listed are worker-editable and carry zero measurement trust; a valid judge
  design requires every scored component to derive from at least one protected stage,
  and `evolve validate` warns when a scoring stage does not appear to reference one.
- **Knowledge paths are an injection channel**: anything under
  `evolve.knowledge_paths` is untrusted input read by agents; the gate is the
  mitigation, not the prompt.
- Lineage stays on local branches; nothing is pushed, merged, or released by the
  runtime.
