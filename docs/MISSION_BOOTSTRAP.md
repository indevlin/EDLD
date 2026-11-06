# EDLD Mission Bootstrap

EDLD tracks two mission views. The general board records every mission you
have, of any type: what it asks for, where, by when, and whether it is ready
to turn in. The massacre stack sums the massacres by source faction. Both
need a bootstrap, because the game's `Missions` event at login lists each
active mission's ID, name and time left, and nothing else.

At every `Missions` snapshot the board is rebuilt from the journal index:
each active mission's `MissionAccepted`, wherever in the journals it is, then
every `MissionRedirected` and `CargoDepot` for those missions since, up to the
snapshot. What follows the snapshot is replayed or arrives live. So a
delivery shows the tons delivered so far and a redirected mission shows as
ready, however long EDLD was closed. A mission whose acceptance is no longer
in the journals still appears, from what the snapshot says: its name, its
type, and its deadline. Before this, the board was filled only from
`MissionAccepted` as it happened, and emptied at every `LoadGame`, so after
a relog or a restart it held nothing accepted in an earlier session, which
is why the Missions tab only ever showed massacres.

When EDLD starts, it needs to know which massacre missions you have active and what they're worth. The game's `Missions` journal event at login contains the active mission list but frequently omits reward values — and if EDLD is launched mid-session, that event may not appear in the current journal at all.

EDLD resolves this by reading every `MissionAccepted`, `MissionCompleted`, `MissionAbandoned`, `MissionFailed` and `MissionRedirected` event in **all available journal files**, in chronological order, before the current journal is replayed — from the journal index ([Start-up](STARTUP.md)), so nothing else in the journals is read — replaying `MissionAccepted`, `MissionCompleted`, `MissionAbandoned`, `MissionFailed`, and `MissionRedirected` events to reconstruct exactly which missions are active, what they're worth, and how many have had their kill quota met. Missions whose `Expiry` timestamp has passed are filtered out automatically.

This means your stack value and completion count are accurate from the moment monitoring goes live, regardless of when or how EDLD was started — mid-session, after a relog, or with missions accepted in a previous game session.

---

## Why the stack does not count kills

The massacre table reports missions done of missions held (`01 / 05`), not
kills made. Counting kills was tried twice, and both times the figure fell
behind the game's own mission screen.

The game credits a kill to the oldest unfinished mission of each source
faction, and writes a `Bounty` for only some of the kills it credits. Over
every massacre stack in the journals the second attempt was checked against
(178 redirects), the bounties covered about seven kills in ten; at the moment
a mission redirected there was often no `Bounty` at all. The kills without
one leave no other trace either: across all those journals, a ship of a
target faction seen at zero hull without a bounty happened once. On the Wolf
359 stack of 6 November the game showed 12 of 45 while the journal held 10
bounties, one of them that single zero-hull sighting and the other nothing at
all.

`MissionRedirected` is exact: it is written the moment a mission reaches its
count. So that is what the stack reports. Anchoring a kill count on redirects
was tried too: it never read high, but with one 45-kill mission there is no
redirect until the end, so it could still only lag.
