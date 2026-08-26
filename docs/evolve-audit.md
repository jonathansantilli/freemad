# Evolve runtime — pre-commit audit

**Date:** 2026-08-24
**Scope:** the uncommitted change set on `main` (8 modified files, `freemad/evolve/`, `tests/pkg_mad/evolve/`, `examples/`, `docs/evolve-runtime.md`)
**Traced against:** `evolve.md` (the implementation handoff plan, rev. 2 — "everything else in this document is a decision, not a suggestion"), `docs/evolve-runtime.md`, `AGENTS.md`

Repros for findings B1–B4 and H1 were written and run; they are reproduced inline.

## Status (updated 2026-08-24, same day)

**Everything in this audit is implemented.** 293 tests pass, `mypy` clean across 65 files,
`ruff` clean across the change set, evolve coverage 82% → 90% (`report.py` 0% → 66%,
`context.py`/`store.py`/`sandbox.py` 100%). Regression tests live in
`tests/pkg_mad/evolve/test_audit_regressions.py`, `test_spec_deltas.py`, `test_sandbox.py`
and `test_cli.py` — the CLI had no tests at all before.

### Blockers

| ID | Finding | Fix |
|---|---|---|
| B1 | Judge fails open on a failed stage | `failed_stage` rejects unconditionally, in the iteration, the baseline and `validate` |
| B2 | Regression bound measured against the baseline | Measured against `best_score`; `incumbent` and `best_ever` collapsed into one |
| B3 | Additions survive protected-path restore | Path removed before checkout; existence tested against the ref, not the working tree |
| B4 | Crash between tag and branch-advance wedges the run | `git tag -f`; the post-variation body moved under `try/finally` |
| B5 | Empty `stop.target` read as "already met" | *(found while writing the B2 test)* `target_met` returns False on an empty target |

### High

| ID | Finding | Fix |
|---|---|---|
| H1 | Addition-only edits reported as no changes | `-uno` dropped; `diff_stat` uses `--intent-to-add` so the stat matches what is committed |
| H2 | Rebuilt escalation counter never reset | Rebuild mirrors the live path: a commit or human input clears it |
| H3 | `answer()` left the counter at the limit | Resets it, so autonomous interventions resume |
| H4 | Env scrubbing and `judge.network` documented but absent | New `freemad/evolve/sandbox.py`: allowlisted environment for judge stages and worker commands, black-holed proxies when `network: false`, `judge.env_passthrough` as the escape hatch |
| H5 | A stray worker path killed the run | New `VariationPolicyError` → `WORKER_FAILED`; `ConfigError` stays fatal |

### Spec deltas

| ID | `evolve.md` | Fix |
|---|---|---|
| S1 | §2.2 the outer worker budget always wins | `scope_worker_budget` caps agent and command timeouts (the adapter takes their *max*, so both come down); `scope_debate_budget` scopes an inner debate to the remaining iteration time |
| S2 | §2.2 re-verify the *judge subsection's* hash | Manifest is goal + judge only, so resuming with a different `max_iterations` no longer fails |
| S3 | §2.2 iteration 0 tags the seed `v0` | Baseline tags it |
| S4 | §3 operators produce a self-report | `SELF-REPORT:` marker asked for and extracted, falling back to truncated output |
| S5 | §2.2 every scored component derives from a protected stage | `evolve validate` warns when a scoring stage references no protected path (a heuristic, hence a warning) |
| S6 | §7 templates live in `freemad/prompts/` | New `freemad/prompts/evolve.py` |
| S7 | §3 `answer` CLI | `--decline` takes no guidance text |
| S8 | M2 every stop reason exercised | Resolved as documented, not implemented: `BUDGET` has no trigger because no adapter reports cost, which is exactly what §2.2 prescribes. The test now says so and fails if something starts emitting it |

### Medium and Low

`shlex.split` for judge commands; `status`/`inspect` take `--config` and read the run's own
store; `repo_path`/`store_path` resolve against the config file; dashboard gained an
`/evolve` index, a nav link, `--evolve-store`, and a chart driven by whatever components the
judge declares; `EvolveEventKind` replaces raw string comparisons; `IterationRecord.from_dict`
added; `report._fmt` annotated; dead code removed (`list_run_files`, `verify_manifest_judge_hash`,
`Lineage.worktree_is_dirty`, `first_failing_stage`, `gate_failure_signature_from_failures`,
`result_origin_ids` — the last replaced by real debate agent ids); `directions_given += 0` and
the no-op ternary gone; transcripts anchored beside the store; the supervisor saves the whole
intervention, not just its conclusion; `context_budget_chars` is a real cap; the `bin/`
wrapper's permissions flag is switchable; `knowledge_paths`, `debate_agent_ids`,
`supervisor.intervention: single_agent` and `interventions_without_new_best` all do something
now. `.freemad/` gitignored; the embedded `examples/evolve_toy/.git` moved out of the tree.

### Found while fixing, and fixed

- **B5**, above.
- **The toy proving ground was measuring timer granularity, not code.** `slow_sum` slept for
  a microsecond per iteration, so the unmodified seed scored anywhere from 8 to 5022 ops/sec
  against its own target of 5000 — whether a run ended instantly at `TARGET_REACHED` or
  optimized for ten iterations was a coin flip, and an epsilon of 2.0 ops/sec against that
  spread is noise. Now CPU-bound: baseline ~2.9k ± 5%, closed form ~11M, target 100k,
  epsilon 50.
- **The dependency-update example could not start.** Its gate and its target were both
  `compat_score >= 100`, but the seed scores 50 (1.x vendored lib), and §2.2 stops a run
  `FATAL_ERROR` when the seed fails its own gate. The gate is now the floor (50, behaviour
  preserved) and the target carries the goal (100, upgraded *and* behaviour preserved) —
  which is the distinction that example exists to teach.

Both examples now pass `evolve validate` from any working directory.

---

## Round 2 — adversarial review of the fixes (2026-08-25)

Five reviewers were pointed at the round-1 fixes and told to refute them. They found
**two blockers introduced by those fixes**, one long-standing P0 that round 1 missed, and
a proving ground that could not measure. Regressions live in
`tests/pkg_mad/evolve/test_adversarial_findings.py` and `test_sandbox.py`.

### Introduced by the round-1 fixes

| Finding | What happened |
|---|---|
| **Path escape in `restore_protected`** | The B3 fix made restoration *delete* before checking out. `Path.is_symlink()` lstats only the final component and `shutil.rmtree` refuses only when the path *itself* is a link — so a worker that turned a **parent** component into a symlink made `is_dir()` follow it and handed `rmtree` a directory outside the worktree. Reproduced end to end with one allowlisted `python -c`: operator data deleted, run continuing silently. The pre-fix code was non-destructive, so this was strictly a regression. `_reject_escaping_path` now walks the components and refuses first, and tampering fails the *iteration*, not the run. |
| **epsilon 50 was half a sigma** | The retuned toy claimed "above run-to-run noise". Measured over 25 runs: median 2771, sigma 102, spread 368. Two draws of identical code differ by more than 50 about 73% of the time — a run committed a "better" version whose entire diff was two `.pyc` files. Worse, `commit_candidate` had no empty-index guard, so a noise-accepted no-op made `git commit` exit 1 and killed the run (an intermittent suite failure, ~1 in 6). Now epsilon 400 (~4 sigma), and `NoChangesToCommit` rejects the iteration. |
| **H5 was incomplete** | Four worker payloads still escaped as non-`VariationPolicyError` and killed the run *before* any event was written — so `status` said `running` forever and `resume` replayed the same iteration: `path="."`, `.git/config`, an unbalanced quote (`shlex.split` sat outside the `try`), and an allowlisted binary that is not installed. |
| **`network: true` stripped the proxy variables** | A network-enabled stage had no route out from behind a corporate proxy — and the test asserted that as correct behaviour. |

### Missed by round 1

