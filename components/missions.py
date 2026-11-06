"""
components/missions.py — Massacre mission stack tracking.

Owns: active_missions, missions_complete, stack_value,
      mission_value_map, mission_target_faction_map, mission_detail_map.

Persistence
───────────
mission_detail_map is persisted to plugin storage on every change and
restored on load. This is the only source of kill_count, faction, target,
and reward data after a restart, since the Missions bulk event carries only
MissionID, Name, PassengerMission, and Expires.

On the Missions bulk event:
  - The reconciliation ALWAYS runs (no short-circuit guard) so that an empty
    Active list correctly clears any stale stored missions.
  - Any active mission already in mission_detail_map keeps its stored detail.
  - Any active mission NOT in detail_map gets an empty skeleton entry, then
    backfill scans backwards through journals to populate it.
  - Any stored detail for a MissionID no longer in Active is discarded.

Kills against the stack
───────────────────────
state.massacre_ledger (core/massacre.py) holds the kills credited to each
massacre mission. It is not persisted: it is rebuilt from the journals at the
Missions snapshot on every login (and on every start, since preload replays
the current journal through it), then fed live from MissionAccepted, Bounty,
MissionRedirected and the end of each mission. So it is right however long
EDLD was not running, and a start never counts a kill twice. Why the count is
anchored on redirects rather than a tally of Bounty events is explained in
core/massacre.py.
"""

from core.plugin_loader import BasePlugin
from core.emit import fmt_credits
from core import massacre as _massacre


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


def _mission_category(raw: str) -> str:
    low = (raw or "").lower()
    for stem, label in _MISSION_CATEGORIES:
        if stem in low:
            return label
    return "Other"


def _pretty_mission_name(raw: str) -> str:
    """Best-effort readable name when the journal gives no localised one."""
    text = (raw or "").strip()
    for prefix in ("Mission_", "MISSION_"):
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.split("_name")[0].replace("_", " ").strip() or "Mission"


