"""core/engagement.py — whether the commander is in a fight, and whether they are
jumping out of one.

* Was a fighter lost to the enemy, or left behind? The game writes
  FighterDestroyed for both: for a fighter shot down, and for one the ship
  jumps away from or flies out of range of. Only the first is a loss worth
  ending a session over.
* Was cargo taken, or thrown out? EjectCargo is written for a hatch breaker
  and for the commander's own jettison alike, with the same fields.

Cargo is judged more narrowly (judge_jettison).

* the cargo panel (Status.json GuiFocus 1, the right-hand panel) open at the
  jettison: the commander did it — live only, as Status.json is not kept;
* a pirate's demand for cargo in the last DEMAND_WINDOW_S: the commander
  paying him off;
* otherwise, being shot at or interdicted in the last COMBAT_WINDOW_S, by
  the journal's own UnderAttack and interdiction events: taken.

Times are journal times (UTC), so the same answer comes out whether an event
is read live or replayed from a file.
"""
from __future__ import annotations

from datetime import datetime, timezone

#: How long after the last sign of a fight the commander still counts as in
#: one.
COMBAT_WINDOW_S = 60

#: How long after StartJump a FighterDestroyed is the ship leaving it behind.
#: The game writes it within a second or two of the jump starting; chat and
#: other lines can land between the two.
JUMP_WINDOW_S = 10

#: How long a jump may take to finish before it is taken to have failed.
JUMP_COMPLETE_S = 30

#: How far a sign of a fight may come *after* the event being judged and
#: still count. Status.json and the journal are written separately; the danger
#: flag can carry a timestamp a second or two later than the EjectCargo or
#: FighterDestroyed it explains.
SKEW_S = 15

#: Status.json Flags bits: IsInDanger, BeingInterdicted.
FLAG_IN_DANGER = 0x00400000
FLAG_BEING_INTERDICTED = 0x00800000

#: How long after a pirate's demand (or his reminder of it) a jettison is
#: paying him. The game repeats the demand every half minute or so while it
#: stands.
DEMAND_WINDOW_S = 90

#: Slack either side of the cargo panel's open interval. Status.json and the
#: journal are written separately, to the second.
PANEL_SLACK_S = 2

#: Status.json GuiFocus: the right-hand panel, where the cargo is.
GUI_INTERNAL_PANEL = 1

#: Being shot at or pulled out of supercruise: what cargo theft needs. Not
#: hull or shield damage (rocks do that) and not your own kills.
_HOSTILE_EVENTS = {"UnderAttack", "Interdicted", "EscapeInterdiction"}

#: NPC message keys for a pirate's demand for cargo, and his reminders.
_DEMAND_KEYS = ("$Pirate_Threaten", "$Pirate_Reminder",
                "$Pirate_OnUnsatisfactoryCargoDropped")

_ATTACK_EVENTS = {"UnderAttack", "Interdicted", "Interdiction", "EscapeInterdiction",
                  "Bounty", "FactionKillBond", "CapShipBond", "PVPKill", "HullDamage"}


def _utc(t) -> datetime | None:
    if t is None:
        return None
    if isinstance(t, datetime):
        return t if t.tzinfo else t.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromisoformat(str(t).replace("Z", "+00:00"))
    except ValueError:
        return None


def note_event(state, event: dict, at=None) -> None:
    """Record what this event says about fighting and jumping."""
    ev = event.get("event")
    t = _utc(at if at is not None else event.get("timestamp"))
    if t is None:
        return
    if ev in _ATTACK_EVENTS or (ev == "ShieldState" and not event.get("ShieldsUp", True)):
        _fought(state, t)
    if ev in _HOSTILE_EVENTS and event.get("Target") != "Fighter":
        last = getattr(state, "last_hostile_time", None)
        if last is None or t > last:
            state.last_hostile_time = t
    if ev == "ReceiveText" and event.get("Channel") == "npc" \
            and str(event.get("Message", "")).startswith(_DEMAND_KEYS):
        state.pirate_demand_time = t
        state.pirate_demand_from = event.get("From_Localised") or ""
    elif ev == "StartJump":
        state.last_start_jump_time = t
    elif ev in ("SupercruiseEntry", "FSDJump"):
        state.last_jump_done_time = t


