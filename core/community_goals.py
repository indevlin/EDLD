"""core/community_goals.py — community goals from the journal, CAPI and Inara,
in one shape.

    journal  CommunityGoal lists every goal the commander is signed up for,
             running or finished and not yet handed in, with their
             contribution; it is written at start-up and whenever one changes.
    CAPI     /communitygoals: every running goal, signed up for or not.
    Inara    getCommunityGoalsRecent: running and recently finished goals as
             Inara has them recorded.

A goal is a dict:

    id            CGID (int), or None where the source has none (Inara)
    title, system, station, objective
    expiry        ISO 8601, UTC, "Z"; "" when unknown
    complete      bool
    total, contributors, tier, top_tier
    joined        signed up for
    contribution, percentile, reward, top_rank   (joined only)
"""
from __future__ import annotations

from datetime import datetime, timezone


def _int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _tier(v):
    """"Tier 5" or 5 → 5; anything else → None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    digits = "".join(c for c in str(v or "") if c.isdigit())
    return int(digits) if digits else None


def when(text) -> datetime | None:
    """An expiry as an aware UTC datetime; a time with no zone is UTC."""
    s = str(text or "").strip()
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(text) -> str:
    dt = when(text)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if dt else ""


def key(goal: dict) -> tuple:
    """Title and system, case and spacing aside: how a goal from Inara, which
    carries no CGID, is matched to the same goal from elsewhere."""
    return (" ".join(str(goal.get("title", "")).split()).casefold(),
            " ".join(str(goal.get("system", "")).split()).casefold())


def from_journal(g: dict) -> dict:
    """One entry of a CommunityGoal event's CurrentGoals."""
    top = g.get("TopTier") or {}
    return {
        "id":           _int(g.get("CGID")),
        "title":        str(g.get("Title", "")).strip(),
        "system":       g.get("SystemName", "") or "",
        "station":      g.get("MarketName", "") or "",
        "objective":    "",
        "expiry":       _iso(g.get("Expiry")),
        "complete":     bool(g.get("IsComplete", False)),
        "total":        _int(g.get("CurrentTotal"), 0),
        "contributors": _int(g.get("NumContributors"), 0),
        "tier":         _tier(g.get("TierReached")),
        "top_tier":     _tier(top.get("Name") if isinstance(top, dict) else top),
        "joined":       True,
        "contribution": _int(g.get("PlayerContribution"), 0),
        "percentile":   _int(g.get("PlayerPercentileBand")),
        "reward":       _int(g.get("Bonus"), 0),
        "top_rank":     bool(g.get("PlayerInTopRank", False)),
    }


def from_join(event: dict) -> dict:
    """A CommunityGoalJoin, until the next CommunityGoal fills it in."""
    return {
        "id": _int(event.get("CGID")), "title": str(event.get("Name", "")).strip(),
        "system": event.get("System", "") or "", "station": "", "objective": "",
        "expiry": "", "complete": False, "total": 0, "contributors": 0,
        "tier": None, "top_tier": None, "joined": True, "contribution": 0,
        "percentile": None, "reward": 0, "top_rank": False,
    }


def from_capi(data) -> list[dict]:
    """The /communitygoals payload: {"activeCommunityGoals": [...]}, each goal
    with its numbers under "commander_progress"."""
    if isinstance(data, dict):
        goals = data.get("activeCommunityGoals")
        if goals is None:
            goals = data.get("communityGoals")
    else:
        goals = data
    if isinstance(goals, dict):
        goals = list(goals.values())
    out = []
    for g in goals if isinstance(goals, list) else []:
        if not isinstance(g, dict):
            continue
        prog = g.get("commander_progress") or {}
        if not isinstance(prog, dict):
            prog = {}
        title = str(g.get("title", "")).strip()
        if not title:
            continue
        joined = bool(prog.get("commanderSubscribed", False))
        out.append({
            "id":           _int(g.get("id")),
            "title":        title,
            "system":       g.get("starsystem_name", "") or "",
            "station":      g.get("market_name", "") or "",
            "objective":    str(g.get("objective", "") or "").strip(),
            "expiry":       _iso(g.get("expiry")),
            "complete":     bool(prog.get("complete", False)),
            "total":        _int(prog.get("currentQty"), 0),
            "contributors": _int(prog.get("numContributors"), 0),
            "tier":         None,
            "top_tier":     None,
            "joined":       joined,
            "contribution": _int(prog.get("commanderContributionQty"), 0) if joined else 0,
            "percentile":   _int(prog.get("commanderPercentile")) if joined else None,
            "reward":       0,
            "top_rank":     False,
        })
    return out


