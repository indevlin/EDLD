"""EDCMDR client: reads Elite Dangerous journals and publishes what the commander chose to EDCMDR."""

import re
import time
from pathlib import Path

NAME = 'EDCMDR-client'
try:
    from ._build_info import VERSION  # written by scripts/build.py
except ImportError:
    try:
        VERSION = (Path(__file__).resolve().parent.parent / 'version').read_text().strip()
    except OSError:
        VERSION = ''
    if not re.fullmatch(r'\d{8}', VERSION):
        VERSION = time.strftime('%Y%m%d', time.gmtime())
