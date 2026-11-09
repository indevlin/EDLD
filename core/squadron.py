"""core/squadron.py — the commander's squadron, from the journal."""
from __future__ import annotations

#: Events that name the squadron (and perhaps the rank), and those that end it.
NAMING = ("SquadronStartup", "JoinedSquadron", "SquadronCreated",
          "SquadronPromotion", "SquadronDemotion")
ENDING = ("LeftSquadron", "KickedFromSquadron", "DisbandedSquadron")
EVENTS = NAMING + ENDING


def _rank(raw) -> str:
    """A rank name, or "" for a localization key the journal left unresolved
    ($SQUADRON_DEFAULTRANKNAME_RANK0;)."""
    text = str(raw or "").strip()
    return "" if text.startswith("$") else text


def apply(state, event: dict) -> None:
    ev = event.get("event")
    if ev in ENDING:
        state.pilot_squadron_name = ""
        state.pilot_squadron_tag = ""
        state.pilot_squadron_rank = ""
        return
    if ev not in NAMING:
        return
    name = str(event.get("SquadronName") or "").strip()
    if not name:
        return
    if name.casefold() != str(getattr(state, "pilot_squadron_name", "") or "").casefold():
        state.pilot_squadron_tag = ""          # another squadron: its tag is unknown
        state.pilot_squadron_rank = ""
    state.pilot_squadron_name = name
    rank = _rank(event.get("CurrentRankName") or event.get("NewRankName"))
    if rank:
        state.pilot_squadron_rank = rank