| Finding | What happened |
|---|---|
| **`evolve pause` and `evolve stop` never worked** | Neither subparser defined `--config`, but the branch they fall into reads `args.config`. Every invocation was an `AttributeError` swallowed by the CLI boundary. Documented as working in three places. Round 1 reviewed this exact function and did not notice. |
| **`answer`/`decline` rewrote terminal runs** | `decline` turned a `completed`/`target_reached` run into `stopped`/`human_declined`; `answer` resurrected it and kept iterating. Both now require `WAITING_FOR_HUMAN`. |
| **`seed_ref` was symbolic** | `_path_in_ref` resolved it in the main repo while `git checkout` resolved it in the worktree — different commits for the default `HEAD` — and it moved under a running optimization. Now pinned to a sha at `create_run`. |
| **`_str_tuple` accepted a bare string** | `protected_paths: bench.py` became eight one-character entries, each individually valid: validation passed while nothing was protected. |
| **Protected hashes were stamped, never compared** | Restoration is a point in time, and `subprocess.run(timeout=)` reaps only the direct child, so a daemonised grandchild could rewrite a protected file before the judge read it. Now re-verified against `seed_ref` with git after judging. |
| **`validate` blessed the exploitable config** | `pytest tests` + `protected_paths: [tests/]` satisfied the "derives from a protected stage" check — and that is exactly the shape a root-level `conftest.py` owns. A second warning now names the steering files. |
| **Worker failures were invisible to the supervisor** | The graveyard and `detect_loop` both filtered to the two `REJECTED_*` outcomes, so a run wedged on `WORKER_FAILED` never tripped loop detection. |
| **Context truncation dropped ACTIVE DIRECTIVES** | Past ~90 iterations the trajectory table alone overflowed the budget and `enforce_size` cut the tail — so on exactly the long unattended runs the supervisor exists for, its directives silently stopped reaching the worker. The table is now capped. |
| **The dependency example's README overstated its gate** | `>= 50` also admits 2.x at 3/5 and 4/5 goldens — broken behaviour that still beats the seed. What rejects those is stage *ordering*, not the gate. The README now shows the lattice and says so. |
| Others | Judge-only manifest hashing let `stop.target` be weakened on resume (now a `fitness_hash` over judge + target, separate from the stamped manifest); `_persist_intervention_count` and `_escalate` bypassed `_merge_with_fresh` and could clobber an external pause/stop; `debate_agent_ids` naming no enabled agent burned every iteration silently; the `act()` capability check ran mid-run instead of at creation; `remove_worktree` raising inside `finally` replaced a pending return; the worktree was held across the supervisor's debate; a crash between the commit event and the snapshot write double-committed an iteration (resume now reconciles); the toy README stated the *opposite* of the path-resolution behaviour; ENDURANCE.md had four broken commands and a hardcoded personal venv path. |

### Tests that protected nothing

A reviewer mutation-tested every round-1 fix: reinstate the bug in a scratch copy, check
the claimed regression test actually fails. **All 11 named mutations were killed**, so
those claims hold. Two *unlisted* probes survived — tests of mine that asserted nothing:

- `test_worker_timeouts_are_capped_at_the_iteration_budget` asserted `timeout <= 60.0`
  with `worker_budget.max_minutes: 1`. The config defaults are already `60.0` and
  `60000`, so the assertion held *before* `scope_worker_budget` ran: replacing the whole
  function with `return cfg` left all five tests green. S1's worker-budget half had zero
  coverage. The fixture now starts at 3600s and asserts the exact scoped values.
- The protected-path test compared `restore_protected`'s output to a **second call** of
  `restore_protected`. Stamping a constant kept it green. It now compares against an
  independently computed SHA-256 of the seed content.

Both mutations are now killed — verified, not assumed. Also fixed: an escape-path
assertion that checked the wrong directory (`../../escaped.py` resolves under the
worktrees dir, not `tmp_path`); a knowledge-block assertion pinned to a bare string
literal rather than the template; `evolve report` covered only a run with one event and
no iterations, so M1's byte-identical criterion was effectively unverified — it now
renders a real trajectory with a commit, a rejection and a no-op, from two independent
stores. And `supervisor.intervene` still ignored a configured `context_budget_chars`
below 20000, because the round-1 "fix" made 20000 a floor rather than using the value.

### Spec-fidelity round

The spec reviewer's headline finding — that the regression bound was still cumulative —
was against a tree from before `_best_envelope` landed. I re-ran its exact 10-step
scenario against current code: one commit, drift bounded at a single `max_regress`, every
later candidate rejected as "regression bound violated". Its independent derivation (a
per-component high-water envelope) is what `_best_envelope` implements, so that reads as
corroboration. It was also wrong that `freemad/__init__.py:12`'s E402 is in the change
set — it is present at HEAD.

Its non-stale findings are fixed:

- **The `evolve validate` heuristic blessed almost anything.** The `candidate in
  prot.parents` clause treated an *ancestor* token as evidence, and `.` is an ancestor of
  every relative path — so `pytest . --benchmark-json=o.json` was silently approved
  against any protected path at all. Ancestors no longer count.
- **Scored components with no `protected_paths` is now a load-time error.** That case
  needs no heuristic: every scorer is worker-editable.
- **No escape may leave a run advertising `running`.** A `LineageError` out of
  `_run_iteration` left `status=running`, `stop_reason=None`, no `RUN_STOPPED` event —
  so an unattended run stopped without ever saying so (§4.2). `step()` now converts it to
  a fatal stop.
- **Events are stamped with the manifest hash** (§2.2's third obligation, previously
  unmet — events carried no configuration identity at all).
- **Four `Literal` aliases became `StrEnum`s** (`GateOp`, `CompareDirection`,
  `JudgeParseMode`, `SupervisorIntervention`), with the six raw-literal comparison sites
  converted. AGENTS.md requires this and `VariationKind` in the same section already did
  it, so the convention was applied selectively — by me.
- **The escalation question moved into `freemad/prompts/evolve.py`** and no longer
  interpolates a Python list repr into text a human reads.
- `worker_budget.max_turns` now warns in `validate`, matching the precedent §2.2 sets for
  `max_total_cost_usd`.

Known and not fixed, recorded rather than quietly dropped: `render_report` reads the
`evolve_runs` table as well as the event log, so M1's "byte-identical **from events
alone**" is met in practice but not by construction; `worker_budget.max_minutes` bounds
each call rather than the iteration, so N worker commands can consume N x the budget; and
several M1/M2/M3 acceptance criteria remain untested (a 10-iteration alternating-operator
run, a mid-*judge* SIGKILL, every stop reason exercised via a fake clock, cost columns).

### Round 3 — everything remaining (2026-08-25)

The list of "open" items from round 2 is now empty. What was closed:

| Area | Change |
|---|---|
| `allowed_write_roots` | Honoured by evolve, mirroring `TaskOrchestrator._is_under_roots`. It was enforced under `freemad task` and silently dropped under `freemad evolve` against the same config. |
| Event-store redaction | Payloads are redacted on the way in, recursively. `final_output`, `self_report` and judge stdout/stderr were persisted verbatim to SQLite, the report and the dashboard while the console redacted them. |
| Pathspec magic | `protected_paths: ["tests/*"]` and `:!tests` are rejected. Git glob-expanded them while the Python side treated them literally, so the entry looked protected and protected nothing. |
| `env_passthrough` denylist | `LD_PRELOAD`, `PYTHONPATH`, `PYTHONSTARTUP`, `NODE_OPTIONS` and friends are refused: passing them through hands a worker the interpreter the judge runs. |
| Supervisor counters | Detection is bounded below by the last intervention (§3, "reset counters after intervention"). Stall was re-firing on pre-intervention evidence, reaching `WAITING_FOR_HUMAN` about twice as fast as configured. |
| Dashboard series | `cumulative_best` was `{**best, **score}` — the last-accepted value per component, neither a maximum nor a minimum. Now each accepted version reports its own score, on an x-axis in **iteration** space, with interventions and escalations marked on the chart. |
| Report | `render_report` is event-sourced. It read the `evolve_runs` row for goal, status and best — derived state — so M1's "byte-identical **from events alone**" was not met by construction. A test now deletes the row and re-renders. The `# cost` section §3 asks for is present and honestly empty. |
| Worker budget | `run_commands_policy` spends a shared iteration budget instead of giving each command the full per-call cap, so N commands can no longer consume N x `worker_budget`. |
| `restore_protected` | Validates every protected path before destroying any, so a raise partway through cannot leave the set half-restored. |
| Model symmetry | `EvolveEvent.from_dict` and `SupervisorDirective.to_dict`/`from_dict` added; the store reconstructs through them. |
| Truncation markers | Nine bare slices became `enforce_size` calls, so a human whose 2000-character guidance is cut is told. |
| Dead code | `_supervisor_check`'s `new_best` parameter removed. |

