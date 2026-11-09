"""core/keys.py — pressing the game's keys.

* **Linux**: a virtual keyboard made with the kernel's uinput, which every
  program — the game under Proton included, X11 or Wayland — reads like a
  real one. Needs write access to /dev/uinput: membership of the ``input``
  group with a udev rule, as docs/AUTOMATION.md explains.
* **Windows**: SendInput with hardware scan codes, which the game reads where
  it ignores virtual-key codes.
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import threading
import time

#: Game key name → (Linux evdev code, set-1 scan code, extended).
KEYS: dict[str, tuple[int, int, bool]] = {
    "Key_Escape": (1, 0x01, False), "Key_Minus": (12, 0x0C, False),
    "Key_Equals": (13, 0x0D, False), "Key_Backspace": (14, 0x0E, False),
    "Key_Tab": (15, 0x0F, False), "Key_LeftBracket": (26, 0x1A, False),
    "Key_RightBracket": (27, 0x1B, False), "Key_Enter": (28, 0x1C, False),
    "Key_LeftControl": (29, 0x1D, False), "Key_SemiColon": (39, 0x27, False),
    "Key_Apostrophe": (40, 0x28, False), "Key_Grave": (41, 0x29, False),
    "Key_LeftShift": (42, 0x2A, False), "Key_BackSlash": (43, 0x2B, False),
    "Key_Comma": (51, 0x33, False), "Key_Period": (52, 0x34, False),
    "Key_Slash": (53, 0x35, False), "Key_RightShift": (54, 0x36, False),
    "Key_Numpad_Multiply": (55, 0x37, False), "Key_LeftAlt": (56, 0x38, False),
    "Key_Space": (57, 0x39, False), "Key_CapsLock": (58, 0x3A, False),
    "Key_NumLock": (69, 0x45, False), "Key_ScrollLock": (70, 0x46, False),
    "Key_Numpad_7": (71, 0x47, False), "Key_Numpad_8": (72, 0x48, False),
    "Key_Numpad_9": (73, 0x49, False), "Key_Numpad_Subtract": (74, 0x4A, False),
    "Key_Numpad_4": (75, 0x4B, False), "Key_Numpad_5": (76, 0x4C, False),
    "Key_Numpad_6": (77, 0x4D, False), "Key_Numpad_Add": (78, 0x4E, False),
    "Key_Numpad_1": (79, 0x4F, False), "Key_Numpad_2": (80, 0x50, False),
    "Key_Numpad_3": (81, 0x51, False), "Key_Numpad_0": (82, 0x52, False),
    "Key_Numpad_Decimal": (83, 0x53, False), "Key_F11": (87, 0x57, False),
    "Key_F12": (88, 0x58, False), "Key_NumpadEnter": (96, 0x1C, True),
    "Key_RightControl": (97, 0x1D, True), "Key_Numpad_Divide": (98, 0x35, True),
    "Key_RightAlt": (100, 0x38, True), "Key_Home": (102, 0x47, True),
    "Key_UpArrow": (103, 0x48, True), "Key_PageUp": (104, 0x49, True),
    "Key_LeftArrow": (105, 0x4B, True), "Key_RightArrow": (106, 0x4D, True),
    "Key_End": (107, 0x4F, True), "Key_DownArrow": (108, 0x50, True),
    "Key_PageDown": (109, 0x51, True), "Key_Insert": (110, 0x52, True),
    "Key_Delete": (111, 0x53, True),
}
for _i, _c in enumerate("1234567890"):
    KEYS[f"Key_{_c}"] = (2 + _i, 0x02 + _i, False)
for _row, _start in (("QWERTYUIOP", 16), ("ASDFGHJKL", 30), ("ZXCVBNM", 44)):
    for _i, _c in enumerate(_row):
        KEYS[f"Key_{_c}"] = (_start + _i, _start + _i, False)
for _i in range(10):
    KEYS[f"Key_F{_i + 1}"] = (59 + _i, 0x3B + _i, False)

#: Characters for typing, on a US layout: (key, shifted).
_CHARS: dict[str, tuple[str, bool]] = {" ": ("Key_Space", False), "-": ("Key_Minus", False),
    "_": ("Key_Minus", True), "=": ("Key_Equals", False), "+": ("Key_Equals", True),
    ".": ("Key_Period", False), ",": ("Key_Comma", False), "'": ("Key_Apostrophe", False),
    '"': ("Key_Apostrophe", True), "/": ("Key_Slash", False), ";": ("Key_SemiColon", False),
    ":": ("Key_SemiColon", True), "(": ("Key_9", True), ")": ("Key_0", True),
    "&": ("Key_7", True), "!": ("Key_1", True), "#": ("Key_3", True),
    "[": ("Key_LeftBracket", False), "]": ("Key_RightBracket", False)}
for _c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
    _CHARS[_c] = (f"Key_{_c}", True)
    _CHARS[_c.lower()] = (f"Key_{_c}", False)
for _c in "0123456789":
    _CHARS[_c] = (f"Key_{_c}", False)

#: Game mouse button name → (Linux evdev code, Windows down flag, up flag,
#: XBUTTON number).
MOUSE: dict[str, tuple[int, int, int, int]] = {
    "Mouse_1": (0x110, 0x0002, 0x0004, 0),      # BTN_LEFT
    "Mouse_2": (0x111, 0x0008, 0x0010, 0),      # BTN_RIGHT
    "Mouse_3": (0x112, 0x0020, 0x0040, 0),      # BTN_MIDDLE
    "Mouse_4": (0x113, 0x0080, 0x0100, 1),      # BTN_SIDE, XBUTTON1
    "Mouse_5": (0x114, 0x0080, 0x0100, 2),      # BTN_EXTRA, XBUTTON2
}

#: Window titles the game runs under.
GAME_TITLES = ("Elite - Dangerous (CLIENT)", "Elite - Dangerous", "EliteDangerous64")


def typeable(text: str) -> bool:
    return all(c in _CHARS for c in text)


# ── Backends ──────────────────────────────────────────────────────────────────

class _UInput:
    """A virtual keyboard, or mouse, on Linux's /dev/uinput, without any
    library."""

    _UI_SET_EVBIT, _UI_SET_KEYBIT, _UI_SET_RELBIT = 0x40045564, 0x40045565, 0x40045566
    _UI_DEV_CREATE, _UI_DEV_DESTROY = 0x5501, 0x5502
    _EV_SYN, _EV_KEY, _EV_REL = 0, 1, 2

    def __init__(self, mouse: bool = False) -> None:
        import fcntl
        self._fcntl = fcntl
        self._fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(self._fd, self._UI_SET_EVBIT, self._EV_KEY)
        if mouse:
            for code, *_rest in MOUSE.values():
                fcntl.ioctl(self._fd, self._UI_SET_KEYBIT, code)
            # Relative motion is what makes a desktop take it for a mouse;
            # it never moves.
            fcntl.ioctl(self._fd, self._UI_SET_EVBIT, self._EV_REL)
            for rel in (0, 1):                     # REL_X, REL_Y
                fcntl.ioctl(self._fd, self._UI_SET_RELBIT, rel)
        else:
            for code, _sc, _ext in KEYS.values():
                fcntl.ioctl(self._fd, self._UI_SET_KEYBIT, code)
        name = b"EDLD virtual mouse" if mouse else b"EDLD virtual keyboard"
        # struct uinput_user_dev: name[80], input_id (4 × u16), ff_effects_max,
        # then the four 64-entry abs arrays, unused here.
        dev = struct.pack("80sHHHHi", name, 0x06, 0x1209, 0xED1E if mouse else 0xED1D, 1, 0)
        os.write(self._fd, dev + b"\0" * (4 * 64 * 4))
        fcntl.ioctl(self._fd, self._UI_DEV_CREATE)
        # The desktop needs a moment to notice a new device.
        time.sleep(0.5)

    def _emit(self, code: int, down: bool) -> None:
        now = time.time()
        sec, usec = int(now), int((now % 1) * 1e6)
        os.write(self._fd, struct.pack("llHHi", sec, usec, self._EV_KEY, code, 1 if down else 0))
        os.write(self._fd, struct.pack("llHHi", sec, usec, self._EV_SYN, 0, 0))

    def key(self, name: str, down: bool) -> None:
        self._emit(KEYS[name][0], down)

    def button(self, name: str, down: bool) -> None:
        self._emit(MOUSE[name][0], down)

    def close(self) -> None:
        try:
            self._fcntl.ioctl(self._fd, self._UI_DEV_DESTROY)
        finally:
            os.close(self._fd)


class _SendInput:
    """Hardware scan codes through Windows' SendInput."""

    def __init__(self) -> None:
        import ctypes
        from ctypes import wintypes
        self._ct = ctypes
        ULONG_PTR = ctypes.c_size_t

        class KEYBDINPUT(ctypes.Structure):
            _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD),
                        ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD),
                        ("dwExtraInfo", ULONG_PTR)]

        class MOUSEINPUT(ctypes.Structure):
            _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG),
                        ("mouseData", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
                        ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

        class _U(ctypes.Union):
            _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

        class INPUT(ctypes.Structure):
            _fields_ = [("type", wintypes.DWORD), ("u", _U)]

        self._INPUT, self._KEYBDINPUT, self._MOUSEINPUT = INPUT, KEYBDINPUT, MOUSEINPUT
        self._send = ctypes.windll.user32.SendInput

    def key(self, name: str, down: bool) -> None:
        _code, sc, ext = KEYS[name]
        flags = 0x0008 | (0 if down else 0x0002) | (0x0001 if ext else 0)
        inp = self._INPUT(type=1)
        inp.u.ki = self._KEYBDINPUT(0, sc, flags, 0, 0)
        self._send(1, self._ct.byref(inp), self._ct.sizeof(inp))

    def button(self, name: str, down: bool) -> None:
        _code, down_flag, up_flag, xbutton = MOUSE[name]
        inp = self._INPUT(type=0)
        inp.u.mi = self._MOUSEINPUT(0, 0, xbutton, down_flag if down else up_flag, 0, 0)
        self._send(1, self._ct.byref(inp), self._ct.sizeof(inp))

    def close(self) -> None:
        pass


# ── Focus ─────────────────────────────────────────────────────────────────────

def _active_title() -> str | None:
    """The focused window's title, or None when it cannot be told."""
    if sys.platform == "win32":
        try:
            import ctypes
            u32 = ctypes.windll.user32
            hwnd = u32.GetForegroundWindow()
            n = u32.GetWindowTextLengthW(hwnd)
            buf = ctypes.create_unicode_buffer(n + 1)
            u32.GetWindowTextW(hwnd, buf, n + 1)
            return buf.value
        except Exception:
            return None
    if not os.environ.get("DISPLAY"):
        return None
    for cmd in (["xdotool", "getactivewindow", "getwindowname"],):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
            if out.returncode == 0:
                return out.stdout.strip()
        except (OSError, subprocess.SubprocessError):
            pass
    try:
        root = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"],
                              capture_output=True, text=True, timeout=2).stdout
        wid = root.strip().split()[-1]
        name = subprocess.run(["xprop", "-id", wid, "_NET_WM_NAME", "WM_NAME"],
                              capture_output=True, text=True, timeout=2).stdout
        for line in name.splitlines():
            if "=" in line:
                return line.split("=", 1)[1].strip().strip('"')
    except (OSError, subprocess.SubprocessError, IndexError):
        pass
    return None