def note_gui_focus(state, focus, at=None) -> None:
    """Status.json GuiFocus: when the cargo panel opened and closed, on the
    game's clock."""
    t = _utc(at) or datetime.now(timezone.utc)
    try:
        focus = int(focus or 0)
    except (TypeError, ValueError):
        return
    opened = getattr(state, "panel_open_since", None)
    closed = getattr(state, "panel_closed_at", None)
    is_open = opened is not None and closed is None
    if focus == GUI_INTERNAL_PANEL and not is_open:
        state.panel_open_since, state.panel_closed_at = t, None
    elif focus != GUI_INTERNAL_PANEL and is_open:
        state.panel_closed_at = t


def panel_open_at(state, at) -> bool:
    """The cargo panel was open at ``at``."""
    t = _utc(at)
    opened = getattr(state, "panel_open_since", None)
    closed = getattr(state, "panel_closed_at", None)
    if t is None or opened is None:
        return False
    if (opened - t).total_seconds() > PANEL_SLACK_S:
        return False
    return closed is None or (t - closed).total_seconds() <= PANEL_SLACK_S


def judge_jettison(state, at) -> tuple[str, str]:
    """What an EjectCargo (not abandoned) at ``at`` was: ("own", ""),
    ("payment", pirate name) or ("taken", "")."""
    t = _utc(at)
    if t is None:
        return "own", ""
    demand = getattr(state, "pirate_demand_time", None)
    if demand is not None and -SKEW_S <= (t - demand).total_seconds() <= DEMAND_WINDOW_S:
        return "payment", getattr(state, "pirate_demand_from", "") or ""
    if panel_open_at(state, t):
        return "own", ""
    hostile = getattr(state, "last_hostile_time", None)
    if hostile is not None and -SKEW_S <= (t - hostile).total_seconds() <= COMBAT_WINDOW_S:
        return "taken", ""
    return "own", ""


def note_status_flags(state, flags: int, at=None) -> None:
    """Status.json: danger or an interdiction in progress is a fight. ``at``
    is Status.json's own timestamp, so it is on the game's clock like the
    journal's."""
    if flags & (FLAG_IN_DANGER | FLAG_BEING_INTERDICTED):
        _fought(state, _utc(at) or datetime.now(timezone.utc))


def _fought(state, t: datetime) -> None:
    last = getattr(state, "last_combat_time", None)
    if last is None or t > last:
        state.last_combat_time = t


def in_combat(state, at=None) -> bool:
    """A sign of a fight within COMBAT_WINDOW_S before ``at`` (default: now)."""
    t = _utc(at) or datetime.now(timezone.utc)
    last = getattr(state, "last_combat_time", None)
    return last is not None and -SKEW_S <= (t - last).total_seconds() <= COMBAT_WINDOW_S


def fought_since(state, at) -> bool:
    """A sign of a fight from COMBAT_WINDOW_S before ``at`` onwards, on the
    game's clock — for judging an event some time after it happened, when
    this computer's clock and the game's may not agree."""
    t = _utc(at)
    last = getattr(state, "last_combat_time", None)
    return t is not None and last is not None and (t - last).total_seconds() <= COMBAT_WINDOW_S


def jumping_away(state, at=None) -> bool:
    """A jump began within JUMP_WINDOW_S before ``at``: whatever was lost was
    left behind by the ship leaving, not taken."""
    t = _utc(at) or datetime.now(timezone.utc)
    start = getattr(state, "last_start_jump_time", None)
    return start is not None and 0 <= (t - start).total_seconds() <= JUMP_WINDOW_S


def jump_completed_since(state, since) -> bool:
    """Supercruise or hyperspace reached at or after ``since``."""
    done = getattr(state, "last_jump_done_time", None)
    since = _utc(since)
    return done is not None and since is not None and done >= since


def jettison_text(count: int, name: str, kind: str, pirate: str = "") -> str:
    """The line for a jettison that was not theft."""
    text = f"Jettisoned {count:,} × {name}"
    if kind == "payment":
        text += f" for {pirate}" if pirate else " for a pirate"
    return text
