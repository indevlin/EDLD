#!/usr/bin/env bash
# Vendor the newest EDCMDR-client release (YYYYMMDD tag) into vendor/edcmdr-client and commit it.
#   scripts/vendor_edcmdr.sh [PATH_TO_EDCMDR_CLIENT]     default ../EDCMDR-client
# Fetches the client's tags, checks the tag out in a temporary worktree, runs scripts/sync_edcmdr.py on it,
# and commits only when vendor/edcmdr-client changed. Refuses to run with other uncommitted vendor changes.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLIENT="$(cd "${1:-$ROOT/../EDCMDR-client}" && pwd)"
VENDOR='vendor/edcmdr-client'

cd "$ROOT"
if [ -n "$(git status --porcelain -- "$VENDOR")" ]; then
    echo "vendor_edcmdr: $VENDOR has uncommitted changes; commit or discard them first" >&2
    exit 1
fi

git -C "$CLIENT" fetch --quiet --tags 2>/dev/null || echo 'vendor_edcmdr: could not fetch client tags; using local tags' >&2
TAG="$(git -C "$CLIENT" tag --list '[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]' | sort | tail -n 1)"
if [ -z "$TAG" ]; then
    echo "vendor_edcmdr: no YYYYMMDD tag in $CLIENT" >&2
    exit 1
fi
if grep -qx "source: EDCMDR-client $TAG" "$VENDOR/VENDORED" 2>/dev/null; then
    echo "vendor_edcmdr: already at EDCMDR-client $TAG"
    exit 0
fi

WT="$(mktemp -d)"
trap 'git -C "$CLIENT" worktree remove --force "$WT" >/dev/null 2>&1 || true; rm -rf "$WT"' EXIT
git -C "$CLIENT" worktree add --quiet --detach "$WT" "refs/tags/$TAG"
python3 scripts/sync_edcmdr.py "$WT"

git add -A -- "$VENDOR"
if git diff --cached --quiet -- "$VENDOR"; then
    echo "vendor_edcmdr: EDCMDR-client $TAG matches what is vendored"
    exit 0
fi
git commit --quiet -m "chore(edcmdr): vendor EDCMDR-client $TAG" -- "$VENDOR"
echo "vendor_edcmdr: committed EDCMDR-client $TAG"
