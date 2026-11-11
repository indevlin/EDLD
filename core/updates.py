"""core/updates.py — whether a newer EDLD release is out.

``newer_release`` asks GitHub for the latest release and returns its tag
when it sorts after the running version. ``UpdateWatcher`` asks at start-up
and every ``INTERVAL`` seconds after, and hands each new tag it finds to its
callback once. A failed request is written to the diagnostic log and retried
at the next interval, sooner after a start-up failure.
"""
from __future__ import annotations

import json
import threading
from urllib.request import Request, urlopen

#: Between checks while EDLD runs.
INTERVAL = 6 * 3600
#: After a failed check, the next one comes this soon.
RETRY = 15 * 60
#: How long a request may take.
TIMEOUT = 10


def latest_url(repo: str) -> str:
    return f"https://api.github.com/repos/{repo}/releases/latest"


def page_url(repo: str) -> str:
    return f"https://github.com/{repo}/releases/latest"


def newer_release(repo: str, version: str, opener=urlopen) -> str | None:
    """The latest release's tag when it is newer than ``version``, else
    None. Raises on a failed request or an answer without a tag."""
    from core.state import version_key
    req = Request(latest_url(repo), headers={
        "Accept": "application/vnd.github+json",
        "User-Agent": f"EDLD/{version}",
    })
    with opener(req, timeout=TIMEOUT) as resp:
        status = getattr(resp, "status", 200)
        if status != 200:
            raise OSError(f"HTTP {status}")
        tag = str(json.loads(resp.read()).get("tag_name") or "").lstrip("v").strip()
    if not tag:
        raise ValueError("no tag_name in the answer")
    return tag if version_key(tag) > version_key(version) else None


class UpdateWatcher:
    """Checks for a newer release in the background; ``on_newer(tag)`` is
    called from the watcher's thread for each newer tag, once."""

    def __init__(self, repo: str, version: str, on_newer, opener=urlopen,
                 interval: float = INTERVAL, retry: float = RETRY) -> None:
        self.repo, self.version = repo, version
        self.on_newer, self.opener = on_newer, opener
        self.interval, self.retry = interval, retry
        self.announced: str = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def check_once(self) -> bool:
        """One check. True when GitHub answered."""
        from core import debug
        try:
            tag = newer_release(self.repo, self.version, self.opener)
        except Exception as e:
            debug.log(f"Update check failed: {type(e).__name__}: {e}", level="WARNING")
            return False
        if tag and tag != self.announced:
            self.announced = tag
            debug.info(f"Update available: v{tag} (running v{self.version})")
            try:
                self.on_newer(tag)
            except Exception as e:
                debug.exception("Update notice failed", e)
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            ok = self.check_once()
            if self._stop.wait(self.interval if ok else self.retry):
                break

    def start(self) -> None:
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, daemon=True,
                                            name="update-check")
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
