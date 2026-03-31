# Autonomous Quorum Runtime Specification

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Status:** The first autonomous milestone described here is implemented in this repository. This document now serves as the architectural contract for the shipped first cut and notes the places where the implementation is intentionally narrower than the full design ambition.

**Goal:** Define FREE-MAD v2 autonomous mode as a persistent, quorum-governed task runtime where no single agent can unilaterally complete a stage, approve its own work, or declare a task done.

**Architecture:** Keep the current debate runtime intact in [`freemad/orchestrator.py`](../../freemad/orchestrator.py) and add an additive autonomous runtime beside it. The autonomous runtime uses persisted task state, append-only task events, stage-specific artifacts, and mandatory peer review at every stage.

**Tech Stack:** Python, immutable dataclasses, `enum.StrEnum`, SQLite, task-scoped artifact directories, FastAPI dashboard endpoints, existing Claude Code and Codex CLI adapters.

---

## 1. Purpose

FREE-MAD v1 is a bounded answer-selection system. It starts from a requirement, runs generation and critique rounds, scores answers, validates candidates, and returns a final answer. That flow is appropriate for one-shot reasoning, but it cannot safely own a long-lived engineering goal.

FREE-MAD v2 autonomous mode is a different runtime with a different contract:

- the unit of work is a persistent task, not a final answer
- the runtime advances through explicit stages, not open-ended critique rounds
- every accepted artifact requires independent review
- no agent can self-certify completion
- unresolved disagreement is recorded and escalated instead of hidden
- human clarification is a first-class state, not an exception path

The design principle is two-person integrity with bounded escalation:

- minimum quorum: 2 agents per stage
- tiebreak quorum: 3 agents when the first two disagree
- human escalation when the issue is ambiguous, risky, or policy-bound

## 2. Non-Negotiable Invariants

These rules apply to every autonomous task and every stage.

1. No single-agent completion. Every stage requires at least one proposing agent and one independent reviewing or verifying agent.
2. No self-approval. The agent that authored an artifact version cannot approve that same version.
3. No silent disagreement. If agents disagree, the task records a dispute and either retries, invokes an arbiter, or asks the human.
4. No implicit done state. A task is done only after review acceptance and verification acceptance.
5. No irreversible autonomous action by default. Publish, push, merge, delete, or external side-effect actions require explicit policy approval or a human decision.
6. No hidden tool usage. Research sources, file mutations, commands, and verification outputs must be captured as artifacts or task events.
7. No infinite loops. Each stage has bounded retries and a maximum escalation depth.

## 3. Runtime Shape

Autonomous mode is an additive runtime beside debate mode.

- Keep [`freemad/orchestrator.py`](../../freemad/orchestrator.py), [`freemad/run_events.py`](../../freemad/run_events.py), and the current transcript model unchanged for `debate`.
- Add a new autonomous runtime rooted under `freemad/tasks/`.
- Add a separate task event model instead of overloading `RunEvent`.
- Add mode-aware config so current debate configs still load unchanged.

The autonomous runtime owns:

- task intake
- task state transitions
- role assignment
- artifact persistence
- quorum and approval logic
- escalation logic
- resume after restart

The agents still own:

- planning content
- research content
- code changes
- review findings
- verification interpretation

## 4. Task State Model

### 4.1 Task Status

The task has a top-level lifecycle:

- `pending`
- `running`
- `waiting_for_human`
- `paused`
- `completed`
- `failed`
- `cancelled`

### 4.2 Task Stages

Stages are ordered, but they may loop backward:

1. `intake`
2. `research`
3. `draft_plan`
4. `plan_review`
5. `execute`
6. `code_review`
7. `verify`
8. `finalize`

### 4.3 Stage Outcomes

Each stage ends in one of these outcomes:

- `approved`
- `rejected`
- `needs_revision`
- `needs_human`
- `blocked`
- `budget_exhausted`

### 4.4 Stage Attempts

Every stage is attempt-based. The task records:

- `stage_attempt_index`
- `proposer_agent_id`
- `reviewer_agent_id`
- optional `arbiter_agent_id`
- input artifact ids
- output artifact ids
- decision reason

Retries are bounded by config. Once the retry budget is exhausted, the stage either:

- escalates to an arbiter, or
- pauses for a human decision

## 5. Roles

Roles are capabilities, not fixed agent identities. Any configured agent may advertise one or more roles, but a single task attempt must still respect independence rules.

Roles:

- `researcher`
- `planner`
- `reviewer`
- `implementer`
- `verifier`
- `arbiter`

Rules:

