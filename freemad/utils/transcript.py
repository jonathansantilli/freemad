from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


def save_transcript(result: dict[str, Any], fmt: str, dirpath: str) -> Path:
    ts = time.strftime("%Y%m%d-%H%M%S")
    p = Path(dirpath)
    p.mkdir(parents=True, exist_ok=True)
    if fmt == "json":
        out = p / f"transcript-{ts}.json"
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return out
    out = p / f"transcript-{ts}.md"
    lines = [
        f"# FREE-MAD Run {ts}",
        "",
        f"Final answer id: {result.get('final_answer_id')}",
        f"Winning agents: {', '.join(result.get('winning_agents', []))}",
        "",
        "## Transcript (JSON)",
        "```json",
        json.dumps(result, indent=2),
        "```",
    ]
    out.write_text("\n".join(lines), encoding="utf-8")
    return out
