# freemad `evolve` Runtime: Implementation Handoff Plan

**Status:** Ready for implementation
**Revision:** 2 — hardened after design review (2026-08-23); resolutions summarized in section 8
**Audience:** Implementing agent working inside the freemad repository (github.com/jonathansantilli/freemad)
**Supersedes:** the standalone "avagent" TypeScript plan. This plan re-targets that design as a third freemad runtime, in Python, reusing freemad's existing infrastructure.
**Origin:** NVIDIA AVO (arXiv 2603.24517, Agentic Variation Operators) adapted so that freemad's debate machinery can serve as the variation operator, with a deterministic judge as the selection mechanism.

---

## 0. The objective, in plain terms

The user states a goal once, defines how success is measured once, and walks away. The `evolve` runtime is the director: it drives freemad's agents toward the goal, measures every candidate objectively, keeps only proven progress, notices when the effort is stalling or looping, changes course on its own, and stops when the goal is met or the budget is spent. Escalation to a human is the last resort, not the default. Freemad today produces one high-quality artifact per task through deliberation; it has no notion of "measured progress toward an external goal over many generations." That notion is exactly what this runtime adds.

The director loop, one sentence: **agents propose (alone or by debate), the deterministic judge disposes, the lineage remembers, the supervisor redirects, the stop conditions decide when it ends.**

### Division of responsibility (memorize this)

| Question | Answered by | Mechanism |
|---|---|---|
| What is the goal? | Manifest | `goal` prose + judge definition |
| Is this candidate acceptable? | Judge | deterministic scripts, gate predicates |
| Is this candidate better? | Judge | score-vector comparator |
| Does the measurement measure real work? | Lineage prep + judge | `protected_paths` restored from `seed_ref` before judging; hashes stamped into `CANDIDATE_JUDGED` |
| Which of several proposals do we try? | Debate (optional) | freemad trajectory scoring |
| Are we on the right path? | Supervisor detection | pure code over the event history |
| What should change? | Supervisor intervention | a freemad debate over the lineage |
| When do we stop? | Stop conditions | target score, budgets, iteration cap |
| When does a human get involved? | Escalation policy | only after N failed interventions |

Debate judges *quality among proposals*. The judge judges *fitness against the goal*. These are never merged: debate output can choose what to attempt, but only the deterministic judge admits a candidate into the lineage. If quorum approval can ever gate a commit, the design is broken.

---

## 1. What exists in freemad today (verified against the code, 2026-08-23)

The implementer must read these before writing anything. Line counts approximate.

- `freemad/types.py` (193 lines): all StrEnums. `RuntimeMode {DEBATE, AUTONOMOUS}`, `TaskStage`, `TaskStatus` (includes `WAITING_FOR_HUMAN`, `PAUSED`), `TaskEventKind`, `ActionKind`, etc.
- `freemad/config.py` (674): frozen-dataclass config sections (`AgentConfig`, `SecurityConfig`, `BudgetConfig`, `TaskConfig` with `TaskToolPolicyConfig`, ...) parsed from YAML/JSON into one frozen `Config`.
- `freemad/agents/` : `base.py` defines `Agent` ABC with `generate(requirement)`, `critique_and_refine(...)`, `act(TaskRequest) -> TaskResponse`, `health()`, plus command allowlist enforcement. `cli_adapter.py` (233) is the subprocess CLI adapter (stdin/stdout, mode argument, timeout, allowlist, no shell). `claude_agent.py` and `codex_agent.py` are thin presets. `factory.py`/`registry.py` construct agents from config.
- `freemad/orchestrator.py` (632): the debate runtime. Rounds, topologies, quorum deadlines, scoring via `freemad/scoring/scorer.py`, transcripts.
- `freemad/tasks/`: the autonomous runtime. `models.py` (309): frozen dataclasses (`TaskSnapshot`, `StageAttempt`, `WorkItem`, `ArtifactRef`, ...) with `to_dict`/`from_dict` at boundaries. `store.py` (424): `TaskStore` over SQLite, tables `tasks`, `task_events`, `task_artifacts`, `task_work_items`. `orchestrator.py` (786): `TaskOrchestrator` with `run()` looping `step()`, one `_run_<stage>` method per stage, `_wait_for_human`, `_pause`, `_fail`, `_persist`, `_run_command` (policy-bound local commands), `_apply_writes` (policy-bound file writes under `allowed_write_roots`), review-dispute arbitration.
- `freemad/run_events.py`, `freemad/task_events.py`: event emission plumbing; dashboard tails persisted events.
- Conventions (from `AGENTS.md`): immutable dataclasses, StrEnums for all constants, no hard-coded strings internally, serialization only at boundaries. Poetry, pytest, mypy, pre-commit. Follow all of them.

