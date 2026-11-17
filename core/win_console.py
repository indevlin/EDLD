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

#: CreateToolhelp32Snapshot selector for the process list.
TH32CS_SNAPPROCESS = 0x2

#: MessageBoxW style: OK button, error icon, topmost.
MB_ICONERROR_TOPMOST = 0x0 | 0x10 | 0x40000

#: Set when ensure_console() made a console of its own, which closes with the
#: process: an error printed into it needs a pause to be read.
_own_console = False

#: Whether printed output reaches anyone, as last found by
#: enable_console_output() or ensure_console().
_output_visible: bool | None = None

#: Cleared by startup_complete(): past that point an uncaught exception is the
#: interface's to report, not a dialog's.
_starting = True

#: Cleared by no_dialogs(): a service has no one to dismiss a dialog.
_dialogs = True


def attach_target(my_pid: int, my_exe: str, procs: dict[int, tuple[int, str]]) -> int | None:
    """The pid whose console to borrow when the parent has none.

    ``procs`` maps pid to (parent pid, exe name). A one-file build runs as a
    child of its own bootloader, which is windowed and has no console: the
    console belongs to the bootloader's parent.
    """
    me = procs.get(my_pid)
    if me is None:
        return None
    parent = procs.get(me[0])
    if parent is None or parent[1].lower() != my_exe.lower():
        return None
    return parent[0] or None


def _process_table(kernel32) -> dict[int, tuple[int, str]]:
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    kernel32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    kernel32.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel32.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32FirstW.restype = wintypes.BOOL
    kernel32.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(PROCESSENTRY32W)]
    kernel32.Process32NextW.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [ctypes.c_void_p]

    snap = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID_HANDLE_VALUE:
        return {}
    table: dict[int, tuple[int, str]] = {}
    try:
        entry = PROCESSENTRY32W()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        ok = kernel32.Process32FirstW(snap, ctypes.byref(entry))
        while ok:
            table[entry.th32ProcessID] = (entry.th32ParentProcessID, entry.szExeFile)
            ok = kernel32.Process32NextW(snap, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snap)
    return table


def _attach_console(kernel32) -> bool:
    """Attach to the parent's console, or the grandparent's past a bootloader."""
    if kernel32.AttachConsole(ctypes_u32(ATTACH_PARENT_PROCESS)):
        return True
    try:
        target = attach_target(os.getpid(),
                               os.path.basename(sys.executable),
                               _process_table(kernel32))
    except (OSError, ValueError, AttributeError):
        return False
    if target is None:
        return False
    return bool(kernel32.AttachConsole(ctypes_u32(target)))


def ctypes_u32(value: int):
    import ctypes
    return ctypes.c_uint32(value & 0xFFFFFFFF)


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
    global _output_visible
    if sys.platform != "win32":
        return True

    if _is_usable(sys.stdout) and _is_usable(sys.stderr):
        _output_visible = True
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

        attached = False
        if handles["stdout"] is None and handles["stderr"] is None:
            attached = _attach_console(kernel32)
            handles = {
                "stdout": std_handle(STD_OUTPUT_HANDLE),
                "stderr": std_handle(STD_ERROR_HANDLE),
            }
            if attached and handles["stdout"] is None:
                for name in ("stdout", "stderr"):
                    if not _is_usable(getattr(sys, name, None)):
                        setattr(sys, name, open("CONOUT$", "w", buffering=1,
                                                encoding="utf-8", errors="replace"))

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
        _output_visible = False
        return False

    _output_visible = _is_usable(sys.stdout) and _is_usable(sys.stderr)
    return _output_visible


def ensure_console() -> bool:
    """Give a terminal interface a console to run in, on Windows.

    ``enable_console_output`` borrows the console the user launched from.

    Never raises.
    """
    global _own_console, _output_visible
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
            _own_console = True
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
    _output_visible = _is_usable(sys.stdout)
    return _output_visible


def hold_own_console() -> bool:
    """Wait for Enter before a console of EDLD's own closes with the process.

    Returns whether it waited. Never raises.
    """
    if sys.platform != "win32" or not _own_console:
        return False
    try:
        if not _is_usable(sys.stdin):
            return False
        sys.stdout.write("\nPress Enter to close this window.")
        sys.stdout.flush()
        sys.stdin.readline()
        return True
    except Exception:
        return False


def startup_error(message: str, title: str = "EDLD could not start") -> bool:
    """Make a fatal startup message seen on Windows.

    Printed output already reaches a console or a redirect; this covers the
    two cases where it does not: a windowed launch with no console, which
    gets a dialog, and a console of EDLD's own, which closes on exit unless
    held open. Returns whether a dialog was shown. Never raises; a no-op
    elsewhere.
    """
    if sys.platform != "win32":
        return False
    if hold_own_console():
        return False
    try:
        visible = _output_visible
        if visible is None:
            visible = _is_usable(sys.__stdout__) or _is_usable(sys.stdout)
        if visible or not _dialogs:
            return False
        import ctypes
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        user32.MessageBoxW.argtypes = [ctypes.c_void_p, ctypes.c_wchar_p,
                                       ctypes.c_wchar_p, ctypes.c_uint]
        user32.MessageBoxW(None, _plain(message)[-3000:], title, MB_ICONERROR_TOPMOST)
        return True
    except Exception:
        return False


def _plain(text: str) -> str:
    """``text`` without terminal color codes."""
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", str(text)).strip()


def install_startup_hook() -> None:
    """Show an uncaught startup exception that would otherwise vanish."""
    if sys.platform != "win32":
        return
    prior = sys.excepthook

    def _hook(exc_type, exc_value, exc_tb):
        try:
            prior(exc_type, exc_value, exc_tb)
        except Exception:
            pass
        if not _starting or issubclass(exc_type, KeyboardInterrupt):
            return
        import traceback
        shown = startup_error("".join(traceback.format_exception(exc_type, exc_value, exc_tb)))
        if shown and getattr(sys, "frozen", False):
            os._exit(1)     # the bootloader would show a second, emptier dialog

    sys.excepthook = _hook


def no_dialogs() -> None:
    """Never show startup_error() as a dialog."""
    global _dialogs
    _dialogs = False


def startup_complete() -> None:
    """Stop install_startup_hook() reporting: the interface is up."""
    global _starting
    _starting = False


__all__ = [
    "ATTACH_PARENT_PROCESS",
    "attach_target",
    "ensure_console",
    "hold_own_console",
    "install_startup_hook",
    "no_dialogs",
    "startup_complete",
    "startup_error",
    "STD_ERROR_HANDLE",
    "STD_OUTPUT_HANDLE",
    "enable_console_output",
]