### Found while doing it

Two more defects surfaced from writing the ten-iteration acceptance test — both mine,
both from round 2:

- **`verify_protected` fired on the judge's own leavings.** Build artifacts were filtered
  from the *untracked* half only. Without a `.gitignore` in the target repo,
  `commit_candidate`'s `git add -A` committed `tests/__pycache__/*.pyc` into the lineage;
  from the next iteration those were *tracked* differences from the seed, so every
  candidate after the first was rejected as "protected path tampering" forever. The
  filter now applies to both halves.
- **The lineage was accumulating bytecode.** `commit_candidate` now excludes interpreter
  and tool caches by pathspec, so a target repo without a `.gitignore` does not get its
  `.pyc` files committed as part of every accepted candidate.

### Acceptance criteria now covered

Ten unattended iterations alternating clean and broken edits, ending on
`MAX_ITERATIONS` with rejections surfacing in the next context document (M1); the report
rendered from events after the runs row is deleted (M1); every reachable stop reason
driven to its **real** trigger, wall clock via a fake clock (M2) — with a test that fails
if `BUDGET` ever gains a trigger, since §2.2 says it cannot have one until an adapter
reports cost; a real `SIGKILL` **mid-judge**, not mid-variation, resuming to a declared
state (M2); a cost column in the comparison harness (M3); and the dependency example
rejecting a version bump that breaks goldens (M4).

Genuinely out of scope and unchanged: the agent adapter holds its own credentials by
construction; `HOME` passthrough leaves `~/.claude/` readable to judge stages;
allowlisted commands are arbitrary code execution; `judge.network: false` does not stop
raw sockets, ssh or DNS. All four are stated plainly in the security posture rather than
papered over. The 8-hour endurance run remains a manual sign-off gate.

### Round 4 — the examples could not launch an agent (2026-08-25)

Found by asking a plain question: does evolve authenticate by subscription rather than an
API key? It does — and checking that turned up a defect nothing else had caught.

`freemad` never reads an API key. `security.api_key_source` and `api_key_name` are
declared in `config.py` and read nowhere; no `ANTHROPIC_API_KEY`/`OPENAI_API_KEY`
reference exists in the package. The adapter shells out to `claude` / `codex`, which
authenticate with their own logged-in session stored on disk.

Checking how the examples wire that up: **all three shipped configs were unrunnable with
a real agent.**

- `evolve_toy/evolve.yaml` and `evolve_dependency_update/evolve.yaml` declared
  `type: claude_code` with **no `cli_command`**. `CLIAdapter._run_cli` raises
  `ConfigError("agent ... missing cli_command")` on the first `act()`.
- `endurance.yaml` named `python ../../bin/claude_print_wrapper.py`, wrong twice:
  `python` is not in `security.cli_allowed_commands` (default `zen, zen-mcp, claude,
  codex`), and the relative path does not exist once the example is copied out, as that
  example's own README instructs.

None of this surfaced because **`evolve validate` exercises the judge and never the
agent**, and because `SingleAgentOperator` turns an agent exception into `WORKER_FAILED`
— so a run burned its whole iteration budget doing nothing and stopped cleanly, with no
crash to notice. The 8-hour endurance run would have produced a night of failures.

All three now call `claude` directly, which is already allowlisted and needs no path
resolution. `test_acceptance_criteria.py` pins both properties: every enabled agent in a
shipped example has a `cli_command` whose executable the allowlist accepts, and no
API-key path exists in the package.

**This also re-weights the security posture.** Environment scrubbing protects against
env-borne secrets — but this project's own credentials are *disk*-borne
(`~/.claude/.credentials.json`, `~/.codex/auth.json`). `HOME` passthrough hands judge
stages a readable path to exactly those files, which makes HOME isolation the control
that matters most here, not a nice-to-have. It remains unimplemented and is the one open
item that is genuinely available.

### Round 5 — stale model references (2026-08-25)

Checked every model reference in the repo against the current Anthropic lineup.

**Claude side: nothing was retired.** `opus` / `sonnet` / `haiku` are Claude Code CLI
*aliases*, not model IDs — they resolve to the current model of each tier, so they cannot
go stale and need no maintenance. Kept as aliases deliberately. The one change: the evolve
examples were on `sonnet` because I picked it unprompted in an earlier turn; a worker whose
whole job is editing code should default to `opus`, and downgrading a tier is the
operator's call, not a silent one.

**Codex side: stale, and the repo contradicted itself.** `bin/codex_exec_wrapper.py`
already defaulted to `gpt-5.3-codex`, while `README.md` and all three `config_examples/`
still pinned `gpt-5.1`, `gpt-5.1-codex` and `gpt-5.1-codex-mini`; `ALL_KEYS.yaml` used
`gpt-4o` in a syntax comment. Someone updated the wrapper and left the configs behind.
All now on `gpt-5.3-codex`.

Collapsing three agents onto one model would have made them identical, so they are now
differentiated by what actually varies — `model_reasoning_effort` high / medium / low — and
the ids say so (`codex-high`, `codex-medium`, `codex-low`) instead of naming a model
version that will age again. Every edited config was re-loaded and re-validated.

### Round 6 — the end-to-end test was never end-to-end (2026-08-25)

Jonathan's diagnosis, and it was correct: bugs kept surfacing only when he pointed at
something, which meant the coverage had a structural hole rather than a thin patch.

It did. **Every evolve test substituted a Python class for the agent** — `register_agent`
plus a `_resolve_agent` monkeypatch — so nothing between the orchestrator and the worker
was ever executed: `AgentFactory`, `_ensure_allowed`, the subprocess spawn, the task
prompt, the JSON response parse. The only adapter test in the repo
(`test_smoke_adapters.py`) is `@skipUnless(SMOKE=1)`, covers the *debate* runtime rather
than evolve, and `bin/mock_agent.py` speaks only `generate`/`critique` — it has no
`act()` support, which is the protocol evolve uses.

So config wiring was invisible to the suite **by construction**. That is the root cause of
round 4: three shipped configs could not launch an agent at all while 333 tests passed.

Closed with two pieces:

- `bin/evolve_stub_agent.py` — a scriptable stub *executable* that speaks the real `act()`
  protocol: reads the task prompt from stdin, parses its own identity out of it, emits a
  JSON `TaskResponse` with `writes`. Driven per-iteration by `EVOLVE_STUB_PLAN`.
- `tests/pkg_mad/evolve/test_end_to_end.py` — seven runs driven from a **config file on
  disk** through `CLIAdapter` into that stub, with no monkeypatching. Asserts a real
  commit lands in git (`git show <sha>:impl.py`), that the worker really was a subprocess
  (state only it could have written), that the self-report survives prompt → subprocess →
  JSON → parse → extraction, and that a broken edit is rejected while the run continues.

### Found by writing it

`create_run` verified the agent implements `act()` but never that it could be **launched**.
A missing `cli_command` or a non-allowlisted executable still failed inside `act()`, became
`WORKER_FAILED`, and burned the whole iteration budget in silence. New `require_launchable`
turns both into a `ConfigError` at run creation, where the operator can act on it.

Mutation-checked: removing `require_launchable` fails both wiring tests.

### Round 7 — actually using it (2026-08-25)

Jonathan's follow-up: tests are not use. So I ran the CLI against the **live `claude`
agent** on his subscription, following `examples/evolve_toy/README.md` verbatim. Two more
defects, neither reachable by any test I had written.

**1. Every iteration timed out at 60 seconds.** `CLIAdapter._run_cli` uses
`max(agent.timeout, security.cli_timeout_ms, budget.max_agent_time_sec)` — which default
to 60s, 60s and 20s. The toy and dependency examples set none of them, so a real model
doing a code edit never finished. Seven agent calls, seven timeouts, zero commits; the run
then spent its whole iteration budget on `WORKER_FAILED` and stopped *cleanly* on
`max_iterations`. No crash, no error, `evolve validate` clean, 340 tests green.
`endurance.yaml` was the only config that set `timeout: 600`, which is why it alone would
have worked. Both examples now set it, with `worker_budget` raised so the outer cap does
not clamp it back down.

