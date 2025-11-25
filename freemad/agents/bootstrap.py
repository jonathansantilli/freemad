from __future__ import annotations

"""Bootstrap agent registrations.

Importing this module registers built-in adapters with the registry.
"""

from .registry import register_agent
from .claude_agent import ClaudeCodeAgent
from .codex_agent import OpenAICodexAgent


def register_builtin_agents() -> None:
    register_agent("claude_code", ClaudeCodeAgent)
    register_agent("openai_codex", OpenAICodexAgent)


# Register on import for convenience
register_builtin_agents()
