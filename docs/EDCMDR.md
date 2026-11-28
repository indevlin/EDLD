# ED Commanders

[ED Commanders](https://edcmdr.com) is a public showcase for Elite Dangerous
commanders: a dossier for each commander, rosters for their squadrons, and
leaderboards across combat, trade, mining, exploration, exobiology and more.
EDLD can publish to it, as the standalone EDCMDR client does. It is off until
you turn it on, and nothing is published until you choose what to share.

## Turning it on

1. **Options → ED Commanders:** set **Enable ED Commanders** to on (or
   `Enabled = true` under `[EDCMDR]` in `config.toml`) and restart EDLD. The
   page is the same in the desktop window and the terminal dashboard.
2. On the same page:
   - **Sharing:** the sections to publish, each with a delay: none, 1 hour,
     12 hours, 1 day or 1 week. ED Commanders holds a delayed section back
     until its time; switching a section off deletes it from the site. What
     you save applies to every commander EDLD has a profile for.
   - **Verify with Frontier:** a one-time sign-in on Frontier's own site that
     proves the commander is yours. EDLD shows a code; continue on edcmdr.com
     only if it shows the same one. It puts you on the leaderboards and lets a
     squadron leader save the **Squadron** settings.
   - **Codex portrait:** set **Screenshot file** to a screenshot of the Codex
     hub with your commander tile highlighted, save, then **Send portrait**.
   - **Squadron:** home system, power, factions, recruiting and tagline, for
     a verified squadron leader; **Save squadron** publishes them.
   - **Forget on EDCMDR**, pressed twice, removes the commander from the site.
   - **Status** shows where each commander stands.

## Squad Goals

A verified squadron leader can run events for their squadron on ED Commanders:
tons refined, bounty value earned, combat bond value earned, tons sold,
credits from sales, or tons delivered to construction, over a window of up to
62 days, optionally limited to star systems, markets and commodities, with a
prize pool paid out by place.

- **Objectives → Squad Goals** shows your squadron's events, and any you were
  invited to: the measure, where, time left, the squadron's total, the prize
  pool and the standings, your own row highlighted. A paired EDAM device shows
  the same. Nothing about events is on the website.
- **Take part in my squadron's events** (under Sharing) is on unless you switch
  it off. Taking part, ED Commanders reads your journal from Frontier for each
  event's days, using EDLD's Frontier sign-in (**Options → Services →
  Frontier CAPI**), and counts only what Frontier confirms; your local journal
  never counts. Without that sign-in the tab says so and nothing is counted.
  The same reading keeps your squadron membership confirmed.
- **Invitation code**, then **Use invitation**, joins an event you were
  invited to from outside the squadron (you must be verified).
- **Update standings now** reads events and your Frontier journal now; it
  otherwise happens every 15 to 30 minutes while an event is open.

For the leader, **Squad Goals: run an event**:

- Fill in title, measure, start and end (UTC, such as `2026-12-01 18:00`),
  and optionally star systems (checked to be real), market ids and
  commodities, then **Save event**. Leave **Event id** blank for a new event;
  the saved event's id fills it in, and is shown in the Squad Goals tab.
  Saving again with an id changes that event.
- **Prize pool** and **Place weights** (`5, 3, 2`: 1st gets 5 shares, 2nd 3,
  3rd 2), **Band weights** for the rest (`50:2, 100:1`: the top half of the
  rest 2 shares each, the others 1), **Least amount that qualifies**, and
  **Squadron goal tiers** (`10000:50, 25000:100`: half the pool once the
  squadron reaches 10,000, all of it at 25,000). Weights never rise going down
  the standings, so a lower place never pays more; ties share the places they
  span. With no places or bands the pool is shared by amount.
- Events end on time by themselves, read late journal days for 48 hours, then
  their results are final. **End event now**, **Finalize results** (after the
  end), **Cancel event**.
- **Make invitation**: for one named commander or anyone verified with the
  code, optionally expiring and with a number of uses.
- **Remove from events** / **Restore to events** for a member.
- **Discord webhook**: announces an event opening, being cancelled and its
  final standings, without mentioning anyone.

## EDLD and the EDCMDR client together

EDLD uses EDCMDR's own keys and sharing settings, in the EDCMDR config folder,
so a commander published by one is the same installation to ED Commanders when
published by the other, and verification carries over. Only one publishes at a
time: whichever starts second stands by, says so in its status, and takes over
when the first stops.

Sharing saved in EDLD's Options is written to that shared settings file; a
change made in the client is copied back into EDLD's Options. The last change,
in either, is what both publish.

With `PrimaryInstance = false`, as on a second machine reading the same
journals, EDLD does not publish.

## How it works

EDLD reads the journals as always. The ED Commanders component builds each
commander's sections from them with EDCMDR-core, the library the EDCMDR client
uses too, and hands them to EDCMDR-core's publisher, which pushes only the
sections you switched on, signed with a key made for each commander on this
computer. At start it reads your history once, from EDLD's journal index, then
follows the game as you play.

Release builds carry EDLD's own build key, which ED Commanders lists; a build
without one runs, but ED Commanders refuses what it sends. EDCMDR-core is
pinned by release tag in `requirements.txt`; `scripts/pre_release.sh` (run by
`grel`) stops a release whose pinned tag is not on GitHub yet.

What is sent, and what ED Commanders keeps, is in [PRIVACY.md](PRIVACY.md)
and edcmdr.com's [privacy policy](https://edcmdr.com/privacy).