Note the shape of this: the round-6 end-to-end tests drive a **stub executable**, which
returns instantly, so they could never have caught it. The regression is therefore a
config-shape assertion — the effective worker timeout for a shipped example must exceed
60s — not another run.

**2. The default redaction pattern eats ordinary words.** `sk-[A-Za-z0-9_\-]+` has no word
boundary, and "ta**sk-execute**" matches: log lines read `mode=ta[REDACTED]`. Cosmetic in
logs — but round 3 wired that same redactor into the event store, so it was rewriting
`self_report`, `final_output` and judge output on their way into SQLite. Now anchored with
`\b` and a minimum length.

**The run after the fixes did what the runtime is supposed to do:**

```
baseline    2,512.73 ops/sec
best (it2)  8,952,896.87 ops/sec        3563x
stop_reason target_reached
tags        .../v0 (seed), .../v2 (accepted)
commit      Evolve-Score: {"ops_per_sec": 8952896.87}
worktrees   0 left
```

Iteration 1 was rejected as "no changes produced" and iteration 2 committed, so the reject
path ran too. `status`, `inspect`, `report` (byte-identical across invocations) and `stop`
(on a live run) were all driven against it, and the dashboard rendered the run at
`/evolve` and `/evolve/<id>` with a real chart.

One unplanned observation worth recording: the model's own commit message explains that it
considered `lru_cache`, measured it at ~2.7x *above* the closed form on this benchmark, and
rejected it because the gain came entirely from the benchmark's 100% cache-hit rate. It
declined to game the judge. That is a property of the model, not of anything in this
runtime — but it is the failure mode `protected_paths` exists for, so it is worth knowing
it is not the only line of defence.

### Round 8 — container isolation, promoted from non-goal to capability (2026-08-25)

`evolve.md` section 6 listed container-based judge isolation as an explicit non-goal
("document as production posture only"). Jonathan overrode that decision — the spec is
updated so it and the code agree, rather than the code quietly exceeding it.

**Why it was the right call.** Env scrubbing is the wrong layer for this project. Auth is
the agent CLI's own subscription session, stored on disk under `~/.claude/` and
`~/.codex/`. Stripping variables buys nothing while `HOME` names the operator's home
directory, and `HOME` cannot simply be dropped — processes need it. The credential is a
*file*, so only a filesystem boundary closes it.

`freemad/evolve/container.py` wraps judge stages and worker-proposed commands:

- **only the worktree is mounted** — `$HOME` is absent, not unreadable
- `judge.network: false` becomes `--network=none`, covering raw sockets, DNS and ssh
  rather than only clients that honour proxy variables
- `--cap-drop=ALL`, `--security-opt=no-new-privileges`, read-only root with a `/tmp` tmpfs
- the operator's uid/gid, so files written inside stay usable by git outside
- a unique container name, so a stage killed by `timeout` is killed rather than left
  holding the bind-mounted worktree
- **a missing runtime is a hard failure.** No fall back to the host: a control that
  silently degrades is worse than none, because the operator believes it is on.

Measured, not asserted — the same probe stage, run both ways:

| | `~/.claude` visible | host `/Users` visible |
|---|---|---|
| host (container off) | **1.0** | 1.0 |
| container (on) | **0.0** | 0.0 |

Honest limit: **this machine has no outbound network**, so the `--network=none` claim is
not demonstrated here, only inferred — it fails instantly with `OSError` where the host
and a default-network container both time out. Worth re-checking somewhere with network.

Default is `enabled: false` so existing configs keep working, but `evolve validate` now
states the posture either way: it hard-fails when the runtime is missing and isolation is
on, and warns plainly when isolation is off that stages will run on the host with `$HOME`
readable.

**Found while building it.** `_coerce_container` substituted a default for an image the
operator had written as blank, which made the validation for it unreachable. Absent keys
still get defaults; a value someone explicitly typed is now kept and rejected. Silently
substituting for what a config says is how a config comes to mean something else.

### Round 9 — full end-to-end verification against real agents (2026-08-25)

Every runtime path driven from the CLI with the live `claude` agent, not a stub.

| Scenario | Result |
|---|---|
| toy, `single_agent`, host | 2,512 → **8,952,896** ops/sec, `target_reached` |
| toy, `single_agent`, **containerised judge** | 3,092 → **10,658,900** ops/sec, `target_reached` |
| toy, **`debate` operator**, two real agents | 2,908 → **14,848,081** ops/sec, `target_reached` |
| **dependency-update example** | `compat_score` 50 → **100**, `target_reached` |
| `pause` mid-flight then `resume` | paused at the iteration boundary, process exited cleanly, resumed to completion |
| `validate` / `status` / `inspect` / `report` / `stop` | all driven against real runs; report byte-identical across invocations |
| dashboard `/evolve`, `/evolve/<id>`, `/api/evolve` | render real runs; unknown id 404s |

This closes the two gaps I had named: the **debate operator** (M3, the thesis milestone)
and the **dependency-update example** (M4) had never met a real model. Both work. The
debate run wrote `it1_debate.json`, its `VARIATION_PRODUCED` event records `kind=debate`
with the origin agent that implemented the winning plan, and the committed diff is that
agent's implementation — not parsed prose, exactly as section 3 requires.

M4's criterion is met precisely: the dependency example committed **only** at
`compat_score: 100` (2.x *and* all five goldens holding). Iterations 1 and 2 were rejected.

**Found by watching why they were rejected.** Both said `command 'git' not allowed for
evolve workers`. The agent reached for `git` to commit its own work, and the allowlist
refused — correctly, since a worker with `git` could rewrite the lineage it is being
judged on. But nothing told it that, so two of three iterations went on discovering it.
Fixed in the prompt rather than the policy: both the worker requirement and the
implementer mandate now say the runtime owns version control.

Pause is properly cooperative: the process kept running while an agent call was in
flight, then exited at the iteration boundary with the store reading `paused` — it does
not abandon work mid-iteration. Resume cleaned up the worktree the pause left behind and
carried on to `target_reached`.

### Round 10 — the whole machinery, against the AVO design (2026-08-25)

Jonathan's ask: not "the commands ran" but does the system `evolve.md` specifies — the
AVO adaptation where debate is the variation operator, a deterministic judge is selection,
and a supervisor is the autonomous course-corrector — actually take a task and achieve it
end to end with no one watching. Every prior live run hit target in 1–3 iterations, so
**the supervisor had never fired once**. Two runs, both with two real agents debating.

**Run A — genuine evolution.** Debate variation, target 60M ops/sec (beyond reach), six
iterations. Four generations accepted, one rejected on the regression bound, one empty:

```
seed  3,049 -> v1 8,992,062 -> v3 11,048,906 -> v4 11,740,500 -> v5 14,682,211
```

Every commit carries its `Evolve-Score` trailer; the run stopped on `max_iterations` with
zero worktrees left. The agents kept finding real improvements, which is why the
supervisor never needed to engage — correct behaviour, but it proves only the happy path.

**Run B — forced off course.** `epsilon: 1e12` so nothing can ever count as "better", so
the run *must* stall. Section 0's division-of-responsibility table, row by row, live:

| Question | Answered by | Observed |
|---|---|---|
| Is this candidate better? | Judge | every candidate rejected (`rejected_not_better`) |
| Are we off course? | Supervisor detection | **stall** at it3; **loop** at it7 — both causes exercised |
| What should change? | Supervisor intervention | a real two-agent debate over the lineage; `intervention_it3.json` on disk shows `worker` and `peer` in both generation and critique rounds; **5 schema-validated directions** with `ttl=2` |
| Do directives reach the worker? | Context | the block appears in the it4 prompt |
| When does a human get involved? | Escalation policy | after `max_interventions_before_human`, parked in `waiting_for_human` with a concrete question: goal, current best, why the interventions failed |
| Death is cheap | Runtime | process exited cleanly on escalation; store read `waiting_for_human`; one worktree left for resume to clean |
| Human answers | `evolve answer` | directive recorded, run resumed, escalation counter reset to 0, guidance present in the next 4 worker prompts; a **second** intervention then fired at it7 — H3 working live |
| When do we stop? | Stop conditions | `max_iterations`, zero worktrees, `report` byte-identical with both interventions and the escalation in it |

