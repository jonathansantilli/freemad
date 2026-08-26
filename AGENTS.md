Coding Conventions for FREE-MAD (Single Source of Truth)

- Use immutable dataclasses: prefer `@dataclass(frozen=True)` for all value objects, responses, transcripts, scores, and config-like records. Avoid mutable dictionaries internally; dictionaries are allowed only at API boundaries for JSON/Markdown output serialization.
- Use enums for categories: use `enum.StrEnum` for string-like categories (e.g., decisions, round types, score actions, tie-break strategies, validator names, section markers, logging events). Never compare raw string literals; compare enum members or their `.value`.
- Serialization: convert dataclasses/enums to primitive dicts via explicit `to_dict()` helpers at the boundary (CLI output, transcripts, files). Keep internal state strongly typed.
- Type checking: a `mypy.ini` is provided with strict-ish settings; prefer adding `from __future__ import annotations` and annotating all public functions. CI can run `mypy` when available.
- Determinism: any randomness must be seeded from the config to ensure deterministic tests.
- No shell=True and maintain CLI allowlist from config. Enforce budgets and size caps; include truncation markers where applied.

## Skills (single source of truth)

Detailed, task-specific guidance lives in **`.claude/skills/<name>/SKILL.md`** — five
skills: `freemad-architecture`, `freemad-python-patterns`, `freemad-security`,
`freemad-testing`, `freemad-ui-patterns`. That directory is the only canonical copy.

- **Claude Code** reads `.claude/skills/` natively.
- **Other agents** (Codex and any tool that indexes `.agents/skills/`): the same names
  exist under `.agents/skills/`, but each file there is a *pointer* whose body says
  "read `.claude/skills/<name>/SKILL.md`". Follow it. Do not edit the pointer.
- Any agent without either convention: read the five `.claude/skills/*/SKILL.md` files
  directly before working on the corresponding area.

Both directories are gitignored. Never create a third copy; update `.claude/skills/` and
the pointers stay valid by construction.

Design references: `evolve.md` (the evolve runtime handoff plan — decisions, not
suggestions), `docs/evolve-runtime.md` (user-facing), `docs/evolve-audit.md` (what was
found and fixed, and why).
