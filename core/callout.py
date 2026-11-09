"""core/callout.py — say something: terminal, Discord, the Alerts pane, a sound.

    0  off      1  terminal      2  + Discord      3  + Discord ping

``sound`` names a cue from core/sounds.py, played when the Callouts component
has sounds on.
"""
from __future__ import annotations


def _callout_settings(core) -> dict | None:
    """The Callouts component's settings; None when it is not loaded."""
    p = getattr(core, "_plugins", {}).get("callouts")
    if p is None:
        return None
    try:
        return p.settings()
    except Exception:
        return {}


def play(core, cue: str) -> bool:
    """A cue, when the Callouts component is loaded with sounds on: turning
    the component off silences them."""
    s = _callout_settings(core)
    if s is None or not s.get("Sounds", True):
        return False
    from core import sounds
    return sounds.play(cue, int(s.get("Volume", 70) or 0), getattr(core, "state", None))


def say(core, key: str, emoji: str, text: str, *, sigil: str = "-  INFO",
        sound: str | None = None, alert: bool = False, urgent: bool = False,
        term: str | None = None, discord: str | None = None, timestamp=None) -> None:
    state = getattr(core, "state", None)
    if state is not None and getattr(state, "in_preload", False):
        return
    level = int((getattr(core, "notify_levels", None) or {}).get(key, 1))
    if level <= 0:
        return
    alerts = getattr(core, "_plugins", {}).get("alerts")
    if alert and alerts is not None:
        try:
            alerts.push_external(emoji, text, loglevel=key, msg_term=term or text,
                                 msg_discord=discord, sigil=sigil, urgent=urgent)
        except Exception:
            pass
    else:
        try:
            core.emitter.emit(msg_term=term or text,
                              msg_discord=discord or f"**{text}**",
                              emoji=emoji, sigil=sigil,
                              timestamp=timestamp or getattr(state, "event_time", None),
                              loglevel=level)
        except Exception:
            pass
    if sound:
        play(core, sound)