Ten directions issued, one escalation, one answer, eight iterations — all autonomous
except the one `answer` a human is supposed to give.

**Found live, fixed.** The first two attempts produced *nothing*: a debate is ~5 agent
calls per iteration, and each call was allowed the whole `worker_budget`, so a single
generation call could consume the iteration and the debate structurally could not
finish. 600s per iteration, empty. `validate` now does the arithmetic and says what to
change. Also: debate variation with `--model opus` is impractically slow (a single
generation call exceeded 240s); the debaters in these runs are `sonnet`.

**Honest limits.** Run B's stall was engineered, not organic — the point was to prove the
machinery, not to find a hard task. And `max_iterations: 8` ended it before a second
escalation could occur. The 8-hour endurance run remains the only way to see this over a
real day.

### Round 11 — a production codebase, not the toy (2026-08-25)

Jonathan's point: in production nobody runs `evolve_toy`. So: the real `freemad` package
(224 files at HEAD), a real hot path — `freemad.scoring.ScoreTracker`, which every FREE-MAD
debate calls on every answer in every round — a protected oracle pinning the paper's exact
scoring arithmetic, a protected benchmark, the module's own tests as the editable gate,
and two real agents debating.

**It did not work at first, and the reason is a real gap.** Every generation call timed
out. Reproduced outside evolve: a single `claude -p` on the variation prompt ran 440s+ on
a 1,117-character prompt. Tracing it: `find | xargs grep`, `ls`, `cat`, `Read`, `Read`…
The debate prompt never told the debaters *where the code was*, so a planning agent
searched a 224-file repository before writing a word. On the 20-file toy that cost
seconds and went unnoticed. The supervisor's own intervention debate — same agents, same
model — finished fine, because its prompt asks for directions, not a file-by-file plan.

Two fixes, both structural:

1. **`knowledge_paths` now inlines file contents** into the debate and worker prompts
   (per-file and total caps, still marked untrusted). It previously listed names only,
   so "read-only reference material" was never actually in front of anyone.
2. **`cli_mode_flags`** — per-call-mode flags on `AgentConfig`. A debate's `generating`
   and `critique` calls are *thinking*; only `act()` needs tools. With
   `{"generating": ["--tools", ""], "critique": ["--tools", ""]}` the agent cannot
   explore, and a plan debate becomes one bounded call. Even with the code inlined, an
   agent *with* tools still went off grepping — the flag is what bounds it.

**The honest cost.** With tools off, the real adapter's `generate()` on this prompt took
**451s** and returned a correct, parsed, file-by-file plan — it had found the actual hot
spot (`contrib_counts` rebuilt on every event). That is how long the model thinks about
a real optimisation; it cannot be prompted away. Five calls per debate iteration means
~40 minutes per iteration on real code. The examples' 10-minute `worker_budget` was toy
arithmetic. `validate` now computes this and says what to change.

A third finding along the way: my new loop variable shadowed the adapter's pre-existing
cache `key`, and mypy caught it.

**Properly configured, it worked on production code.** Iteration 1: two agents proposed
different plans; `peer` won and implemented — cached weights, incremental contributor
counts, `__slots__` on both classes, and the one caller in `freemad/orchestrator.py` that
`__slots__` broke, correctly fixed in the same change. The protected oracle confirmed the
paper's arithmetic unchanged; the module's own tests passed; **26,230 → 28,463
debates/sec** went into git as `v1`. Iteration 2 was rejected on the regression bound —
the judge holding the line on real code.

**Fourth finding, from reading the accepted diff.** Two `transcripts/*.json` files were
in the commit. The worker had run the repo's test suite inside the worktree to check its
work; a test wrote a transcript; `git add -A` swept it into the lineage. `commit_candidate`
now excludes the configured transcript directory and `.freemad/` regardless of who wrote
them — the run's artefacts are not the code being evolved.

**The full run, on production code, unattended:**

```
seed   26,230 debates/sec
it1    COMMITTED   28,463    two agents debated; peer won and implemented
it2    rejected    26,434    regression bound: slower than v1, refused
it3    rejected    tie       within epsilon of v1, not strictly better
it4    SUPERVISOR  stall     organic, not engineered: 2 iterations without a commit
       DIRECTIONS  x5        a real two-agent intervention debate over the lineage
       STOPPED     max_iterations
```

The supervisor fired on its own this time — the first organic stall of the whole
exercise. Re-verified cold: `v1` checked out fresh passes the oracle, the module's tests,
and benchmarks at 32–34k (the machine was quieter than during the run). One test in the
*full* package suite fails at `v1` — and identically at `v0`: a pre-existing environment
issue (`python` not on PATH here), not the agent's doing. The completed run left zero
worktrees; the one orphan on disk belonged to the earlier run I killed by hand, and
`cleanup_orphan_worktrees` removed it as designed.

### Round 12 — making the commit gate real (2026-08-26)

Asked whether the work was ready to commit, I checked rather than answered — and found
the commit gate itself had never worked.

**The package was renamed `freemad` at the initial commit, but four tool invocations
still targeted `mad`, a directory that has never existed:** the pre-commit `bandit` hook
(exit 0 on a missing path — *passed while scanning nothing*, on every commit ever made),
and the Makefile's `lint`, `fmt` (`|| true` swallowed the error) and `cov`
(`--cov=mad`: coverage of nothing). All four now point at `freemad`.

A corrected `bandit` then surfaced what it had been missing: one Medium — `exec()` in
`freemad/validation/sandbox.py`, a "sandbox" built on restricted builtins plus a
substring blocklist for `import` and `__`. It is opt-in and off by default, and it is not
a security boundary. Annotated `# nosec` with the reason, and `SECURITY.md` now says so
plainly. The hook runs at `-ll` (Medium and above): this project *is* a subprocess
orchestrator, so its ~34 Low B404/B603 hits are its purpose, and gating on them would
only teach people to bypass hooks. Tests are excluded — a fake `/tmp/wt` in an
argv-construction test is not a hardcoded temp directory.

**And I did damage on the way.** I ran `pre-commit --all-files` to see whether the hooks
passed. They *rewrote 133 files* — `end-of-file-fixer`, `trailing-whitespace`, `black`
across `.github/`, the TypeScript dashboard, `scorer.py`, config files — none of it this
work. Reverted, then reverted again after a `stash`/`pop` "snapshot" restored it. Black
also reflowed three long `# noqa: E402` imports in `freemad/__init__.py` into
parenthesised form, stranding the marker on the closing `)` where ruff cannot see it —
so a hook that had been green went red on pre-existing lines. Markers restored.

Worth recording precisely because it looked like something worse: `scorer.py` showed
modified at the exact minute the evolve agent's iteration committed, and for several
minutes I believed the agent had escaped its worktree into the real repository. It had
not — its commit's blob hash never existed in this repo's object store, and its log
never references the real path. It was black, and it was me. Containment held.

**Then the gate turned out to be structurally unpassable.** With bandit fixed, `black`
and `ruff-format` still failed on every run — and `git diff` showed nothing mutated. The
hook config ran *both* formatters, and they disagree: black reflows a long
`except Exception as exc:  # comment` into a parenthesised three-line form, ruff-format
reflows it back. Alternating them produces hashes A, B, A, B forever. Any file containing
that construct — three of mine, and HEAD's own `orchestrator.py` has 52 lines over 88
columns — fails the gate on every commit regardless of author. Black is removed;
ruff-format is the single formatter (it was already pinned and already lints). A
side-quest along the way: pre-commit's black reported version `0.1.dev1+…` because its
shallow clone carries no tags for hatch-vcs — cosmetic, it is the real 24.10.0 commit and
formats identically. The real cause was the pairing, not the version.

The gate now: every hook passes against the staged set, nothing is mutated while staged,
369 tests, mypy and ruff clean.

### Round 13 — one source of truth for the skills (2026-08-26)

Two copies of the five project skills existed: `.claude/skills/` (Nov 2025, gitignored,
accurate) and `.agents/skills/` (24 Aug, *not* ignored, newer — and corrupted by a global
`claude`→`Codex` replace that labelled `claude_agent.py` the "Codex agent adapter", wrote
`@register_agent("Codex")`, and put `"Codex"` in the security allowlist). Nothing in the
repo referenced `.agents/`, but Codex does use a skills convention on this machine, so
that copy was probably meant for it. Neither copy knew anything about the evolve runtime.

