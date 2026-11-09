"""components/missions.py — Massacre mission stack tracking.

Owns: active_missions, missions_complete, stack_value,
      mission_value_map, mission_target_faction_map, mission_detail_map.

Persistence ─────────── mission_detail_map is persisted to plugin storage on
every change and restored on load.

On the Missions bulk event:
  - The reconciliation ALWAYS runs (no short-circuit guard) so that an empty
    Active list correctly clears any stale stored missions.
  - Any active mission already in mission_detail_map keeps its stored detail.
  - Any active mission NOT in detail_map gets an empty skeleton entry, then
    backfill scans backwards through journals to populate it.
  - Any stored detail for a MissionID no longer in Active is discarded.

Massacre kills are not counted.
"""

from datetime import datetime, timedelta

from core.plugin_loader import BasePlugin
from core.emit import fmt_credits


#: Journal mission names look like "Mission_Massacre_Wing_name".  These map
#: recognisable stems to a category so the Missions tab can group them;
#: anything unmatched falls back to "Other" rather than guessing.
_MISSION_CATEGORIES = (
    ("massacre", "Massacre"), ("assassinat", "Assassination"),
    ("delivery", "Delivery"), ("collect", "Collection"),
    ("mining", "Mining"), ("salvage", "Salvage"), ("courier", "Courier"),
    ("passenger", "Passenger"), ("sightsee", "Passenger"),
    ("rescue", "Rescue"), ("altruism", "Donation"), ("donation", "Donation"),
    ("scan", "Scan"), ("onfoot", "On foot"), ("smuggle", "Smuggling"),
)


def _is_massacre(name) -> bool:
    return "Mission_Massacre" in str(name or "")


def _mission_category(raw: str) -> str:
    low = (raw or "").lower()
    for stem, label in _MISSION_CATEGORIES:
        if stem in low:
            return label
    return "Other"


