"""ctypes binding for ``enter_chat.dll`` (ABI 1.0.0+).

Looks in ``app/_06_party/enter_chat/bin`` (source tree) then the older
``analysis/enter_chat/bin``. x64 only; ``wchar_t`` is UTF-16. The DLL looks
``interception.dll`` up by name, so it is preloaded by full path before the
first call.
"""
from __future__ import annotations

import ctypes
import enum
import threading
from ctypes import wintypes
from pathlib import Path
from typing import Optional

_ENGINE = Path(__file__).resolve().parents[3]
_ENTER_CHAT_BINS = (
    _ENGINE / "app" / "_06_party" / "enter_chat" / "bin",
    _ENGINE / "analysis" / "enter_chat" / "bin",
)
_INTERCEPTION_FALLBACK = _ENGINE / "autologin" / "bot" / "win" / "interception.dll"

_LOAD_LOCK = threading.Lock()
_RESULT_MESSAGE_CHARS = 512


class EcStatus(enum.IntEnum):
    OK = 0
    ARGUMENT = 1
    PID = 2
    WINDOW = 3
    ELEVATION = 4
    INTERCEPTION = 5
    IME = 6
    FOCUS = 7
    TEXT = 8
    INTERNAL = 9


class EcFlag(enum.IntFlag):
    NONE = 0
    CLEAR_FIRST = 0x01
    OPEN_CHAT = 0x02
    NO_FOCUS = 0x04
    SENDINPUT_FALLBACK = 0x08
    DRY_RUN = 0x10
    NO_START_COMMIT = 0x20


class EcRequest(ctypes.Structure):
    _fields_ = [
        ("text", ctypes.c_wchar_p),
        ("pid", wintypes.DWORD),
        ("hwnd", wintypes.HWND),
        ("chars_per_second", ctypes.c_double),
        ("jitter_ms", ctypes.c_int),
        ("jamo_delay_ms", ctypes.c_int),
        ("press_enter", wintypes.BOOL),
        ("flags", wintypes.DWORD),
        ("focus_timeout_ms", wintypes.DWORD),
    ]


class EcResult(ctypes.Structure):
    _fields_ = [
        ("status", ctypes.c_int),
        ("os_error", wintypes.DWORD),
        ("pid", wintypes.DWORD),
        ("hwnd", wintypes.HWND),
        ("chars", ctypes.c_int),
        ("keys", ctypes.c_int),
        ("failed", ctypes.c_int),
        ("skipped", ctypes.c_int),
        ("enter_pressed", wintypes.BOOL),
        ("elapsed_ms", wintypes.DWORD),
        ("message", ctypes.c_wchar * _RESULT_MESSAGE_CHARS),
    ]


class EnterChatUnavailable(RuntimeError):
    """``enter_chat.dll`` could not be loaded."""


def _first_existing(name: str) -> Optional[Path]:
    for folder in _ENTER_CHAT_BINS:
        path = folder / name
        if path.is_file():
            return path
    return None


def default_dll_path() -> Path:
    return _first_existing("enter_chat.dll") or (_ENTER_CHAT_BINS[0] / "enter_chat.dll")


def default_interception_path() -> Path:
    bundled = _first_existing("interception.dll")
    return bundled if bundled is not None else _INTERCEPTION_FALLBACK


class EnterChatLibrary:
    """Lazy handle on ``enter_chat.dll``. ``ec_run`` serializes internally."""

    def __init__(
        self,
        dll_path: Optional[Path] = None,
        interception_path: Optional[Path] = None,
    ) -> None:
        self._dll_path = Path(dll_path or default_dll_path())
        self._interception_path = Path(interception_path or default_interception_path())
        self._lib = None
        self._interception = None

    @property
    def dll_path(self) -> Path:
        return self._dll_path

    @property
    def loaded(self) -> bool:
        return self._lib is not None

    def _load(self):
        if self._lib is not None:
            return self._lib
        with _LOAD_LOCK:
            if self._lib is not None:
                return self._lib
            if not self._dll_path.is_file():
                raise EnterChatUnavailable(f"enter_chat.dll not found: {self._dll_path}")
            if self._interception is None and self._interception_path.is_file():
                self._interception = ctypes.WinDLL(str(self._interception_path))
            lib = ctypes.CDLL(str(self._dll_path))
            lib.ec_run.argtypes = [ctypes.POINTER(EcRequest), ctypes.POINTER(EcResult)]
            lib.ec_run.restype = ctypes.c_int
            lib.ec_decompose_hangul.argtypes = [ctypes.c_wchar, ctypes.c_char_p, ctypes.c_int]
            lib.ec_decompose_hangul.restype = ctypes.c_int
            lib.ec_status_string.argtypes = [ctypes.c_int]
            lib.ec_status_string.restype = ctypes.c_wchar_p
            lib.ec_version.argtypes = []
            lib.ec_version.restype = ctypes.c_wchar_p
            lib.ec_is_elevated.argtypes = []
            lib.ec_is_elevated.restype = wintypes.BOOL
            if hasattr(lib, "ec_press_key"):
                lib.ec_press_key.argtypes = [
                    wintypes.DWORD,
                    wintypes.HWND,
                    ctypes.c_int,
                    ctypes.c_int,
                    ctypes.c_int,
                    wintypes.DWORD,
                    ctypes.POINTER(EcResult),
                ]
                lib.ec_press_key.restype = ctypes.c_int
            self._lib = lib
            return lib

    def run(self, request: EcRequest) -> EcResult:
        result = EcResult()
        self._load().ec_run(ctypes.byref(request), ctypes.byref(result))
        return result

    def press_key(
        self,
        *,
        hwnd: int,
        scancode: int,
        e0: bool = False,
        hold_ms: int = 40,
        focus_timeout_ms: int = 1500,
    ) -> EcResult:
        """One physical key through Interception (``ec_press_key``, ABI 1.1.0)."""
        lib = self._load()
        if not hasattr(lib, "ec_press_key"):
            raise EnterChatUnavailable(
                f"enter_chat.dll {self.version() or '?'} has no ec_press_key "
                f"(needs 1.1.0): {self._dll_path}"
            )
        result = EcResult()
        lib.ec_press_key(
            0, hwnd, int(scancode), int(bool(e0)), int(hold_ms), int(focus_timeout_ms),
            ctypes.byref(result),
        )
        return result

    def decompose_hangul(self, ch: str) -> str:
        """2-beolsik keys for one syllable (uppercase = Shift). ``""`` if not Hangul."""
        buf = ctypes.create_string_buffer(8)
        n = int(self._load().ec_decompose_hangul(ch, buf, len(buf)))
        return buf.raw[: max(n, 0)].decode("ascii")

    def status_string(self, status: int) -> str:
        return str(self._load().ec_status_string(int(status)) or "")

    def version(self) -> str:
        return str(self._load().ec_version() or "")

    def is_elevated(self) -> bool:
        return bool(self._load().ec_is_elevated())


__all__ = [
    "EcFlag",
    "EcRequest",
    "EcResult",
    "EcStatus",
    "EnterChatLibrary",
    "EnterChatUnavailable",
    "default_dll_path",
    "default_interception_path",
]