- one agent may hold multiple roles across a task
- one agent may not approve its own artifact version
- an arbiter for a dispute may not be the original proposer
- a verifier that authored a patch may not be the sole verifier for that patch

## 6. Quorum Rules

### 6.1 Base Quorum

Every stage begins with a two-agent quorum:

- `author`: produces the artifact or action
- `checker`: independently critiques, reviews, or verifies it

Acceptance requires:

- one authored artifact
- one independent approval
- no unresolved blocking findings

### 6.2 Dispute Handling

If `author` and `checker` disagree:

1. record the disagreement
2. allow bounded revision by the author
3. if disagreement remains after the configured retry count, assign an `arbiter`

The arbiter may return:

- `side_with_author`
- `side_with_checker`
- `needs_human`

### 6.3 Tiebreak Semantics

The arbiter does not erase prior disagreement. The task retains both opinions and the arbitration result.

A disputed artifact may be accepted only if:

- the arbiter independently approves it, or
- the original checker changes its decision to approval after revision

A disputed artifact is rejected if:

- both checker and arbiter independently reject it, or
- the arbiter requests human input

### 6.4 Final Completion Quorum

A task is `completed` only if:

- the final implementation state is approved in `code_review`
- the verification stage is approved by an independent verifier
- there are no unresolved blocking findings

At minimum this means:

- one authoring agent
- one reviewing or approving agent
- one verifying agent

The same agent may serve as reviewer or verifier across different stage attempts, but the primary author must never be the sole approver of task completion.

## 7. Human Escalation Policy

The runtime must enter `waiting_for_human` instead of guessing when:

- the goal is ambiguous in a way that changes architecture or user-visible behavior
- multiple valid directions exist and the choice is product or policy driven
- an action exceeds allowed tool or write policy
- the task would create irreversible external effects
- checker and arbiter still cannot resolve a dispute
- the task needs credentials, secrets, or inaccessible context
- stage retry or budget limits are exhausted without a safe default path

The human question must be concrete:

- one decision at a time
- why the task is blocked
- the options under consideration
- the default recommendation, if any

## 8. Stage Contracts

Each stage uses a mandatory proposer/checker flow.

### 8.1 Intake

Purpose:

- normalize the goal
- identify scope, constraints, success criteria, and missing information

Flow:

1. intake agent A writes a task brief
2. intake agent B checks for ambiguity, missing acceptance criteria, and unsafe assumptions
3. if clear, move to `research`
4. if unclear, move to `waiting_for_human`

Output artifacts:

- `task_brief.md`
- `open_questions.json`
- `acceptance_criteria.json`

### 8.2 Research

Purpose:

- collect repo facts and external evidence needed for planning

Flow:

1. researcher A gathers evidence and records provenance
2. researcher B checks coverage, contradictions, and source quality
3. if evidence is insufficient, researcher A may revise once per retry budget
4. unresolved evidence disputes go to arbiter C

Output artifacts:

- `research_bundle.json`
- `sources.json`
- `repo_findings.md`

Acceptance rule:

- planning cannot begin unless a checker or arbiter accepts that the evidence base is sufficient

### 8.3 Draft Plan

Purpose:

- convert the accepted brief and research into an executable plan

Flow:

1. planner A drafts the plan
2. planner B critiques assumptions, missing tests, rollback paths, and sequencing
3. planner A revises
4. if approved, move to `plan_review`

Output artifacts:

- `implementation_plan.md`
- `work_breakdown.json`
- `risk_register.json`

### 8.4 Plan Review

Purpose:

- perform a stricter approval gate than the planner-vs-planner drafting loop

Flow:

1. reviewer B or reviewer C independently evaluates the latest plan
2. plan must include tests, verification commands, write scope, and rollback expectations
3. if rejected, route back to `draft_plan`
4. if approval cannot be reached after retries, ask the human

Acceptance rule:

- no work item may enter execution unless its plan version is independently approved

### 8.5 Execute

Purpose:

- implement approved work items

Flow:

1. planner or coordinator decomposes the approved plan into explicit work items
2. each work item declares `write_scope`, `dependencies`, and `verification_scope`
3. work items with disjoint write scopes may run in parallel
4. each work item is authored by one implementer and checked by another agent

Output artifacts per work item:

- `patch.diff`
- `changed_files.json`
- `implementation_notes.md`
- `commands.log`

Execution rules:

- overlapping write scopes may not execute in parallel
- if two work items collide in practice, pause one and merge through a new integrated work item

### 8.6 Code Review

Purpose:

- independently assess correctness, regressions, missing tests, and plan compliance

Flow:

1. reviewer B evaluates each work item against the approved plan
2. blocking findings send the work item back to `execute`
3. if author disputes a finding and retries are exhausted, arbiter C reviews the same patch