class MissionsPlugin(BasePlugin):
    PLUGIN_NAME    = "missions"
    PLUGIN_DISPLAY = "Massacre Mission Stack"
    PLUGIN_DESCRIPTION = "Active massacre mission stack — progress, value, and completion tracking."
    PLUGIN_VERSION = "1.3.0"

    SUBSCRIBED_EVENTS = [
        "Missions",
        "MissionAccepted",
        "MissionRedirected",
        "MissionAbandoned",
        "MissionCompleted",
        "MissionFailed",
        "Bounty",
        # Where the pilot is: a kill counts only in the mission's system.
        "FSDJump",
        "Location",
        "CarrierJump",
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

    # ── Kill counting ─────────────────────────────────────────────────────────

    def _ledger(self) -> "_massacre.MassacreLedger":
        state = self.core.state
        if getattr(state, "massacre_ledger", None) is None:
            state.massacre_ledger = _massacre.MassacreLedger()
            for mid, info in state.mission_detail_map.items():
                state.massacre_ledger.accept(
                    mid, info.get("faction", ""), info.get("kill_count", 0),
                    info.get("target_faction", ""), info.get("target_system", ""),
                    info.get("accepted_at", ""))
            for mid in self._redirected:
                state.massacre_ledger.mark_done(mid)
        return state.massacre_ledger

    def _rebuild_ledger(self, until: str) -> None:
        """The ledger for the active stack, from the journals up to the
        login snapshot at ``until``; what follows is fed to it as it comes.

        A failure is logged, not swallowed: the stack then counts only from
        here, and the log says why.
        """
        state = self.core.state
        active = list(state.mission_detail_map)
        ledger, system, rebuilt = _massacre.MassacreLedger(), None, False
        jdir = getattr(self.core, "journal_dir", None)
        if active and jdir:
            try:
                ledger, system = _massacre.rebuild(
                    _massacre.journal_events_since_oldest(jdir, active), active, until)
                rebuilt = True
            except Exception as exc:
                from core import debug as _dbg
                _dbg.exception("[Missions] massacre kill history not rebuilt; "
                               "counting from now", exc)
                ledger = _massacre.MassacreLedger()
        # Every active mission is on it, whether or not its acceptance is
        # still in the journals.
        for mid, info in state.mission_detail_map.items():
            ledger.accept(mid, info.get("faction", ""), info.get("kill_count", 0),
                          info.get("target_faction", ""), info.get("target_system", ""),
                          info.get("accepted_at", ""))
        if rebuilt:
            # The journals say which missions were complete at the snapshot,
            # including any redirected while EDLD was not running. Redirects
            # remembered from after it are left for the replay to bring:
            # marked done now, the kills replayed before them would go to
            # the next mission instead.
            done = {mid for mid, m in ledger.missions.items() if m.done}
            if not done <= self._redirected:
                self._redirected |= done
                state.missions_complete = len(self._redirected)
                self._persist()
        else:
            for mid in self._redirected:
                ledger.mark_done(mid)
        state.massacre_ledger = ledger
        if system and not getattr(self, "_system", None):
            self._system = system

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
        """Record any accepted mission on the general board.

        Deliberately shallow: mission events vary a lot by type, so this
        keeps the fields they share and picks up whatever target, count or
        commodity detail happens to be present.  Anything absent is omitted
        rather than rendered as a blank row.
        """
        mid = event.get("MissionID")
        if mid is None:
            return

        raw_name = str(event.get("Name", ""))
        entry = {
            "name": (event.get("LocalisedName")
                     or event.get("Name_Localised")
                     or _pretty_mission_name(raw_name)),
            "category":    _mission_category(raw_name),
            "faction":     event.get("Faction", ""),
            "reward":      int(event.get("Reward", 0) or 0),
            "destination": (event.get("DestinationSystem")
                            or event.get("DestinationStation") or ""),
            "expiry":      event.get("Expiry", ""),
            "wing":        bool(event.get("Wing", False)),
            "status":      "Active",
        }
        for src, key in (("KillCount", "count"), ("Count", "count"),
                         ("TargetFaction", "target_faction"),
                         ("Target_Localised", "target"), ("Target", "target"),
                         ("Commodity_Localised", "commodity"),
                         ("PassengerCount", "passengers")):
            value = event.get(src)
            if value not in (None, "", 0) and key not in entry:
                entry[key] = value
        state.all_missions[int(mid)] = entry

    def on_event(self, event: dict, state) -> None:
        core     = self.core
        gq       = core.gui_queue
        notify   = core.notify_levels
        ev       = event.get("event")

        match ev:

            case "Missions" if "Active" in event:
                # Bulk reconciliation on login.  This branch ALWAYS runs —
                # no short-circuit guard — so that an empty Active list (zero
                # active missions) correctly clears any stale stored detail
                # that survived from a previous session whose MissionCompleted
                # events were processed during the prior preload.
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

                # Backfill skeleton entries that have kill_count == 0.
                # The Missions bulk event carries only MissionID/Name/Expires —
                # no kill counts, factions, or rewards.  Missions accepted in a
                # prior journal session are not replayed during preload, so their
                # MissionAccepted detail must be recovered by scanning backwards.
                needs_backfill = {
                    mid for mid, info in state.mission_detail_map.items()
                    if not info.get("kill_count")
                }
                if needs_backfill:
                    try:
                        from core.journal_index import index_for
                        _jdir = getattr(core, "journal_dir", None)
                        if _jdir:
                            for _f, _ev in index_for(_jdir).events(("MissionAccepted",),
                                                                   newest_first=True):
                                if not needs_backfill:
                                    break
                                if _ev.get("event") == "MissionAccepted":
                                    _mid = int(_ev.get("MissionID", 0))
                                    if _mid in needs_backfill:
                                        state.mission_detail_map[_mid] = {
                                            "faction":        _ev.get("Faction", ""),
                                            "kill_count":     _ev.get("KillCount", 0),
                                            "target_faction": _ev.get("TargetFaction", ""),
                                            "target_system":  _ev.get("DestinationSystem", ""),
                                            "target_type":    (_ev.get("TargetType_Localised")
                                                               or _ev.get("TargetType", "")),
                                            "wing":           _ev.get("Wing", False),
                                            "reward":         _ev.get("Reward", 0),
                                            "accepted_at":    _ev.get("timestamp", ""),
                                        }
                                        needs_backfill.discard(_mid)
                    except Exception as exc:
                        # Was ``except: pass`` — a stack shown with no kill
                        # counts and no word of why.
                        from core import debug as _dbg
                        _dbg.exception("[Missions] massacre mission backfill failed", exc)

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
                self._rebuild_ledger(str(event.get("timestamp", "")))

                core.emitter.emit(
                    msg_term=(
                        f"Missions loaded (active massacres: {len(state.active_missions)}"
                        + (f", {len(self._redirected)} redirected)" if self._redirected else ")")
                    ),
                    emoji="📋", sigil="*  MISS",
                    timestamp=event.get("_logtime"), loglevel=notify["MissionUpdate"],
                )
                if gq: gq.put(("mission_update", None))

            case "FSDJump" | "Location" | "CarrierJump":
                self._system = event.get("StarSystem") or getattr(self, "_system", None)
                if state.mission_detail_map:
                    _massacre.apply(self._ledger(), event, None)

            case "MissionAccepted":
                # Every mission type, not just massacres.  The general board
                # backs the Session window's Missions tab; the massacre
                # bookkeeping below still runs for those.
                self._track_mission(state, event)
                if gq: gq.put(("mission_update", None))
                if _massacre.is_massacre(event.get("Name")):
                    self._on_massacre_accepted(event, state, core, gq, notify)
                    _massacre.apply(self._ledger(), event, None)

            case "MissionRedirected":
                # One arm for every mission.  There used to be two, the
                # general one first: a match takes the first arm that fits,
                # so the massacre arm after it never ran — a redirect never
                # marked a massacre complete or said so, live.
                mid = event.get("MissionID")
                entry = (state.all_missions.get(int(mid))
                         if mid is not None else None)
                if entry is not None:
                    entry["status"] = "Complete — turn in"
                    entry["destination"] = (event.get("NewDestinationSystem")
                                            or entry.get("destination", ""))
                    if gq: gq.put(("mission_update", None))
                if mid is not None and _massacre.is_massacre(event.get("Name")):
                    self._on_massacre_redirected(event, state, core, gq, notify)

            case "Bounty" if state.active_missions:
                # A kill of the stack's target faction, in its system, counts
                # against it (core/massacre.py says how, and why a Bounty is
                # only part of the count).
                if self._ledger().kill(event.get("VictimFaction", ""),
                                       getattr(self, "_system", None)):
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
        _massacre.apply(self._ledger(), event, None)
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
        # Processed during preload too, so that _redirected is drained of
        # turned-in missions; only the notification waits for live events.
        mid = int(event.get("MissionID", 0))
        if mid not in state.active_missions:
            return
        reward = state.mission_value_map.pop(mid, 0)
        if reward:
            state.stack_value -= reward
        state.mission_target_faction_map.pop(mid, None)
        state.mission_detail_map.pop(mid, None)
        self._redirected.discard(mid)
        self._ledger().remove(mid)
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
