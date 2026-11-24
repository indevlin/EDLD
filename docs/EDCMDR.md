# ED Commanders

[ED Commanders](https://edcmdr.com) is a public showcase for Elite Dangerous
commanders: a dossier for each commander, rosters for their squadrons, and
leaderboards across combat, trade, mining, exploration, exobiology and more.
EDLD can publish to it, as the standalone EDCMDR client does. It is off until
you turn it on, and nothing is published until you choose what to share.

## Turning it on

1. **Options → Services → ED Commanders:** set **Enable ED Commanders** to on,
   or `Enabled = true` under `[EDCMDR]` in `config.toml`, and restart EDLD.
2. **ED Commanders settings…** opens the publishing settings:
   - **Commanders:** every commander found in your journal folders, and where
     each stands on ED Commanders. EDLD's journal folder is added for you;
     add others here.
   - **Sharing:** for each commander, the sections to publish and a delay for
     each: none, 1 hour, 12 hours, 1 day or 1 week. ED Commanders holds a
     delayed section back until its time.
   - **Verify with Frontier:** a one-time sign-in on Frontier's own site that
     proves the commander is yours. It puts you on the leaderboards and gives
     a squadron leader the **Squadron** tab.
   - **Portrait…:** a screenshot of the Codex hub with your commander tile
     highlighted becomes your portrait.
   - **Forget on EDCMDR…** removes the commander from the site entirely.

## EDLD and the EDCMDR client together

EDLD uses the EDCMDR client's own keys and settings, in the client's config
folder, so a commander published by one is the same installation to ED
Commanders when published by the other, and verification carries over. Only
one publishes at a time: whichever starts second stands by, says so in its
status, and takes over when the first stops.

With `PrimaryInstance = false`, as on a second machine reading the same
journals, EDLD does not publish.

## How it works

EDLD runs the EDCMDR client's publishing engine on its own thread. It reads
your journals itself (your history once, then the game as you play), keeps one
state per commander, and pushes only the sections you switched on, signed with
a key made for each commander on this computer. Release builds of EDLD carry
EDLD's own build key, which ED Commanders lists; a build without one runs, but
ED Commanders refuses what it sends.

The engine is the client's code, vendored in `vendor/edcmdr-client`. Release
builds vendor the client's latest release automatically: the workflow finds the
newest `YYYYMMDD` tag on EDCMDR-client, checks it out and runs
`scripts/sync_edcmdr.py` on it, and the release notes name that client. The
committed copy is what source runs use, and what a build falls back to when no
client release is found. To refresh it, `python3 scripts/sync_edcmdr.py
~/projects/indevlin/EDCMDR-client`; the script checks the protocol spec against
the client's `protocol.lock`.

What is sent, and what ED Commanders keeps, is in [PRIVACY.md](PRIVACY.md)
and edcmdr.com's [privacy policy](https://edcmdr.com/privacy).
