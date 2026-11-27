#!/usr/bin/env bash
# Run by grel on dev before a release: steps that must land in the release commit.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
scripts/vendor_edcmdr.sh
