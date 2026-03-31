# Autonomous Quorum Runtime Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a new autonomous, quorum-governed task runtime beside the existing debate runtime without breaking current debate behavior, transcripts, or dashboard flows.

**Architecture:** Build autonomous mode as an additive subsystem under `freemad/tasks/` with its own task state, task events, persistence layer, and dashboard/API surfaces. Reuse the existing agent CLI infrastructure where possible, but introduce a distinct task-oriented contract so stages, approvals, and human escalation are explicit and strongly typed.

**Tech Stack:** Python, immutable dataclasses, `enum.StrEnum`, SQLite, FastAPI, Jinja2 templates, pytest, mypy.

---

## Pre-Work

Before starting code work:

- read [`docs/autonomous-mode.md`](../autonomous-mode.md)
- read [`docs/plans/2026-03-31-autonomous-quorum-runtime-spec.md`](2026-03-31-autonomous-quorum-runtime-spec.md)
- confirm the work starts from clean `main`
- confirm debate mode tests are green before adding any autonomous code

Run:

```bash
cd /Users/jonathansantilli/workspace/mad
poetry run pytest -q
```

Expected:

- current debate-mode test suite passes

## Task 1: Add Autonomous Enums and Config Surface

**Files:**
- Modify: `/Users/jonathansantilli/workspace/mad/freemad/types.py`
- Modify: `/Users/jonathansantilli/workspace/mad/freemad/config.py`
- Modify: `/Users/jonathansantilli/workspace/mad/freemad/__init__.py`
- Test: `/Users/jonathansantilli/workspace/mad/tests/pkg_mad/config/test_config.py`

**Step 1: Write failing config tests for autonomous mode**

Add tests covering:

- task stage enums serialize correctly
- task-mode config loads from YAML
- agent role declarations validate
- invalid autonomous config is rejected

**Step 2: Run the targeted config tests**

Run:

```bash
cd /Users/jonathansantilli/workspace/mad
poetry run pytest -q tests/pkg_mad/config/test_config.py
```

Expected:

- failing tests for missing task config and enum support

**Step 3: Add the minimal autonomous type surface**

Implement:

- `TaskStage`
- `TaskStatus`
- `TaskOutcome`
- `TaskRole`
- `TaskDecision`
- `ActionKind`

Use `enum.StrEnum` for every string-like category.

**Step 4: Extend config with autonomous-mode settings**

Add immutable config records for:

- task persistence paths
- retry limits
- role bindings
- tool policy
- verification commands

Do not break current debate config loading.

**Step 5: Export new public symbols**

Update `freemad/__init__.py` so the public config and type surface stays explicit.

**Step 6: Re-run targeted tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/config/test_config.py
```

Expected:

- config tests pass

## Task 2: Add Autonomous Domain Models

**Files:**
- Create: `/Users/jonathansantilli/workspace/mad/freemad/tasks/__init__.py`
- Create: `/Users/jonathansantilli/workspace/mad/freemad/tasks/models.py`
- Create: `/Users/jonathansantilli/workspace/mad/freemad/task_events.py`
- Test: `/Users/jonathansantilli/workspace/mad/tests/pkg_mad/tasks/test_models.py`

**Step 1: Write failing model tests**

Add tests for:

- task dataclass construction
- artifact immutability
- work item serialization
- task event `to_dict()` output

**Step 2: Run the model tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/tasks/test_models.py
```

Expected:

- failures because the task models do not exist yet

**Step 3: Add immutable task dataclasses**

Create frozen dataclasses for:

- `ArtifactRef`
- `ReviewRecord`
- `WorkItem`
- `StageAttempt`
- `TaskSnapshot`
- `TaskRequest`
- `TaskResponse`

Keep dictionaries at the serialization boundary only.

**Step 4: Add task-specific event types**

Create a separate event model from debate `RunEvent`, including:

- `TaskEventKind`
- `TaskEvent`
- `TaskObserver`
- `NullTaskObserver`

**Step 5: Re-run the model tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/tasks/test_models.py
```

Expected:

- task model tests pass

## Task 3: Add SQLite Task Store and Artifact Layout

**Files:**
- Create: `/Users/jonathansantilli/workspace/mad/freemad/tasks/store.py`
- Test: `/Users/jonathansantilli/workspace/mad/tests/pkg_mad/tasks/test_store.py`

**Step 1: Write failing persistence tests**

Cover:

- task creation
- event append
- snapshot reconstruction
- artifact registration
- pause and resume after reopen

**Step 2: Run the store tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/tasks/test_store.py
```

