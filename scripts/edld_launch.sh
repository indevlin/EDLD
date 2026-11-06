#!/usr/bin/env bash
# ==============================================================================
# edld_launch.sh — EDLD on the game machine, or a dashboard of it on a second one
# ==============================================================================
#
# Run the same script on both machines; it works out which one it is on by
# hostname. See docs/guides/REMOTE_ACCESS.md.
#
#   Game machine       starts EDLD with your normal profile.
#   Second machine     finds the game machine (LAN first, then WAN), mounts its
#                      journal folder over sshfs, starts EDLD there with no
#                      interface if it is not already running, then opens the
#                      dashboard here with the [REMOTE] profile.
#
# Safe to run again: a mount already in place is kept, and EDLD already running
# on the game machine is left alone.
#
# Edit the settings below to match your machines.
# ==============================================================================

set -u

DESKTOP_SHORT="gamestation"           # short hostname of the game machine (hostname -s)
LAPTOP_SHORT="laptop"                 # short hostname of the secondary machine

DESKTOP_LAN="gamestation.local.net"   # LAN hostname / IP for the game machine
DESKTOP_WAN="gamestation.duckdns.org" # WAN hostname (DuckDNS or similar)

JOURNAL_REMOTE="${HOME}/games/ED-Logs/EDP1"  # journal path on the game machine
MOUNT_LOCAL="${HOME}/mnt/ed-journals"         # where to mount it locally

EDLD_DIR="$HOME/.local/bin/EDLD"      # path to your EDLD installation
GAME_PROFILE="EDP1"                   # your normal profile, on the game machine
REMOTE_PROFILE="REMOTE"               # the dashboard profile, on this machine
REMOTE_INTERFACE="--dasht"            # --dasht (terminal), --edcars or --dashg (needs a display)

# ------------------------------------------------------------------------------

say()  { printf '[edld_launch] %s\n' "$*"; }
fail() { printf '[edld_launch] %s\n' "$*" >&2; exit 1; }

here="$(hostname -s)"
edld=(python3 "$EDLD_DIR/edld.py")

# ── The game machine ──────────────────────────────────────────────────────────
if [[ "$here" == "$DESKTOP_SHORT" ]]; then
    if pgrep -f "edld.py.*-p $GAME_PROFILE" >/dev/null; then
        say "EDLD is already running here with profile $GAME_PROFILE."
        exit 0
    fi
    say "Game machine: starting EDLD with profile $GAME_PROFILE."
    exec "${edld[@]}" -p "$GAME_PROFILE"
fi

[[ "$here" == "$LAPTOP_SHORT" ]] || \
    fail "This is '$here', neither $DESKTOP_SHORT nor $LAPTOP_SHORT — set DESKTOP_SHORT and LAPTOP_SHORT at the top of this script."

# ── The secondary machine ─────────────────────────────────────────────────────
command -v sshfs >/dev/null || fail "sshfs is not installed (see docs/guides/REMOTE_ACCESS.md)."

host=""
for candidate in "$DESKTOP_LAN" "$DESKTOP_WAN"; do
    say "Trying $candidate…"
    if ssh -o BatchMode=yes -o ConnectTimeout=5 "$candidate" true 2>/dev/null; then
        host="$candidate"
        break
    fi
done
[[ -n "$host" ]] || fail "Cannot reach the game machine by SSH at $DESKTOP_LAN or $DESKTOP_WAN."
say "Game machine reachable at $host."

mkdir -p "$MOUNT_LOCAL"
if mountpoint -q "$MOUNT_LOCAL"; then
    say "Journals already mounted at $MOUNT_LOCAL."
else
    say "Mounting $host:$JOURNAL_REMOTE at $MOUNT_LOCAL."
    sshfs -o reconnect,ServerAliveInterval=15,ServerAliveCountMax=3,ro \
        "$host:$JOURNAL_REMOTE" "$MOUNT_LOCAL" || fail "sshfs mount failed."
fi
ls "$MOUNT_LOCAL"/Journal.*.log >/dev/null 2>&1 || \
    fail "No journals at $MOUNT_LOCAL — check JOURNAL_REMOTE."

# EDLD on the game machine, with no interface, if nothing is running there yet.
if ssh -o BatchMode=yes "$host" "pgrep -f 'edld.py' >/dev/null"; then
    say "EDLD is already running on the game machine."
else
    say "Starting EDLD on the game machine (profile $GAME_PROFILE, no interface)."
    ssh -o BatchMode=yes "$host" \
        "nohup python3 '$EDLD_DIR/edld.py' -p '$GAME_PROFILE' --headless >/dev/null 2>&1 &" \
        || say "Could not start EDLD on the game machine; carrying on with the dashboard."
fi

say "Opening the dashboard with profile $REMOTE_PROFILE."
exec "${edld[@]}" -p "$REMOTE_PROFILE" "$REMOTE_INTERFACE"
