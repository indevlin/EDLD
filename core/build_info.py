"""core/build_info.py — which build this is."""

from __future__ import annotations

import sys
from pathlib import Path


def variant() -> str:
    base = getattr(sys, "_MEIPASS", None)
    if base:
        try:
            v = (Path(base) / "BUILD_VARIANT").read_text(encoding="utf-8").strip()
            if v in ("full", "server"):
                return v
        except OSError:
            pass
    return "full"


def is_server_build() -> bool:
    return variant() == "server"
