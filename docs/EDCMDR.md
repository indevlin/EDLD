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