Resolution, per Jonathan's direction:

- **`.claude/skills/` is the single canonical copy.** All five updated against the code —
  every factual claim verified programmatically (12/12). The security skill needed an
  actual correction, not just an extension: its "secrets from environment variables"
  section described a model this project does not use. FREE-MAD never reads an API key;
  agents authenticate with their own on-disk subscription session, which is why env
  scrubbing cannot protect the credentials and container isolation is the boundary.
- **`.agents/skills/` holds pointers only**: same frontmatter (so a tool indexing by name
  still finds the skill), body = "read `.claude/skills/<name>/SKILL.md`".
- **`AGENTS.md`** — the cross-tool convention file — now tells every agent where the
  canonical skills are and that the pointers are pointers.
- **Both directories gitignored.** Skills are local tooling configuration, not source.

### Round 14 — committed, and what the clean-export check caught (2026-08-26)

Three commits on `main`:

- `998e3bd chore(tooling): make the commit gate real`
- `3040ebe feat(evolve): goal-directed optimisation runtime with deterministic judge`
- `f8ac05c test(evolve): stop assuming the venv is on PATH`

The third exists because of a check worth making a habit: after committing, export
`HEAD` to a clean directory and run the suite there, with the interpreter invoked
directly rather than through `poetry run`. One test failed that passed in the working
tree on byte-identical code. Twenty judge-stage commands in the fixtures were a bare
`python`, resolvable only because `poetry run` puts the venv on PATH. Under any other
runner every judge stage failed to start, the baseline failed its own gate, and the
`v0`-tag test — the only one asserting on a side effect of a *successful* baseline —
caught it. Fixed with `sys.executable`, except where that is wrong: container tests keep
the image's own `python` (the host path does not exist inside), and worker-policy tests
use `python3` (the allowlist matches `cmd[0]` by name). The comparison harness in
`examples/` carried the same assumption.

Final verification: a clean export of `f8ac05c`, full suite, PATH restricted to
`/usr/bin:/bin` — passes.

### Round 15 — the pre-existing test, and what CI actually runs (2026-08-26)

Asked whether the one pre-existing failure was still worth keeping, I looked at what it
protects. `test_health_with_allowed_python` is the only success-path coverage of
`Agent.health()`, which backs `freemad --health` — so it stays. But it configured a bare
`python` as the stand-in agent CLI, which resolves only with a venv on PATH (macOS ships
no `/usr/bin/python`): it was asserting an accident of `poetry run`, and its failure read
as "health() is broken". Now `sys.executable`, in both the command and the allowlist
(`4544cf7`).

Checking that fix the way CI would check it turned up something larger. CI's type step is
`mypy .` — also the Makefile's `type` target. It is clean at `origin/main` and was broken
by the evolve commits. Every "mypy clean" earlier in this log came from running mypy on
the changed files, never on `.`: true statements about a check CI does not run. Two
causes:

- `examples/evolve_dependency_update` reaches its vendored module by two names
  (`vendored_lib` off a `sys.path` insert in the benchmark, `vendor.vendored_lib` from the
  app). Under crawling that is a module-name collision, and mypy stopped there before
  checking anything else. The examples are evolve *targets* the agent rewrites, not the
  package; `mypy.ini` now excludes them.
- Behind it, 34 errors in 10 test files: config dataclasses built with bare strings where
  `GateOp`/`CompareDirection` are expected, a generator fixture annotated as its yielded
  type, `**kwargs` from an untyped dict, monkeypatching `_run_cli` on a variable typed as
  the base `Agent`, a lambda using `list.append`'s `None`, a dead assignment to an
  attribute the orchestrator no longer has, and `import yaml` — PyYAML has no stubs, CI
  installs none, and the global `ignore_missing_imports` is deliberately not honoured for
  typeshed's legacy bundled packages, so it has to be per-module. Annotating
  `build_orchestrator`'s return type then surfaced four more, two of them
  `ScoreVector.get` returning `Optional[float]` even with a default — fixed at the source
  with `dict.get`-style overloads (`b784dc5`).

CI also runs the matrix on Python 3.10–3.13 with `--cov-fail-under=80`, and installs
whatever `pip install mypy` resolves to today — 2.3.1, against the pinned 1.18.2. So the
replay used a `uv`-built 3.10 environment with CI's exact install line. `mypy .` is clean
under both versions; coverage is 88% (`freemad` only, as CI measures it).

That replay caught a third instance of the PATH assumption, one `f8ac05c` had kept on
purpose: the container tests use the image's own `python`, but the *contrast* test — the
run without a container that shows `~/.claude` is visible from a judge stage — executes
on the host. The condition that exposes it is Docker reachable *and* no venv on PATH. The
earlier clean-export check restricted PATH to `/usr/bin:/bin`, which drops
`/usr/local/bin` and Docker with it, so the whole class skipped and the assumption
survived. The host-side run now uses `sys.executable` (`835bf96`).

Two lessons for this log. "Clean" has to name the command CI runs, not a convenient
subset of it. And a harsh-condition check that silently skips a test class is not harsh
for that class — the tightened condition keeps Docker reachable.

Final verification, on a clean export of `835bf96` with `freemad` resolving inside the
export: `mypy .` clean under mypy 2.3.1; Python 3.10, Docker reachable, CI's coverage
gate — 369 passed, 2 skipped, coverage 88.48%; Python 3.13 with
`PATH=/usr/bin:/bin:/usr/local/bin` (no `python` on it, Docker on it) — 369 passed,
2 skipped. The two skips are the `SMOKE=1`-gated adapter test and a supervisor test
marked as covered by M1. The one warning on 3.10 is a `StarletteDeprecationWarning`
raised inside `fastapi/testclient.py` by the newest pip-resolved Starlette — a
dependency's notice, not ours.

Addendum, same day. Asked whether anything was still pending, I checked the one CI job I
had not replayed: `smoke`, which runs `test_smoke_adapters.py` with `SMOKE=1` — skipped
in every ordinary run, so a green full suite says nothing about it. It failed under the
harsh condition, and identically at `origin/main`: a fourth bare `python`, in the mock
agent's `cli_command` and its allowlist. CI passes it only because `setup-python` puts a
`python` on PATH. Same fix as the health test, `sys.executable`; it passes on 3.13 with
no venv on PATH, on 3.10, and under `poetry run`, and stays skipped without `SMOKE=1`.

### Round 16 — the first push, and what CI's 3.11 lane caught (2026-08-26)

Pushed `main` (nine commits, `52dd467..e2aeab3`). CodeQL, SBOM, Scorecards, Release
Drafter and the `smoke` job went green; of the four `tests` lanes, 3.12 and 3.13 passed,
3.11 failed and 3.10 was cancelled by fail-fast. The failure:
`test_kill9_mid_variation_costs_at_most_one_iteration — variation worktree never
appeared`, and nothing else in the log — the test read one line from the runner's stdout
pipe and never looked at the runner again.

Ruling things out first: the 3.11 lane resolved dependency versions identical to 3.13's;
a `uv`-built 3.11 environment passed the test 3/3 and the full suite; the runner writes
37 bytes before the worktree appears, so an undrained pipe was not what stalled it. Then
the measurement that explained it. With the runner's instant fake worker an iteration is
rejected as "no changes" the moment it starts, and the `it1` worktree exists for **62–69
ms** — 1 ms polling, three runs, the same under a coverage tracer. The test polled every
50 ms. That margin loses a race on a loaded two-vCPU runner, and it means the kill had
only ever landed "mid-variation" by luck: the "slow" config raised the worker's timeout
without making the worker slow.

`3a10d31`: the runner's worker holds `act()` open for a minute when the test sets
`FREEMAD_TEST_ACT_SLEEP`, so the worktree persists until the kill lands inside iteration
1 — the event trail at kill time ends at `iteration_started`. The runner's output goes
to files rather than pipes nobody drains, both waits are bounded (`readline()` on the
pipe was not), and a failed wait reports the runner's exit state, its output and the
run's event trail. 3/3 on each of 3.10, 3.11 and 3.13.