### Reuse / Build / Never-do map

**Reuse as-is (do not reimplement):** `Agent` ABC and both CLI adapters; agent factory/registry; `SecurityConfig` allowlist enforcement; config loading machinery; the debate orchestrator (invoked as a library, unchanged); SQLite store *pattern* (`TaskStore` as the template for a new `EvolveStore`); CLI wiring pattern from `freemad/cli.py` task commands; dashboard event-tailing pattern; `_run_command` and `_apply_writes` policy patterns as reference for judge sandboxing.

**Build new:** everything in section 3: the `freemad/evolve/` package (loop, manifest, judge, lineage, worktrees, context document, supervisor, escalation), new enums in `types.py`, one new config section, new CLI subcommands, new store tables, dashboard trajectory view (last milestone). Store hardening beyond `TaskStore` (WAL journal, `synchronous=FULL`, read-only connections for `status`/`inspect`/report/dashboard) is part of the store work.

**Never do:** modify the debate runtime's semantics; let debate or quorum results gate admissibility; store lineage artifacts in SQLite (git is ground truth for code, SQLite for events/metadata); allow the worker, the debate, or the supervisor to read or alter the judge definition; add population/island/branching evolution; couple `tasks/` and `evolve/` (they are sibling runtimes; shared code lives in `agents/`, `config`, `types`, `security` only).

---

## 2. New types and config (in existing files, following existing style)

### 2.1 `freemad/types.py` additions

```python
class RuntimeMode(StrEnum):
    DEBATE = "debate"
    AUTONOMOUS = "autonomous"
    EVOLVE = "evolve"                      # add

class EvolveRunStatus(StrEnum):
    PENDING = "pending"; RUNNING = "running"; PAUSED = "paused"
    WAITING_FOR_HUMAN = "waiting_for_human"
    COMPLETED = "completed"; STOPPED = "stopped"; FAILED = "failed"

class IterationOutcome(StrEnum):
    COMMITTED = "committed"; REJECTED_GATE = "rejected_gate"
    REJECTED_NOT_BETTER = "rejected_not_better"; WORKER_FAILED = "worker_failed"

class VariationKind(StrEnum):
    SINGLE_AGENT = "single_agent"          # one agent proposes
    DEBATE = "debate"                      # a freemad debate proposes; winner is the candidate

class SupervisorCause(StrEnum):
    STALL = "stall"; LOOP = "loop"

class EvolveStopReason(StrEnum):
    TARGET_REACHED = "target_reached"; MAX_ITERATIONS = "max_iterations"
    WALL_CLOCK = "wall_clock"; BUDGET = "budget"; MANUAL = "manual"
    FATAL_ERROR = "fatal_error"; HUMAN_DECLINED = "human_declined"

class EvolveEventKind(StrEnum):
    RUN_CREATED = "run_created"; RUN_STARTED = "run_started"
    BASELINE_JUDGED = "baseline_judged"
    ITERATION_STARTED = "iteration_started"
    VARIATION_PRODUCED = "variation_produced"      # payload: kind, agent_ids or debate transcript ref, self_report
    CANDIDATE_JUDGED = "candidate_judged"          # payload: score vector, stage outputs, protected-path hashes, duration
    CANDIDATE_COMMITTED = "candidate_committed"    # payload: commit sha, tag
    CANDIDATE_REJECTED = "candidate_rejected"      # payload: outcome, failure_signature
    SUPERVISOR_TRIGGERED = "supervisor_triggered"  # payload: cause, window stats
    SUPERVISOR_DIRECTIONS = "supervisor_directions"# payload: directions[], debate transcript ref
    HUMAN_ESCALATED = "human_escalated"; HUMAN_INPUT_RECEIVED = "human_input_received"
    RUN_PAUSED = "run_paused"; RUN_RESUMED = "run_resumed"
    RUN_STOPPED = "run_stopped"                    # payload: EvolveStopReason
```

### 2.2 `freemad/config.py` addition: `EvolveConfig` (frozen dataclass, one YAML section `evolve:`)

Fields, with defaults where sensible:

- `repo_path: str`, `seed_ref: str = "HEAD"`, `run_branch_prefix: str = "evolve/"`
- `variation: VariationConfig` — `kind: VariationKind = SINGLE_AGENT`; `agent_id: str | None` (single-agent); `debate_rounds: int = 2` and `debate_agent_ids: tuple[str, ...] = ()` (debate variation; empty = all configured agents)
- `judge: JudgeConfig` — `stages: tuple[JudgeStageConfig, ...]` where each stage is `{name, command, timeout_sec, parse: "exit_code" | "json_stdout", provides: tuple[str, ...] = ()}`; `gate: tuple[GatePredicateConfig, ...]` (`{component, op, value}`); `comparator: tuple[ComparatorTermConfig, ...]` (`{component, direction, epsilon, max_regress: float | None = None}` ordered lexicographically); `protected_paths: tuple[str, ...] = ()` (judge-owned files restored from `seed_ref` before every judging); `network: bool = False`; `container: ContainerConfig` — `{enabled: bool = False, runtime: str = "docker", image: str, workdir: str = "/workspace", memory: str | None, cpus: str | None, read_only_mounts: tuple[str, ...] = ()}`
- `supervisor: EvolveSupervisorConfig` — `stall_window: int = 8`; `loop_threshold: int = 3`; `directions_ttl_iterations: int = 4`; `max_interventions_before_human: int = 3`; `intervention: "debate" | "single_agent" = "debate"`
- `stop: EvolveStopConfig` — `max_iterations`, `max_wall_clock_minutes`, `max_total_cost_usd` (enforced only when adapters report cost; otherwise wall clock is the budget), `target: tuple[GatePredicateConfig, ...] | None` (goal-met test over the best score)
- `store_path: str` (defaults beside `task.store_path`), `context_budget_chars: int = 8000`
- `worker_budget: {max_minutes: int, max_turns: int | None}`
- `knowledge_paths: tuple[str, ...] = ()` (read-only reference material; untrusted input, injection channel, mitigated by the gate — document this plainly)

Decided semantics:

- **Extraction is fail-closed.** Each `json_stdout` stage must print exactly `{"components": {...}}` with finite float values. A stage declares what it `provides`; duplicate provision of a component across stages, gate/comparator references to never-provided components (both `ConfigError` at load), and malformed or non-finite output at runtime (stage failure) all fail closed.
- **Admission rule.** A candidate enters the lineage iff the gate passes AND the comparator says strictly better than the incumbent AND no component regresses beyond its `max_regress` versus best-ever. Default `max_regress` = that term's `epsilon`, which bounds cumulative drift: epsilon-vs-incumbent alone is not transitive and permits ratcheting a component arbitrarily far downward across accepted steps.
- **Baseline.** Iteration 0 judges the unmodified seed, tags it `v0`, and does not count against `max_iterations`. If the seed fails its own gate, the run stops `FATAL_ERROR` (payload reason `baseline_gate_failed`). If the seed already satisfies `stop.target`, the run ends `TARGET_REACHED` immediately.
- **Tamper defense.** Before every JUDGE phase, every path in `judge.protected_paths` is restored from `seed_ref`; SHA-256 of each restored file is stamped into `CANDIDATE_JUDGED`. Worker edits to protected paths are computed on, then overwritten — they can never influence a score. Paths *not* listed are worker-editable and carry zero measurement trust; a valid judge design requires every scored component to derive from at least one protected stage. Domains where tests legitimately change (e.g., dependency updates) satisfy this via a protected characterization/benchmark script while project tests stay editable.
- **Budgets.** When `variation.kind: debate`, the debate's inner `BudgetGuard` total time is scoped to the remaining `worker_budget` for that iteration — the outer budget always wins. `max_total_cost_usd` is enforced only when all variation agents report cost; otherwise `evolve validate` warns and wall clock is the effective budget.

