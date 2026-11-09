"""tests/test_undefined_names.py — no module may use a name it never defines.
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

pytest.importorskip("pyflakes")


def _sources() -> list[Path]:
    # Walk the tree rather than asking git, so a new file is checked before
    # it is committed.  Hidden directories (.git, .private, venvs) are skipped.
    return sorted(p for p in ROOT.rglob("*.py")
                  if not any(part.startswith(".") or part == "__pycache__"
                             for part in p.relative_to(ROOT).parts))


def test_no_undefined_names_anywhere():
    from pyflakes import api, reporter, messages

    class _Collect(reporter.Reporter):
        def __init__(self):
            self.found: list[str] = []
        def flake(self, msg):
            if isinstance(msg, messages.UndefinedName):
                self.found.append(str(msg))
        def unexpectedError(self, filename, msg):
            self.found.append(f"{filename}: {msg}")
        def syntaxError(self, filename, msg, lineno, offset, text):
            self.found.append(f"{filename}:{lineno}: {msg}")

    rep = _Collect()
    for path in _sources():
        api.check(path.read_text(encoding="utf-8"),
                  str(path.relative_to(ROOT)), rep)
    assert not rep.found, "undefined names:\n" + "\n".join(rep.found)
