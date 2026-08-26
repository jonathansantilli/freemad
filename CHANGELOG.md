# Changelog

All notable changes to this project will be documented in this file.

The format is based on Keep a Changelog, and this project aims to follow Semantic Versioning.

## [Unreleased]

### Added
- `evolve` runtime: goal-directed optimization over generations with a
  deterministic judge (gates + score comparator), git-worktree lineage with
  score-trailer commits and tags, stall/loop supervision with debate-driven
  interventions (directive TTL), human escalation with `answer`/`--decline`,
  durable event store (WAL + `synchronous=FULL`, read-only readers), CLI
  (`validate`/`start`/`status`/`inspect`/`report`/`pause`/`resume`/`stop`),
  protected judge paths with SHA-256 stamping, dashboard trajectory view,
  `examples/evolve_toy` proving ground with an operator comparison harness,
  and `examples/evolve_dependency_update` real-domain scaffold
  (`docs/evolve-runtime.md`)
- Evolve judge sandboxing: judge stages and worker-proposed commands run with a
  scrubbed environment built from an allowlist, so credentials are not visible to
  worker-authored code; `judge.network: false` black-holes proxy variables;
  `judge.env_passthrough` is the escape hatch for variables a judge needs
- Evolve dashboard: `/evolve` run index, a trajectory chart driven by whatever
  components the judge declares, and a `--evolve-store` flag
- Initial community health files (CoC, Contributing, Security, Governance, Support)
- Issue/PR templates, CODEOWNERS placeholder
- Dependabot, Scorecard, CodeQL workflows
- Pre-commit configuration (Black, Ruff, Bandit, hygiene)
- Editorconfig and gitattributes

### Fixed
- Evolve admission is fail-closed on judge stage failures. A stage that fails
  short-circuits the pipeline, so the gate could pass on a partial score vector and
  admit a candidate that broke the test suite
- Evolve comparator regression bounds are measured against the best-ever score rather
  than the baseline, closing the ratchet where a candidate improved the deciding term
  while destroying a lower-priority one
- Evolve protected paths are removed before being restored from `seed_ref`: files
  *added* inside a protected directory (a `conftest.py`, say) no longer survive
- Evolve runs resume after a crash between tagging and advancing the run branch;
  the iteration worktree is always cleaned up
- An absent `stop.target` no longer reads as "target already met", which ended every
  such run at the baseline with zero iterations
- Edits that only add files are no longer reported as "no changes produced"
- Escalation counters reset on a new best when rebuilt from events, and after human
  guidance, so a resumed run does not escalate immediately
- A worker's malformed write path or timed-out command fails the iteration instead of
  the whole run
- `evolve status`/`inspect` read the store named by `--config` instead of the default
  config's; `evolve answer --decline` no longer requires guidance text
- `evolve.repo_path` and `store_path` resolve against the config file's directory, as
  every other config-managed path does
- Judge stage commands are split with `shlex`, so quoted arguments survive

### Changed
- `freemad --version` reports the installed package version. It was a hard-coded `0.1.0`,
  and the package carried a second, different `__version__`; both now come from the
  distribution metadata
- `output.transcript_dir` and `cache.dir` are created and confined relative to the working
  directory — where they are written — instead of beside the config file, which created a
  phantom directory next to the config and rejected overrides the write path accepted
- `bin/structured_human_task_mock.py` and `config_examples/autonomous_ui_smoke.yaml` speak
  the autonomous runtime's actual human-in-the-loop protocol (reviewer findings, arbiter,
  `HUMAN_INPUT` feedback on resume); the README's autonomous quick start runs to completion
  with no credentials and is covered by a `SMOKE=1` test
- Repository links use the canonical `jonathansantilli/freemad` name. GitHub Discussions are
  not enabled, so questions go through a new *Question* issue template
- The whole repository is formatted with ruff-format and passes `pre-commit run --all-files`;
  build output and vendored assets are excluded from the hooks

### Fixed
- README audited against the code: dead design-doc links removed, the evolve runtime
  documented (quick start, CLI, configuration, dashboard, citation), the agent CLI contract
  corrected (the mode argument is opt-in via `cli_mode_arg`; critique replies start with
  `DECISION:`), and the dashboard described as shipped rather than as a roadmap
