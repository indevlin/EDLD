"""tests/test_announce_once.py — "Monitoring Active" is posted once per run.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.state import MonitorState  # noqa: E402


def test_a_new_journal_does_not_announce_again(tmp_path, monkeypatch):
    from core import journal as J

    files = []
    for stamp in ("2026-10-24T161910", "2026-10-25T152503", "2026-10-25T162025"):
        f = tmp_path / f"Journal.{stamp}.01.log"
        f.write_text(json.dumps({"event": "Fileheader"}) + "\n", encoding="utf-8")
        files.append(f)

    current = [0]
    monkeypatch.setattr(J, "handle_event", lambda *a, **k: None)
    monkeypatch.setattr(J.time, "sleep", lambda s: None)
    for name in ("bootstrap_last_session_end", "bootstrap_missions", "bootstrap_slf",
                 "bootstrap_crew", "bootstrap_hull", "load_session_state"):
        monkeypatch.setattr(J, name, lambda *a, **k: None)
    # Each pass of the live loop finds the game has opened the next journal.
    monkeypatch.setattr(J, "find_latest_journal",
                        lambda d: files[min(current[0] + 1, len(files) - 1)])

    embeds = []
    emitter = SimpleNamespace(post_embed=embeds.append, emit=lambda **k: None)
    cfg = SimpleNamespace(refresh=lambda: None, notify_levels={"x": 2})
    state = MonitorState()
    state.pilot_name = "MERRICK CALBRUIN"
    for i in range(2):
        current[0] = i
        nxt = J.monitor_journal(files[i], state, None, None, emitter, cfg, None,
                                tmp_path, [files[i]], 0.0)
        assert nxt == files[i + 1]
    assert len(embeds) == 1
    assert state.monitoring_announced is True
