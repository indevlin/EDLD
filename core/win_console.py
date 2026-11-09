"""Making standard output usable on Windows GUI builds.

*Redirected* — ``EDLD.exe --version > out.txt``, or a shell capturing the
output.

*Interactive* — the user runs the command in an existing console.
"""

from __future__ import annotations

import os
import sys

#: Passed to AttachConsole to mean "the console of my parent process".
ATTACH_PARENT_PROCESS = -1

#: GetStdHandle selectors.
STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE = -12

#: What GetStdHandle returns when there is no handle to give.
INVALID_HANDLE_VALUE = 2**64 - 1


def _is_usable(stream: object) -> bool:
    """Return whether ``stream`` can actually be written to."""
    if stream is None:
        return False
    fileno = getattr(stream, "fileno", None)
    if fileno is None:
        return False
    try:
        return fileno() >= 0
    except (OSError, ValueError):
        return False


def enable_console_output() -> bool:
    """Reconnect ``sys.stdout`` and ``sys.stderr`` on Windows.

    Returns ``True`` when both streams are usable afterwards. Never
    raises: failing to attach a console must not stop the command from
    running, since its exit code may be all the caller needs.
    """
    if sys.platform != "win32":
        return True

    if _is_usable(sys.stdout) and _is_usable(sys.stderr):
        return True

    try:
        import ctypes
        import msvcrt
    except ImportError:  # pragma: no cover - Windows only
        return False

    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        # Declared explicitly: a HANDLE is pointer-sized, and ctypes'
        # default int return type truncates it on 64-bit Windows.
        kernel32.GetStdHandle.argtypes = [ctypes.c_uint32]
        kernel32.GetStdHandle.restype = ctypes.c_void_p
        kernel32.AttachConsole.argtypes = [ctypes.c_uint32]
        kernel32.AttachConsole.restype = ctypes.c_bool

        def std_handle(selector: int) -> int | None:
            handle = kernel32.GetStdHandle(ctypes.c_uint32(selector & 0xFFFFFFFF))
            if not handle or handle == INVALID_HANDLE_VALUE:
                return None
            return handle

        handles = {
            "stdout": std_handle(STD_OUTPUT_HANDLE),
            "stderr": std_handle(STD_ERROR_HANDLE),
        }

        if handles["stdout"] is None and handles["stderr"] is None:
            kernel32.AttachConsole(ctypes.c_uint32(ATTACH_PARENT_PROCESS & 0xFFFFFFFF))
            handles = {
                "stdout": std_handle(STD_OUTPUT_HANDLE),
                "stderr": std_handle(STD_ERROR_HANDLE),
            }

        for name, handle in handles.items():
            if handle is None or _is_usable(getattr(sys, name, None)):
                continue
            descriptor = msvcrt.open_osfhandle(handle, os.O_WRONLY)
            stream = os.fdopen(
                descriptor,
                "w",
                buffering=1,
                encoding="utf-8",
                errors="replace",
                closefd=False,
            )
            setattr(sys, name, stream)
    except (OSError, ValueError, AttributeError):  # pragma: no cover
        return False

    return _is_usable(sys.stdout) and _is_usable(sys.stderr)


def ensure_console() -> bool:
    """Give a terminal interface a console to run in, on Windows.

    ``enable_console_output`` borrows the console the user launched from.

    Never raises.
    """
    if sys.platform != "win32":
        return True
    have_output = enable_console_output()
    if have_output and _is_usable(sys.stdin):
        return True
    try:
        import ctypes
    except ImportError:  # pragma: no cover - Windows only
        return False
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.GetConsoleWindow.restype = ctypes.c_void_p
        if not kernel32.GetConsoleWindow():
            if have_output:
                return True     # redirected to a file or pipe: leave it so
            if not kernel32.AllocConsole():
                return False
            have_output = False
        try:
            kernel32.SetConsoleOutputCP(65001)    # UTF-8, for the box drawing
        except Exception:
            pass
        streams = [(0, "stdin", open("CONIN$", "r", encoding="utf-8",
                                     errors="replace"))]
        if not have_output:
            # A console of our own: nothing was inherited to keep.
            streams += [(1, "stdout", open("CONOUT$", "w", buffering=1,
                                           encoding="utf-8", errors="replace")),
                        (2, "stderr", open("CONOUT$", "w", buffering=1,
                                           encoding="utf-8", errors="replace"))]
        for fd, name, stream in streams:
            try:
                os.dup2(stream.fileno(), fd)
            except OSError:
                pass
            setattr(sys, name, stream)
            setattr(sys, f"__{name}__", stream)
    except (OSError, ValueError, AttributeError):  # pragma: no cover
        return False
    return _is_usable(sys.stdout)


__all__ = [
    "ATTACH_PARENT_PROCESS",
    "ensure_console",
    "STD_ERROR_HANDLE",
    "STD_OUTPUT_HANDLE",
    "enable_console_output",
]