A third lesson for this log: a test that fails on one lane is a test with a timing
window until proven otherwise. Measure the window before blaming the lane.

CI for `3a10d31`: all four `tests` lanes, `smoke`, CodeQL, SBOM and Scorecards green;
coverage 88–89% on every lane.

### Process notes

- I picked the `security-auditor` agent type for the security lens; its toolset is
  Read/Grep/Glob, so it could not run anything. Everything it reported was static
  analysis, and I verified the load-bearing claims before acting — two of its five
  "confirmed" items were wrong as stated once actually executed.
- The credentials claim in `docs/evolve-runtime.md` was overstated and is now corrected:
  scrubbing covers processes the *runtime* launches, not the agent adapter, which holds
  its own keys by construction — and `HOME` passthrough leaves `~/.claude/`, `~/.aws/`
  and `~/.netrc` readable to any judge stage.

## Baseline health

`mypy` clean across all 13 changed files. 96 evolve tests pass (1 skipped). The tests are real
integration tests — actual git repos, actual `pytest` subprocesses — not mocks, including a genuine
`SIGKILL` durability test that spawns a subprocess runner and resumes from persisted events only.
Layering respects `evolve.md` §1 (no `evolve/`↔`tasks/` coupling; git is ground truth for code,
SQLite for events). Config validation is thorough (dangling component refs, duplicate `provides`,
path traversal). Fail-closed `json_stdout` parsing is well built. `advance_run_branch` correctly uses
`update-ref` compare-and-swap. Coverage 82%, with `report.py` at 0%.

The M1–M4 milestone scope is essentially all present. What follows are the defects inside it.

---

## Blockers

### B1 — The judge fails open: a candidate is committed despite a failing judge stage

`judge_worktree` records `failed_stage` (`freemad/evolve/judge.py:160-186`) but nothing in the
orchestrator ever reads it; the accept path checks only `verdict.gate_passed`
(`freemad/evolve/orchestrator.py:278`). If a scoring stage runs *before* an `exit_code` stage, the
gate is satisfied from components already collected and the stage failure is discarded.

Verified — stages ordered `bench` → `tests`, candidate implements `total(n) -> 0` (wrong answer,
pytest fails):

```
failed_stage : tests      gate_passed : True      committed? : True
```

Both shipped examples happen to order `exit_code` stages first, so this is latent — but nothing
validates that ordering. `evolve validate` has the same hole: `freemad/cli.py:350` only reports a
stage failure when the gate *also* fails, so it can print `ok: true` on a repo whose judge is broken.

Violates `evolve.md` §4.1 ("progress is proven, not claimed").

**Fix:** treat `verdict.failed_stage is not None` as an unconditional rejection, before the gate is
consulted. Same in `_evolve_validate`.

### B2 — The regression bound is measured against the baseline, not the best-ever score

`freemad/evolve/orchestrator.py:276` binds `best_ever = snapshot.baseline_score`. The local name says
one thing, `snapshot.best_score` sits directly above it unused, and four other places say best-ever:
the docstring (`judge.py:96`), the config comment (`config.py:186`), `docs/evolve-runtime.md` step 3,
and `evolve.md` §2.2 / §8.3.

Consequence with a multi-term comparator — a candidate can destroy a hard-won secondary metric and
still be admitted, because a higher-priority term improved:

```
best-ever  {correctness 0.6, ops_per_sec 5000}
candidate  {correctness 0.7, ops_per_sec 99.5}
vs baseline (implementation): ACCEPTED
vs best-ever (documented)   : REJECTED — regressed past bound: 99.5 vs floor 4999.0
```

This is precisely the "ratchet a component arbitrarily far downward across accepted steps" hole that
`evolve.md` §8.3 says `max_regress` exists to close.

**Fix:** pass `snapshot.best_score`. If the intent was genuinely a fixed floor, then the parameter
name, the docstring, both docs and the spec all need to change instead — but §8.3's stated rationale
only makes sense against best-ever.

### B3 — Protected-path restoration doesn't remove agent-added files; the tamper defense is bypassable

`restore_protected` (`freemad/evolve/lineage.py:161-183`) runs `git checkout <seed> -- <path>`, which
only overwrites paths present in the seed. Verified against real git — with `tests/` protected, an
agent that writes `tests/conftest.py` keeps it through the restore:

```
$ git checkout HEAD -- tests/ && ls tests/
conftest.py   test_a.py   test_b.py        # conftest.py survived
```

A `pytest_collection_modifyitems` hook in that file neutralises the entire suite. `_hash_tree` then
hashes the *post-restore* tree and stamps it into `CANDIDATE_JUDGED`, and nothing ever compares that
hash against the seed's — so the tampering leaves no trace in the audit record. Root-level
`conftest.py` / `pytest.ini` / `sitecustomize.py` are the same class and aren't protectable at all.

The existing tamper test (`test_tampered_bench_cannot_move_score`) covers *overwriting* an existing
protected file, which restoration does handle correctly. The gap is that `evolve.md` §4.7's threat
model says "edits", and adding beats editing.

**Fix:** restore protected directories with `git rm -r --cached` + checkout, or delete the directory
before checkout, so untracked additions cannot survive. Additionally compare each stamped hash
against the seed's hash and reject the iteration on mismatch.

### B4 — A crash between tag and branch-advance permanently wedges the run

`freemad/evolve/orchestrator.py:306-310` commits → tags → advances the branch, with no idempotency.
`resume` re-runs the same iteration and `git tag` collides. Verified:

```
resume RAISED: LineageError ... tag evolve/<run>/v1 ... already exists
```

Every subsequent resume raises identically — unrecoverable without a manual `git tag -d`. Violates
`evolve.md` §4.6 ("death is cheap: any crash, anywhere, costs at most one iteration on resume").

The existing `SIGKILL` test is well built but kills during the *variation* phase, before any commit
or tag exists, so it never enters the fragile window. `evolve.md` M2 asks for "kill -9 mid-variation
**and mid-judge**"; only mid-variation is covered.

Related: `_run_iteration` has no `try/finally` after `operator.propose`, so any failure in
`restore_protected` / judge / commit also leaks the iteration worktree.

**Fix:** make `tag_version` idempotent (`git tag -f`, or check-then-skip when the tag already points
at the same tree), wrap the post-variation body in `try/finally`, and add a kill point after
`commit_candidate` to the durability test.

### B5 — An empty `stop.target` means the goal is already met

Found while building the B2 regression test. `EvolveStopConfig.target` defaults to `()`, and
`target_met` delegated straight to `evaluate_gate`, which is vacuously true on an empty
predicate list. Any config without an explicit target therefore completed at the baseline
with `TARGET_REACHED` and zero iterations.

`evolve.md` §2.2 types the field as `... | None`, so an absent target is a supported
configuration, not a misconfiguration. Vacuous truth is right for `judge.gate` (no predicates
means nothing blocks admission) and wrong here.

**Fixed:** `target_met` returns False when no target is configured.

---

## High

### H1 — Addition-only edits are reported as "no changes produced"

`worktree_is_dirty` uses `--porcelain -uno` (`variation.py:119`, `lineage.py:66`), which excludes
untracked files — while `commit_candidate` uses `git add -A`. Verified with an agent that only adds
files:

```
produced_changes : False
diff_stat        : ''
outcome          : worker_failed
signature        : "no changes produced"
```

Real CLI adapters that edit the worktree directly (rather than returning `writes`) will hit this
constantly, and the false signature poisons the graveyard and the supervisor's stall detection.

**Fix:** drop `-uno` in the two worktree-change checks (keep it in `repo_is_clean`, where ignoring
untracked files is intended).

### H2 — `interventions_since_best` is rebuilt wrong on resume

The live path resets the counter to 0 on every commit (`orchestrator.py:343`); the rebuild
(`orchestrator.py:711-714`) counts every `SUPERVISOR_TRIGGERED` event ever and never resets. With the
default `max_interventions_before_human: 3`, any long run that recovered from three interventions
will escalate to a human on its first finding after a resume. `evolve.md` §3 explicitly says the
supervisor must "reset counters after intervention".

### H3 — `answer()` doesn't reset the escalation counter either