Manifest = the freemad config file's `evolve:` section plus the goal string given on the CLI. Hash the canonical JSON of (goal + EvolveConfig) as `manifest_hash`; stamp into every event; re-verify the judge subsection's hash every iteration and stop with `FATAL_ERROR` on change.

---

## 3. New package `freemad/evolve/`

```
freemad/evolve/
  __init__.py
  models.py        # frozen dataclasses: EvolveRunSnapshot, ScoreVector, IterationRecord,
                   #   VariationResult, JudgeVerdict, SupervisorDirective
  store.py         # EvolveStore: SQLite tables evolve_runs, evolve_events (JSON payloads),
                   #   modeled directly on tasks/store.py; append-only events; fsync on append
                   #   (WAL journal, PRAGMA synchronous=FULL, busy_timeout=5000);
                   #   status/inspect/report/dashboard open read-only connections
  lineage.py       # all git operations: worktree add/remove per iteration, commit-on-accept
                   #   with score trailer, tag evolve/<run_id>/v<K>, fast-forward-only run branch,
                   #   orphan worktree cleanup on resume,
                   #   restore_protected(seed_ref, paths) used before every judging
  judge.py         # stage pipeline executor: subprocess per stage in the worktree cwd,
                   #   scrubbed env, network off by default. When judge.container.enabled,
                   #   the stage runs inside a container (container.py) with ONLY the
                   #   worktree bind-mounted, --network=none when judge.network is false,
                   #   --cap-drop=ALL, --security-opt=no-new-privileges, and the operator's
                   #   uid/gid so written files stay git-usable. A missing runtime is a hard
                   #   failure, never a silent fall back to the host,
                   #   short-circuit on gated stage failure, partial outputs recorded;
                   #   json_stdout parsing is fail-closed per the section-2 semantics;
                   #   pure functions evaluate_gate(score, gate) and
                   #   compare_scores(a, b, comparator) with exhaustive unit tests —
                   #   compare_scores decides commits; keep it boring
  variation.py     # VariationOperator protocol: propose(context_doc, worktree, directives) -> VariationResult
                   #   SingleAgentOperator: wraps Agent.act with an 'evolve_iterate' TaskRequest;
                   #     the agent works directly in the worktree under freemad write policy.
                   #     At run creation, verify the agent actually overrides act() (the base
                   #     implementation raises NotImplementedError); otherwise ConfigError.
                   #   DebateOperator: two steps, both counted against the iteration budget.
                   #     Step 1: a debate (library call into freemad.orchestrator) whose
                   #     requirement embeds the context document and demands competing
                   #     implementation plans. Step 2: the origin agent of the winning answer
                   #     immediately act()s in the worktree on a narrow mandate — "implement
                   #     exactly your winning proposal, no redesign". Its diff is the candidate.
                   #     Never parse patches out of debate prose. The debate's scoped Config
                   #     sets budget.max_total_time_sec to the remaining worker_budget so the
                   #     inner guard can never outrank the iteration budget.
                   #   Both operators must produce a self-report (<=300 words:
                   #     tried/worked/failed/why); absent report -> truncated final output.
                   #     Reports feed the graveyard.
  context.py       # generate_context(events, budget_chars) -> str, deterministic, priority order:
                   #   goal; current best (score, sha, iteration); score trajectory table;
                   #   accepted-approach one-liners; THE GRAVEYARD (rejected directions grouped
                   #   by failure_signature with counts and reasons — last section allowed to
                   #   shrink); active supervisor directives. Also failure_signature(verdict):
                   #   normalized stable string (failed predicate name, or first failing stage +
                   #   first stderr line, lowercased, digits stripped)
  supervisor.py    # detection: pure code over recent events (stall: no commit in stall_window;
                   #   loop: loop_threshold consecutive rejections sharing a signature; reset
                   #   counters after intervention). intervention: run a debate whose requirement
                   #   is the extended context (20k chars) + recent failures verbatim + fixed
                   #   instruction to propose 3-5 materially different directions absent from the
                   #   graveyard, JSON output, schema-validated; winner's directions become
                   #   SupervisorDirective rows with TTL. Supervisor is read-only: no worktree,
                   #   no judge access, cannot halt the run; on failure log and continue.
                   #   escalation: after max_interventions_before_human interventions with no new
                   #   best, transition to WAITING_FOR_HUMAN (reuse the tasks-runtime pattern);
                   #   human answer arrives via CLI and is injected as a directive; resume.
  orchestrator.py  # EvolveOrchestrator: mirrors TaskOrchestrator shape — create_run/run/step/
                   #   pause/resume/status; state machine:
                   #   PREPARE -> VARIATION -> JUDGE -> DECIDE -> SUPERVISOR_CHECK ->
                   #   [INTERVENE | ESCALATE] -> STOP_CHECK -> PREPARE | STOPPED
                   #   JUDGE begins by restoring judge.protected_paths from seed_ref (via
                   #   lineage) and stamping their hashes into CANDIDATE_JUDGED;
                   #   iteration 0 judges the unmodified seed (baseline measured, not assumed)
                   #   per the baseline semantics in section 2;
                   #   run() loops step(); resume replays events, rebuilds counters/best,
                   #   cleans orphan worktrees, tolerates a truncated final event row;
                   #   kill -9 anywhere costs at most one iteration
```