def game_focused(assume: bool = False) -> tuple[bool, str]:
    """(True, "") when the game's window has the focus. ``assume`` stands in
    for a desktop that cannot say (Wayland without X)."""
    title = _active_title()
    if title is None:
        return (True, "") if assume else (False, "cannot tell which window has the focus")
    if any(t.lower() in title.lower() for t in GAME_TITLES):
        return True, ""
    return False, f"the game is not the focused window ({title or 'none'})"


# ── Bringing the game to the front ────────────────────────────────────────────

def _activate_win32() -> str:
    """Bring the game's window to the front on Windows; "" when asked, or why
    it could not be."""
    import ctypes
    from ctypes import wintypes
    u32 = ctypes.windll.user32
    titles: dict[int, str] = {}

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _each(hwnd, _lparam):
        if u32.IsWindowVisible(hwnd):
            n = u32.GetWindowTextLengthW(hwnd)
            if n:
                buf = ctypes.create_unicode_buffer(n + 1)
                u32.GetWindowTextW(hwnd, buf, n + 1)
                titles[hwnd] = buf.value
        return True

    u32.EnumWindows(_each, 0)
    hwnd = next((h for t in GAME_TITLES for h, title in titles.items()
                 if title.lower().startswith(t.lower())), None)
    if hwnd is None:
        return "the game's window was not found"
    if u32.IsIconic(hwnd):
        u32.ShowWindow(hwnd, 9)                         # SW_RESTORE
    if not u32.SetForegroundWindow(hwnd):
        # Windows hands the foreground only to the program that had the
        # last input; a tap of Alt is that input.
        u32.keybd_event(0x12, 0, 0, 0)
        u32.keybd_event(0x12, 0, 2, 0)                  # KEYEVENTF_KEYUP
        if not u32.SetForegroundWindow(hwnd):
            return "Windows would not bring the game to the front"
    return ""


