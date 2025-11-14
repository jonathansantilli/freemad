from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SecretSpec:
    source: str  # e.g., "env"
    name: str


def get_secret(spec: SecretSpec) -> Optional[str]:
    if spec.source == "env":
        return os.getenv(spec.name)
    # Future: keychain/OS keyring integrations
    return None