Acceptance rule:

- a work item is accepted only after an independent reviewer or arbiter approves it

### 8.7 Verify

Purpose:

- confirm that the integrated result meets technical acceptance criteria

Flow:

1. verifier A runs the approved verification commands and records outputs
2. verifier B checks that the results justify the claimed state
3. if verification fails, route back to `execute`
4. if verification passes but interpretation is disputed, use arbiter C

Output artifacts:

- `verification_report.md`
- `verification_commands.json`
- `verification_output.log`

Acceptance rule:

- verification approval must be independent of the primary work-item author

### 8.8 Finalize

Purpose:

- publish the final task record and terminal state

Flow:

1. finalize only after plan approval, code review approval, and verification approval
2. assemble a final summary with evidence, decisions, unresolved non-blocking notes, and artifact pointers
3. mark task `completed`

Output artifacts:

- `final_summary.md`
- `decision_log.json`

## 9. Approval Matrix

| Stage | Author | Checker | Arbiter trigger | Human trigger |
|---|---|---|---|---|
| intake | intake/planner A | intake/reviewer B | repeated ambiguity disagreement | requirement ambiguity |
| research | researcher A | researcher B | evidence sufficiency dispute | missing external context |
| draft_plan | planner A | planner B | plan correctness dispute | product choice ambiguity |
| plan_review | planner A | reviewer B | repeated review conflict | unresolved architecture tradeoff |
| execute | implementer A | reviewer or implementer B | patch correctness dispute | unsafe action or blocked policy |
| code_review | reviewer B | reviewer C or arbiter C | reviewer disagreement | unresolved risk acceptance |
| verify | verifier A | verifier B | interpretation dispute | verification policy ambiguity |
| finalize | coordinator A | reviewer or verifier B | summary conflict | publish or release approval |

Rules:

- checker must be independent of the artifact author
- arbiter must be independent of the current artifact author
- human decision overrides stage state and becomes a recorded artifact

## 10. Artifact Model

Artifacts are immutable records attached to a task and, when relevant, to a stage attempt.

Required fields:

- `artifact_id`
- `task_id`
- `stage`
- `kind`
- `version`
- `created_by_agent_id`
- `created_ts_ms`
- `path`
- `summary`
- `parent_artifact_ids`

Artifact kinds:

- `task_brief`
- `question_set`
- `research_bundle`
- `source_bundle`
- `plan`
- `risk_register`
- `work_item`
- `patch`
- `review`
- `verification_report`
- `decision_record`
- `final_summary`

Immutability rule:

- revisions create a new artifact version
- approvals reference a specific artifact id and version

## 11. Work Item Model

The execution unit is a work item, not an entire task.

Required fields:

- `work_item_id`
- `task_id`
- `title`
- `description`
- `depends_on`
- `write_scope`
- `verification_scope`
- `status`
- `author_agent_id`
- `reviewer_agent_id`
- optional `arbiter_agent_id`

Work item statuses:

- `queued`
- `in_progress`
- `in_review`
- `changes_requested`
- `approved`
- `verified`
- `blocked`

Parallelism rule:

- two work items may run concurrently only if their normalized write scopes do not overlap

## 12. Event Model

Autonomous mode needs a new append-only event stream, not reuse of [`freemad/run_events.py`](../../freemad/run_events.py).

Event kinds:

- `task_created`
- `task_started`
- `stage_started`
- `artifact_created`
- `review_recorded`
- `decision_recorded`
- `stage_retried`
- `arbiter_requested`
- `human_input_requested`
- `human_input_received`
- `work_item_created`
- `work_item_started`
- `work_item_completed`
- `verification_started`
- `verification_completed`
- `task_paused`
- `task_resumed`
- `task_completed`
- `task_failed`

Every event must carry:

- `event_id`
- `task_id`
- `kind`
- `ts_ms`
- `stage`
- `actor_id` where relevant
- `payload`

The current task snapshot is always derived from the event log plus the artifact store.

## 13. Persistence

Persistence is required because autonomous tasks are long-lived.

Use:

- SQLite for task rows, stage attempts, approvals, work items, and event metadata
- task-scoped artifact directories for larger payloads

Recommended layout:

- `.freemad/tasks/tasks.db`
- `.freemad/tasks/artifacts/<task_id>/`

The runtime must be able to:

- reconstruct task state after restart
- resume a paused or waiting task
- inspect prior disputes and approvals
- replay task history in the dashboard

## 14. Agent Contract

The current agent contract in [`freemad/agents/base.py`](../../freemad/agents/base.py) exposes only:

- `generate()`
- `critique_and_refine()`

The shipped first milestone uses a typed action contract:

- `act(TaskRequest) -> TaskResponse`

Current `TaskRequest` fields:

- `task_id`
- `goal`
- `stage`
- `role`
- `workspace_root`
- `allowed_actions`
- optional `task_type`
- `artifact_refs`
- `feedback`
- optional `work_item`
- optional `required_output_kind`
- `write_scope`
- `verification_scope`

Current `TaskResponse` fields:

- `agent_id`
- `stage`
- `role`
- `content`
- optional `review_decision`
- `findings`
- `commands`
- `artifact_ids`
- `work_items`
- `writes`
- `sources`

Not yet normalized in the first cut:

- `task_brief`
- structured human-question payloads
- explicit policy-constraint fields inside the task request

The orchestrator stays in charge of transitions. Agents never move the task directly to the next stage by themselves.

## 15. Tool Policy

Tools are policy-bound, not implicit.

Policy dimensions:

- web research allowed or disallowed
- local command execution allowed or disallowed
- allowed command allowlist
- workspace write allowed or disallowed
- allowed write roots
- destructive action policy

Default posture:

- allow repo reads
- allow agent-native research tools
- allow local commands only from an allowlist
- allow writes only inside configured roots
- deny publish actions unless explicitly approved

Current first-milestone note:

- research provenance is persisted as structured `source_bundle` artifacts generated from `TaskResponse.sources`

## 16. CLI and Dashboard Shape

CLI:

- `freemad task start`
- `freemad task status`
- `freemad task inspect`
- `freemad task resume`
- `freemad task answer`
- `freemad task approve`
- `freemad task pause`

Dashboard:

- task list view
- task detail page
- task event timeline
- open questions pane
- artifact browser
- dispute and approval history
- work item graph

The current debate UI remains separate. `POST /api/tasks` starts a background autonomous task, and `WS /ws/tasks/{task_id}` tails persisted task events until the task reaches a terminal state.

## 17. Integration Points in the Current Codebase

Primary files and modules touched by the implemented first milestone:

- [`freemad/config.py`](../../freemad/config.py) for task-mode config, role config, and policy config
- [`freemad/types.py`](../../freemad/types.py) for stage, role, status, and decision enums
- [`freemad/agents/base.py`](../../freemad/agents/base.py) for the autonomous task contract beside debate mode
- [`freemad/agents/cli_adapter.py`](../../freemad/agents/cli_adapter.py) for the stage-aware prompt and task response path
- [`freemad/tasks/models.py`](../../freemad/tasks/models.py) for immutable task dataclasses
- [`freemad/tasks/store.py`](../../freemad/tasks/store.py) for SQLite persistence
- [`freemad/tasks/orchestrator.py`](../../freemad/tasks/orchestrator.py) for the autonomous state machine
- [`freemad/task_events.py`](../../freemad/task_events.py) for task-specific event types
- [`freemad/cli.py`](../../freemad/cli.py) for task commands
- [`freemad/dashboard/app.py`](../../freemad/dashboard/app.py) and [`freemad/dashboard/task_state.py`](../../freemad/dashboard/task_state.py) for task APIs, task pages, and dashboard reduction

## 18. First-Milestone Acceptance Criteria

The shipped first milestone is acceptable only if all of the following are true:

1. Debate mode continues to work unchanged.
2. Every autonomous stage records proposer, checker, and optional arbiter.
3. No artifact can be self-approved.
4. Tasks can pause for human input and resume afterward.
5. Task rows, task events, artifacts, and work items persist across restart.
6. Execution partitions work items by non-overlapping write scopes and runs each disjoint group in parallel.
7. Review rejection routes work back to execution.
8. Verification rejection routes work back to execution.
9. Task completion requires independent review and verification acceptance.
10. Dashboard and CLI can inspect task state and disputes after restart.

Still pending beyond the first milestone:

- arbitrary workflows beyond `plan` and `code`
- dedicated pub/sub transport for task streams beyond persisted-event tailing
- structured human-question payloads in the agent contract
- richer task telemetry for autonomous tool usage

## 19. Deliberate Non-Goals for the First Milestone

These should stay out of the first implementation:

- arbitrary business workflow automation outside repo and research tasks
- automatic merge or release actions
- unbounded agent spawning
- free-form side effects without policy
- replacing the debate runtime

## 20. Recommended Next Step

Use this document as the architectural contract for the current implementation, then plan the next hardening slice:

- richer task telemetry for autonomous tool usage
- structured human-question payloads in the agent contract
- task-aware policy for irreversible external side effects