def _activate_x11() -> str:
    """The same on an X11 desktop (or XWayland), with xdotool or wmctrl."""
    for title in GAME_TITLES:
        pattern = "^" + title.replace("(", "\\(").replace(")", "\\)")
        try:
            out = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", pattern],
                                 capture_output=True, text=True, timeout=3)
        except FileNotFoundError:
            break
        except (OSError, subprocess.SubprocessError):
            continue
        ids = out.stdout.split()
        if ids:
            try:
                subprocess.run(["xdotool", "windowactivate", "--sync", ids[0]],
                               capture_output=True, timeout=3)
                return ""
            except (OSError, subprocess.SubprocessError):
                return "xdotool could not bring the game to the front"
    for title in GAME_TITLES:
        try:
            out = subprocess.run(["wmctrl", "-a", title], capture_output=True, timeout=3)
        except FileNotFoundError:
            return "bringing the game to the front needs xdotool or wmctrl"
        except (OSError, subprocess.SubprocessError):
            continue
        if out.returncode == 0:
            return ""
    return "the game's window was not found"


def focus_game(timeout: float = 1.5) -> tuple[bool, str]:
    """Bring the game's window to the front, for a key pressed from EDLD's own
    window — which has the focus the moment its button is clicked.

    (True, "") once the game has the focus.
    """
    title = _active_title()
    if title is None:
        return False, ("this desktop cannot say which window has the focus, so EDLD "
                       "does not press keys from its own window; EDAM can")
    if any(t.lower() in title.lower() for t in GAME_TITLES):
        return True, ""
    if sys.platform == "win32":
        why = _activate_win32()
    elif os.environ.get("DISPLAY"):
        why = _activate_x11()
    else:
        why = "this desktop cannot bring the game to the front"
    if why:
        return False, why
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        title = _active_title() or ""
        if any(t.lower() in title.lower() for t in GAME_TITLES):
            # The game takes keys a moment after it takes the focus.
            time.sleep(0.25)
            return True, ""
        time.sleep(0.1)
    return False, "the game did not come to the front"