def _pretty_mission_name(raw: str) -> str:
    """Best-effort readable name when the journal gives no localized one."""
    text = (raw or "").strip()
    for prefix in ("Mission_", "MISSION_"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.split("_name")[0].replace("_", " ").strip() or "Mission"


class MissionsPlugin(BasePlugin):
    PLUGIN_NAME    = "missions"
    PLUGIN_DISPLAY = "Missions"
    PLUGIN_DESCRIPTION = ("Active missions of every type, and the massacre stack — "
                          "progress, value, and completion tracking.")
    PLUGIN_VERSION = "1.4.0"

    SUBSCRIBED_EVENTS = [
        "Missions",
        "MissionAccepted",
        "MissionRedirected",
        "MissionAbandoned",
        "MissionCompleted",
        "MissionFailed",
        # Delivery progress: tons delivered of tons asked for.
        "CargoDepot",
    ]

    DEFAULT_COL    = 0
    DEFAULT_ROW    = 6
    DEFAULT_WIDTH  = 8
    DEFAULT_HEIGHT = 4

    def on_load(self, core) -> None:
        super().on_load(core)
        self._restore()
        core.register_block(self, priority=30)

    # ── Persistence ───────────────────────────────────────────────────────────

    def _restore(self) -> None:
        """Restore mission state from storage on load."""
        data  = self.storage.read_json() or {}
        state = self.core.state

        detail = data.get("mission_detail_map", {})
        # Keys are stored as strings (JSON); convert back to int
        state.mission_detail_map = {int(k): v for k, v in detail.items()}

        active = data.get("active_missions", [])
        state.active_missions = [int(m) for m in active]

        redirected = data.get("redirected_missions", [])
        self._redirected: set[int] = {int(m) for m in redirected}

        # Safety net: prune any redirected IDs that are not in the persisted
        # active_missions list.
        self._redirected &= set(state.active_missions)
        state.massacre_redirected = self._redirected
        state.missions_complete = len(self._redirected)
        state.stack_value       = sum(
            v.get("reward", 0)
            for v in state.mission_detail_map.values()
        )
        state.mission_value_map = {
            mid: v.get("reward", 0)
            for mid, v in state.mission_detail_map.items()
        }
        state.mission_target_faction_map = {
            mid: v.get("target_faction", "")
            for mid, v in state.mission_detail_map.items()
        }

    def _persist(self) -> None:
        """Write mission state to storage."""
        state = self.core.state
        self.storage.write_json({
            "active_missions":    state.active_missions,
            "mission_detail_map": {
                str(k): v for k, v in state.mission_detail_map.items()
            },
            "redirected_missions": list(self._redirected),
        })

    # ── The mission board ─────────────────────────────────────────────────────

    def _rebuild_board(self, event) -> dict:
        """The board for the snapshot's Active missions, from the journals up to
        the snapshot; what follows is replayed or comes live. Returns each
        found MissionAccepted by mission ID, for the massacre detail.
        """
        state = self.core.state
        active = {int(m["MissionID"]): m for m in event.get("Active", [])
                  if m.get("MissionID") is not None}
        until = str(event.get("timestamp", ""))
        accepted: dict[int, dict] = {}
        history: list[dict] = []
        jdir = getattr(self.core, "journal_dir", None)
        if active and jdir:
            try:
                from core.journal_index import index_for, journal_sort_key
                idx = index_for(jdir)
                want, oldest = set(active), None
                for fname, ev in idx.events(("MissionAccepted",), newest_first=True):
                    mid = ev.get("MissionID")
                    if mid is not None and int(mid) in want:
                        accepted[int(mid)] = ev
                        want.discard(int(mid))
                        oldest = fname
                        if not want:
                            break
                if oldest is not None:
                    files = [f for f in sorted(idx.files(), key=journal_sort_key)
                             if journal_sort_key(f) >= journal_sort_key(oldest)]
                    for _f, ev in idx.events(("MissionRedirected", "CargoDepot"), files=files):
                        if until and str(ev.get("timestamp", "")) >= until:
                            break
                        if ev.get("MissionID") is not None and int(ev["MissionID"]) in active:
                            history.append(ev)
            except Exception as exc:
                from core import debug as _dbg
                _dbg.exception("[Missions] mission history not read from the journals", exc)

        state.all_missions = {}
        for mid, snap in active.items():
            ev = accepted.get(mid) or {"MissionID": mid, "Name": snap.get("Name", "")}
            self._track_mission(state, ev)
            entry = state.all_missions[mid]
            if snap.get("PassengerMission") and entry["category"] == "Other":
                entry["category"] = "Passenger"
            if not entry.get("expiry") and snap.get("Expires") and until:
                try:
                    at = datetime.fromisoformat(until.replace("Z", "+00:00"))
                    entry["expiry"] = (at + timedelta(seconds=int(snap["Expires"]))
                                       ).strftime("%Y-%m-%dT%H:%M:%SZ")
                except ValueError:
                    pass
        for ev in history:
            self._progress(state, ev)
        return accepted

    @staticmethod
    def _progress(state, event) -> bool:
        """A redirect or a cargo depot update onto the board. True if it
        changed a mission there."""
        mid = event.get("MissionID")
        entry = state.all_missions.get(int(mid)) if mid is not None else None
        if entry is None:
            return False
        if event.get("event") == "MissionRedirected":
            entry["status"] = "Ready"
            entry["dest_system"] = event.get("NewDestinationSystem") or entry.get("dest_system", "")
            entry["dest_station"] = event.get("NewDestinationStation") or entry.get("dest_station", "")
        elif event.get("event") == "CargoDepot":
            total = int(event.get("TotalItemsToDeliver", 0) or 0)
            if total:
                entry["total"] = total
                entry["delivered"] = int(event.get("ItemsDelivered", 0) or 0)
                entry["collected"] = int(event.get("ItemsCollected", 0) or 0)
        return True

    # ── Events ────────────────────────────────────────────────────────────────

    def _on_massacre_accepted(self, event, state, core, gq, notify) -> None:
        """Massacre-specific bookkeeping for an accepted mission."""
        mid = int(event["MissionID"])
        # During preload, only skip if this mission is already fully tracked
        # (either restored from storage or enriched by backfill).  Missions
        # accepted after the Missions bulk snapshot, or skeletons that backfill
        # didn't reach, still need to be processed.
        if state.in_preload and mid in state.mission_detail_map:
            return
        already_active = mid in state.active_missions
        if not already_active:
            state.active_missions.append(mid)
        reward = event.get("Reward", 0)
        if reward and mid not in state.mission_value_map:
            state.stack_value += reward
            state.mission_value_map[mid] = reward
        target_f = event.get("TargetFaction", "")
        if target_f:
            state.mission_target_faction_map[mid] = target_f
        state.mission_detail_map[mid] = {
            "faction":        event.get("Faction", ""),
            "kill_count":     event.get("KillCount", 0),
            "target_faction": target_f,
            "target_system":  event.get("DestinationSystem", ""),
            "target_type":    (event.get("TargetType_Localised")
                               or event.get("TargetType", "")),
            "wing":           event.get("Wing", False),
            "reward":         reward,
            "accepted_at":    event.get("timestamp", ""),
        }
        self._persist()
        if not state.in_preload:
            total_now = len(state.active_missions)
            core.emitter.emit(
                msg_term=f"Accepted massacre mission (active: {total_now})",
                emoji="📋", sigil="*  MISS",
                timestamp=event.get("_logtime"), loglevel=notify["MissionUpdate"],
            )
            full_stack = core.app_settings.get("FullStackSize", 20)
            if total_now == full_stack and state.stack_value > 0:
                _sl = f"Stack full ({total_now} missions) — {fmt_credits(state.stack_value)}"
                core.emitter.emit(
                    msg_term=_sl, msg_discord=f"**{_sl}**",
                    emoji="🏆", sigil="*  MISS",
                    timestamp=event.get("_logtime"), loglevel=notify["MissionUpdate"],
                )
        if gq: gq.put(("mission_update", None))


    def _track_mission(self, state, event) -> None:
        """Record any accepted mission on the general board."""
        mid = event.get("MissionID")
        if mid is None:
            return

        raw_name = str(event.get("Name", ""))
        entry = {
            "name": (event.get("LocalisedName")
                     or event.get("Name_Localised")
                     or _pretty_mission_name(raw_name)),
            "category":     _mission_category(raw_name),
            "faction":      event.get("Faction", ""),
            "reward":       int(event.get("Reward", 0) or 0),
            "dest_system":  event.get("DestinationSystem", "") or "",
            "dest_station": event.get("DestinationStation", "") or "",
            "expiry":       event.get("Expiry", ""),
            "wing":         bool(event.get("Wing", False)),
            "status":       "Active",
        }
        for src, key in (("KillCount", "count"), ("Count", "count"),
                         ("TargetFaction", "target_faction"),
                         ("Target_Localised", "target"), ("Target", "target"),
                         ("Commodity_Localised", "commodity"), ("Commodity", "commodity"),
                         ("PassengerCount", "passengers"),
                         ("Donated", "donation"), ("Donation", "donation")):
            value = event.get(src)
            if value not in (None, "", 0) and key not in entry:
                entry[key] = value
        raw = str(event.get("Commodity", "") or "")
        if raw:
            entry["commodity_key"] = raw.strip("$;").removesuffix("_Name").removesuffix("_name").lower()
        if "donation" in entry:
            try:
                entry["donation"] = int(entry["donation"])
            except (TypeError, ValueError):
                entry.pop("donation")
        state.all_missions[int(mid)] = entry

    def on_event(self, event: dict, state) -> None:
        core     = self.core
        gq       = core.gui_queue
        notify   = core.notify_levels
        ev       = event.get("event")

        match ev:

            case "Missions" if "Active" in event:
                # Bulk reconciliation on login.
                live_ids = {
                    int(m["MissionID"])
                    for m in event["Active"]
                    if "Mission_Massacre" in m.get("Name", "")
                    and (m.get("Expires", 0) == 0 or m.get("Expires", 0) > 0)
                }

                # Discard stored detail for missions no longer active
                for mid in list(state.mission_detail_map.keys()):
                    if mid not in live_ids:
                        state.mission_detail_map.pop(mid, None)
                        state.mission_value_map.pop(mid, None)
                        state.mission_target_faction_map.pop(mid, None)
                self._redirected &= live_ids

                # Ensure every live mission has a detail entry (skeleton if new)
                for m in event["Active"]:
                    if "Mission_Massacre" not in m.get("Name", ""):
                        continue
                    mid = int(m["MissionID"])
                    if mid not in state.mission_detail_map:
                        state.mission_detail_map[mid] = {
                            "faction":        m.get("Faction", ""),
                            "kill_count":     m.get("KillCount", 0),
                            "target_faction": m.get("TargetFaction", ""),
                            "target_system":  m.get("DestinationSystem", ""),
                            "target_type":    (m.get("TargetType_Localised")
                                               or m.get("TargetType", "")),
                            "wing":           m.get("Wing", False),
                            "reward":         m.get("Reward", 0),
                        }

                # The whole board, every type, from the journals: the
                # snapshot carries no kill counts, factions or rewards, and a
                # mission accepted in an earlier session is not replayed.
                accepted = self._rebuild_board(event)
                for mid, info in list(state.mission_detail_map.items()):
                    ev = accepted.get(mid)
                    if ev is not None and not info.get("kill_count"):
                        state.mission_detail_map[mid] = {
                            "faction":        ev.get("Faction", ""),
                            "kill_count":     ev.get("KillCount", 0),
                            "target_faction": ev.get("TargetFaction", ""),
                            "target_system":  ev.get("DestinationSystem", ""),
                            "target_type":    (ev.get("TargetType_Localised")
                                               or ev.get("TargetType", "")),
                            "wing":           ev.get("Wing", False),
                            "reward":         ev.get("Reward", 0),
                            "accepted_at":    ev.get("timestamp", ""),
                        }
                # A redirect made while EDLD was closed still counts.
                self._redirected |= {mid for mid in live_ids
                                     if state.all_missions.get(mid, {}).get("status") == "Ready"}
                state.massacre_redirected = self._redirected

                state.active_missions   = list(live_ids)
                state.missions_complete = len(self._redirected)
                state.stack_value       = sum(
                    v.get("reward", 0) for v in state.mission_detail_map.values()
                )
                state.mission_value_map = {
                    mid: v.get("reward", 0)
                    for mid, v in state.mission_detail_map.items()
                }
                state.mission_target_faction_map = {
                    mid: v.get("target_faction", "")
                    for mid, v in state.mission_detail_map.items()
                }
                state.missions = True
                self._persist()

                core.emitter.emit(
                    msg_term=(
                        f"Missions loaded (active massacres: {len(state.active_missions)}"
                        + (f", {len(self._redirected)} redirected)" if self._redirected else ")")
                    ),
                    emoji="📋", sigil="*  MISS",
                    timestamp=event.get("_logtime"), loglevel=notify["MissionUpdate"],
                )
                if gq: gq.put(("mission_update", None))

            case "MissionAccepted":
                # Every mission type, not just massacres.  The general board
                # backs the Session window's Missions tab; the massacre
                # bookkeeping below still runs for those.
                self._track_mission(state, event)
                if gq: gq.put(("mission_update", None))
                if _is_massacre(event.get("Name")):
                    self._on_massacre_accepted(event, state, core, gq, notify)

            case "MissionRedirected":
                # One arm for every mission.
                mid = event.get("MissionID")
                if self._progress(state, event):
                    if gq: gq.put(("mission_update", None))
                if mid is not None and _is_massacre(event.get("Name")):
                    self._on_massacre_redirected(event, state, core, gq, notify)

            case "CargoDepot":
                if self._progress(state, event):
                    if gq: gq.put(("mission_update", None))

            case "MissionCompleted" | "MissionFailed" | "MissionAbandoned":
                # Off the board however it ended.  Likewise one arm: the
                # massacre arm that came after this one never ran, so a
                # turned-in massacre stayed on the stack, its reward still
                # counted, until the next login's Missions snapshot.
                mid = event.get("MissionID")
                if mid is not None and int(mid) in state.all_missions:
                    state.all_missions.pop(int(mid), None)
                    if gq: gq.put(("mission_update", None))
                if mid is not None and state.missions:
                    self._on_massacre_ended(ev, event, state, core, gq, notify)

    def _on_massacre_redirected(self, event, state, core, gq, notify) -> None:
        mid = int(event["MissionID"])
        if mid not in state.mission_detail_map:
            return
        if mid in self._redirected:
            return                      # replayed: already counted and said
        self._redirected.add(mid)
        state.missions_complete = len(self._redirected)
        self._persist()
        if not state.in_preload:
            total = len(state.active_missions)
            done  = state.missions_complete
            if done < total:
                log      = notify["MissionUpdate"]
                msg_term = (f"Mission {done} of {total} complete "
                            f"({total - done} remaining)")
            else:
                log      = notify["AllMissionsReady"]
                msg_term = f"All {total} missions complete — ready to turn in!"
            core.emitter.emit(
                msg_term=msg_term, emoji="✅", sigil="*  MISS",
                timestamp=event.get("_logtime"), loglevel=log,
            )
        if gq: gq.put(("mission_update", None))

    def _on_massacre_ended(self, ev, event, state, core, gq, notify) -> None:
        mid = int(event.get("MissionID", 0))
        if mid not in state.active_missions:
            return
        reward = state.mission_value_map.pop(mid, 0)
        if reward:
            state.stack_value -= reward
        state.mission_target_faction_map.pop(mid, None)
        state.mission_detail_map.pop(mid, None)
        self._redirected.discard(mid)
        state.active_missions = [m for m in state.active_missions if m != mid]
        state.missions_complete = len(self._redirected)
        self._persist()
        if not state.in_preload:
            event_label = ev[7:].lower()
            core.emitter.emit(
                msg_term=(f"Massacre mission {event_label} "
                          f"(active: {len(state.active_missions)})"),
                emoji="📋", sigil="*  MISS",
                timestamp=event.get("_logtime"), loglevel=notify["MissionUpdate"],
            )
        if gq: gq.put(("mission_update", None))

    def get_summary_line(self) -> str | None:
        state = self.core.state
        if state.stack_value <= 0:
            return None
        done      = state.missions_complete
        total     = len(state.active_missions)
        remaining = total - done
        status = (
            "all complete — turn in!"
            if remaining == 0
            else f"{done}/{total} complete, {remaining} remaining"
        )
        return f"- Missions: {fmt_credits(state.stack_value)} stack ({status})"
