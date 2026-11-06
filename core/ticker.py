"""
core/ticker.py — the once-a-second clock for components that watch time pass.

A component may define ``tick(self, state)``: things that happen because time
went by rather than because the journal said something — no kills for an hour,
a kill rate fallen below the floor, a lost fighter whose jump never finished.
Nothing called it. The inactivity and kill-rate alerts were configurable in
Options and documented, and never fired.

Started beside the Status.json poller, which every interface runs.
"""
from __future__ import annotations

import threading
import time

INTERVAL_S = 1.0


def tick_all(core, state, faults: set) -> None:
    """One pass: each component's tick, a failure in one not stopping the rest.

    A component that raises is reported once, to the diagnostic log and as a
    dashboard alert, and keeps being ticked: a fault on one tick may not
    recur, and silence is how this went unnoticed in the first place.
    """
    for name, plugin in list(getattr(core, "_plugins", {}).items()):
        fn = getattr(plugin, "tick", None)
        if not callable(fn):
            continue
        try:
            fn(state)
        except Exception as exc:
            if name in faults:
                continue
            faults.add(name)
            try:
                import traceback
                from core import debug as _dbg
                _dbg.log(f"{name}.tick failed: {exc}\n{traceback.format_exc()}",
                         level="ERROR")
            except Exception:
                pass
            try:
                core.plugin_call("alerts", "push_fault", "⚠️",
                                 f"{name}: timed checks failed ({type(exc).__name__})")
            except Exception:
                pass


def start(core, state) -> threading.Thread:
    faults: set = set()

    def run() -> None:
        while True:
            time.sleep(INTERVAL_S)
            tick_all(core, state, faults)

    t = threading.Thread(target=run, name="edld-ticker", daemon=True)
    t.start()
    return t