def _pointer_over_active() -> bool | None:
    """Whether the pointer is over the focused window, or None when it
    cannot be told."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes
            u32 = ctypes.windll.user32
            u32.WindowFromPoint.argtypes = [wintypes.POINT]
            u32.WindowFromPoint.restype = wintypes.HWND
            u32.GetAncestor.restype = wintypes.HWND
            pt = wintypes.POINT()
            if not u32.GetCursorPos(ctypes.byref(pt)):
                return None
            under = u32.GetAncestor(u32.WindowFromPoint(pt), 2)      # GA_ROOT
            return bool(under) and under == u32.GetAncestor(u32.GetForegroundWindow(), 2)
        except Exception:
            return None
    if not os.environ.get("DISPLAY"):
        return None

    def _shell(cmd: list[str]) -> dict | None:
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
        except (OSError, subprocess.SubprocessError):
            return None
        if out.returncode != 0:
            return None
        vals = dict(line.split("=", 1) for line in out.stdout.splitlines() if "=" in line)
        try:
            return {k: int(v) for k, v in vals.items() if k in ("X", "Y", "WIDTH", "HEIGHT")}
        except ValueError:
            return None
    ptr = _shell(["xdotool", "getmouselocation", "--shell"])
    win = _shell(["xdotool", "getactivewindow", "getwindowgeometry", "--shell"])
    if not ptr or not win or not {"X", "Y"} <= ptr.keys() \
            or not {"X", "Y", "WIDTH", "HEIGHT"} <= win.keys():
        return None
    return (win["X"] <= ptr["X"] < win["X"] + win["WIDTH"]
            and win["Y"] <= ptr["Y"] < win["Y"] + win["HEIGHT"])


def pointer_in_game(assume: bool = False) -> tuple[bool, str]:
    """(True, "") when a mouse button pressed now would reach the game: it
    has the focus and the pointer is over it. ``assume`` stands in for a
    desktop that cannot say, as for the focus."""
    ok, why = game_focused(assume)
    if not ok:
        return ok, why
    over = _pointer_over_active()
    if over is None:
        return (True, "") if assume else (False, "cannot tell where the mouse pointer is")
    return (True, "") if over else (False, "the mouse pointer is not over the game's window")


# ── Keyboard ──────────────────────────────────────────────────────────────────

class Keyboard:
    """Presses keys, and mouse buttons, through whichever backend this
    platform has; one at a time, from any thread."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._dev = None
        self._mouse = None
        self._error = ""

    def available(self) -> tuple[bool, str]:
        with self._lock:
            return self._open()

    def _open(self) -> tuple[bool, str]:
        if self._dev is not None:
            return True, ""
        try:
            if sys.platform == "win32":
                self._dev = _SendInput()
            elif sys.platform.startswith("linux"):
                self._dev = _UInput()
            else:
                self._error = "pressing keys is supported on Linux and Windows"
                return False, self._error
        except PermissionError:
            self._error = ("no permission to use /dev/uinput — see "
                           "docs/AUTOMATION.md for the one-time setup")
            return False, self._error
        except Exception as exc:
            self._error = f"cannot press keys: {type(exc).__name__}: {exc}"
            return False, self._error
        return True, ""

    def _open_mouse(self):
        """The device mouse buttons go through: SendInput's own on Windows,
        a virtual mouse made the first time one is needed on Linux."""
        if self._mouse is None:
            self._mouse = self._dev if sys.platform == "win32" else _UInput(mouse=True)
        return self._mouse

    def press(self, key: str, modifiers=(), hold: float = 0.06) -> bool:
        """Press ``key`` — a key or a mouse button — with ``modifiers`` (keys)
        held, for ``hold`` seconds."""
        if (key not in KEYS and key not in MOUSE) or any(m not in KEYS for m in modifiers):
            return False
        with self._lock:
            ok, _ = self._open()
            if not ok:
                return False
            try:
                if key in MOUSE:
                    try:
                        dev = self._open_mouse()
                    except PermissionError:
                        self._error = ("no permission to use /dev/uinput — see "
                                       "docs/AUTOMATION.md for the one-time setup")
                        return False
                    down = lambda d: dev.button(key, d)     # noqa: E731
                else:
                    down = lambda d: self._dev.key(key, d)  # noqa: E731
                for m in modifiers:
                    self._dev.key(m, True)
                    time.sleep(0.02)
                down(True)
                time.sleep(max(hold, 0.03))
                down(False)
                for m in reversed(list(modifiers)):
                    time.sleep(0.02)
                    self._dev.key(m, False)
            except OSError:
                return False
        time.sleep(0.05)
        return True

    def type_text(self, text: str, gap: float = 0.04) -> bool:
        if not typeable(text):
            return False
        for c in text:
            key, shifted = _CHARS[c]
            if not self.press(key, ("Key_LeftShift",) if shifted else (), hold=0.03):
                return False
            time.sleep(gap)
        return True

    def close(self) -> None:
        with self._lock:
            for dev in {id(d): d for d in (self._mouse, self._dev) if d is not None}.values():
                try:
                    dev.close()
                except Exception:
                    pass
            self._dev = self._mouse = None


_KEYBOARD: Keyboard | None = None


def keyboard() -> Keyboard:
    global _KEYBOARD
    if _KEYBOARD is None:
        _KEYBOARD = Keyboard()
    return _KEYBOARD
