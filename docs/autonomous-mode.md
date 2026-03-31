# FREE-MAD Autonomous Mode

FREE-MAD ships two runtimes:

- `debate`: consensus-free answer selection
- `autonomous`: persistent tasks with quorum review and resumable state

Autonomous mode is different from debate mode. Instead of producing a single best answer and stopping, the system owns a task and advances it through explicit stages until the work is approved, blocked, paused, or completed.

This document is the contributor-facing overview of the shipped first milestone. It complements the detailed specification in [`docs/plans/2026-03-31-autonomous-quorum-runtime-spec.md`](plans/2026-03-31-autonomous-quorum-runtime-spec.md).

## Current Scope

The current autonomous implementation supports:

- `plan` tasks
- `code` tasks
- persisted task state in SQLite
- task-scoped artifacts on disk
- structured research provenance via `source_bundle` artifacts
- CLI task commands
- dashboard task APIs and task pages
- background task execution through the dashboard
- live task websocket streaming
- proposer/checker review gates with optional arbitration
- human answer and approval feedback on resume
- parallel execution for non-overlapping work-item groups
- pause, resume, and `waiting_for_human` task states

The current first milestone does not yet provide:

- arbitrary workflows beyond `plan` and `code`
- autonomous publish actions such as push, merge, or release
- a dedicated pub/sub transport for live task streams beyond persisted-event tailing

## Why a New Mode

The current debate runtime is good for:

- code generation prompts
- architecture questions
- requirement critique
- selecting the strongest answer from competing proposals

It is not designed for:

- long-lived goals that require multiple steps
- tasks that must pause and resume
- code changes that need review and verification before completion
- workflows where agents must ask the human for clarification at the right moment

Autonomous mode addresses those gaps without replacing debate mode.

## Core Principle

Autonomous mode uses quorum work, not self-attestation.

That means:

- no single agent completes a stage alone
- no agent approves its own artifact version
- no task is marked done just because the author says it is done
- unresolved disagreement is recorded and escalated

The minimum pattern is:

1. one agent proposes or performs work
2. a second independent agent critiques, reviews, or verifies it
3. if they still disagree after bounded revision, a third agent arbitrates
4. if the dispute is really about product ambiguity, policy, or risk tolerance, the human decides

## Stage Model

The current stage flow is:

1. `intake`
2. `research`
3. `draft_plan`
4. `plan_review`
5. `execute`
6. `code_review`
7. `verify`
8. `finalize`

These stages are not strictly linear. A task may loop:

- from `plan_review` back to `draft_plan`
- from `code_review` back to `execute`
- from `verify` back to `execute`
- from any stage to `waiting_for_human`

The important point is that progress is governed by approval gates, not by the number of rounds completed.

## Roles

Agents participate through roles rather than a single generic debate interface.

Roles:

- `researcher`
- `planner`
- `reviewer`
- `implementer`
- `verifier`
- `arbiter`

An agent may support multiple roles, but role independence still matters. The same agent cannot author an artifact and then be the final approver of that same artifact version.

## Agreement Model

Debate mode chooses a winner by score. Autonomous mode uses gated acceptance.

Examples:

- a research bundle is accepted when an independent checker says the evidence is sufficient
- a plan is accepted when an independent reviewer approves it
- a code change is accepted when an independent reviewer approves it
- a task is complete only when verification also passes under independent review

This is a different notion of agreement. The goal is not textual consensus. The goal is whether the proposed work has survived independent challenge.

## When Agents Act Alone vs Ask the Human

Agents should be highly autonomous inside a bounded policy.

They may act autonomously when:

- the goal is clear
- the plan is approved
- the write scope is allowed
- the next action is reversible and low-risk

They must ask the human when:

- the requirement is materially ambiguous
- there are multiple valid directions with product tradeoffs
- policy blocks the next action
- credentials or missing context are required
- the disagreement between agents cannot be resolved safely

The system should not fake certainty in those cases. It should pause and present one concrete question.

## Persistence and Resume

Autonomous tasks must survive process restarts. That means the runtime needs:

- persisted task metadata
- an append-only event log
- stored artifacts such as plans, review notes, and verification outputs
- resumable stage state

The current implementation uses:

- `.freemad/tasks/tasks.db` by default for task rows and events
- `.freemad/tasks/artifacts/<task_id>/` by default for artifact files

The CLI surface for this is:

- `freemad task start`
- `freemad task status`
- `freemad task inspect`
- `freemad task resume`
- `freemad task answer`
- `freemad task approve`
- `freemad task pause`

`task answer` and `task approve` persist human input and approval decisions as task events, and those events are injected back into later `TaskRequest.feedback` payloads when the task resumes.

## Parallelism

Parallel work is allowed, but only when the orchestrator can prove the work items do not conflict.

The current design requires each work item to declare:

- `write_scope`
- `dependencies`
- `verification_scope`

The current implementation partitions work items by non-overlapping write scopes and executes each disjoint group in parallel. If two work items collide, the orchestrator routes them through separate groups instead of pretending they are independent.

## Human Role

Autonomous mode is supervised, not unsupervised.

The human remains the source of truth for:

- ambiguous product intent
- high-risk approvals
- irreversible external actions
- unresolved disputes that are really judgment calls

This keeps the system useful without letting it silently make the wrong irreversible decision.

## Relationship to Debate Mode

Debate mode stays.

That is important because the existing answer-centric runtime is still useful on its own:

- quick reasoning problems
- solution selection
- one-shot architecture critique
- cases where a persistent task would be unnecessary overhead

Autonomous mode is additive. It reuses existing agents and configuration patterns where possible, but it does not distort the debate runtime into something it was not designed to be.

## Dashboard Surface

The dashboard currently exposes:

- `GET /tasks`
- `GET /tasks/<task_id>`
- `GET /api/tasks`
- `GET /api/tasks/<task_id>`
- `POST /api/tasks`
- `WS /ws/tasks/<task_id>`

`POST /api/tasks` starts the task in a background thread, and `WS /ws/tasks/<task_id>` tails persisted task events until the task reaches a terminal state.

## First-Milestone Notes

The first milestone is intentionally narrow:

- research and plan critique tasks
- code-change tasks with review and verification
- policy-bound writes and local commands

It does not attempt to support arbitrary external business workflows or autonomous publish actions.

## Related Docs

- [`../README.md`](../README.md)
- [`plans/2026-03-31-autonomous-quorum-runtime-spec.md`](plans/2026-03-31-autonomous-quorum-runtime-spec.md)
- [`plans/2026-03-31-autonomous-quorum-runtime-implementation-plan.md`](plans/2026-03-31-autonomous-quorum-runtime-implementation-plan.md)