Expected:

- failures because the task store does not exist

**Step 3: Implement the task store**

Add:

- SQLite schema creation
- append-only event persistence
- task metadata persistence
- work item persistence
- artifact path helpers

Use task-scoped artifact directories under the configured path.

**Step 4: Enforce deterministic reconstruction**

Implement state rebuild from persisted task events plus stored records.

**Step 5: Re-run the store tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/tasks/test_store.py
```

Expected:

- store tests pass

## Task 4: Extend the Agent Contract for Autonomous Tasks

**Files:**
- Modify: `/Users/jonathansantilli/workspace/mad/freemad/agents/base.py`
- Modify: `/Users/jonathansantilli/workspace/mad/freemad/agents/cli_adapter.py`
- Create: `/Users/jonathansantilli/workspace/mad/freemad/prompts/autonomous.py`
- Modify: `/Users/jonathansantilli/workspace/mad/freemad/prompts/__init__.py`
- Test: `/Users/jonathansantilli/workspace/mad/tests/pkg_mad/agents/test_autonomous_cli_adapter.py`

**Step 1: Write failing agent-contract tests**

Cover:

- task request prompt generation
- task response parsing
- role and stage propagation
- autonomous prompt contract does not break debate prompt contract

**Step 2: Run the agent tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/agents/test_autonomous_cli_adapter.py
```

Expected:

- failures because the autonomous contract is missing

**Step 3: Add a task-oriented method to the base agent**

Introduce:

- `act(TaskRequest) -> TaskResponse`

Do not remove or weaken:

- `generate()`
- `critique_and_refine()`

**Step 4: Extend the CLI adapter**

Support:

- stage-aware prompts
- role-aware prompts
- structured parsing of task outputs
- capture of sources, review findings, and command logs when present

**Step 5: Re-run the agent tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/agents/test_autonomous_cli_adapter.py
```

Expected:

- autonomous agent tests pass

## Task 5: Implement the Autonomous Orchestrator

**Files:**
- Create: `/Users/jonathansantilli/workspace/mad/freemad/tasks/orchestrator.py`
- Test: `/Users/jonathansantilli/workspace/mad/tests/pkg_mad/tasks/test_orchestrator.py`

**Step 1: Write failing orchestrator tests**

Cover:

- stage transitions
- proposer/checker quorum
- arbiter escalation
- `waiting_for_human`
- retry exhaustion
- non-overlapping work item parallelism rules

**Step 2: Run the orchestrator tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/tasks/test_orchestrator.py
```

Expected:

- failures because the orchestrator does not exist

**Step 3: Implement stage state transitions**

Support:

- `intake -> research -> draft_plan -> plan_review -> execute -> code_review -> verify -> finalize`
- loops back from review and verification to earlier stages
- pause and resume semantics

**Step 4: Implement quorum and arbitration logic**

Enforce:

- no self-approval
- minimum two-agent stage participation
- third-agent arbitration on unresolved dispute
- human escalation on ambiguity or policy boundaries

**Step 5: Implement work-item scheduling**

Allow concurrent execution only when write scopes do not overlap.

**Step 6: Re-run the orchestrator tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/tasks/test_orchestrator.py
```

Expected:

- orchestrator tests pass

## Task 6: Add CLI Commands for Autonomous Tasks

**Files:**
- Modify: `/Users/jonathansantilli/workspace/mad/freemad/cli.py`
- Test: `/Users/jonathansantilli/workspace/mad/tests/pkg_mad/cli/test_cli_tasks.py`

**Step 1: Write failing CLI tests**

Cover:

- `freemad task start`
- `freemad task status`
- `freemad task inspect`
- `freemad task resume`
- `freemad task answer`
- `freemad task approve`
- `freemad task pause`

**Step 2: Run the CLI tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/cli/test_cli_tasks.py
```

Expected:

- failures because task subcommands are not implemented

**Step 3: Add the CLI command group**

Preserve current behavior:

- `freemad "<requirement>"` still runs debate mode

Add new task-oriented commands without changing the old entry path.

