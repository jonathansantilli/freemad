# Autonomous Debate-First Implementation Plan

**Goal:** Rebuild autonomous mode so every decision-producing step uses the existing FREE-MAD consensus-free multi-agent debate algorithm, with autonomy handled as stage orchestration around repeated debate kernels rather than single-author workflow gates.

**Architecture:** The current autonomous runtime persists task state correctly, but it selects a single proposer for research, planning, and execution-adjacent stages. The corrected design keeps the stage machine, persistence, human-intervention model, and UI, while replacing every decision-producing stage with a reusable stage-level debate runner built from the existing FREE-MAD orchestration, scoring, and selection logic.

**Tech Stack:** Python, FastAPI, SQLite, existing FREE-MAD scoring/selection runtime, React dashboard UI.

---

## Why This Plan Exists

The current autonomous runtime is structurally wrong for FREE-MAD's core requirement.

Today, autonomous mode behaves like:

1. one agent authors a stage artifact
2. one independent agent reviews it
3. an arbiter may break ties
4. the task continues if the authored artifact survives review

That is a valid peer-review workflow, but it is not the FREE-MAD algorithm.

The required behavior is:

1. multiple agents generate competing candidate artifacts for the stage
2. those candidates go through critique/refinement rounds
3. the existing FREE-MAD scoring and selection logic chooses the stage winner
4. a writer or executor may apply the selected artifact, but does not decide it
5. if the selected artifact is a human question, the task pauses and asks it

This plan corrects the architecture so the debate kernel remains the decision engine at every stage.

## Non-Negotiable Invariants

These rules define the target architecture:

- Every decision-producing stage must use FREE-MAD debate and selection.
- No single agent-authored artifact becomes canonical by default.
- A writer/executor agent may apply the selected result, but cannot define it alone.
- Human clarification requests are debate-selected artifacts, not ad hoc reviewer messages.
- Debate mode remains intact and reusable as its own runtime.
- Autonomous mode becomes a stage machine around repeated debate kernels.

If any implementation step breaks one of these rules, it is the wrong implementation.

## Decision-Producing Stages

The following stages must all use debate-based selection:

- `research`
- `draft_plan`
- `plan_review`
- `execute`
- `code_review`
- `verify`
- `finalize`

Notes:

- `intake` is not a debate stage unless it produces a structured scoped interpretation that affects downstream work.
- `execute` may include a split between `decide what to change` and `apply the selected change`, but the decision half must still use FREE-MAD debate.

## Correct Autonomous Stage Model

Each stage must follow the same high-level contract:

1. Build a stage-specific debate prompt from task state, prior selected artifacts, human responses, and allowed actions.
2. Run a multi-agent generation round for that stage.
3. Run bounded critique/refinement rounds for that stage.
4. Score and select the winning artifact using the existing FREE-MAD selector.
5. Persist:
   - all candidate artifacts
   - the winning artifact
   - the stage debate transcript
   - the scores and selector metadata
6. If the winner is executable, apply it through a writer/executor path.
7. If the winner is a human question, transition to `waiting_for_human`.
8. If the winner is a rejection or retry outcome, route to the next stage transition.

This is the key correction: the stage result is no longer the proposer's artifact that survived review. It is the debate-selected artifact.

## Required New Internal Abstractions

### 1. Stage Debate Runner

Create a reusable internal runner that wraps the existing debate machinery for use inside autonomous mode.

Responsibilities:

- run generation for a stage
- run critique/refinement rounds for a stage
- score answers
- validate/select the winning artifact
- return full transcript and winner metadata

Required output:

- candidate artifacts
- selected artifact id
- selected content
- scores
- transcript
- origin agents / holders history

This runner should reuse logic from the existing debate runtime instead of re-implementing FREE-MAD in parallel.

### 2. Stage Debate Spec

Each stage needs a typed specification that tells the runner:

- which agents/roles participate
- what prompt to build
- what output artifact kind is expected
- whether the winning artifact is directly executable
- whether a human question is an allowed outcome
- what follow-up stage transitions are legal

This spec is what lets autonomous mode stay generic without falling back to single-author methods.

### 3. Selected Artifact Model

The task model must distinguish:

- candidate stage artifacts
- selected stage artifact
- applied artifact or execution result

Current artifact storage is not enough by itself because it records artifacts but does not establish `this one won the debate`.

### 4. Question Artifact Model

Human questions must be explicit selected artifacts with:

- question text
- rationale/context
- response type (`free_text`, `single_select`, `multi_select`, etc.)
- options if structured

This avoids the current drift where a reviewer can effectively become the human-escalation authority.

## Stage-by-Stage Target Behavior

### Research

- multiple researchers produce competing research bundles
- critique rounds challenge evidence quality, scope, and missing sources
- the winner is the selected research bundle
- if the winner is insufficient and a clarification question wins instead, ask the human

### Draft Plan

- multiple planners propose plans from the selected research bundle
- critique rounds attack assumptions, sequencing, missing tests, and architectural violations
- the winner is the selected plan
- work items are derived only from the selected plan

### Plan Review

- this is not a single reviewer veto stage
- it is a debate over outcomes such as `approve`, `revise`, `ask_human`
- the winning review outcome determines whether the plan advances, loops, or pauses

### Execute

- for work that materially changes architecture or behavior, multiple implementers propose the implementation artifact or patch plan
- the selected implementation artifact is then applied by one writer/executor
- for purely mechanical write steps, debate may choose the write plan and a single executor applies it

