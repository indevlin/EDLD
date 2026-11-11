# Third-party notices

ED Live Dashboard (EDLD) is distributed under the MIT license (see `LICENSE`).
It incorporates or depends on the components listed below. Where a license
requires its text to accompany distribution, that text is in `licenses/` and
ships inside every release archive and every binary.

| Component | License | Used by | Bundled in binaries |
|---|---|---|---|
| **PySide6 / Qt** | **LGPL v3** | desktop window (EDCARS and `--dashg`) | yes |
| **Textual** | MIT | terminal dashboard (`--dasht`) | yes |
| **Rich** | MIT | terminal dashboard markup | yes |
| **miniaudio** (pyminiaudio) | MIT | Radio tab playback | yes |
| **miniaudio / dr_libs / stb_vorbis** (C, inside pyminiaudio) | public domain or MIT-0 | audio output; MP3, FLAC, Vorbis decoding | yes |
| **cffi** | MIT | pulled in by miniaudio | yes |
| **psutil** | BSD 3-Clause | game-process detection, session management | yes |
| **certifi** | **MPL 2.0** | CA bundle for HTTPS in packaged builds | yes |
| **cryptography** | Apache 2.0 or BSD 3-Clause | server mode (`-s`): the server's key and certificate | yes |
| **OpenSSL** (inside cryptography's wheels) | Apache 2.0 | server mode TLS primitives | yes |
| **segno** | BSD 3-Clause | server mode: the pairing QR code | yes |
| **PyInstaller** | GPL 2.0 with bootloader exception | build tool | bootloader only, under its exception |
| **JetBrains Mono** | **SIL OFL 1.1** | Streamer Stats Overlay typeface | yes — `fonts/` |
| **Euro Caps** | freeware | Streamer Stats Overlay typeface; dossier headings; EDCARS's chrome | yes — `fonts/` |
| **Rajdhani** (Bold) | **SIL OFL 1.1** | the ORDER console's chrome | yes — `fonts/` |
| **Saira Condensed** (Bold) | **SIL OFL 1.1** | the REBEL console's chrome | yes — `fonts/` |
| **VT323** | **SIL OFL 1.1** | the ROGUE console's chrome | yes — `fonts/` |
| **Permanent Marker** | **Apache 2.0** | the ROGUE console's tape labels | yes — `fonts/` |
| **EliteDangerousRegionMap** (klightspeed) | MIT | which galactic region a system is in, for the codex | yes — `data/regions.py` |
| **earcongen** callout sounds | MIT | callout chimes | yes — `sounds/` |

Packages that come in only as dependencies of these — markdown-it-py, mdurl,
mdit-py-plugins, Pygments, platformdirs, typing-extensions, pycparser — are
MIT, BSD, Apache 2.0 or PSF, all permissive. Their exact set varies with the versions a build picks up.

**Every bundled package's own license text ships inside each binary**, under
`licenses/third-party/<package>-<version>/`, copied at build time from the
package metadata of the build environment, so the texts always match the
versions actually shipped. Apache 2.0 NOTICE files are included the same way.
A package with no license file stops the build rather than shipping without
one. See `licence_files()` in `packaging/build_common.py`.

Only PySide6 constrains how EDLD is packaged. See
[docs/LICENSING.md](docs/LICENSING.md) for the full reasoning and for how each
LGPLv3 condition is met.

## JetBrains Mono

Copyright 2020 The JetBrains Mono Project Authors
<https://github.com/JetBrains/JetBrainsMono>

Licensed under the SIL Open Font License, Version 1.1. The full text travels
with the font in `fonts/OFL.txt`, which is what the license requires. The OFL
permits bundling with software provided the license accompanies the font, the
font is not sold by itself, and a modified copy is not distributed under the
reserved family name. EDLD ships the files unmodified and sells nothing.


## Rajdhani, Saira Condensed and VT323

Rajdhani: Copyright (c) 2014, Indian Type Foundry.
Saira: Copyright 2016 The Saira Project Authors, with reserved font name
"Saira".
VT323: Copyright 2011, The VT323 Project Authors.

Each licensed under the SIL Open Font License, Version 1.1, and each license's
full text travels beside its font: `fonts/OFL-Rajdhani.txt`,
`fonts/OFL-SairaCondensed.txt` and `fonts/OFL-VT323.txt`. EDLD ships the
files unmodified, under their own names, and sells nothing. The faces come
from the Google Fonts repository (github.com/google/fonts).


## Permanent Marker

Copyright (c) 2010 by Font Diner, Inc. Licensed under the Apache License,
Version 2.0, whose full text travels beside the font in
`fonts/LICENSE-PermanentMarker.txt`. Shipped unmodified.


## Euro Caps

Freeware, ©2010. Used for the Streamer Stats Overlay's Elite-styled default,
and embedded in the dossier's web page (`dossier/html/index.html`) for its
headings, so the page needs nothing beside it.


## Qt for Python (PySide6)

Copyright © The Qt Company Ltd. Licensed under the GNU Lesser General Public
License version 3. The full texts are bundled:

- `licenses/LGPL-3.0-only.txt`
- `licenses/GPL-3.0-only.txt` (LGPLv3 incorporates the GPLv3 by reference)

Qt is **never statically linked**. PyInstaller stores the Qt shared libraries
inside the executable's archive; they are extracted to a temporary directory at
launch and loaded dynamically by the operating system's normal mechanism. You
may replace them with your own build of Qt — see
[docs/BUILDING.md](docs/BUILDING.md) for the commands.

## certifi

Copyright © Kenneth Reitz and contributors. Licensed under the Mozilla Public
License 2.0.

certifi is a curated copy of the Mozilla root certificate store. It is bundled
unmodified, as data rather than as linked code, and is what makes HTTPS work in
the packaged builds — a frozen binary carries its own OpenSSL, whose
compiled-in certificate paths do not exist on most target machines. See
`core/certs.py`.

The MPL is a file-level copyleft: it attaches to the covered files themselves,
not to a work that merely ships alongside them. Bundling the certificate store
unmodified therefore places no condition on EDLD's own license. Were you to
modify the bundle, those modifications would need to be made available under
the MPL.

The license text is at https://mozilla.org/MPL/2.0/ and travels inside the
certifi package included in each binary.

## psutil

Copyright © Giampaolo Rodola. BSD 3-Clause. Used to detect whether the game is
running, and by the session-management component to stop it.

## miniaudio

pyminiaudio: Copyright © Irmen de Jong. MIT license.
<https://github.com/irmen/pyminiaudio>

It compiles in David Reid's miniaudio library and dr_mp3 and dr_flac, and Sean
Barrett's stb_vorbis. Each is dual-licensed public domain (Unlicense) or
MIT No Attribution, so none places any condition on EDLD or its binaries. Used
by the Radio tab to decode station streams and play them through the system's
audio output. See `core/radio.py`.

## Textual and Rich

Copyright © Will McGugan and contributors. MIT license. Used for the terminal
dashboard and for the console markup the dashboard blocks emit.

## cryptography and segno

cryptography is under Apache 2.0 or BSD 3-Clause, at the recipient's choice,
and its wheels include OpenSSL, under Apache 2.0. Server mode uses it for the
server's key, certificate and TLS. segno, under BSD 3-Clause, draws the pairing
QR code.

## Region map

`data/regions.py` is the run-length map of the galaxy's 42 regions from Ben
Peddell's [EliteDangerousRegionMap](https://github.com/klightspeed/EliteDangerousRegionMap),
copyright (c) 2020 Ben Peddell, MIT license; the text is in
`licenses/EliteDangerousRegionMap-MIT.txt`. `core/region.py`, which reads it,
is EDLD's own.

## Callout sounds

The chimes in `sounds/` were made with
[earcongen](https://github.com/indevlin/earcongen), MIT license, as one family
so they read as related and sit at the same loudness.

## Services

EDLD can exchange data with services run by others — Frontier's Companion API,
EDDN, EDSM, EDAstro, Inara, Raven Colonial, Spansh, Discord, DuckDNS, a Google
Sheet you set up, the radio stations on the Radio tab, and the build sites whose
links the Engineering window follows (EDSY, Coriolis's sh.orbis.zone and EDOMH's
link.edomh.nl). None is part of
EDLD or affiliated with it, each has its own terms, and every upload is off
until you turn it on. What goes where is in [docs/PRIVACY.md](docs/PRIVACY.md).

## Module data

`data/outfitting.py` — each ship module's in-game name, class and rating — is
generated by `scripts/export_outfitting.py` from `outfitting.csv` in EDCD's
community-maintained [FDevIDs](https://github.com/EDCD/FDevIDs) repository.
Its ratings, and EDLD's ship names, were checked against
[EDSY](https://edsy.org); a few ratings and modules FDevIDs lacks are taken
from there, as facts — none of EDSY's files are included.

`data/fsd_drives.py` — each frame shift drive's optimal mass, fuel per jump
and fuel curve — is generated by `scripts/export_fsd_drives.py` from
`modules/standard/frame_shift_drive.json` in EDCD's
[coriolis-data](https://github.com/EDCD/coriolis-data) repository. The figures
are Frontier Developments' game data, under Frontier's terms; none of
coriolis-data's files are included.

`data/eddb.sqlite` — hulls and their slots, modules, blueprints, experimental
effects, their recipes and the materials — is made from `eddb.js` in
[EDSY's repository](https://github.com/taleden/EDSY), © taleden, under the
[Creative Commons Attribution-NonCommercial 4.0](https://creativecommons.org/licenses/by-nc/4.0/)
license; its game data is Frontier Developments'. It is an adaptation: the
tables the Engineering window uses are taken out of the JavaScript source and
stored as SQLite, and nothing is added to them. It is shipped in the
repository and in every binary under that license, not EDLD's, and its `meta`
table records where it came from and the version it was made from. The
journal's own record of each roll at an engineer is checked against it. It is
provided as is, without warranties of any kind, as section 5 of that license
sets out.

## Elite Dangerous

Elite Dangerous is a trademark of Frontier Developments plc. EDLD reads the
journal files the game writes to the local filesystem, in the documented format
Frontier publishes for exactly this purpose. It does not modify the game, inject
code, read process memory, or interact with Frontier's servers other than
through the Companion API using the commander's own credentials. The optional
automation presses keys through the operating system's own input, as a
keyboard does, through the commander's own bindings.

EDLD is an unofficial community tool, not affiliated with, endorsed by, or
supported by Frontier Developments plc.
