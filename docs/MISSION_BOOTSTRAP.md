# EDLD Mission Bootstrap

EDLD tracks two mission views. The general board records every mission you
accept, of any type, and drops it when it is completed, failed or abandoned;
that needs no bootstrap because it is rebuilt from the journal as it replays.
The massacre stack is the one that does, because it has to know reward values
to be useful.

When EDLD starts, it needs to know which massacre missions you have active and what they're worth. The game's `Missions` journal event at login contains the active mission list but frequently omits reward values — and if EDLD is launched mid-session, that event may not appear in the current journal at all.

EDLD resolves this by reading every `MissionAccepted`, `MissionCompleted`, `MissionAbandoned`, `MissionFailed` and `MissionRedirected` event in **all available journal files**, in chronological order, before the current journal is replayed — from the journal index ([Start-up](STARTUP.md)), so nothing else in the journals is read — replaying `MissionAccepted`, `MissionCompleted`, `MissionAbandoned`, `MissionFailed`, and `MissionRedirected` events to reconstruct exactly which missions are active, what they're worth, and how many have had their kill quota met. Missions whose `Expiry` timestamp has passed are filtered out automatically.

This means your stack value and completion count are accurate from the moment monitoring goes live, regardless of when or how EDLD was started — mid-session, after a relog, or with missions accepted in a previous game session.

---

## Kills against the stack

The Missions tab shows, for each source faction and for the stack as a whole,
the kills made against the kills needed: `002 / 045`. It took two attempts to
get this right, and the reason is worth keeping.

The game credits a kill of the target faction, in the target system, to one
mission per source faction: the oldest of that faction's missions still short
of its count. Every source faction sees the same kill, which is why a stack
completes when its tallest faction does. Over every massacre stack in the
journals the feature was built against (178 redirects), missions from one
faction always completed in the order they were accepted.

The obvious way to count, adding one for every `Bounty` against the target
faction, does not match the game, and that is why the first attempt was
dropped. The game credits kills the journal never writes a `Bounty` for: over
those same stacks the `Bounty` events accounted for about seven kills in ten,
and at the moment a mission redirected there was often no `Bounty` at all,
only the target lock dropping. A count of bounties is a floor, nothing more.

`MissionRedirected` is exact. When a faction's third mission redirects, that
faction has been credited with exactly its first three missions' kill counts.
So EDLD anchors the count on redirects: each mission's kills rise with every
qualifying `Bounty`, held one short of its count, and snap to the exact figure
when it redirects. Every source faction sees every kill, so a faction whose
missions were held from the moment kills became possible for another (when
you arrived in the target system, not when you accepted them) is never shown
fewer kills than that other; that is how the kills a redirect uncovers reach
the rest of the stack.

Two stronger rules were tried and dropped because, measured the same way,
they read high: handing a redirect's uncovered kills straight to every other
faction's current mission. A figure that runs ahead of the game is worse than
one that lags it.

The rule kept never read high over those 178 redirects: no `Bounty` ever met
a mission already at its cap unless that mission redirected within three
seconds. Between redirects it can read low; just before a mission redirected
it read on average under two kills short, and was exactly right for 101 of
the 178 (a plain count of bounties managed 46). On the Wolf 359 stack this
was written against, it matched the game's own mission screen exactly.

The count is not stored. It is rebuilt from the journals, through the journal
index, at every login's `Missions` snapshot, and fed live from there, so it is
right however long EDLD was not running, and a restart never counts a kill
twice. A redirect EDLD missed while it was closed is picked up by the rebuild,
so the "Ready to turn in" count is right as well.
