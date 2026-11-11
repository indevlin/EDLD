"""components/community_goals.py — the community goals the commander has
signed up for, and their contribution to each.

Owns: cg_joined (CGID → goal, see core/community_goals.py).

    LoadGame              a new session: the list is cleared, since the game
                          writes CommunityGoal at start-up only when there is
                          something to list
    CommunityGoal         the whole list, replacing what was held; a goal
                          handed in, or left, is no longer in it
    CommunityGoalJoin     a goal added until the next CommunityGoal
    CommunityGoalReward   handed in: gone
    CommunityGoalDiscard  left: gone

Persisted, as the journal replayed at start-up may hold no session.
Goals open to join come from CAPI and Inara (core/data.py,
components/inara.py); the Missions tab merges them (core/windows/objectives.py).
"""
from __future__ import annotations

from core import community_goals as CG
from core.plugin_loader import BasePlugin


class CommunityGoalsPlugin(BasePlugin):
    PLUGIN_NAME        = "community_goals"
    PLUGIN_DISPLAY     = "Community Goals"
    PLUGIN_VERSION     = "1.0.0"
    PLUGIN_DESCRIPTION = ("Community goals signed up for, and the commander's "
                          "contribution to each.")

    SUBSCRIBED_EVENTS = [
        "LoadGame",
        "CommunityGoal",
        "CommunityGoalJoin",
        "CommunityGoalReward",
        "CommunityGoalDiscard",
    ]

    def on_load(self, core) -> None:
        super().on_load(core)
        self._restore()

    def _restore(self) -> None:
        data = self.storage.read_json() or {}
        goals = {}
        for g in data.get("joined", []) or []:
            if isinstance(g, dict) and g.get("id") is not None:
                goals[int(g["id"])] = g
        self.core.state.cg_joined = goals

    def _persist(self) -> None:
        self.storage.write_json({"joined": list(self.core.state.cg_joined.values())})

    def on_event(self, event: dict, state) -> None:
        ev = event.get("event")
        goals = getattr(state, "cg_joined", None)
        if goals is None:
            goals = state.cg_joined = {}
        before = dict(goals)

        if ev == "LoadGame":
            goals.clear()
        elif ev == "CommunityGoal":
            goals.clear()
            for raw in event.get("CurrentGoals") or []:
                g = CG.from_journal(raw)
                if g["id"] is not None:
                    goals[g["id"]] = g
        elif ev == "CommunityGoalJoin":
            g = CG.from_join(event)
            if g["id"] is not None and g["id"] not in goals:
                goals[g["id"]] = g
        elif ev in ("CommunityGoalReward", "CommunityGoalDiscard"):
            cgid = event.get("CGID")
            try:
                goals.pop(int(cgid), None)
            except (TypeError, ValueError):
                pass

        if goals != before:
            self._persist()
            gq = self.core.gui_queue
            if gq:
                gq.put(("mission_update", None))
