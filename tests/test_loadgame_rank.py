"""tests/test_loadgame_rank.py — the commander line before the rank is known.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.ranks import combat_rank_text  # noqa: E402
from core.state import MonitorState  # noqa: E402
from test_on_foot import _aboard_procurator, _commander  # noqa: E402

LOADGAME = {"timestamp": "2026-11-03T15:27:44Z", "event": "LoadGame",
            "Commander": "MERRICK CALBRUIN", "Ship": "AnacondaMkII",
            "Ship_Localised": "Anaconda Mk II", "ShipID": 39, "ShipName": "PROCURATOR",
            "ShipIdent": "AN-PRO", "FuelLevel": 64.0, "FuelCapacity": 64.0,
            "GameMode": "Solo"}


def test_the_rank_text():
    s = MonitorState()
    assert combat_rank_text(s) == ""
    s.pilot_rank = "Expert"
    assert combat_rank_text(s) == "Expert"
    s.pilot_rank_progress = 16
    assert combat_rank_text(s) == "Expert +16%"


def test_loadgame_before_the_rank_leaves_it_out():
    state = _aboard_procurator()
    state.pilot_rank = state.pilot_rank_progress = None
    p, said = _commander(state)
    p.on_event(dict(LOADGAME), state)
    line = said[-1]["msg_term"]
    assert line == "CMDR MERRICK CALBRUIN (Anaconda Mk II / Solo)"
    assert "None" not in said[-1]["msg_discord"]


def test_loadgame_after_the_rank_shows_it():
    state = _aboard_procurator()
    state.pilot_rank, state.pilot_rank_progress = "Expert", 16
    p, said = _commander(state)
    p.on_event(dict(LOADGAME), state)
    assert said[-1]["msg_term"] == "CMDR MERRICK CALBRUIN (Anaconda Mk II / Solo / Expert +16%)"


def test_the_pirate_line_has_an_apostrophe():
    for rel in ("core/journal.py", "components/alerts.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert 'didn"t' not in src, rel
        assert "Pirate didn't engage" in src, rel
