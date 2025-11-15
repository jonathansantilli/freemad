from __future__ import annotations

from typing import Iterable
from freemad import GenMarker, CritMarker


GEN_SOLUTION = f"{GenMarker.SOLUTION.value}:"
GEN_REASONING = f"{GenMarker.REASONING.value}:"

CRT_DECISION = f"{CritMarker.DECISION.value}:"
CRT_REVISED_SOLUTION = f"{CritMarker.REVISED_SOLUTION.value}:"
CRT_REASONING = f"{CritMarker.REASONING.value}:"


def build_generation_prompt(requirement: str) -> str:
    """Self-descriptive prompt for Round 0 (independent generation).

    Scope: general problem-solving (not just coding). Produce the best
    final answer for the user's requirement. If code is required, include
    full code; if analysis/design is required, provide the final artifact
    (e.g., plan, spec, outline) directly in SOLUTION.

    Strict output contract:
    - Emit exactly two sections in this order, with all-caps markers:
      1) SOLUTION:
      2) REASONING:
    - No text before SOLUTION: or after REASONING:.
    - SOLUTION: the final deliverable (text and/or code). If code is present,
      use fenced code blocks with a language tag (e.g., ```python).
    - REASONING: brief rationale (<= 8 lines). State key assumptions if any
      information was missing; prefer decisive choices with short justifications.
    """
    return (
        "You are an expert problem-solving agent. Provide your best final answer.\n"
        "STRICT OUTPUT FORMAT — follow exactly.\n\n"
        f"{GEN_SOLUTION} <final deliverable: text and/or fenced code>\n\n"
        f"{GEN_REASONING} <succinct rationale and assumptions if needed>\n\n"
        "Requirement:\n" + requirement
    )


def build_critique_prompt(requirement: str, own_solution: str, peer_solutions: Iterable[str]) -> str:
    """Self-descriptive prompt for critique (anti-conformity, general tasks).

    Agent task:
    - Inspect your prior solution and anonymized peers’ solutions.
    - KEEP if your solution remains the best final answer for the user.
    - REVISE if you discover flaws, omissions, or a clearly better approach.
      You may synthesize an improved solution by integrating peers’ strengths.

    Strict output contract:
    - First line must be: DECISION: KEEP or DECISION: REVISE (uppercase).
    - If REVISE, include REVISED_SOLUTION: with the full updated deliverable
      (text and/or code; use fenced code blocks with language tags when code exists).
    - Always include REASONING: briefly justify the decision; cite peers as “Peer #k”.
    - No extra sections beyond DECISION, (optional) REVISED_SOLUTION, and REASONING.
    """
    peers = list(peer_solutions)
    peer_blob = "\n\n".join(f"Peer #{i+1}:\n{p}" for i, p in enumerate(peers)) if peers else "(no peers)"
    return (
        "Anti-conformity critique. Analyze peers for flaws and improvements.\n"
        "STRICT OUTPUT FORMAT — follow exactly.\n\n"
        f"{CRT_DECISION} KEEP|REVISE\n\n"
        f"{CRT_REVISED_SOLUTION} <required only if REVISE; full updated solution, ideally fenced with ```python>\n\n"
        f"{CRT_REASONING} <brief rationale; cite peers as Peer #k>\n\n"
        "Requirement:\n" + requirement + "\n\n"
        "Your prior solution:\n" + own_solution + "\n\n"
        "Peer solutions (anonymized):\n" + peer_blob
    )
