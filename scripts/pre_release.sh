#!/usr/bin/env bash
# Run by grel on dev before a release: steps that must land in the release commit, and checks that must pass.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

# The edcmdr-core tag requirements.txt pins must already be on GitHub: the release builds install it from there.
pin="$(sed -n 's/^edcmdr-core @ \(.*\)@\([0-9]\{8\}\)$/\1 \2/p' requirements.txt)"
if [ -z "$pin" ]; then
    echo "pre_release: no edcmdr-core @ …@YYYYMMDD line in requirements.txt" >&2
    exit 1
fi
url="${pin% *}"; url="${url#git+}"; tag="${pin##* }"
if ! git ls-remote --exit-code --tags "$url" "refs/tags/$tag" >/dev/null; then
    echo "pre_release: edcmdr-core tag $tag is not on $url; release EDCMDR-core first" >&2
    exit 1
fi
echo "pre_release: edcmdr-core $tag is on $url"
