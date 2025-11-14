# Contributing

Thanks for your interest in contributing! This document explains how to set up a dev environment, run tests, follow our workflow, and propose changes.

## Quick Start
- Prereqs: Python 3.10+, Poetry 2.x, Git, make (optional).
- Install: `poetry install`
- Run CLI: `poetry run freemad --version`
- Run dashboard: `poetry run freemad-dashboard --dir transcripts`

## Running Tests
- We use pytest.
- Command: `poetry run pytest -q --cov=mad`
- Type checking: `poetry run mypy .`

## Lint/Format
- Pre-commit hooks are provided (Black, Ruff, basic hygiene):
  - Install: `poetry run pre-commit install`
  - Run all: `poetry run pre-commit run --all-files`

## Commit Style
- Use Conventional Commits (e.g., `feat:`, `fix:`, `docs:`, `test:`). This enables clean changelogs and release automation.
- Example: `feat(orch): add consensus early-stop policy`

## DCO (Developer Certificate of Origin)
- We require Signed-off-by lines on commits to certify origin and license.
- Add with: `git commit -s -m "your message"`

## Pull Requests
- Ensure: tests pass, coverage not reduced, type checks clean, pre-commit clean.
- Describe: what and why, user impact, and any config changes.
- Link related issues and add tests for new behavior.

## Design & Spec
- The normative spec is in `conclusion/normative-spec.md`. When in doubt, it prevails.
- Internal code uses immutable dataclasses and StrEnums. Avoid dicts and raw string comparisons.

## Security & Privacy
- Do not include secrets in issues/PRs or transcripts. Use redaction patterns in config.
- Report vulnerabilities privately (see SECURITY.md).

## Governance
- See GOVERNANCE.md for decision-making and maintainer roles.

Thank you for helping make FREE‑MAD better!

