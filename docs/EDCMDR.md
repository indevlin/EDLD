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
   - **Verify with Frontier:** proves the commander is yours. It uses EDLD's
     own Frontier sign-in (**Options → Services → Frontier CAPI**), so there is
     one sign-in for everything: once you are signed in there, EDLD verifies
     you by itself within a minute. If you are not signed in yet, pressing
     this opens Frontier's sign-in page. Verifying puts you on the
     leaderboards, lets you take part in Squad Goals, and gives a squadron
     leader the **Squadron** settings and the Squad Goals event form. Press it
     yourself only to move the commander over from another computer.
   - **Codex portrait:** press **Browse…** beside **Screenshot file**, choose a
     screenshot of the Codex hub with your commander tile highlighted, save,
     then **Send portrait**.
   - **Squadron:** home system, power, factions, recruiting and tagline, for
     a verified squadron leader; **Save squadron** publishes them.
   - **Forget on EDCMDR**, pressed twice, removes the commander from the site.
   - **Status** shows where each commander stands.

## Squad Goals

> **Beta.** Squad Goals is new and still being tested: expect rough edges, and
> check standings and payouts before paying anyone out. Feedback and bug
> reports are very welcome on the [Indevlin Discord](https://discord.indevlin.com).

Squad Goals are events your squadron's leader runs: a mining push, a bounty
week, a trade run, a construction drive. Everyone in the squadron who is
signed in to Frontier takes part just by playing. Only what Frontier's own
copy of your journal shows counts, so nothing can be typed in, edited or
faked, and a session the game rolled back does not count either.

### Taking part

- Sign in to Frontier in **Options → Services → Frontier CAPI**. That is all.
  Once you are signed in and in a squadron (or invited to an event), a
  **Squad Goals** button appears in the EDCARS rail between Objectives and
  Exploration. In the Dashboard style it is the **Squad Goals** menu, and
  **Ctrl+U** opens it in either, and in the terminal.
- The **Events** tab shows each event: what counts, where, which days, the
  time left, the squadron's total, the prize pool and the standings, with
  your own row highlighted. EDAM shows the same. Nothing about events is ever
  on the website.
- EDLD has ED Commanders read your journal from Frontier every 15 to 30
  minutes while an event is running. **Update standings** does it now.
- After an event ends, journal days that arrive late are still read for 24
  hours; then the results are final. Open EDLD during that time if you played
  near the end.
- **Take part in my squadron's events** (Options → ED Commanders → Sharing)
  is on unless you switch it off. Off, you count in no event.
- Taking part never puts your name on the website: a commander who shares
  nothing there is not listed at all.
- Invited to an event by another squadron? Paste the code into **Invitation
  code** in Options → ED Commanders and press **Use invitation**, or use
  **Use invitation…** in the Squad Goals window.

### Running an event (squadron leaders)

The **Create event** tab appears for the squadron's verified leader. The form
is in groups (the event, when, what counts, prize, Discord, members), side by
side on a wide window, with the buttons along the bottom always in view.

1. **Event:** "New event", or one of yours to change it.
2. **Title**, and a **Note** for your squadron if you like.
3. **First day** and **Last day**. Events run whole days in UTC, from
   00:00:00 on the first day to 23:59:59 on the last; one day is the
   shortest, 62 days the longest.
4. **Measure:** what counts. Tons refined, bounty value earned, combat bond
   value earned (as earned, not as handed in), tons sold, credits from sales,
   or tons delivered to construction.
5. **Prize pool:** the credits you will pay out, such as `100M`. Leave it
   blank for standings only.
6. **Reward tiers** (optional): unlock the pool in steps as the squadron's
   combined total grows, for example 50% of the pool at 10,000 t and all of it
   at 25,000 t. With no tiers the whole pool is paid.
7. **Shares for the top places:** `50, 30, 20` pays 1st place 50 shares of
   the pool, 2nd 30 and 3rd 20. Each place gets the same as the one above it
   or less, never more. Leave it blank to share the pool by amount instead:
   whoever brings in twice as much gets twice as much.
8. **Shares for everyone else** (optional): groups after the top places, such
   as "the next 50% of them get 5 shares each, the rest 2". A group never
   gets more than a place above it.
9. **Participation floor:** the least a commander must bring in to share in
   the prize. Everyone still shows in the standings.
10. **Example** shows what each place would be paid with 10 commanders, so
    you can see the effect before saving. While Squad Goals is in beta, check
    the final results before paying anyone.
11. Optionally, where it counts: a **Star system** (its name, or its system
    address if you know it; **Find** checks it is real), a **Station** in it
    (any station, outpost, settlement or carrier with a market; "Anywhere in
    the system" otherwise), and **Commodities** (type the names; suggestions
    appear as you type, and close misses such as "Platnum" or "LTD" are
    understood).
12. **Save event.** Your squadron sees it straight away.

Ties share the places they span equally. Payouts are whole credits; anything
left over by rounding is shown in the results. EDLD and edcmdr.com use the
same rule, and paying the credits out is up to you.

Along the bottom: **Save event**, **End now** (the event stops counting now and finalizes 24
hours later), **Finalize results** (after the end, without waiting the 24
hours), **Cancel event**, and **Make invitation…** for one named commander,
or anyone verified who has the code, optionally expiring after some days or
some uses. **Member** with **Remove from events** / **Restore** leaves a
squadron member out of your events.

**Discord webhook:** paste the address from Discord (Server Settings →
Integrations → Webhooks) and **Save**; a test message is posted. It is kept,
encrypted, for your squadron and used for every event until you press
**Forget**. **Announce now** posts the event as it stands: when it starts, or
the time left and standings, or the closing standings with a reminder that
results are final in 24 hours, or the final results with rewards. Tick
**Post to Discord automatically** and edcmdr.com posts by itself, whether
you are online or not: when the event is saved, when it starts, while it runs
(every 6 hours for an event of one day, every 12 for two, daily for longer),
when it ends and when the results are final. Nobody is ever mentioned.

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