CLI (`freemad/cli.py`, mirroring task commands):

```
python -m freemad.cli evolve start  --config cfg.yaml "goal text"
python -m freemad.cli evolve status <run_id> | inspect <run_id> | report <run_id>
python -m freemad.cli evolve resume <run_id> | pause <run_id> | stop <run_id>
python -m freemad.cli evolve answer <run_id> "human guidance text"
python -m freemad.cli evolve validate --config cfg.yaml     # schema + repo clean + judge dry-run on seed; warns when max_total_cost_usd is set but an agent cannot report cost
```

`report` renders trajectory (accepted versions, scores, interventions, escalations, cost) purely from `evolve_events`; deleting derived output and re-rendering must be byte-identical.

---

## 4. The self-regulation contract (what "no babysitting" means, testably)

1. **Progress is proven, not claimed.** Nothing enters the lineage unless the gate passes and the comparator says strictly better (beyond epsilon). The worker's opinion of its own work is recorded but carries zero authority.
2. **The run knows when it is done.** `stop.target` over the best score ends the run with `TARGET_REACHED`. Budgets and caps end it cleanly otherwise. There is no state in which the run needs a human to notice completion.
3. **The run notices it is off course by itself.** Stall and loop detection are deterministic and cheap, evaluated every iteration.
4. **Course changes are generated, not hand-fed.** Interventions come from a debate over the lineage and graveyard; directives expire after their TTL so stale advice cannot steer forever.
5. **Humans are the escalation of last resort.** Only after `max_interventions_before_human` autonomous interventions fail to produce a new best does the run park in `WAITING_FOR_HUMAN`. The question posed to the human is concrete (current best, what was tried, why interventions failed), reusing the tasks runtime's clarification pattern. `HUMAN_DECLINED` is a valid clean stop.
6. **Death is cheap.** Any crash, anywhere, costs at most one iteration on resume.
7. **The measurement cannot be gamed by the measured.** Judge-owned paths are restored from the seed before every judging; worker edits to them never reach a score. Restoration removes the path first, so files *added* inside a protected directory cannot survive it either, and the restored copy is re-verified against `seed_ref` after the judge runs.

