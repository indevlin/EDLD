#!/usr/bin/env python3
"""Vendor the EDCMDR client's engine into vendor/edcmdr-client from an EDCMDR-client checkout.

  python3 scripts/sync_edcmdr.py [PATH_TO_EDCMDR_CLIENT]     default ../EDCMDR-client

Copies the edcmdr package (keys, protocol, journal reading, engine, settings window) and the
protocol spec it was built against, checks the spec against the client's protocol.lock, and
records the source commit in vendor/edcmdr-client/VENDORED. Commit the result.
"""
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / 'vendor' / 'edcmdr-client'
SKIP = shutil.ignore_patterns('__pycache__', '*.pyc', '_build_secret.py', '_build_info.py')


def main() -> int:
    src = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT.parent / 'EDCMDR-client').expanduser().resolve()
    lock = json.loads((src / 'protocol.lock').read_text())
    spec = src / lock['path']
    if hashlib.sha256(spec.read_bytes()).hexdigest() != lock['sha256']:
        sys.exit(f'{spec} does not match {src}/protocol.lock')
    git = subprocess.run(['git', '-C', str(src), 'describe', '--always', '--dirty', '--tags'],
                         capture_output=True, text=True)
    if git.stdout.strip().endswith('-dirty'):
        print('warning: the client checkout has uncommitted changes', file=sys.stderr)
    shutil.rmtree(DEST, ignore_errors=True)
    shutil.copytree(src / 'edcmdr', DEST / 'edcmdr', ignore=SKIP)
    (DEST / 'protocol' / 'v1').mkdir(parents=True)
    shutil.copy2(spec, DEST / 'protocol' / 'v1' / 'spec.json')
    shutil.copy2(src / 'protocol.lock', DEST / 'protocol.lock')
    shutil.copy2(src / 'LICENSE', DEST / 'LICENSE')
    (DEST / 'VENDORED').write_text(f'source: EDCMDR-client {git.stdout.strip() or "unknown"}\n'
                                   f'protocol sha256: {lock["sha256"]}\n')
    print(f'vendored {src} ({git.stdout.strip() or "no git"}) into {DEST.relative_to(ROOT)}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
