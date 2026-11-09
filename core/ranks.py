"""core/ranks.py — the commander's ranks, from the journal or from Frontier.
"""
from __future__ import annotations

#: Journal key → the companion API's key, as data/ranks.CAPI_RANK_SKILLS names them.
_KEYS = {"Combat": "combat", "Trade": "trade", "Explore": "explore", "CQC": "cqc",
         "Soldier": "soldier", "Exobiologist": "exobiologist",
         "Federation": "federation", "Empire": "empire"}


def apply(state, event: dict) -> None:
    """A Rank or Progress event into ``state``."""
    from data.ranks import RANK_NAMES
    ev = event.get("event")
    values = {_KEYS[k]: int(v) for k, v in event.items()
              if k in _KEYS and isinstance(v, (int, float))}
    if ev == "Rank":
        state.journal_ranks = values
        if "combat" in values and 0 <= values["combat"] < len(RANK_NAMES):
            state.pilot_rank = RANK_NAMES[values["combat"]]
    elif ev == "Progress":
        state.journal_rank_progress = values
        if "combat" in values:
            state.pilot_rank_progress = values["combat"]


def rows(state) -> list[tuple[str, str]]:
    """(label, "Rank name  +n%") for each rank known, in the game's order."""
    from data.ranks import CAPI_RANK_SKILLS
    ranks = getattr(state, "capi_ranks", None) or getattr(state, "journal_ranks", None) or {}
    progress = (getattr(state, "capi_progress", None) if getattr(state, "capi_ranks", None)
                else getattr(state, "journal_rank_progress", None)) or {}
    out = []
    for key, label, table in CAPI_RANK_SKILLS:
        idx = ranks.get(key)
        if idx is None:
            continue
        name = table[idx] if 0 <= idx < len(table) else str(idx)
        prog = progress.get(key)
        out.append((label, f"{name}  +{prog}%" if prog is not None else name))
    return out


def combat_rank_text(state) -> str:
    """The combat rank as "Expert +16%", or "" before Rank and Progress.

    The game writes LoadGame before Rank and Progress, so on the first
    LoadGame of a run neither is known yet.
    """
    if state.pilot_rank is None:
        return ""
    if state.pilot_rank_progress is None:
        return str(state.pilot_rank)
    return f"{state.pilot_rank} +{state.pilot_rank_progress}%"