**Step 4: Re-run the CLI tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/cli/test_cli_tasks.py
```

Expected:

- CLI task tests pass

## Task 7: Add Dashboard APIs and Views for Autonomous Tasks

**Files:**
- Modify: `/Users/jonathansantilli/workspace/mad/freemad/dashboard/app.py`
- Create: `/Users/jonathansantilli/workspace/mad/freemad/dashboard/task_state.py`
- Create: `/Users/jonathansantilli/workspace/mad/freemad/dashboard/templates/tasks.html`
- Create: `/Users/jonathansantilli/workspace/mad/freemad/dashboard/templates/task.html`
- Modify: `/Users/jonathansantilli/workspace/mad/freemad/dashboard/templates/base.html`
- Test: `/Users/jonathansantilli/workspace/mad/tests/pkg_mad/dashboard/test_tasks_api.py`
- Test: `/Users/jonathansantilli/workspace/mad/tests/pkg_mad/dashboard/test_task_state.py`

**Step 1: Write failing dashboard tests**

Cover:

- task list API
- task detail API
- task websocket stream
- state reduction from task events
- task page rendering

**Step 2: Run the dashboard tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/dashboard/test_tasks_api.py tests/pkg_mad/dashboard/test_task_state.py
```

Expected:

- failures because the task dashboard surfaces do not exist

**Step 3: Add task APIs**

Expose:

- task creation
- task inspection
- task status
- task event streaming

Do not disturb current debate transcript pages.

**Step 4: Add task views**

Render:

- current stage
- open questions
- artifact history
- review decisions
- work items

**Step 5: Re-run the dashboard tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/dashboard/test_tasks_api.py tests/pkg_mad/dashboard/test_task_state.py
```

Expected:

- dashboard task tests pass

## Task 8: Add End-to-End Safety and Compatibility Coverage

**Files:**
- Modify: `/Users/jonathansantilli/workspace/mad/tests/pkg_mad/config/test_config.py`
- Create: `/Users/jonathansantilli/workspace/mad/tests/pkg_mad/tasks/test_policies.py`
- Create: `/Users/jonathansantilli/workspace/mad/tests/pkg_mad/tasks/test_resume_flow.py`
- Modify or add: debate-mode regression tests as needed under `/Users/jonathansantilli/workspace/mad/tests/pkg_mad/`

**Step 1: Write failing compatibility and policy tests**

Cover:

- debate mode remains unchanged
- blocked commands are rejected
- blocked write roots are rejected
- human escalation path is persisted
- restart and resume rebuild the same task state

**Step 2: Run the focused safety tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/tasks/test_policies.py tests/pkg_mad/tasks/test_resume_flow.py
```

Expected:

- failures for missing policy and resume behavior

**Step 3: Implement the minimal missing policy and compatibility logic**

Patch only what the failing tests require. Avoid inventing extra autonomous features at this stage.

**Step 4: Re-run the focused safety tests**

Run:

```bash
poetry run pytest -q tests/pkg_mad/tasks/test_policies.py tests/pkg_mad/tasks/test_resume_flow.py
```

Expected:

- focused safety tests pass

## Task 9: Run Full Verification

**Files:**
- No new product files unless verification uncovers defects

**Step 1: Run the full test suite**

Run:

```bash
cd /Users/jonathansantilli/workspace/mad
poetry run pytest -q
```

Expected:

- full test suite passes

**Step 2: Run type checking**

Run:

```bash
mypy .
```

Expected:

- no type errors

**Step 3: Manually smoke test both modes**

Run a debate task and one autonomous task command path to confirm both entry points are alive.

## Task 10: Final Documentation Sync

**Files:**
- Modify: `/Users/jonathansantilli/workspace/mad/README.md`
- Modify: `/Users/jonathansantilli/workspace/mad/docs/autonomous-mode.md`
- Modify: `/Users/jonathansantilli/workspace/mad/docs/plans/2026-03-31-autonomous-quorum-runtime-spec.md`

**Step 1: Update docs to reflect actual shipped behavior**

After code lands, remove any drift between:

- public README
- architecture doc
- runtime spec
- actual CLI and dashboard behavior

**Step 2: Add any final troubleshooting notes**

Document:

- how autonomous tasks pause for human input
- how to resume tasks
- where artifacts live
- how quorum and arbitration appear in the dashboard

## Execution Notes

Use these constraints throughout implementation:

- do not break debate mode
- keep autonomous events separate from debate run events
- keep internal state strongly typed
- use frozen dataclasses for task state and artifacts
- use `StrEnum` for stage, role, status, and decision categories
- keep shell usage disabled and preserve the CLI allowlist model
- add tests before each implementation slice

## Recommended Commit Boundaries

- `feat: add autonomous task config and enums`
- `feat: add task models and event types`
- `feat: add sqlite task store`
- `feat: add autonomous agent contract`
- `feat: add autonomous orchestrator`
- `feat: add task cli commands`
- `feat: add autonomous dashboard views`
- `test: add autonomous policy and resume coverage`
- `docs: sync autonomous runtime docs`
