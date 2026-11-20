"""UIMessage probe via analysis LCAPI DLL ``dll/uimsg.dll``.

Standard Engine/analysis path (same ABI as party/partyhud):
  LoadLibrary → lcapi_configure → lcapi_run(sink) with count=1.

Source: ``analysis/probes/uimsg_1021.c`` + ``analysis/src/api/uimsg_api.c``
Design: ``analysis/docs/DESIGN_UIMESSAGE_BLOCK.md``
"""
from __future__ import annotations

import ctypes
import os
import re
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Optional

from session.paths import manmabot_root

UIMSG_CHECK_INTERVAL_S = 30.0

_DISCONNECT_PATTERNS = (
    "與伺服器連線中斷",
    "与服务器连线中断",
    "与服务器连接中断",
    "連線中斷",
    "连接中断",
    "서버와의 연결",
    "서버와 연결",
    "연결이 끊어",
    "접속이 끊어",
    "connection lost",
    "disconnected",
    "lost connection",
)

_POLICY_PATTERNS = (
    "운영자의 요청",
    "정책에 의해",
    "게임 접속이 종료",
    "이용이 중지",
    "운영 정책",
    "營運者",
    "營運政策",
    "因營運",
    "因运营",
    "遊戲連線已結束",
    "遊戲連接已結束",
    "終止連線",
    "終止連接",
    "policy",
    "administrator",
    "terminated by",
)

_LINE_RE = re.compile(r"^\s*\d+\s+UIMSG\t.*?\t(?P<text>.+)\s*$", re.M)
_STDOUT_TEXT_RE = re.compile(r'text="([^"]*)"')

_SINK = ctypes.CFUNCTYPE(
    ctypes.c_int,
    ctypes.c_void_p,
    ctypes.c_uint32,
    ctypes.c_char_p,
    ctypes.c_uint32,
)


class UiMsgKind(str, Enum):
    NONE = "none"
    DISCONNECT = "disconnect"
    POLICY_BLOCK = "policy_block"
    OTHER = "other"


@dataclass(frozen=True)
class UiMsgSample:
    kind: UiMsgKind
    text: str = ""
    detail: str = ""
    ok: bool = True


def _analysis_root() -> Path:
    return manmabot_root() / "analysis"


def uimsg_dll_path() -> Path:
    return _analysis_root() / "dll" / "uimsg.dll"


def registry_path() -> Path:
    return _analysis_root() / "registry" / "LC930_REGISTRY.txt"


def classify_uimsg_text(text: str) -> UiMsgKind:
    raw = (text or "").strip()
    if not raw:
        return UiMsgKind.NONE
    folded = raw.casefold()
    for p in _POLICY_PATTERNS:
        if p.casefold() in folded or p in raw:
            return UiMsgKind.POLICY_BLOCK
    for p in _DISCONNECT_PATTERNS:
        if p.casefold() in folded or p in raw:
            return UiMsgKind.DISCONNECT
    return UiMsgKind.OTHER


def extract_uimsg_text(blob: str) -> str:
    """Parse LCAPI sink / out-file text for the UTF-8 popup body."""
    if not blob:
        return ""
    text = ""
    for m in _LINE_RE.finditer(blob):
        text = m.group("text").strip()
    if text:
        return text
    for m in _STDOUT_TEXT_RE.finditer(blob):
        text = m.group(1).strip()
    return text


def read_uimsg_once() -> UiMsgSample:
    """One-shot LCAPI sample from ``uimsg.dll`` (count=1)."""
    dll = uimsg_dll_path()
    reg = registry_path()
    if not dll.is_file():
        return UiMsgSample(UiMsgKind.NONE, detail=f"uimsg.dll missing: {dll}", ok=False)
    if not reg.is_file():
        return UiMsgSample(UiMsgKind.NONE, detail=f"registry missing: {reg}", ok=False)

    os.environ["LCAPI_ROOT"] = str(_analysis_root())
    chunks: list[str] = []
    try:
        lib = ctypes.CDLL(str(dll))
        configure = lib.lcapi_configure
        configure.argtypes = [
            ctypes.c_char_p,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_uint32,
            ctypes.c_char_p,
        ]
        configure.restype = ctypes.c_int
        run = lib.lcapi_run
        run.argtypes = [_SINK, ctypes.c_void_p, ctypes.c_char_p, ctypes.c_uint32]
        run.restype = ctypes.c_int

        @_SINK
        def sink(_ctx, _seq, text, length):
            if text and length:
                raw = ctypes.string_at(text, int(length))
                chunks.append(raw.decode("utf-8", "replace"))
            return 0

        # Keep callback alive across the native call.
        held = sink  # noqa: F841
        err = ctypes.create_string_buffer(512)
        rc_cfg = int(configure(str(reg).encode("utf-8"), 0, 0, 1, None))
        if rc_cfg != 0:
            return UiMsgSample(
                UiMsgKind.NONE,
                detail=f"lcapi_configure rc={rc_cfg}",
                ok=False,
            )
        rc = int(run(sink, None, err, len(err)))
        if rc < 0:
            message = err.value.decode("utf-8", "replace") or f"lcapi_run rc={rc}"
            return UiMsgSample(UiMsgKind.NONE, detail=message, ok=False)
    except OSError as exc:
        return UiMsgSample(UiMsgKind.NONE, detail=f"uimsg dll load failed: {exc}", ok=False)
    except Exception as exc:
        return UiMsgSample(UiMsgKind.NONE, detail=f"uimsg dll error: {exc}", ok=False)

    blob = "\n".join(chunks)
    text = extract_uimsg_text(blob)
    kind = classify_uimsg_text(text)
    return UiMsgSample(kind=kind, text=text, detail="ok" if text else "empty", ok=True)


class UiMsgWatch:
    """Throttle UIMessage checks to once per interval (default 30s)."""

    def __init__(self, interval_s: float = UIMSG_CHECK_INTERVAL_S):
        self.interval_s = max(5.0, float(interval_s))
        self._next_at = 0.0
        self.last: Optional[UiMsgSample] = None

    def poll(self, *, force: bool = False) -> Optional[UiMsgSample]:
        now = time.monotonic()
        if not force and now < self._next_at:
            return None
        self._next_at = now + self.interval_s
        sample = read_uimsg_once()
        self.last = sample
        return sample
