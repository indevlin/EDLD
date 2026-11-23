"""One publisher per computer: an OS file lock in the config directory, held while publishing."""
import os
import sys
from pathlib import Path

from . import paths


class PublisherLock:
    def __init__(self, path: Path | None = None):
        self.path = path or paths.config_dir() / 'publisher.lock'
        self.fd: int | None = None

    def acquire(self) -> bool:
        if self.fd is not None:
            return True
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            os.close(fd)
            return False
        self.fd = fd
        return True

    def release(self) -> None:
        if self.fd is None:
            return
        try:
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(self.fd, msvcrt.LK_UNLCK, 1)
        finally:
            os.close(self.fd)
            self.fd = None
