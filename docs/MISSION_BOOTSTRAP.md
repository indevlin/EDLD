# EDLD Mission Bootstrap

EDLD tracks two mission views. The general board records every mission you
have, of any type: what it asks for, where, by when, and whether it is ready
to turn in. The massacre stack groups the massacres by target faction, then
by the source factions that gave them, with the kills each has made. Both
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

## How the stack counts kills

The massacre table has a row for each target faction, the faction whose ships
are to be killed, and under it a row for each source faction that gave
missions against it. A source faction's KILLS are the kills credited to its
missions of the kills they need (`12 / 45`); the target faction's are the
stack's, measured against its tallest source faction, since every kill of the
target counts once for each source faction. MISSIONS is missions done of
missions held. A row turns green when all its missions are ready to turn in.
Two target factions are two stacks, with a Totals row under them.

The game credits a kill of a target faction ship, made in the mission's
target system, to the oldest unfinished mission of each source faction, in
the order they were accepted. Replayed over 249 redirects in two commanders'
journals, crediting in any other order (mission ID aside) read high. EDLD
does the same with every kill the journal shows:

- `Bounty`, naming the victim's faction. Skimmers and on-foot targets are not
  ships and do not count.
- `FactionKillBond`, naming the victim's faction: a kill in a conflict zone
  pays a combat bond rather than a bounty, and counts for a civil-war
  massacre like any other kill of that faction.
- `CommitCrime` with `murder`, when the victim was scanned in full
  (`ShipTargeted` stage 3) and found to be of the target faction. A clean
  ship of the target faction counts for the mission, but pays no bounty, so
  no `Bounty` is written for it.
- The locked target dropping (`ShipTargeted` with `TargetLocked` false) when
  its last reading was at no hull and its scan had not finished, with no
  `Bounty`, bond or murder for that pilot within three seconds. A ship destroyed
  before the scan completes pays no bounty either. Its faction is not known,
  so it is counted only when one target faction is held for the system.

A mission is held one short of its count until `MissionRedirected`, which is
written the moment the game finds it complete and sets it to its count; the
kills the journal missed are recovered there, and the next mission of that
source faction counts on from it.

A redirect also says how many kills were missed while its mission was
current, from when it became its faction's current mission, or reached its
target system if later, to the redirect. Every kill counts once for each
source faction, so those kills count for every other faction current over
that span too, but the redirect does not say when in the span they fell.
EDLD keeps each redirect as a span of missed kills and credits each current
mission the fewest missed kills its own span must hold under all of them,
the missed count never falling over time: a set of difference constraints,
solved as a shortest path, so it never claims a kill some span does not
force. A faction that took up its mission part way through a span gains
nothing from it. A wing mission adds no span once a wing is joined during it,
since a wingmate's kill counts for it alone. Spans disagreeing with each
other, which the model says cannot happen, make it claim nothing for that
stack rather than guess. Kills
of ships destroyed before a scan finished and while not locked leave nothing
in the journal, so between redirects the count can lag the game's mission
screen, never lead it; each redirect brings it back in step. Each redirect
is logged with the kills seen and those known from other redirects, so a lag can be measured from
real journals.

The kills are not stored: at every `Missions` snapshot they are rebuilt from
the journal index, from the journal holding the oldest active massacre's
acceptance up to the snapshot, then fed live.
