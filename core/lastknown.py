"""
core/lastknown.py — the windows as they last stood, while the journals load.

A window opens before the journals have been read: the commander, the ship,
the career and the rest are not known until the history bootstraps have run
and the current journal has been replayed (``state.in_preload``), and until
then every window showed dashes. With this installed, each window model
(core/windows, the EDCARS header's facts, the route) answers with what it
showed at the end of the last run instead, the window says it is restoring
the last session, and the first full repaint after the replay replaces it
all with the live figures.

What a model answers is remembered only once the replay has finished, so
nothing half-built is ever kept; it is written to the commander's data
directory when EDLD exits and every few minutes while it runs. A different
EDLD version starts without it: the models may have changed shape.

    lastknown.install(core)     after the components load, before a window
"""
from __future__ import annotations

import atexit
import functools
import importlib
import pickle
import threading
from pathlib import Path
from typing import Any, Callable

#: module → the model functions in it, each taking the core (or, for the
#: EDCARS header's facts, the state) first.
MODELS: dict[str, tuple[str, ...]] = {
    "core.windows.career": ("tabs",),
    "core.windows.commander": ("headers", "home_line", "info", "ranks", "wallet",
                               "ships", "modules", "carrier", "squadron_carrier",
                               "identity_tabs", "fleet_tabs"),
    "core.windows.crew": ("crew", "tab"),
    "core.windows.exploration": ("view",),
    "core.windows.objectives": ("missions", "colonisation"),
    "core.windows.ship": ("header", "price_source", "cargo", "modules", "engineering",
                          "tabs"),
    "core.route_view": ("route_view",),
    "core.edcars": ("title_text", "title_forms", "strip", "location_text",
                    "vessel_text", "cargo_text", "squadron_text"),
}

FILE_NAME = "last_session.pickle"
SAVE_EVERY_S = 300.0


def _warming(first) -> bool:
    """Whether the history is still being read: the current journal's replay
    has not finished. ``first`` is the core or the state."""
    state = getattr(first, "state", first)
    return bool(getattr(state, "in_preload", False))


class LastKnown:
    def __init__(self, path: Path | None, version: str):
        self.path = path
        self.version = version
        self._lock = threading.Lock()
        self._values: dict[tuple, Any] = {}
        self._dirty = False
        self.restored = False       # whether anything was loaded

    # ── the file ─────────────────────────────────────────────────────────────

    def load(self) -> None:
        if self.path is None:
            return
        try:
            with open(self.path, "rb") as fh:
                saved = pickle.load(fh)
        except Exception:
            return
        if not isinstance(saved, dict) or saved.get("version") != self.version:
            return
        values = saved.get("values")
        if isinstance(values, dict):
            with self._lock:
                self._values = dict(values)
            self.restored = bool(values)

    def save(self) -> None:
        if self.path is None:
            return
        with self._lock:
            if not self._dirty:
                return
            values = dict(self._values)
            self._dirty = False
        keep = {}
        for key, value in values.items():
            try:
                pickle.dumps(value)
            except Exception:
                continue          # not something that can be kept: left out
            keep[key] = value
        tmp = self.path.with_suffix(".part")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with open(tmp, "wb") as fh:
                pickle.dump({"version": self.version, "values": keep}, fh,
                            protocol=pickle.HIGHEST_PROTOCOL)
            tmp.replace(self.path)
        except Exception:
            try:
                tmp.unlink()
            except OSError:
                pass

    # ── the models ───────────────────────────────────────────────────────────

    def wrap(self, key: str, fn: Callable) -> Callable:
        @functools.wraps(fn)
        def model(first, *args, **kwargs):
            k = (key,) + tuple(repr(a) for a in args) + tuple(
                f"{n}={v!r}" for n, v in sorted(kwargs.items()))
            if _warming(first):
                with self._lock:
                    if k in self._values:
                        return self._values[k]
                return fn(first, *args, **kwargs)
            value = fn(first, *args, **kwargs)
            with self._lock:
                self._values[k] = value
                self._dirty = True
            return value
        model.__wrapped_model__ = fn
        return model


_installed: LastKnown | None = None


def installed() -> LastKnown | None:
    return _installed


def restoring(core) -> bool:
    """Whether the windows are showing the last session: there was one to
    show, and the replay of the current journal has not yet finished."""
    return _installed is not None and _installed.restored and _warming(core)


def install(core, path: Path | None = None, version: str | None = None) -> LastKnown:
    """Wrap every model function and load the last session (once a run)."""
    global _installed
    if _installed is not None:
        return _installed
    if version is None:
        from core.state import VERSION as version
    if path is None:
        try:
            from core.state import cmdr_data_dir
            path = cmdr_data_dir() / FILE_NAME
        except Exception:
            path = None
    lk = LastKnown(path, version)
    lk.load()
    for mod_name, names in MODELS.items():
        mod = importlib.import_module(mod_name)
        for name in names:
            fn = getattr(mod, name, None)
            if fn is None or hasattr(fn, "__wrapped_model__"):
                continue
            setattr(mod, name, lk.wrap(f"{mod_name}.{name}", fn))
    _installed = lk
    atexit.register(lk.save)

    def _keep(stop=threading.Event()):
        while not stop.wait(SAVE_EVERY_S):
            lk.save()
    threading.Thread(target=_keep, daemon=True, name="lastknown-save").start()
    return lk
