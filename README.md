# FREE-MAD: Consensus-Free Multi-Agent Debate

[![CI](https://github.com/jonathansantilli/mad/actions/workflows/ci.yml/badge.svg)](https://github.com/jonathansantilli/mad/actions/workflows/ci.yml)
[![CodeQL](https://github.com/jonathansantilli/mad/actions/workflows/codeql.yml/badge.svg)](https://github.com/jonathansantilli/mad/actions/workflows/codeql.yml)
[![Scorecard](https://github.com/jonathansantilli/mad/actions/workflows/scorecard.yml/badge.svg)](https://github.com/jonathansantilli/mad/actions/workflows/scorecard.yml)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/jonathansantilli/freemad)

Production-ready Python implementation of the **Free-MAD** algorithm from the paper ["Free-MAD: Consensus-Free Multi-Agent Debate"](https://arxiv.org/html/2509.11035v1).

---

<video src="docs/images/freemad_ui.mp4" width="756" height="407" controls></video>

## What is Free-MAD?

Free-MAD is a revolutionary approach to multi-agent AI systems that **eliminates the need for consensus** among agents while achieving better accuracy and efficiency than traditional debate methods.

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

### Installation

```bash
# With Poetry (recommended)
poetry install
poetry run freemad --version

# With pip
pip install -e .
freemad --version
```

### Run Your First Multi-Agent Debate

```bash
# Using YAML configuration
poetry run freemad "Write a function that returns Fibonacci(n)." \
  --rounds 2 \
  --config config_examples/multi_agent.yaml

# Using JSON configuration
poetry run freemad "Write a function that returns Fibonacci(n)." \
  --rounds 2 \
  --config config_examples/multi_agent.json
```

Both YAML and JSON formats are supported. See `config_examples/multi_agent.yaml` or `config_examples/multi_agent.json` for complete configuration examples.

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

  - id: gpt-5
    type: openai_codex
    cli_command: "codex exec"
    cli_args: {--model: "gpt-5.1"}
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

**Complete configuration examples:**
- YAML: [`config_examples/multi_agent.yaml`](config_examples/multi_agent.yaml)
- JSON: [`config_examples/multi_agent.json`](config_examples/multi_agent.json)
- All available options: [`config_examples/ALL_KEYS.yaml`](config_examples/ALL_KEYS.yaml)

---

## Configuration Reference

### Agents
Define the AI agents participating in the debate:
- `id`: Unique identifier
- `type`: Adapter type (`claude_code`, `openai_codex`)
- `cli_command`: Command to invoke the agent
- `cli_args`: Key-value arguments passed to the CLI
- `cli_flags`: Boolean flags (e.g., `["--verbose"]`)
- `cli_positional`: Positional arguments (e.g., `["-"]` for stdin)
- `timeout`: Per-call timeout in seconds
- `config.temperature`: Model temperature (0.0-1.0)
- `config.max_tokens`: Max output tokens (null = unlimited)

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
- `cli_allowed_commands`: Whitelist of allowed executables
- `cli_use_shell`: Must be `false` for security
- `max_requirement_size`: Input size cap (chars)
- `max_solution_size`: Output size cap (chars)
- `redact_patterns`: Regex patterns to redact from logs

### Budget
- `max_total_time_sec`: Overall wall time budget
- `max_round_time_sec`: Per-round budget
- `max_agent_time_sec`: Per-agent call budget
- `max_tokens_per_agent_per_round`: Prompt truncation cap
- `enable_token_truncation`: Allow prompt truncation
- `max_concurrent_agents`: Parallelism limit

### Output
- `save_transcript`: Persist debate transcript
- `transcript_dir`: Output directory
- `format`: `json` or `markdown`
- `verbose`: Print extra info during execution

### Validation
- `enable_sandbox`: Run solutions in restricted Python sandbox
- `sandbox_timeout_ms`: Sandbox execution limit

### Cache
- `enabled`: On-disk memoization of agent outputs
- `dir`: Cache directory
- `max_entries`: Eviction limit

---

## Agent CLI Contract

Free-MAD communicates with agents via stdin/stdout. Your agent CLI must:

1. **Accept mode as argument**: `<cli_command> generate` or `<cli_command> critique`
2. **Read prompt from stdin**: The debate requirement or critique instructions
3. **Output structured response**:

```
SOLUTION:
<your proposed solution>

REASONING:
<your reasoning/arguments>
```

### Example Agent Wrapper

If your agent doesn't follow this contract, wrap it:

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

# With coverage
poetry run pytest --cov=freemad --cov-report=term --cov-report=xml
```

### Type Checking

```bash
mypy .
```

### Pre-commit Hooks

```bash
poetry run pre-commit install
poetry run pre-commit run --all-files
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

Find transcripts in `transcripts/` by default when `output.save_transcript: true`.

---

## Dashboard (WIP)

Free-MAD includes a web-based dashboard to visualize debate results. The dashboard reads JSON transcripts and displays the final answer, winning agents, and scores.

### Running the Dashboard

```bash
poetry run freemad-dashboard --dir transcripts --host 127.0.0.1 --port 8001
```

Then open your browser to `http://127.0.0.1:8001` to view the results.

**Command Options:**
- `--dir`: Directory containing JSON transcripts (default: `transcripts`)
- `--host`: Server host address (default: `127.0.0.1`)
- `--port`: Server port (default: `8001`)

### Current Features

- ✅ View final debate results
- ✅ See winning agents and scores
- ✅ Browse all transcript files

### Future Roadmap

The dashboard is actively being developed. Planned features include:

**Real-Time Debate Visualization:**
- Live conversation view showing agent-to-agent interactions
- Visual timeline of debate rounds
- See who said what in each round

**Metrics & Analytics:**
- Token usage tracking per agent and per round
- Time/duration metrics for each debate phase
- Cost estimation based on model pricing

**Agent Information:**
- Display model configurations (temperature, max_tokens)
- Show agent types and CLI commands used
- Topology visualization (peer assignment graphs)

**Configuration UI:**
- Configure agents through the web interface
- Edit debate parameters (rounds, weights, timeouts)
- Save and load configuration presets

**Interactive Final Agent:**
- Chat with a final orchestrator agent
- Execute the winning solution interactively
- Provide feedback and iterate on results

**Enhanced UX:**
- Make the system more user-friendly vs. command-line only
- Drag-and-drop configuration builder
- Real-time progress indicators

**Contributions Welcome!** If you'd like to help build these features, please see [CONTRIBUTING.md](CONTRIBUTING.md) or open an issue to discuss implementation ideas.

---

## Troubleshooting

### Agents not responding
- Verify `cli_command` is in your PATH
- Check `cli_command` is in `security.cli_allowed_commands`
- Increase `agents[].timeout` if needed
- Enable debug logging: `logging.level: DEBUG`

### Empty final solution
- Agents must output exactly `SOLUTION:` and `REASONING:` markers
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

---

## Community & Support

- **Issues**: [GitHub Issues](https://github.com/jonathansantilli/mad/issues)
- **Contributing**: See [CONTRIBUTING.md](CONTRIBUTING.md)
- **Code of Conduct**: See [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md)
- **Security**: See [SECURITY.md](SECURITY.md) for private vulnerability reporting
- **Governance**: See [GOVERNANCE.md](GOVERNANCE.md)

---

## Citation

If you use this implementation in your research, please cite:

```bibtex
@software{freemad2025,
  author = {Santilli, Jonathan},
  title = {FREE-MAD: Consensus-Free Multi-Agent Debate Implementation},
  year = {2025},
  url = {https://github.com/jonathansantilli/mad}
}
```

And the original paper:

```bibtex
@article{freemad2024,
  title={Free-MAD: Consensus-Free Multi-Agent Debate},
  author={...},
  journal={arXiv preprint arXiv:2509.11035},
  year={2024}
}
```

---

## License

MIT License © 2025 Jonathan Santilli. See [`LICENSE`](LICENSE) for full text.

---

## Trademarks & Affiliations

This project is independent and not affiliated with Anthropic, OpenAI, or any other vendor. "Claude", "Codex", and any other product names are trademarks of their respective owners and are used here only for identification.

---

## Research Paper

This implementation is based on the paper:

**"Free-MAD: Consensus-Free Multi-Agent Debate"**
arXiv:2509.11035v1
https://arxiv.org/html/2509.11035v1

### Key Contributions from the Paper:

1. **Eliminates consensus requirement**: Agents can disagree throughout the debate
2. **Score-based decision mechanism**: Evaluates entire debate trajectory, not just final votes
3. **Improved accuracy**: Outperforms traditional MAD on reasoning benchmarks
4. **Better efficiency**: Requires fewer debate rounds than consensus-based approaches
5. **Robustness**: Resistant to conformity bias and communication attacks

