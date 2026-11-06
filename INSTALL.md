# EDLD Installation Guide

EDLD is a Python daemon for real-time Elite Dangerous session monitoring, running on Linux, Windows and macOS. It offers four interfaces over the same dashboard: EDCARS, the PySide6 desktop window drawn as a console (`--edcars`, the default); the same window with every panel at once (`--dashg` or `--gui`); a Textual terminal dashboard (`--dasht` or `--tui`); and plain scrolling terminal output (`--term` or `--text`).

Running from source is the norm on Linux, and needs **Python 3.11 or later**. On Windows and macOS, download a prebuilt binary from the [Releases page](https://github.com/indevlin/EDLD/releases) — no Python install needed — or follow the source instructions below if you prefer.

Server mode, for the EDAM mobile app, needs two more packages, `cryptography` and `segno`; add them to the `pip install` line below if you will use it (on Arch, `cryptography` is `python-cryptography` from pacman). See [Dependencies](#dependencies).

---

## Linux — Arch

Arch ships current versions of everything EDLD needs.

```bash
sudo pacman -S python-psutil
pip install discord-webhook textual miniaudio --break-system-packages
```

```bash
git clone https://github.com/indevlin/EDLD.git
cd EDLD
bash install.sh
nano ~/.local/share/EDLD/config.toml   # JournalFolder, unless the game runs under Steam/Proton

./edld.py                    # EDCARS, the desktop window (default)
./edld.py --dashg            # desktop window, Dashboard layout (or --gui)
./edld.py --dasht            # terminal dashboard (or --tui)
./edld.py --term             # plain scrolling output (or --text)
```

---

## Linux — Debian / Ubuntu

```bash
sudo apt install python3-psutil
pip install discord-webhook textual miniaudio --break-system-packages
```

```bash
git clone https://github.com/indevlin/EDLD.git
cd EDLD
bash install.sh
nano ~/.local/share/EDLD/config.toml

./edld.py
./edld.py --dasht
./edld.py --term
```

---

## Linux — Fedora

```bash
sudo dnf install python3-psutil
pip install discord-webhook textual miniaudio --break-system-packages
```

```bash
git clone https://github.com/indevlin/EDLD.git
cd EDLD
bash install.sh
nano ~/.local/share/EDLD/config.toml

./edld.py
./edld.py --dasht
./edld.py --term
```

---

## Windows and macOS

### Prebuilt binary (recommended)

Download the archive for your platform from the
[Releases page](https://github.com/indevlin/EDLD/releases), extract it, and run
the executable. Everything is bundled — Python, Qt and all dependencies.

Verify the download first if you like; see [docs/SIGNING.md](docs/SIGNING.md).

The binary opens EDCARS by default. On its first run the Windows binary adds a
Start-menu folder, **EDLD**, holding one shortcut per interface — EDCARS,
Dashboard, Terminal dashboard and Terminal text. It remakes them if you move or
update the binary; `EDLD.exe --remove-shortcuts` removes them and stops it
making them again, and `--shortcuts` brings them back. The terminal shortcuts
open their own console window. Server mode needs no shortcut of its own: turn
it on in **Options → Server** and it runs beside whichever interface you open.

From a shell, `--dasht` and `--term` open the terminal interfaces on any
platform, and `--version` confirms which build you have.

The game's journal folder, `Saved Games\Frontier Developments\Elite
Dangerous`, is found by itself. To read journals from anywhere else, set
`JournalFolder` in the config file — its path is printed at startup — or in
Options → General.

### From source

```bash
git clone https://github.com/indevlin/EDLD.git
cd EDLD
pip install -r requirements.txt
python edld.py
```

---

## The desktop interface

The desktop window — EDCARS, the default, and the Dashboard layout (`--dashg`) —
needs **PySide6**. It is the largest dependency EDLD has (roughly 100 MB), so
`install.sh` asks before installing it rather than assuming, and the terminal
interfaces work perfectly without it.

```bash
pip install PySide6 --break-system-packages
```

If PySide6 is missing, a plain `./edld.py` opens the terminal dashboard instead
and says why; `--edcars` and `--dashg`, which ask for the window by name, exit
with a message. `--dasht` and `--term` are unaffected.

`install.sh` also adds a launcher entry for each interface to your desktop's
application menu (`~/.local/share/applications`); run `./edld.py --shortcuts`
to add them yourself, or `--remove-shortcuts` to take them away.

PySide6 is Qt for Python, under the LGPL v3. See
[docs/LICENSING.md](docs/LICENSING.md) for what that means for redistribution,
and [docs/BUILDING.md](docs/BUILDING.md) for how to build your own binaries.

On a minimal Linux install Qt also needs a few X libraries present at runtime:

```bash
sudo apt-get install -y libegl1 libxkbcommon-x11-0 libxcb-cursor0 \
  libxcb-icccm4 libxcb-keysyms1 libxcb-shape0 libxcb-randr0 \
  libxcb-render-util0 libxcb-xinerama0
```

---

## Config file location

| Platform | `config.toml` |
|---|---|
| Linux | `~/.local/share/EDLD/config.toml` — `~/.config/EDLD` is a symlink to the same directory |
| Windows | `%LOCALAPPDATA%\EDLD\config.toml` |
| macOS | `~/Library/Application Support/EDLD/config.toml` |

A repo-adjacent `config.toml` is accepted as a development fallback.

If no config file is found on startup, EDLD writes one — a copy of `example.config.toml`, every setting at its default with a note on what it does — and prints its location. A blank `JournalFolder` finds the game's own journal folder on Windows and under Steam/Proton on Linux; anywhere else, set it and restart.

---

## Dependencies

| Dependency | Purpose | Install method |
|------------|---------|----------------|
| `python-psutil` | Process utilities | Package manager |
| `discord-webhook` | Discord notifications | pip |
| `textual>=0.47` | Terminal dashboard (`--dasht`) | pip |
| `rich>=13.3.3` | Terminal dashboard markup — arrives with Textual | pip |
| `miniaudio>=1.71` | Radio tab playback (MP3, Ogg Vorbis, FLAC) — optional | pip |
| `PySide6>=6.6` | Desktop window: EDCARS (the default) and `--dashg` — optional | pip |
| A compositor (`picom` or equivalent) | Streamer Stats Overlay transparency on Linux — optional | distro package |
| `cryptography>=42` | Server mode (`-s`) for the EDAM mobile app: the server's key and certificate — optional | package manager (`python-cryptography`, `python3-cryptography`) or pip |
| `segno>=1.5` | Server mode: draws the pairing QR code — optional; without it `--pair` still prints the code as text | pip |

Prebuilt binaries bundle all of the above, including psutil, the server-mode
packages and a CA certificate bundle (`certifi`), so they have no external
requirements at all. Server mode is covered in [docs/SERVER.md](docs/SERVER.md).

> **Do not install `psutil` via pip on Linux.** It has C extensions that require system libraries only available through the distro package manager.

---

## Verifying a Linux install

```bash
./edld.py --selftest
```

That reports on each interface directly:

```
EDLD 20261105 selftest
  OK    server (identity qJqSd2OL…)
  OK    pairing QR code
  OK    terminal dashboard (--dasht)
  OK    desktop window (--edcars, --dashg)
  OK    radio (miniaudio 1.71, MP3 decode OK)
```

A `FAIL` line names the missing piece. The server and QR lines only matter if
you use server mode, and the radio line only if you use the Radio tab. To check the individual packages
instead:

```bash
python3 -c "import discord_webhook, textual, miniaudio; print('Core OK')"
python3 -c "import psutil;  print('psutil OK')"    # game-process detection
python3 -c "import PySide6; print('Desktop OK')"   # only for the desktop window
```

EDLD starts and runs without psutil, but it cannot detect whether the game is
running and session management is unavailable.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'psutil'`**
Install via package manager: `sudo pacman -S python-psutil` (Arch) · `sudo apt install python3-psutil` (Debian/Ubuntu) · `sudo dnf install python3-psutil` (Fedora).

**`ModuleNotFoundError: No module named 'discord_webhook'`**
Run `pip install discord-webhook --break-system-packages`.

**`ModuleNotFoundError: No module named 'textual'`**
Run `pip install textual --break-system-packages`.

**`PySide6 GUI import failed`**
Run `pip install PySide6 --break-system-packages`. The terminal interfaces do
not need it.

**The desktop window fails to start with an xcb plugin error**
Qt cannot find its X libraries. Install the `libxcb-*` packages listed under
[The desktop interface](#the-desktop-interface) above.

**sshfs for remote access**
`sudo pacman -S sshfs` (Arch) · `sudo apt install sshfs` (Debian/Ubuntu) · `sudo dnf install fuse-sshfs` (Fedora). See [docs/guides/REMOTE_ACCESS.md](docs/guides/REMOTE_ACCESS.md).