def from_inara(goals) -> list[dict]:
    """getCommunityGoalsRecent's eventData. Inara does not say who signed up."""
    out = []
    for g in goals if isinstance(goals, list) else []:
        if not isinstance(g, dict):
            continue
        title = str(g.get("communitygoalName", "")).strip()
        if not title:
            continue
        out.append({
            "id":           _int(g.get("communitygoalGameID")),
            "title":        title,
            "system":       g.get("starsystemName", "") or "",
            "station":      g.get("stationName", "") or "",
            "objective":    str(g.get("goalObjectiveText", "") or "").strip(),
            "expiry":       _iso(g.get("goalExpiry")),
            "complete":     bool(g.get("isCompleted", False)),
            "total":        _int(g.get("contributionsTotal"), 0),
            "contributors": _int(g.get("contributorsNum"), 0),
            "tier":         _int(g.get("tierReached")),
            "top_tier":     _int(g.get("tierMax")),
            "joined":       False,
            "contribution": 0,
            "percentile":   None,
            "reward":       0,
            "top_rank":     False,
        })
    return out


def finished(goal: dict, now: datetime | None = None) -> bool:
    end = when(goal.get("expiry"))
    return bool(goal.get("complete")) or (end is not None and end <= (now or datetime.now(timezone.utc)))


def merged(joined: dict, capi: list | None, inara: list | None,
           now: datetime | None = None) -> list[dict]:
    """Every goal to show: those signed up for (from the journal; running or
    waiting to be handed in), then those still running that are open to join
    (from CAPI, else Inara). Facts the journal lacks — the objective, a tier
    count — come from the others."""
    now = now or datetime.now(timezone.utc)
    others = list(capi or []) + list(inara or [])
    by_id = {g["id"]: g for g in others if g.get("id") is not None}
    by_key: dict[tuple, dict] = {}
    for g in others:
        by_key.setdefault(key(g), g)

    mine = []
    seen_ids, seen_keys = set(), set()
    for g in (joined or {}).values():
        g = dict(g)
        extra = by_id.get(g.get("id")) or by_key.get(key(g))
        if extra:
            for k in ("objective", "station", "expiry", "system"):
                if not g.get(k) and extra.get(k):
                    g[k] = extra[k]
            for k in ("tier", "top_tier"):
                if g.get(k) is None and extra.get(k) is not None:
                    g[k] = extra[k]
        mine.append(g)
        seen_ids.add(g.get("id"))
        seen_keys.add(key(g))
    # CAPI knows a sign-up the journal has not yet listed.
    for g in capi or []:
        if g.get("joined") and g.get("id") not in seen_ids and key(g) not in seen_keys:
            mine.append(dict(g))
            seen_ids.add(g.get("id"))
            seen_keys.add(key(g))

    open_ = []
    for g in others:
        if g.get("id") in seen_ids and g.get("id") is not None:
            continue
        if key(g) in seen_keys or finished(g, now):
            continue
        open_.append(dict(g))
        seen_keys.add(key(g))
        if g.get("id") is not None:
            seen_ids.add(g["id"])

    far = datetime.max.replace(tzinfo=timezone.utc)

    def by_end(g):
        return (when(g.get("expiry")) or far, g.get("title", ""))
    running = sorted((g for g in mine if not finished(g, now)), key=by_end)
    to_claim = sorted((g for g in mine if finished(g, now)), key=by_end)
    return running + to_claim + sorted(open_, key=by_end)
