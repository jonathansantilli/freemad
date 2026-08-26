from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from app import normalize_title


def test_basic() -> None:
    assert normalize_title("Hello World") == "hello-world"


def test_punctuation() -> None:
    assert normalize_title("  Fast, Reliable & True!  ") == "fast-reliable-true"