`orchestrator.py:499-527`. After a human provides guidance the counter is still at the limit, so the
next supervisor finding re-escalates immediately — autonomous interventions never resume, defeating
`evolve.md` §4.5 ("humans are the escalation of last resort").

### H4 — Documented security controls that don't exist

`evolve.md` §3 specifies judge stages run with a "scrubbed env, network off by default (env-scrub
v1)". `docs/evolve-runtime.md` tells the reader "env scrubbing is hygiene, not isolation".

There is **no `env=` argument on any subprocess call anywhere in `freemad`**, and no `os.environ`
filtering. Judge stages and worker commands inherit the full parent environment — `ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, cloud credentials, everything. `judge.network` (`config.py:196`) is parsed and
validated but never enforced.

This is an unimplemented M1 deliverable, not merely a documentation error, and it is the one place
where the docs credit a control that does not exist.

### H5 — Agent-controlled input can kill the run

`apply_writes_policy` raises `ConfigError` on an absolute or escaping write path
(`variation.py:67,70`); `orchestrator.py:222` catches `ConfigError` only to remove the worktree and
re-raise, aborting the whole run. One malformed path from an agent ends the optimization.
Separately, `subprocess.TimeoutExpired` from `run_commands_policy` (`variation.py:91`) is uncaught
entirely. Both should be iteration-level rejections (`WORKER_FAILED`), not run-fatal.

---

## Spec deltas (decided semantics in `evolve.md` that were not implemented)

| # | `evolve.md` | Implementation |
|---|---|---|
| S1 | §2.2 — inner debate `BudgetGuard` scoped to remaining `worker_budget`; "the outer budget always wins" | `variation.py:242` and `supervisor.py:133` both pass `self._cfg` unmodified. `worker_budget.max_minutes`/`max_turns` are validated and set in every example YAML but never enforced anywhere. |
| S2 | §2.2 — "re-verify **the judge subsection's** hash every iteration" | `orchestrator.py:770` hashes the entire `evolve:` block, so changing `max_iterations` or `store_path` on resume triggers `FATAL_ERROR: manifest changed mid-run`. Since `resume` requires `--config`, this is easy to hit. |
| S3 | §2.2 — "Iteration 0 judges the unmodified seed, **tags it `v0`**" | `tag_version` is only called on the accept path (`orchestrator.py:308`). The baseline is never tagged. |
| S4 | §3 — operators "must produce a self-report (≤300 words: tried/worked/failed/why); absent report → truncated final output" | No extraction: `self_report` and `final_output` are the same response text truncated to 2200 and 4000 chars. |
| S5 | §2.2 / §8.1 — "a valid judge design requires every scored component to derive from at least one protected stage" | Stated as a validity requirement; nothing in `_validate_evolve` checks it, and `evolve validate` does not warn. |
| S6 | §7 — "keep templates in `freemad/prompts/` beside existing ones" | `freemad/prompts/` exists (`autonomous.py`, `templates.py`); evolve's prompts are inlined in `variation.py` and `supervisor.py`. |
| S7 | §3 CLI — `evolve answer <run_id> "text"` | Also requires `--config`, and `--decline` requires a dummy positional `text` that is then discarded (argparse rejects `answer <id> --decline`). |
| S8 | M2 — "every `EvolveStopReason` is exercised in CI using compressed budgets and a fake clock" | `TestStopReasons` calls `orch.stop(run_id, reason)` directly and asserts the status mapping. It proves the mapping, not the trigger. `BUDGET` is never produced by any code path. |

---

## Medium

- `judge.py:189` uses `stage.command.split()` while `variation.py:86` uses `shlex.split`. `pytest -k "not slow"` splits wrong. Judge commands also bypass the `allowed_local_commands` allowlist that worker commands go through — defensible (config is operator-owned) but the `# noqa: S603 - fixed argv from validated config` comment overstates what validation checks.
- **`status` / `inspect` read the wrong database.** They are the only subcommands without `--config`, and `load_store_path_from_default()` (`cli.py:373`) calls `load_config()` with no path — returning the *default* `store_path`, not the run's. Any custom `store_path` makes both commands silently useless.
- **`repo_path` and `store_path` are CWD-relative** while `transcript_dir` and `cache.dir` are resolved against the config file's directory (`config.py:1004-1008`). Running the documented quick-start from the repo root instead of `examples/evolve_toy` silently targets the wrong repository.
- ~~**The dashboard trajectory view is effectively undelivered**~~ *(fixed; see Round 2)* despite CHANGELOG and readiness-checklist claims (M4 acceptance: "the dashboard renders a finished run's trajectory"): the chart hardcodes `p.cumulative_best.get('ops_per_sec', 0)` (`evolve.html:38`) so the dependency-update example plots a flat line; `main()` has no `--evolve-store` flag so the path is fixed relative to the dashboard's CWD; and **no template links to `/evolve/<run_id>`** — the page is unreachable without hand-typing a UUID.
- **Config surface that does nothing:** `judge.network`, `worker_budget.*`, `knowledge_paths`, `variation.debate_agent_ids`, `supervisor.intervention`, `EvolveStopReason.BUDGET`, and the persisted `interventions_without_new_best` column. All validated, none consulted. `max_total_cost_usd` at least warns in `validate`, per §2.2.
- **Repo hygiene — a release blocker on its own.** `git add -A` would stage **185 files, 137 of them `.freemad/` runtime state** (110 evolve transcripts, 704K); `.gitignore` covers `transcripts/*.json` but not `.freemad/`. And `examples/evolve_toy/.git` is an **embedded git repository** — git warns it would be committed as a gitlink, so anyone cloning gets an empty directory where the advertised proving ground should be.

---

## Low

- **ruff: 16 errors** (3 pre-existing in `dashboard/app.py`). New: `report.py:6,8`, `variation.py:12`, plus 11 in the new tests. The pre-commit ruff hook will reject this commit as-is. Note the bandit hook and Makefile still target `-r mad`, a directory that no longer exists — so none of this new subprocess code is being scanned.
- **`report.py` is 0% covered**, and M1 acceptance requires "`report` is reproducible byte-identical from events alone" — that criterion is currently unverified. It also contains `directions_given += 0` (`report.py:84`), a dead statement. There are **zero CLI tests** for `freemad evolve` — 220 new lines of `_evolve_main` / `_evolve_validate` untested, while `tests/pkg_mad/cli/` covers the other commands.
- **Dead code:** `Lineage.list_run_files`, `delete_run_branch`, `worktree_is_dirty` (duplicate of `variation.py`'s), `verify_manifest_judge_hash`; `JudgeVerdict.first_failing_stage`; `gate_failure_signature_from_failures`; `result_origin_ids` (always returns `()`); the no-op ternary at `orchestrator.py:570`.
- **AGENTS.md violations:** `dashboard/app.py:507-527` compares `event.kind.value` to raw string literals (`"baseline_judged"`, `"candidate_committed"`, …) with `EvolveEventKind` importable; `IterationRecord` is the only model without `from_dict`; `report._fmt` / `_fmt_dict` are untyped with suppressions.
- **`bin/claude_print_wrapper.py`:** `--dangerously-skip-permissions` is declared `action="store_true", default=True` — always on, with no way to turn it off.
- **Transcript paths are CWD-relative** (`Path(".freemad")` at `supervisor.py:202`, `variation.py:316`) rather than repo-rooted; the supervisor's "transcript" saves only `final_solution` while the debate operator saves the actual transcript; `supervisor.py:116` hardcodes `budget_chars=20000` instead of `cfg.evolve.context_budget_chars`.
- `generate_context` only shrinks the graveyard to fit the budget (`context.py:93-104`) — the trajectory table grows unbounded, so `context_budget_chars` is not a hard cap on long runs.

---

## Suggested order

1. **B1** (fail-open judge) — breaks §4.1, the core promise.
2. **B4** (tag collision) — breaks §4.6; cheap fix.
3. **H1** (`-uno`) — what you hit first with a real agent; cheap fix.
4. **B2** (regression bound) — breaks §8.3.
5. **B3** (protected-path additions) — breaks §4.7; needs a design decision.
6. **H2/H3** (counters), **H5** (fatal `ConfigError`), then **H4** + the S-series spec deltas.
7. Repo hygiene (`.gitignore`, embedded `.git`) and ruff before any commit.
