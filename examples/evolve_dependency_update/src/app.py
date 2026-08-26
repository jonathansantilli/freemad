"""Application code that consumes vendored_lib using the pinned 1.x API."""

from __future__ import annotations

from vendor.vendored_lib import slugify


def normalize_title(title: str) -> str:
    return slugify(title)
