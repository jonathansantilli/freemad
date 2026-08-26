# FREE-MAD: Consensus-Free Multi-Agent Debate

[![arXiv](https://img.shields.io/badge/arXiv-2509.11035-b31b1b.svg)](https://arxiv.org/abs/2509.11035)
[![arXiv](https://img.shields.io/badge/arXiv-2603.24517-b31b1b.svg)](https://arxiv.org/abs/2603.24517)
[![CI](https://github.com/jonathansantilli/freemad/actions/workflows/ci.yml/badge.svg)](https://github.com/jonathansantilli/freemad/actions/workflows/ci.yml)
[![CodeQL](https://github.com/jonathansantilli/freemad/actions/workflows/codeql.yml/badge.svg)](https://github.com/jonathansantilli/freemad/actions/workflows/codeql.yml)
[![Scorecard](https://github.com/jonathansantilli/freemad/actions/workflows/scorecard.yml/badge.svg)](https://github.com/jonathansantilli/freemad/actions/workflows/scorecard.yml)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/jonathansantilli/freemad)

A Python implementation of the **Free-MAD** algorithm from the paper ["Free-MAD: Consensus-Free Multi-Agent Debate"](https://arxiv.org/abs/2509.11035), plus two sibling runtimes built on the same agents, security model and configuration: **autonomous tasks** and **evolve**.

Agents are CLI tools you already have — Claude Code (`claude`) and OpenAI Codex (`codex`) — driven over stdin/stdout. FREE-MAD never reads or stores API keys; each agent CLI authenticates with its own login.

---


https://github.com/user-attachments/assets/8408ca39-14fc-4c2c-9959-5bbc78d6fc95



## Project Status

FREE-MAD ships three runtimes. This is what is on `main` today.

| Runtime | Status | Documentation |
|---|---|---|
| `debate` | Released (v2.0.0). The paper's algorithm: a generation round, critique rounds with anti-conformity prompting, trajectory scoring, deterministic selection. | this README |
| `autonomous` | First milestone. Persisted, resumable `plan` and `code` tasks; every stage has a proposer and an independent reviewer, with an arbiter on disagreement; pauses for human answers and approvals; dashboard task pages with live event streaming. | [`docs/autonomous-mode.md`](docs/autonomous-mode.md) |
| `evolve` | New on `main`, not yet in a tagged release. Goal-directed optimisation over generations: agents propose (alone or by debate), a deterministic judge admits or rejects every candidate, git keeps the lineage, a supervisor detects stalls and loops and redirects through debate, and a human is escalated to only as a last resort. | [`docs/evolve-runtime.md`](docs/evolve-runtime.md) |

Known limits of the autonomous first milestone: only `plan` and `code` workflows; no autonomous publish actions (push, merge, release); live task streams tail persisted events rather than using a dedicated pub/sub layer.

The evolve runtime has been audited and exercised end to end against real agents on a production codebase; the trail is in [`docs/evolve-audit.md`](docs/evolve-audit.md). Its one remaining manual gate is the 8-hour endurance run described in [`examples/evolve_toy/ENDURANCE.md`](examples/evolve_toy/ENDURANCE.md), which has not been run yet.

### Design Docs

- [`evolve.md`](evolve.md): the implementation handoff plan for the evolve runtime, adapted from NVIDIA's AVO paper so that debate is the variation operator and a deterministic judge is the selection mechanism
- [`docs/evolve-runtime.md`](docs/evolve-runtime.md): the shipped evolve runtime — design, CLI, configuration and security posture
- [`docs/evolve-audit.md`](docs/evolve-audit.md): the audit and fix log for evolve, round by round
- [`docs/autonomous-mode.md`](docs/autonomous-mode.md): the shipped autonomous runtime, its stage model, roles, persistence and current limits
- [`docs/autonomous-debate-first-implementation-plan.md`](docs/autonomous-debate-first-implementation-plan.md): a proposed redesign in which every decision-producing stage runs the FREE-MAD debate kernel. **A proposal, not implemented** — the shipped autonomous runtime is the proposer/checker one
- [`PRD.md`](PRD.md): the original design document (November 2025)
- [`AGENTS.md`](AGENTS.md): code conventions; [`CHANGELOG.md`](CHANGELOG.md): what changed since v2.0.0

## What is Free-MAD?

Free-MAD is an approach to multi-agent AI systems that **eliminates the need for consensus** among agents while achieving better accuracy and efficiency than traditional debate methods.

### Three Runtimes

Free-MAD ships three sibling runtimes over the same agent/security/config infrastructure:

| Runtime | Question it answers | Entry point |
|---|---|---|
| **Debate** | Which proposal is *best among candidates*? | `freemad "requirement" --config cfg.yaml` |
| **Autonomous tasks** | How do agents collaborate through a staged workflow? | `freemad task start --config cfg.yaml "goal"` |
| **Evolve** | How does measured progress toward an *external goal* accumulate over generations? | `freemad evolve start --config cfg.yaml "goal"` |

The evolve runtime keeps a strict division of responsibility: **debate judges quality
among proposals; a deterministic judge judges fitness against the goal. These are
never merged** — debate output can choose what to attempt, but only the deterministic
judge (gates + score comparator) admits a candidate into the lineage. If quorum
approval could ever gate a commit, the design is broken.

See [docs/evolve-runtime.md](docs/evolve-runtime.md) for the full design, the CLI,
the self-regulation contract, and the security posture.

### The Problem with Traditional Multi-Agent Debates

When you have multiple AI agents working on the same problem, traditional approaches (MAD - Multi-Agent Debate) work like this:

1. **Agents debate until they agree** (reach consensus)
2. **The final answer is chosen by majority vote**

This has serious problems:
- **Conformity bias**: Agents with the right answer get pressured by the majority into changing their minds (like peer pressure)
- **High cost**: Multiple debate rounds are needed to reach agreement
- **Majority tyranny**: The right answer can lose if fewer agents picked it—truth doesn't always win by popularity

### How Free-MAD Solves This

Free-MAD takes a fundamentally different approach:

1. **No consensus required** - Agents can disagree throughout the entire debate
2. **Score the journey, not just the destination** - Instead of only looking at final votes, Free-MAD evaluates the quality of reasoning across ALL debate rounds
3. **Quality beats quantity** - A single agent with strong reasoning can win, even if all others disagree

Think of it like judges scoring a debate competition: they don't wait to see who "wins" by convincing everyone else. Instead, they score **the quality of each debater's arguments** throughout the entire debate. The best-argued position wins, regardless of whether it convinced the majority.

### How It Works

**The Algorithm:**

1. **Round 0 (Generation)**: All agents independently propose solutions
2. **Round 1+ (Critique)**: Agents debate in two modes:
   - **Conformity mode**: Present arguments supporting their answer
   - **Anti-conformity mode**: Find flaws in other agents' answers
3. **Scoring**: Track the entire debate trajectory and score based on:
   - Quality of arguments
   - Valid criticisms found
   - How positions evolved over time
4. **Decision**: Select the answer with the highest score (not the most votes)

**Example:**

```
Round 1:
  Agent 1: Answer A (with strong reasoning)
  Agent 2: Answer B
  Agent 3: Answer B

Round 2:
  Agent 1: Stays with A, points out flaws in B
  Agent 2: Switches to A (convinced by Agent 1's arguments)
  Agent 3: Stays with B

Traditional MAD: B wins (2 votes)
Free-MAD: A wins (higher score due to quality of reasoning)
```

This means a single agent with the right answer and strong reasoning can win, even if the majority disagrees—something impossible with traditional consensus-based approaches.

---

## Quick Start

This section covers all three runtimes. The commands that need no credentials were run as written while auditing this README; the real-agent ones need the CLIs logged in.

### Requirements

- Python 3.10 or newer (CI runs 3.10, 3.11, 3.12 and 3.13).
- For real debates and tasks: the Claude Code CLI (`claude`) and/or the OpenAI Codex CLI (`codex`), each logged in with its own account. FREE-MAD runs them as subprocesses and never handles API keys.
- Optional: Docker or Podman, for the evolve runtime's container isolation. Node.js only if you want to rebuild the dashboard's React app — a build is committed.

### Installation

```bash
# With Poetry (recommended)
poetry install
poetry run freemad --version     # prints the installed package version, e.g. 2.0.0

# With pip
pip install -e .
freemad --version
```

`freemad` is the console script installed with the package. Inside the repository `poetry run freemad …` finds it; from anywhere else, put the environment's `bin/` on your PATH (`export PATH="$(poetry env info -p)/bin:$PATH"`).

### Run Your First Multi-Agent Debate

No credentials needed — two canned agents that follow the CLI contract:

```bash
poetry run freemad "Write a function that returns Fibonacci(n)." \
  --rounds 1 \
  --config config_examples/mock_agents.yaml
```

The result prints to the terminal and the full transcript is written to `transcripts/transcript-<timestamp>.json`.

With real agents (Claude Code and Codex, both logged in):

```bash
# Using YAML configuration
poetry run freemad "Write a function that returns Fibonacci(n)." \
  --rounds 2 \
  --config config_examples/multi_agent.yaml

# Using JSON configuration
poetry run freemad "Write a function that returns Fibonacci(n)." \
  --rounds 2 \
  --config config_examples/multi_agent.json

# Check that every configured agent CLI resolves and answers `--version`
poetry run freemad --health --config config_examples/multi_agent.yaml
```

Both YAML and JSON formats are supported. See `config_examples/multi_agent.yaml` or `config_examples/multi_agent.json` for complete configuration examples.

### Run Your First Autonomous Task

Autonomous mode uses a persistent task store and role-aware agents. `config_examples/autonomous_ui_smoke.yaml` drives it with canned agents, so this needs no credentials:

```bash
poetry run freemad task start \
  --config config_examples/autonomous_ui_smoke.yaml \
  --task-type plan \
  --workspace-root "$PWD" \
  "Critique this architecture until the agents approve an implementation-ready plan."
```

The command prints the task as JSON. The canned reviewer withholds approval until a product decision is made, the arbiter declines to make it, and the task parks in `waiting_for_human` with the question in `error`:

```bash
poetry run freemad task status <task_id> --config config_examples/autonomous_ui_smoke.yaml
#   "status": "waiting_for_human", "current_stage": "plan_review",
#   "error": "Which storage backend should we use first? (SQLite, Postgres)"

poetry run freemad task answer <task_id> "Use SQLite." --config config_examples/autonomous_ui_smoke.yaml
poetry run freemad task resume <task_id> --config config_examples/autonomous_ui_smoke.yaml
#   "status": "completed", "current_stage": "finalize"
```

The answer reaches the agents on resume as feedback (`HUMAN_INPUT: Use SQLite.`), the reviewer approves, and the plan finalizes. Other commands:

```bash
poetry run freemad task inspect <task_id> --config …          # full event log, artifacts, work items
poetry run freemad task approve <task_id> plan_review --config …   # record an approval for a stage
poetry run freemad task pause <task_id> --config …
```

Task state lives in `task.store_path` (SQLite) and `task.artifacts_dir`, relative to the working directory — `.freemad/ui-smoke/` for the smoke config.

To run the same workflow with real agents, start from [`config_examples/autonomous_ui_real_latest.yaml`](config_examples/autonomous_ui_real_latest.yaml): Claude and Codex through the bundled wrappers, with workspace writes and a short allowlist of local commands enabled. Read its `tool_policy` before pointing it at a repository you care about.

The first milestone supports:

- `plan` tasks that research, draft, review, arbitrate, and finalize plans
- `code` tasks that execute work items, run code review, run verification, and finalize

See [`docs/autonomous-mode.md`](docs/autonomous-mode.md) for role requirements, persistence layout, dashboard routes, and current limitations.

### Run Your First Evolve Optimisation

Evolve needs a real agent (the toy's config drives Claude Code) and its own git repository to build worktrees and lineage in, so work on a **copy** of the example:

```bash
export PATH="$(poetry env info -p)/bin:$PATH"          # `freemad` on PATH outside the repo
cp -R examples/evolve_toy /tmp/evolve_toy && cd /tmp/evolve_toy
git init -q . && git add -A && git commit -qm init

freemad evolve validate --config evolve.yaml          # config, repo cleanliness, judge dry-run on the seed
freemad evolve start --config evolve.yaml "make slow_sum as fast as possible"
```

Every subcommand takes `--config`, which names the store to read:

```bash
freemad evolve status  <run_id> --config evolve.yaml
freemad evolve report  <run_id> --config evolve.yaml   # trajectory report, byte-identical on re-run
freemad evolve inspect <run_id> --config evolve.yaml   # full event log
freemad evolve pause   <run_id> --config evolve.yaml
freemad evolve resume  <run_id> --config evolve.yaml
freemad evolve stop    <run_id> --config evolve.yaml

# If the run escalates to you, either guide it…
freemad evolve answer <run_id> "try memoizing partial sums" --config evolve.yaml
# …or decline, which is a valid clean stop
freemad evolve answer <run_id> --decline --config evolve.yaml
```

The toy's `evolve.yaml` runs the judge on the host, which `evolve validate` warns about: judge stages execute worker-authored code as you. To isolate them, enable `judge.container` (Docker or Podman must be reachable — a missing runtime fails the run rather than falling back to the host). Read the security posture in [`docs/evolve-runtime.md`](docs/evolve-runtime.md#security-posture-read-this) before running against code you do not fully trust.

Examples:

- [`examples/evolve_toy/`](examples/evolve_toy/): the proving ground — a deliberately slow function, a correctness gate, a benchmark, and `compare_operators.py`, which runs the toy under both variation operators
- [`examples/evolve_dependency_update/`](examples/evolve_dependency_update/): a real-domain example — upgrade a vendored library to 2.x without changing behaviour, with a protected characterization stage and a worked explanation of gate versus target
- [`examples/evolve_toy/ENDURANCE.md`](examples/evolve_toy/ENDURANCE.md): the 8-hour unattended run used for sign-off

---

## Configuration

Free-MAD is configured via YAML or JSON files. Here's a minimal example:

```yaml
agents:
  - id: claude-sonnet
    type: claude_code
    cli_command: "claude"
    cli_args: {model: "sonnet"}
    timeout: 600

  - id: codex
    type: openai_codex
    cli_command: "codex exec"
    cli_args: {--model: "gpt-5.3-codex"}
    cli_flags: ["--skip-git-repo-check"]
    cli_positional: ["-"]
    timeout: 600

topology:
  type: all_to_all    # all agents review all others
  seed: 427           # deterministic peer assignment

deadlines:
  soft_timeout_ms: 15000   # quorum wait
  hard_timeout_ms: 30000   # hard stop
  min_agents: 2            # quorum size

scoring:
  weights: [20.0, 25.0, 30.0, 20.0]  # [initial, change-penalty, change-bonus, keep]
  normalize: true                     # contributor-based normalization
  tie_break: deterministic            # or 'random'

security:
  cli_allowed_commands: ["claude", "codex"]
  cli_use_shell: false
  max_requirement_size: 20000
  max_solution_size: 400000

output:
  save_transcript: true
  transcript_dir: transcripts
  format: json
```

Relative output paths (`output.transcript_dir`, `cache.dir`, `task.store_path`, `task.artifacts_dir`) resolve against the working directory. The evolve runtime's `repo_path` and `store_path` name the *input* and resolve against the config file's directory instead, so `--config examples/evolve_toy/evolve.yaml` cannot silently optimise the outer repository.

**Complete configuration examples:**
- YAML: [`config_examples/multi_agent.yaml`](config_examples/multi_agent.yaml)
- JSON: [`config_examples/multi_agent.json`](config_examples/multi_agent.json)
- All debate-runtime options: [`config_examples/ALL_KEYS.yaml`](config_examples/ALL_KEYS.yaml)
- Mock agents, no credentials: [`config_examples/mock_agents.yaml`](config_examples/mock_agents.yaml)
- Autonomous tasks: [`config_examples/autonomous_ui_smoke.yaml`](config_examples/autonomous_ui_smoke.yaml) (canned agents), [`config_examples/autonomous_ui_real_latest.yaml`](config_examples/autonomous_ui_real_latest.yaml) (Claude + Codex)
- Evolve: [`examples/evolve_toy/evolve.yaml`](examples/evolve_toy/evolve.yaml), [`examples/evolve_dependency_update/evolve.yaml`](examples/evolve_dependency_update/evolve.yaml)

---

## Configuration Reference

### Agents
Define the AI agents participating in the debate:
- `id`: Unique identifier
- `type`: Adapter type (`claude_code`, `openai_codex`)
- `enabled`: Include the agent (default `true`)
- `cli_command`: Command to invoke the agent
- `cli_args`: Key-value arguments passed to the CLI; a key without a leading dash gets `--` prepended
- `cli_flags`: Boolean flags (e.g., `["--verbose"]`)
- `cli_positional`: Positional arguments (e.g., `["-"]` for stdin)
- `cli_mode_arg`: Pass the mode (`generate`, `critique`, …) as the first positional argument (default `false`)
- `cli_mode_flags`: Extra flags per mode, e.g. `{generating: ["--tools", ""]}`
- `timeout`: Per-call timeout in seconds
- `config.temperature`: Model temperature (0.0-1.0)
- `config.max_tokens`: Max output tokens (null = unlimited)
- `roles`: Optional autonomous-task roles such as `researcher`, `planner`, `reviewer`, `implementer`, `verifier`, `arbiter`
- `capabilities`: Optional autonomous action kinds such as `research`, `plan`, `review`, `implement`, `verify`

### Topology
Control how agents review each other's work:
- `all_to_all`: Every agent reviews all others (full debate)
- `k_reviewers`: Each agent reviews k random peers
- `ring`: Agents review in a circular pattern
- `star`: All agents review a central hub agent

### Scoring
Configure the Free-MAD scoring algorithm:
- `weights`: `[initial, change_penalty, change_bonus, keep]` - Weights for different scoring components
- `normalize`: Divide by contributor count to prevent score inflation
- `tie_break`: `deterministic` (first in list) or `random`
- `random_seed`: Seed for random tie-breaking

### Deadlines
Control debate round timing:
- `soft_timeout_ms`: Wait for quorum before proceeding
- `hard_timeout_ms`: Absolute deadline (accept late arrivals until this)
- `min_agents`: Quorum size at soft deadline

### Security
- `cli_allowed_commands`: Whitelist of allowed executables, matched by name against the first token of `cli_command`
- `cli_use_shell`: Must be `false` for security
- `cli_timeout_ms`: Global ceiling on a single CLI call
- `max_requirement_size`, `max_solution_size`, `max_critique_size`: Input and output size caps (chars)
- `redact_patterns`: Regex patterns to redact from logs

### Budget
- `max_total_time_sec`: Overall wall time budget
- `max_round_time_sec`: Per-round budget
- `max_agent_time_sec`: Per-agent call budget
- `max_tokens_per_agent_per_round`: Prompt truncation cap
- `enable_token_truncation`: Allow prompt truncation
- `max_total_tokens`, `enforce_total_tokens`: Total token budget, and whether exceeding it raises
- `max_concurrent_agents`: Parallelism limit

### Output
- `save_transcript`: Persist debate transcript
- `transcript_dir`: Output directory
- `format`: `json` or `markdown`
- `verbose`: Print extra info during execution
- `include_topology_info`: Include peer assignments in the transcript

### Logging
- `level`: `DEBUG`, `INFO`, `WARNING` or `ERROR`
- `file`: Optional log file path
- `console`: Log to the console
- `structured`: JSON lines instead of text

### Validation
- `enable_sandbox`: Run solutions in restricted Python sandbox
- `sandbox_timeout_ms`: Sandbox execution limit

### Cache
- `enabled`: On-disk memoization of agent outputs
- `dir`: Cache directory
- `max_entries`: Eviction limit

### Autonomous Tasks
- `task.store_path`: SQLite database path for task metadata and events
- `task.artifacts_dir`: Directory for task-scoped artifacts
- `task.max_stage_retries`: Retry count before arbitration or pause
- `task.max_total_iterations`: Overall iteration cap for a task
- `task.tool_policy.allow_web_research`: Whether autonomous tasks may rely on agent-native research tools
- `task.tool_policy.allow_workspace_write`: Whether autonomous tasks may write to the workspace
- `task.tool_policy.allowed_write_roots`: Relative roots autonomous writes may touch
- `task.tool_policy.allow_local_commands`: Whether autonomous tasks may run local commands
- `task.tool_policy.allowed_local_commands`: Allowlist for task-run commands
- `task.tool_policy.verification_commands`: Extra commands run during the verification stage

### Evolve
The `evolve:` section is documented in full in [`docs/evolve-runtime.md`](docs/evolve-runtime.md#configuration). Its parts:
- `repo_path`, `seed_ref`, `store_path`: the repository to optimise, the commit to start from, the event store
- `variation`: `single_agent` (one worker) or `debate` (proposals chosen by a FREE-MAD debate), and `debate_rounds`
- `judge`: `stages` (commands with `exit_code` or `json_stdout` parsing), `gate` predicates, the score `comparator`, `protected_paths`, `network`, `env_passthrough`, and `container` isolation
- `supervisor`: stall and loop detection thresholds, directive TTL, interventions before human escalation
- `stop`: `max_iterations`, `max_wall_clock_minutes`, `target` predicates
- `worker_budget`, `knowledge_paths`

---

## Agent CLI Contract

Free-MAD communicates with agents via stdin/stdout. For the debate runtime, your agent CLI must:

1. **Read the prompt from stdin**: the requirement, or the critique instructions with peer solutions
2. **Know which mode it is in**: with `cli_mode_arg: true` the mode is passed as the first positional argument (`<cli_command> generate` or `<cli_command> critique`); otherwise the prompt itself carries the instructions. `cli_mode_flags` adds per-mode flags (for example `--tools ""` so a coding agent does not run tools while generating)
3. **Output a structured response**

Generation mode:

```
SOLUTION:
<your proposed solution>

REASONING:
<your reasoning/arguments>
```

Critique mode:

```
DECISION: KEEP        (or DECISION: REVISE — must be the first line)

REVISED_SOLUTION:
<the full updated solution; required only when revising>

REASONING:
<why you kept or revised>
```

Autonomous tasks and evolve use a second protocol through the same adapter: the prompt ends with `Task request JSON:` followed by the request (`task_id`, `goal`, `stage`, `role`, `workspace_root`, `allowed_actions`, `artifact_refs`, `feedback`, …), and the agent prints a JSON `TaskResponse` (`agent_id`, `stage`, `role`, `content`, and optionally `review_decision`, `findings`, `commands`, `artifact_ids`, `work_items`, `writes`, `sources`).

### Bundled wrappers and mocks

- [`bin/claude_print_wrapper.py`](bin/claude_print_wrapper.py): runs Claude Code in plain print mode
- [`bin/codex_exec_wrapper.py`](bin/codex_exec_wrapper.py): runs `codex exec` in JSON event mode and extracts the final message
- [`bin/mock_agent.py`](bin/mock_agent.py): canned debate agent (`generate`/`critique`; `--force-revise` makes it revise)
- [`bin/structured_human_task_mock.py`](bin/structured_human_task_mock.py): canned autonomous-task agent that asks the human one question before approving
- [`bin/evolve_stub_agent.py`](bin/evolve_stub_agent.py): scriptable evolve worker speaking the task protocol, used by the test suite

### Example Agent Wrapper

If your agent doesn't follow this contract, wrap it. This wrapper expects `cli_mode_arg: true` and covers generation; a critique wrapper must emit `DECISION:` first.

```python
#!/usr/bin/env python3
import sys
import subprocess

mode = sys.argv[1]  # 'generate' or 'critique'
prompt = sys.stdin.read()

# Call your actual agent
result = subprocess.run(
    ["your-agent-command", "--mode", mode],
    input=prompt,
    capture_output=True,
    text=True
)

# Format output
print(f"SOLUTION:\n{result.stdout}")
print(f"\nREASONING:\nGenerated in {mode} mode")
```

---

## Development

### Running Tests

```bash
# Install dev dependencies
poetry install --with dev

# Run tests
poetry run pytest -q

# With coverage (CI fails under 80%)
poetry run pytest --cov=freemad --cov-report=term --cov-report=xml

# The smoke tests that run the README quick starts through the real CLI adapter
SMOKE=1 poetry run pytest -q tests/pkg_mad/agents/test_smoke_adapters.py tests/pkg_mad/tasks/test_smoke_autonomous_cli.py
```

CI runs the suite on Python 3.10–3.13 with `pip install -e .` — no Poetry and no `python` on PATH beyond what `setup-python` provides — so tests spawn interpreters through `sys.executable`. Tests that need a container runtime skip when none is reachable.

### Type Checking

```bash
poetry run mypy .
```

### Pre-commit Hooks

```bash
poetry run pre-commit install
poetry run pre-commit run              # the staged files, which is what the commit gate checks
```

`pre-commit run --all-files` is clean on `main`; run it before opening a pull request.

### Dashboard UI

The React app served at `/app` is prebuilt into `freemad/dashboard/static_app/`. To change it:

```bash
make ui-dev      # vite dev server
make ui-build    # rebuilds freemad/dashboard/static_app/
```

### Code Conventions

See [`AGENTS.md`](AGENTS.md) for detailed conventions:
- Immutable dataclasses
- StrEnums for constants
- No hard-coded strings internally
- Serialization at boundaries only

---

## Transcripts

Debate transcripts capture the complete history for analysis:

```json
{
  "final_answer_id": "abc123...",
  "final_solution": "def fibonacci(n): ...",
  "scores": {
    "abc123...": 85.5,
    "def456...": 72.3
  },
  "winning_agents": ["claude-sonnet"],
  "transcript": [
    {
      "round": 0,
      "type": "generation",
      "agents": {
        "claude-sonnet": {
          "response": { "solution": "...", "reasoning": "..." },
          "peers_assigned": [],
          "peers_seen": []
        }
      }
    },
    {
      "round": 1,
      "type": "critique",
      "agents": { ... }
    }
  ]
}
```

A transcript also carries `raw_scores`, `score_explainers`, `origin_agents`, `holders_history`, `validation`, `validator_confidence`, `metrics` and `early_stop_reason`, and each round records `deadline_hit_soft`, `deadline_hit_hard`, per-round `scores` and, when `output.include_topology_info` is on, `topology_info`.

Find transcripts in `transcripts/` by default when `output.save_transcript: true`.

---

## Dashboard

Free-MAD includes a local web dashboard for all three runtimes.

### Running the Dashboard

```bash
poetry run freemad-dashboard --dir transcripts --host 127.0.0.1 --port 8001
# with evolve runs: point it at the evolve store
poetry run freemad-dashboard --dir transcripts --evolve-store .freemad/evolve/evolve.db
```

Then open `http://127.0.0.1:8001`.

**Command Options:**
- `--dir`: Directory containing JSON transcripts (default: `transcripts`)
- `--evolve-store`: Path to the evolve SQLite store
- `--host`: Server host address (default: `127.0.0.1`)
- `--port`: Server port (default: `8001`)

### What it serves

- `/` and `/runs/<file>`: recent debate transcripts — final answer, winning agents, scores, round by round
- `/app`: the live debate view (React). `POST /api/live-runs` starts a debate in the background — with `config_examples/mock_agents.yaml` unless a config is given — and `WS /ws/live-runs/<run_id>` streams it as it happens
- `/tasks` and `/tasks/<task_id>`: autonomous tasks — status and current stage, artifacts, the event log, and the question a task is waiting on. `POST /api/tasks` starts a task in a background thread; `WS /ws/tasks/<task_id>` tails its persisted events
- `/evolve` and `/evolve/<run_id>`: every evolve run, and the score at each accepted version with supervisor interventions marked on the chart and human escalations in red; `/api/evolve` serves the same data as JSON
- `/api/runs`, `/api/tasks`, `/api/config/override`, `/health`: the JSON endpoints behind the pages

### Roadmap

Not built yet:

- Token, duration and cost metrics per agent and per round
- A configuration editor in the browser
- An interactive final agent to execute and iterate on the winning solution

**Contributions Welcome!** If you'd like to help build these features, please see [CONTRIBUTING.md](CONTRIBUTING.md) or open an issue to discuss implementation ideas.

---

## Troubleshooting

### Agents not responding
- Run `freemad --health --config <cfg>`: it reports, per agent, whether `cli_command` resolves and answers `--version`
- Verify `cli_command` is in your PATH
- Check the first token of `cli_command` is in `security.cli_allowed_commands`
- Increase `agents[].timeout` if needed
- Enable debug logging: `logging.level: DEBUG`

### Empty final solution
- Agents must output exactly `SOLUTION:` and `REASONING:` markers (and `DECISION:` first when critiquing)
- Check transcript to see what agents actually produced
- Test your agent CLI manually with echo prompts

### Debate ends early
- Increase `deadlines.hard_timeout_ms`
- Increase `budget.max_round_time_sec`
- Ensure `deadlines.min_agents` ≤ number of enabled agents
- Check `early_stop_reason` in transcript

### Deterministic results
- Set `topology.seed` for consistent peer assignments
- Set `scoring.random_seed` for consistent tie-breaking
- Use `scoring.tie_break: deterministic`

### Evolve run refuses to start
- `freemad evolve validate --config <cfg>` reports problems before anything runs — judge configuration errors, a seed that cannot be checked out, judge stages that fail on the seed, a container runtime that is not reachable — and warnings about posture, such as the container being off or a scoring stage that does not reference a protected path

---

## Community & Support

- **Issues**: [GitHub Issues](https://github.com/jonathansantilli/freemad/issues)
- **Questions**: open an issue with the *Question* template — see [SUPPORT.md](SUPPORT.md)
- **Contributing**: See [CONTRIBUTING.md](CONTRIBUTING.md)
- **Code of Conduct**: See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- **Security**: See [SECURITY.md](SECURITY.md) for private vulnerability reporting
- **Governance**: See [GOVERNANCE.md](GOVERNANCE.md)

---

## Citation

If you use this implementation in your research, please cite it (machine-readable metadata is in [`CITATION.cff`](CITATION.cff)):

```bibtex
@software{freemad2025,
  author = {Santilli, Jonathan},
  title = {FREE-MAD: Consensus-Free Multi-Agent Debate Implementation},
  version = {2.0.0},
  year = {2025},
  url = {https://github.com/jonathansantilli/freemad}
}
```

The debate algorithm:

```bibtex
@article{cui2025freemad,
  title={Free-MAD: Consensus-Free Multi-Agent Debate},
  author={Cui, Yu and Fu, Hang and Zhang, Haibin and Wang, Licheng and Zuo, Cong},
  journal={arXiv preprint arXiv:2509.11035},
  year={2025}
}
```

The origin of the evolve runtime:

```bibtex
@article{chen2026avo,
  title={AVO: Agentic Variation Operators for Autonomous Evolutionary Search},
  author={Chen, Terry and Ye, Zhifan and Xu, Bing and Ye, Zihao and Liu, Timmy and Hassani, Ali and Chen, Tianqi and Kerr, Andrew and Wu, Haicheng and Xu, Yang and Chen, Yu-Jung},
  journal={arXiv preprint arXiv:2603.24517},
  year={2026}
}
```

---

## License

MIT License © 2025 Jonathan Santilli. See [`LICENSE`](LICENSE) for full text.

---

## Trademarks & Affiliations

This project is independent and not affiliated with Anthropic, OpenAI, NVIDIA, or any other vendor. "Claude", "Codex", and any other product names are trademarks of their respective owners and are used here only for identification.

---

## Research Papers

The debate runtime implements:

**"Free-MAD: Consensus-Free Multi-Agent Debate"** — Yu Cui, Hang Fu, Haibin Zhang, Licheng Wang, Cong Zuo. arXiv:2509.11035, September 2025. https://arxiv.org/abs/2509.11035

Key contributions from the paper:

1. **Eliminates consensus requirement**: Agents can disagree throughout the debate
2. **Score-based decision mechanism**: Evaluates entire debate trajectory, not just final votes
3. **Improved accuracy**: Outperforms traditional MAD on reasoning benchmarks
4. **Better efficiency**: Requires fewer debate rounds than consensus-based approaches
5. **Robustness**: Resistant to conformity bias and communication attacks

The evolve runtime adapts:

**"AVO: Agentic Variation Operators for Autonomous Evolutionary Search"** — Terry Chen et al. (NVIDIA). arXiv:2603.24517, March 2026. https://arxiv.org/abs/2603.24517

AVO uses agents as the variation operator of an evolutionary search. FREE-MAD re-targets that design so a consensus-free debate can be the variation operator and a deterministic judge is the selection mechanism; the adaptation and every decision made along the way are in [`evolve.md`](evolve.md).
