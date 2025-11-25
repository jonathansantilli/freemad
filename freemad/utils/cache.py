from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional


def _sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


class DiskCache:
    def __init__(self, dir: str, max_entries: int | None = None) -> None:
        self.dir = dir
        self.max_entries = max_entries

    def _path_for(self, key: str) -> Path:
        h = _sha256(key)
        p = Path(self.dir) / f"{h}.json"
        return p

    def get(self, key: str) -> Optional[str]:
        p = self._path_for(key)
        if not p.exists():
            return None
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(obj, dict) or "raw" not in obj:
                return None
            # touch mtime
            os.utime(p, None)
            return str(obj.get("raw", ""))
        except Exception:
            return None

    def set(self, key: str, raw: str) -> None:
        p = self._path_for(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        payload = {"raw": raw}
        p.write_text(json.dumps(payload), encoding="utf-8")
        self._evict_if_needed()

    def _evict_if_needed(self) -> None:
        if not self.max_entries or self.max_entries <= 0:
            return
        files = sorted(Path(self.dir).glob("*.json"), key=lambda x: x.stat().st_mtime)
        while len(files) > self.max_entries:
            f = files.pop(0)
            try:
                f.unlink(missing_ok=True)
            except Exception:
                break

    @staticmethod
    def make_key(mode: str, agent_id: str, prompt: str, adapter_name: str, temperature: float, max_tokens: int | None) -> str:
        base = f"{mode}|{agent_id}|{adapter_name}|{temperature}|{max_tokens}|"
        return base + _sha256(prompt)