### Code Review

- debate selects the review conclusion, not one reviewer's opinion
- allowed winning outcomes include `approve`, `revise`, `ask_human`

### Verify

- verification commands still run concretely
- but the interpretation of verification state and next action should be debate-selected
- the winning outcome decides whether to finalize, loop back to execute, or escalate

### Finalize

- debate selects the completion summary and final task disposition
- no single planner should unilaterally declare completion

## File-Level Implementation Plan

### Task 1: Correct The Documentation First

Modify:

- `README.md`
- `docs/autonomous-mode.md`
- this file

Required changes:

- state clearly that every decision-producing autonomous stage uses FREE-MAD debate
- remove language that centers single proposer/checker quorum as the core model
- remove or replace broken references to `docs/plans/...`
- describe autonomous mode as `stage orchestration around repeated debate kernels`

### Task 2: Extract A Reusable Debate Kernel For Stages

Modify:

- `freemad/orchestrator.py`
- or create a reusable module under `freemad/` for stage debate execution

Required changes:

- isolate generation, critique rounds, scoring, and selection into a reusable internal interface
- keep existing debate CLI behavior unchanged
- make the runner accept stage prompts and typed output adapters

### Task 3: Add Stage Debate Models

Modify:

- `freemad/tasks/models.py`
- `freemad/task_events.py`
- `freemad/types.py`

Add models for:

- stage debate candidate artifact
- selected stage artifact
- stage debate transcript reference
- selected human question artifact
- execution application result

### Task 4: Replace Single-Proposer Research

Modify:

- `freemad/tasks/orchestrator.py`

Required changes:

- delete the single-proposer assumption in `_run_research`
- run a researcher debate instead
- persist all candidate research bundles and the selected winner
- advance only with the selected winner

### Task 5: Replace Single-Planner Drafting

Modify:

- `freemad/tasks/orchestrator.py`

Required changes:

- delete the single-planner assumption in `_run_draft_plan`
- run a planner debate instead
- derive work items only from the selected plan

### Task 6: Convert Review Stages Into Debate Outcomes

Modify:

- `freemad/tasks/orchestrator.py`

Required changes:

- treat `plan_review`, `code_review`, and `verify` as debate stages over outcomes
- allowed outcomes should include at least:
  - `approve`
  - `revise`
  - `ask_human`
- persist the winning review/verification outcome as a selected artifact

### Task 7: Split Execute Into Decision And Application

Modify:

- `freemad/tasks/orchestrator.py`
- possibly task models for execution artifacts

Required changes:

- debate decides the implementation artifact or patch plan
- writer/executor applies the selected artifact
- persist both:
  - selected implementation decision
  - execution application result

### Task 8: Wire Human Questions Through Debate Selection

Modify:

- `freemad/tasks/orchestrator.py`
- `freemad/tasks/models.py`
- `freemad/dashboard/app.py`
- `freemad_dashboard_ui/src/pages/AutonomousWorkspace.tsx`

Required changes:

- only debate-selected question artifacts may trigger `waiting_for_human`
- the UI must show that the question was the selected debate outcome
- the human response must feed the next stage debate input

### Task 9: Update Dashboard And API Surfaces

Modify:

- `freemad/dashboard/app.py`
- `freemad/dashboard/task_state.py`
- `freemad_dashboard_ui/src/pages/AutonomousWorkspace.tsx`

Required changes:

- expose candidate artifacts for a stage
- expose selected winner for a stage
- expose debate transcript summaries per stage
- clearly distinguish:
  - `waiting_for_human`
  - `failed`
  - `paused`
  - `debate-selected question`

### Task 10: Add Exhaustive Tests

Modify/add:

- `tests/pkg_mad/tasks/test_orchestrator.py`
- `tests/pkg_mad/tasks/test_models.py`
- `tests/pkg_mad/tasks/test_resume_flow.py`
- `tests/pkg_mad/dashboard/test_tasks_api.py`
- UI tests under `freemad_dashboard_ui/src/pages/`

Required test coverage:

- multiple candidates exist for each decision-producing stage
- selected artifacts come from debate, not single-author shortcuts
- human questions are selected by debate
- writer/executor only applies the selected artifact
- pause/resume preserves stage debate state
- dashboard surfaces the winner and candidates clearly
- failed tasks show explicit failure reasons, not human-checkpoint language

## Migration Strategy

The safest rollout order is:

1. docs correction
2. reusable stage debate runner
3. research and plan stages
4. review stages
5. execute split
6. UI/API exposure
7. full regression pass

Do not try to rewrite every stage at once.

## Success Criteria

This plan is complete only when all of the following are true:

- no decision-producing autonomous stage is single-author by default
- each stage records multiple candidate artifacts
- each stage records a debate-selected winner
- human questions are selected stage outcomes
- execution is downstream of decision, not the source of decision
- debate mode remains unchanged for one-shot runs

## Explicit Rejection Of The Old Model

The following model must not remain the architectural baseline:

- one proposer authors the artifact
- one reviewer challenges it
- one arbiter breaks ties
- the surviving authored artifact becomes canonical

That model is useful for code review workflows, but it is not FREE-MAD.

The correct model is:

- many agents debate at each stage
- FREE-MAD selects the winning stage artifact
- autonomy moves the task between stages and applies selected outputs
