# Open‑Source Readiness Checklist

This checklist summarizes the non‑functional items that keep the repo healthy and safe for public use.

## Compliance & Policy
- [x] License: MIT (LICENSE present)
- [x] Code of Conduct: Contributor Covenant with maintainer contact
- [x] Security policy: SECURITY.md with private email contact
- [x] DCO: `DCO` file and `-s` signoff in CONTRIBUTING.md

## Packaging
- [x] `pyproject.toml` with clear name (`freemad`), authors, classifiers, URLs
- [x] Console scripts: `freemad`, `freemad-dashboard`
- [ ] Optional: include `examples/` and `conclusion/` in sdist if desired (to decide)

## CI / Supply Chain
- [x] CI: tests (pytest), coverage gate, mypy
- [x] CodeQL: static analysis
- [x] Scorecard: supply‑chain checks
- [x] SBOM: SPDX JSON artifact via syft action
- [ ] Pin all actions to commit SHAs after repo is public

## Docs & DX
- [x] README with install/run (Poetry), config reference, troubleshooting, security, trademarks
- [x] CHANGELOG, CONTRIBUTING, GOVERNANCE, SUPPORT
- [x] Examples configs for direct and MCP agents
- [x] Dashboard usage documented
- [ ] Screenshots/GIFs in README (optional)

## Security Hardening
- [x] Subprocess `shell=False`, allowlist, timeouts
- [x] Redaction patterns configurable
- [x] Sandbox validator disabled by default; documented

## Community
- [x] Issue templates and PR template
- [x] CODEOWNERS set to @jonathansantilli
- [ ] Enable Discussions in repository settings

## Release
- [x] Release workflow (trusted publishing)
- [x] Release Drafter
- [x] Version bump instructions (RELEASE.md)

Notes
- Action pinning requires public repo to resolve commit SHAs; planned post‑publish.
