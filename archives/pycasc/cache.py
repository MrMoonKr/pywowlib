from __future__ import annotations

from pathlib import Path


def get_cache_dir() -> Path:
    cache_dir = Path(__file__).resolve().parent.parent / ".cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir
