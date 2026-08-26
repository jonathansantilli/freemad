"""vendored_lib 1.2.0 (pinned). API v1: slugify(text) -> kebab-case string."""

from __future__ import annotations

VERSION = "1.2.0"


def slugify(text: str) -> str:
    lowered = text.strip().lower()
    out = []
    for ch in lowered:
        if ch.isalnum():
            out.append(ch)
        elif ch in (" ", "_", "-"):
            out.append("-")
    collapsed = "".join(out)
    while "--" in collapsed:
        collapsed = collapsed.replace("--", "-")
    return collapsed.strip("-")
