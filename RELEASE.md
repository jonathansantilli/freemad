# Release Guide

This project uses Semantic Versioning and GitHub Actions with Trusted Publishing to PyPI.

## Versioning
- Format: `MAJOR.MINOR.PATCH` (e.g., `1.2.3`).
- Bump version in `pyproject.toml` under `[project] version`.
- Update `CHANGELOG.md` with notable changes.

## Pre‑release checklist
- [ ] CI green on main (tests, type checks, CodeQL, Scorecard, SBOM).
- [ ] Examples load/run (`examples/two_agents_*.{yaml,json}`).
- [ ] README install/run instructions verified under a clean venv.
- [ ] No secrets in history or examples; redaction patterns sensible.

## Tag and Publish
1. Create an annotated tag: `git tag -a vX.Y.Z -m "vX.Y.Z"`
2. Push tags: `git push --tags`
3. The `release.yml` workflow builds and publishes to PyPI via OIDC (no API token required) once PyPI Trusted Publishing is configured for the project name `freemad`.

## Post‑release
- Verify the PyPI page renders README.
- Create a GitHub release with highlights (Release Drafter can generate notes).
- Announce in Discussions.

## Action pinning (security)
- After the repo is public, pin all actions to commit SHAs in: `ci.yml`, `release.yml`, `codeql.yml`, `scorecard.yml`, `release-drafter.yml`, `sbom.yml`.
- Regenerate pins periodically (renovate or manual).