8. **The host is not the sandbox.** Judge stages execute worker-authored code. With `judge.container.enabled` they run inside a container whose only mount is the worktree: the operator's `$HOME` — and therefore the on-disk agent-CLI session this project authenticates with — is absent, not merely unreadable. `judge.network: false` becomes `--network=none` rather than proxy-variable hygiene. The runtime must be present; there is no fall back to the host.

---

## 5. Milestones with acceptance criteria (strict order)

### M1: Deterministic spine (no debate anywhere yet)

Scope: types + config section; `models`, `store`, `lineage`, `judge`, `context`; `orchestrator` without supervisor; `SingleAgentOperator` only; `evolve validate`, `start`, `status`; baseline judging — including store durability (WAL, `synchronous=FULL`), protected-path restoration, and the `act()`-capability check.

Proving ground `examples/evolve_toy/` (in-repo): a small Python module with a deliberately slow pure function, a pytest suite (gate), a benchmark printing `{"components": {"ops_per_sec": N}}` (comparator maximizes, epsilon 2%). Both the pytest suite and the benchmark script are listed in `judge.protected_paths`.

Accept when: 10 unattended iterations complete on the toy driven by a scripted deterministic operator that alternates clean and deliberately broken edits, so gate rejection, not-better rejection, and graveyard surfacing are all exercised without LLM nondeterminism (real-LLM runs are manual smoke tests); a tamper test proves a candidate that edits a protected path is judged against the seed copy and cannot move its score; fail-closed parsing tests pass (malformed JSON, missing component at runtime → stage failure; duplicate provision or dangling component reference → ConfigError at load); baseline semantics verified (v0 not counted against `max_iterations`, seed gate failure → `FATAL_ERROR`, seed-meets-target → immediate `TARGET_REACHED`); a rejected signature appears in the next iteration's context document; final best beats the measured baseline; `report` is reproducible byte-identical from events alone; `mypy` and `pytest` clean; unit tests for `compare_scores` (including `max_regress` drift cases), `evaluate_gate`, `failure_signature`, `generate_context` are exhaustive.

### M2: Self-regulation

Scope: supervisor detection + debate-driven intervention + directive TTL; human escalation and `answer`; `resume`/`pause`/`stop`; run-level budgets and all stop reasons; judge-hash integrity check; orphan-worktree cleanup; concurrent read-only CLI access during a live run.

Accept when: kill -9 mid-variation and mid-judge both resume losing at most one iteration (tests send real SIGKILL, not mocked recovery); a read-only `status` query succeeds while a run is live; an impossible-goal run triggers stall, produces debate-sourced directions (event carries the transcript ref), and after the configured interventions escalates to `WAITING_FOR_HUMAN`, then stops cleanly as `HUMAN_DECLINED` via CLI; a judge rigged to fail one stage identically triggers loop detection at the threshold; editing the judge config mid-run stops the run `FATAL_ERROR` on the next iteration; every `EvolveStopReason` is exercised in CI using compressed budgets and a fake clock; one 8+ hour unattended real-agent run is executed manually before milestone sign-off and its declared stop reason recorded in the PR.

### M3: Debate as variation operator (the thesis milestone)

Scope: two-step `DebateOperator` (plan debate, then the winner implements in the worktree); per-run choice of variation kind; a comparison harness script that runs the toy N times under each operator and reports iterations-to-target, commit rate, and cost from the event logs.

Accept when: the toy reaches target under `variation.kind: debate` end-to-end; the committed candidate is the winner's implementation diff, never parsed prose; debate transcripts are linked from `VARIATION_PRODUCED` events and visible via `inspect`; the comparison harness produces a table from real runs (no claim about which wins is required, only that the measurement works).

### M4: Real domain + surfaces

