# EDLD Privacy Policy

Effective 8 November 2026.

EDLD, the Elite Dangerous Live Dashboard, is published by Indevlin, LLC
(“Indevlin”, “we”, “us”). This policy covers EDLD on Windows, macOS and Linux,
including its server mode and the headless EDLD-server.

EDLD runs on your computer and reads files the game writes there. Almost
everything it does stays there. This policy lists every outside service it can
talk to, what it sends, and what has to be true before it sends anything.

Indevlin runs no server for EDLD and collects nothing from it: there is no
telemetry, no analytics, no account, and nothing is sent to Indevlin by EDLD or
by the EDAM app’s connection to it.

## Always on

| Service | When | What is sent |
|---|---|---|
| **GitHub** (`api.github.com`) | Once at startup | A request for the latest EDLD release, to tell you when there is a new one. Nothing about you or the game |

## Only when you turn it on

Each of these is off until you configure it, and can be switched off again in
Options or `config.toml`.

| Service | Turned on by | What is sent |
|---|---|---|
| **Frontier Companion API** (`companion.orerve.net`, `auth.frontierstore.net`) | Signing in with your Frontier account from EDLD | EDLD asks Frontier for your profile, fleet, market, shipyard, fleet carrier and community goals, using a token issued to you. The token is kept in your commander’s data folder |
| **EDDN** — Elite Dangerous Data Network | `[EDDN] Enabled` | Game data other tools rely on: markets, outfitting, shipyards, systems, bodies and signals you visit or scan, with your commander name as the uploader ID, which EDDN anonymizes before passing it on. Nothing from your inventory, wallet or missions |
| **EDSM** — Elite Dangerous Star Map | `[EDSM] Enabled`, commander name and API key | Your journal — travel, scans, ranks, materials, missions and the rest EDSM accepts — under your EDSM account. EDLD also asks EDSM where it last saw you |
| **EDAstro** | `[EDAstro] Enabled` | Exploration events — scans, signals, codex entries — and, with `UploadCarrierEvents`, your fleet carrier’s movements |
| **Inara** | `[Inara] Enabled`, commander name and API key | Your commander’s activity, under your Inara account: ranks and engineer ranks, reputation, credits, ships and their loadouts, cargo and materials, missions, docking and jumps, deaths, and community goals |
| **Raven Colonial** | `[Colonisation] ApiKey` | Construction progress for colonization projects you contribute to |
| **Discord** | `[Discord] WebhookURL` | Messages to your own channel: the startup notice (commander, location, ship, credits, cargo, fuel, PowerPlay, carrier), alerts, and the quarter-hour summaries, at the levels set under `[LogLevels]` |
| **Google Sheets** (your own sheet’s Apps Script) | `[SurfaceSurvey] Enabled`, URL and token | Surface deposits you record — system, body, commodity, position, amount, density, notes — ring hotspots you map — system, body, ring, ring type, reserve level, commodity, overlap and note — and the reporter name you choose. EDLD also reads back what others have recorded. See [SURFACE_SURVEY.md](https://github.com/indevlin/EDLD/blob/main/docs/SURFACE_SURVEY.md) |
| **DuckDNS** | `[Server] DuckDNSDomain` and token | Your public IP address, to keep your DuckDNS name pointing at it |
| **Your router** (NAT-PMP / UPnP) | `[Server] PortMapping` | A request, on your own network, to forward the server’s port. Removed when EDLD exits |

## Only when you use a feature

| Service | When | What is sent |
|---|---|---|
| **Spansh** | Plotting an FSD, neutron, fleet-carrier or survey route, choosing a target market, searching systems and stations nearby, checking a route for permit locks, or targeting a system with the targeting chime on | The systems, stations, ranges and options you entered, the coordinates searched around, and for an FSD route the current ship’s drive figures, masses, tank sizes and cargo tonnage; for a trade run your capital and cargo space. Nothing that identifies you |
| **Spansh** system data | Every few hours while you hold unsold first discoveries, and on the Discoveries tab | The systems’ addresses, to see whether anyone else has reported their bodies since you scanned them. Nothing that identifies you |
| **EDAstro** DSSA list | Finding a service with fleet carriers included | A request for the published list of Deep Space Support Array carriers. Nothing about you |
| **EDSM** flight log | Pressing *Find and fill gaps* | Your commander name and API key, asking for your own flight log over the days chosen; the jumps it lacks then go up with your other EDSM uploads |
| **EDSM** star data | Plotting a route, or looking a system up | System names, and the coordinates of the system you are in when no database knows it yet. Nothing that identifies you |
| **Radio stations** | Pressing play on the Radio tab | A connection to that station’s stream server, which sees your IP address like any listener’s. EDLD never starts a stream on its own |
| **Coriolis** or **EDSY** | Clicking *Open in Coriolis* or *Open in EDSY* on a ship in the dossier | Your browser opens the site with that ship’s fitting in the link |
| **EDSY**, **sh.orbis.zone**, **link.edomh.nl** | Importing a target build from a short link in the Engineering window | A request for the link, to read where it leads. Nothing about you |
| **Spansh** material traders | Opening the Engineering window’s shopping list, when the traders your journals know are not enough | The coordinates of the system you are in, to find the nearest material traders. Nothing that identifies you |

The radio stations, Spansh, Coriolis and EDSY, and every service above, are run
by others and are not affiliated with EDLD. Their own terms and privacy
policies apply.

## Server mode and the EDAM app

With server mode on, EDLD serves your dashboard to devices you have paired, and
to nothing else. The connection is direct — your phone to your EDLD, over TLS
1.3 with both ends’ keys pinned — and passes through no service run by Indevlin
or anyone else. A device can see what the dashboards show, run the Navigation
window’s forms and press the buttons under a window as the desktop does — a
plot or a search from the phone goes to Spansh from your computer, as above —
and, if you allow it, end the game session in Solo and press the keys on its
Helm panel. See [SERVER.md](https://github.com/indevlin/EDLD/blob/main/docs/SERVER.md).
What the EDAM app itself does is covered by the
[EDAM Privacy Policy](https://www.indevlin.com/privacy/edam/).

## What stays on your machine

* Your journals, which EDLD only reads, and the compressed copies it keeps of
  them in `journal-backups`.
* What you have found in rings of each type, for the ring callout.
* Your unsold first discoveries and the rescan list.
* Everything EDLD keeps: config, per-commander data, the body catalog, the
  surface survey, the commodity catalog, the [dossier](https://github.com/indevlin/EDLD/blob/main/docs/DOSSIER.md) and the
  logs, in EDLD’s data directory.
* What makes starting quick: an index of where each event is in your journals
  (positions and event names, not their contents), the career figures as
  they stood after your older journals, and what each window last showed —
  in EDLD’s data directory and your commander’s data folder
  ([how](https://github.com/indevlin/EDLD/blob/main/docs/STARTUP.md)).
* Credentials — API keys, tokens, the Discord webhook — in `config.toml` and
  your commander’s data folder. The diagnostic log records whether each one is
  set, never its value, and a DuckDNS token is never written to any log.

## A secondary instance uploads nothing

With `PrimaryInstance = false` — EDLD on a second machine reading the same
journals — the EDDN, EDSM, EDAstro and Inara uploads are suppressed, so those
services do not receive the same events twice, and no overlay is drawn. Discord,
Raven Colonial and the survey sheet follow their own settings, which is why the
remote profile in `example.config.toml` turns Discord off. See
[Remote Access](https://github.com/indevlin/EDLD/blob/main/docs/guides/REMOTE_ACCESS.md).

## Getting EDLD

EDLD is downloaded from GitHub, and its source is also on Indevlin’s own git
server. Both record standard access logs — IP address, what was requested and
when — as any web server does. GitHub’s own privacy policy applies to GitHub.
Indevlin’s logs are used only to run and secure its server, and are not shared
or sold.

## Email and bug reports

If you email Indevlin, we use your address and message only to reply, keep
them only as long as that requires, and delete them on request. Bug reports on
GitHub are public and are covered by GitHub’s terms. EDLD’s diagnostic log is
safe to attach: it records whether each credential is set, never its value.

## What we never do

Indevlin does not sell or share personal data, and EDLD has no analytics,
advertising or tracking of any kind.

## Children

EDLD is made for players of Elite Dangerous and is not directed at children
under 13. Indevlin does not knowingly collect information from children.

## Your rights

Depending on where you live, you may have the right to know, access, correct or
delete personal data, and to object to its use. Indevlin holds no personal data
from EDLD beyond emails you send us; ask us about those. What EDLD sends to the
services above is held by them under their own policies, and each of them
offers its own controls — turning an upload off in EDLD stops it, but does not
delete what was sent.

## Changes

If this policy changes, the date at the top changes with it, and significant
changes are noted in EDLD’s release notes.

## Contact

Indevlin, LLC — [support@indevlin.com](mailto:support@indevlin.com)
