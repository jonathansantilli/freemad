# Security Policy

We take security seriously. Please follow these guidelines to report vulnerabilities responsibly.

## Reporting a Vulnerability
- Email: jonathansantilli@gmail.com
- Do not open public issues for suspected vulnerabilities.
- Provide reproduction details, affected versions, and impact if known.

## Response
- We aim to acknowledge in 2 business days and provide a timeline after triage.
- We may request a coordinated disclosure timeline.

## Scope
- The FREE‑MAD Python package and its CLI/dashboard.
- Not in scope: third‑party agent CLIs you configure (e.g., `claude`, `codex`, `zen-mcp`). Report issues in those tools to their maintainers.

## Hardening Notes
- Subprocesses are allowlisted and run with `shell=False`.
- Sandbox validator is disabled by default; when enabled, it runs with timeouts and restricted capabilities.
- Avoid sharing transcripts that may contain sensitive content; enable redaction patterns in config.