Scope: `examples/evolve_dependency_update/`: a repo with a pinned outdated dependency, goal "update to latest major", judge = build + tests + a protected characterization script (the bridge to pachx-style behavioral verification, without coupling to pachx — the characterization script demonstrates the editable-tests-plus-protected-benchmark pattern); dashboard trajectory view (score over iterations, interventions marked) via the existing event-tailing pattern; README section repositioning freemad as three runtimes (debate = judgment, autonomous = collaboration, evolve = goal-directed optimization) with the debate/judge division-of-responsibility table from section 0; a plain-language security note stating what each layer does and does not buy: env scrubbing covers variables only, `judge.container.enabled` is the boundary that removes the operator's `$HOME` and the on-disk session credentials with it, and an uncontainerised run executes worker-authored code with full host privileges; docs page `docs/evolve-runtime.md`.

Accept when: the dependency example commits the update only on a full gate pass; the dashboard renders a finished run's trajectory; docs build and state the security posture plainly; `OPEN_SOURCE_READINESS` conventions (changelog, citation) updated.

---

## 6. Non-goals (reject scope creep, flag instead of building)

Population/island/MAP-Elites evolution; parallel iterations; debate-scored components inside the score vector (a v2 idea, and even then never in the gate); any coupling between `evolve/` and `tasks/`; push/merge/release side effects (lineage stays on local branches, publishing is manual, matching the autonomous runtime's stance); rewriting or "improving" the debate runtime; TypeScript anything.

## 7. Open decisions delegated to the implementer

Exact `TaskRequest` shape for `evolve_iterate` vs. adding a dedicated `Agent` method (prefer whichever touches `agents/base.py` least); whether `evolve_events` payloads live as JSON columns or a payload table (follow whatever `task_events` does); how the debate requirement template embeds the context document (keep templates in `freemad/prompts/` beside existing ones). Decided since revision 1: the evolve store lives in its own SQLite file, separate from the task store, following the same directory convention.

Everything else in this document is a decision, not a suggestion.

---

## 8. Design-review resolutions (2026-08-23)

Hardening decisions folded into the sections above, listed for traceability:

1. **Judge anti-tampering.** `judge.protected_paths` are restored from `seed_ref` before every JUDGE phase; SHA-256 hashes stamped into `CANDIDATE_JUDGED`; every scored component must derive from at least one protected stage (§0 table, §2.2, §3, §4.7).
2. **DebateOperator made concrete.** Two steps: debate selects an implementation plan; the origin agent of the winning answer implements it in the worktree under a no-redesign mandate. No parsing patches from debate prose (§3, M3).
3. **Comparator drift bounded.** `max_regress` caps per-component regression versus best-ever (default: the term's epsilon), closing the cumulative-ratchet hole left by epsilon-vs-incumbent comparison alone (§2.2, M1 tests).
4. **Score extraction is fail-closed.** Declared `provides`, duplicate/dangling component declarations are load-time ConfigErrors; malformed runtime output is stage failure (§2.2, §3).
5. **Baseline semantics fixed.** v0 excluded from `max_iterations`; seed gate failure → `FATAL_ERROR`; seed-meets-target → immediate `TARGET_REACHED` (§2.2, §3, M1 acceptance).
6. **Budget precedence settled.** Inner debate `BudgetGuard` scoped to remaining `worker_budget`; cost enforcement degrades to wall clock with a validate-time warning when agents cannot report cost (§2.2, §3, CLI).
7. **Durability and concurrency specified.** WAL + `synchronous=FULL` + busy timeout, read-only reader connections, real-SIGKILL resume tests, live-read test (§1 build list, §3, M2 acceptance).
8. **Acceptance criteria made CI-safe.** Deterministic scripted operators and rigged candidates replace "if none occurs naturally"; the 8+ hour run is a manual sign-off gate; stop reasons exercised via compressed budgets and fake clocks (M1–M2).
9. **Capability check added.** Run creation verifies the single-agent target overrides `act()` rather than inheriting the base `NotImplementedError` (§3 variation.py).
