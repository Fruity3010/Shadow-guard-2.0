#!/usr/bin/env python3
"""
Shared runtime path helpers for ShadowGuard.
"""

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent


def get_base_dir() -> Path:
    """Return the runtime base directory for generated files."""
    configured = (os.environ.get("SHADOWGUARD_BASE_DIR") or "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if not candidate.is_absolute():
            candidate = PROJECT_ROOT / candidate
    else:
        candidate = PROJECT_ROOT / ".shadowguard"

    candidate.mkdir(parents=True, exist_ok=True)
    return candidate


def runtime_path(*parts: str) -> Path:
    """Return a file path inside the runtime base directory."""
    path = get_base_dir().joinpath(*parts)
    path.parent.mkdir(parents=True, exist_ok=True)
    return path
