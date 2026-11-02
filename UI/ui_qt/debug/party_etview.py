"""etview-style overlay canvas for the Party monitor.

Ports the core of etview_930.c:
  marker = circle + crosshair
  colors: self white, Monster red, Player yellow, Item green, NPC cyan,
          dead gray, bait brown, ATK orange
  AttackAction: orange line attacker→target + red X on target
  underlay: BitBlt of LC.exe client (same as etview capture())
"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Any, Optional

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPen
from PySide6.QtWidgets import QSizePolicy, QWidget


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
try:
    from win32_prototypes import bind_gdi32, bind_user32

    bind_user32(_user32)
    bind_gdi32(_gdi32)
except Exception:
    _user32.GetDC.restype = wintypes.HDC
    _user32.GetDC.argtypes = [wintypes.HWND]
    _user32.ReleaseDC.restype = ctypes.c_int
    _user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    _gdi32.CreateCompatibleDC.restype = wintypes.HDC
    _gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    _gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    _gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    _gdi32.SelectObject.restype = wintypes.HGDIOBJ
    _gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    _gdi32.DeleteObject.restype = wintypes.BOOL
    _gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    _gdi32.DeleteDC.restype = wintypes.BOOL
    _gdi32.DeleteDC.argtypes = [wintypes.HDC]
    _gdi32.BitBlt.restype = wintypes.BOOL
    _gdi32.BitBlt.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
    ]
    _gdi32.GetDIBits.restype = ctypes.c_int
    _gdi32.GetDIBits.argtypes = [
        wintypes.HDC, wintypes.HBITMAP, wintypes.UINT, wintypes.UINT,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT,
    ]


def capture_lc_client() -> Optional[QImage]:
    """BitBlt LC.exe client → QImage (etview capture()). None if unavailable."""
    try:
        from app._05_action.window_bounds import find_game_window, get_client_bounds
    except Exception:
        return None
    hwnd = int(find_game_window("LC.exe") or 0)
    if not hwnd:
        return None
    bounds = get_client_bounds(hwnd)
    if bounds is None or not getattr(bounds, "valid", False):
        return None
    w = int(bounds.width)
    h = int(bounds.height)
    if w < 2 or h < 2:
        return None
    hdc = _user32.GetDC(hwnd)
    if not hdc:
        return None
    mem = None
    bmp = None
    old = None
    try:
        mem = _gdi32.CreateCompatibleDC(hdc)
        bmp = _gdi32.CreateCompatibleBitmap(hdc, w, h) if mem else None
        if not mem or not bmp:
            return None
        old = _gdi32.SelectObject(mem, bmp)
        if not _gdi32.BitBlt(mem, 0, 0, w, h, hdc, 0, 0, 0x00CC0020):
            return None

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER)]

        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h  # top-down
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = 0
        buf = ctypes.create_string_buffer(w * h * 4)
        if _gdi32.GetDIBits(mem, bmp, 0, h, buf, ctypes.byref(bmi), 0) == 0:
            return None
        # Windows BGRA → QImage Format_RGB32 expects BGRA on little-endian.
        # copy() detaches from the temporary buffer before the DC is released.
        return QImage(buf, w, h, w * 4, QImage.Format.Format_RGB32).copy()
    finally:
        if mem and old:
            _gdi32.SelectObject(mem, old)
        if bmp:
            _gdi32.DeleteObject(bmp)
        if mem:
            _gdi32.DeleteDC(mem)
        _user32.ReleaseDC(hwnd, hdc)

# etview colOf()
_SELF = QColor(255, 255, 255)
_MONSTER = QColor(255, 40, 40)
_PLAYER = QColor(255, 220, 0)
_ITEM = QColor(40, 255, 40)
_NPC = QColor(0, 220, 220)
_DEAD = QColor(90, 90, 90)
_BAIT = QColor(120, 80, 40)
_ATK = QColor(255, 120, 0)
_ATK_X = QColor(255, 0, 0)
_LEADER_RING = QColor(0, 200, 80)
_LEADER_TGT = QColor(255, 80, 40)
_LABEL_SHADOW = QColor(0, 0, 0)


def _color_for(ent: dict[str, Any]) -> QColor:
    if ent.get("self"):
        return _SELF
    if ent.get("dead"):
        return _DEAD
    if ent.get("bait"):
        return _BAIT
    if ent.get("atk") and str(ent.get("class") or "") == "Player":
        return _ATK
    cls = str(ent.get("class") or "")
    if cls == "Monster" or cls == "SummonedMonster":
        return _MONSTER
    if cls == "Player":
        return _PLAYER
    if cls in ("Item", "ITEM", "ADENA"):
        return _ITEM
    if "NPC" in cls or cls == "InteractiveNPC":
        return _NPC
    return QColor(160, 160, 160)


def _fold(name: object) -> str:
    return "".join(str(name or "").split()).lower()


def _guid_key(value: object) -> Optional[int]:
    text = str(value or "").strip().lower()
    if text.startswith("0x"):
        text = text[2:]
    if not text or text == "0":
        return None
    try:
        return int(text, 16)
    except ValueError:
        return None


class PartyEtView(QWidget):
    """BitBlt-style frame + etview markers (party leader / ATK highlighted)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(320)
        self.setMinimumWidth(480)
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        self._bg: QImage | None = None
        self._entities: list[dict[str, Any]] = []
        self._attacks: list[dict[str, Any]] = []
        self._client_w = 800.0
        self._client_h = 600.0
        self._leader_name = ""
        self._leader_guid = ""
        self._target_guid = ""
        self._target_name = ""
        self._status = ""
        self._atk_log = ""

    def hasHeightForWidth(self) -> bool:  # noqa: N802
        return True

    def heightForWidth(self, width: int) -> int:  # noqa: N802
        w = max(1.0, float(width))
        return max(1, int(round(w * self._client_h / self._client_w)))

    def client_size(self) -> tuple[float, float]:
        return float(self._client_w), float(self._client_h)

    def has_background(self) -> bool:
        return self._bg is not None and not self._bg.isNull()

    def _set_client_size(self, client_w: float, client_h: float) -> None:
        cw = max(1.0, float(client_w or 800))
        ch = max(1.0, float(client_h or 600))
        if abs(cw - self._client_w) < 0.5 and abs(ch - self._client_h) < 0.5:
            return
        self._client_w = cw
        self._client_h = ch
        self.updateGeometry()

    def set_frame(
        self,
        *,
        entities: list[dict[str, Any]] | None = None,
        attacks: list[dict[str, Any]] | None = None,
        client_w: float = 800,
        client_h: float = 600,
        leader_name: str = "",
        leader_guid: str = "",
        target_name: str = "",
        target_guid: str = "",
        status: str = "",
        background: QImage | None = None,
    ) -> None:
        self._entities = list(entities or [])
        self._attacks = list(attacks or [])
        self._leader_name = str(leader_name or "")
        self._leader_guid = str(leader_guid or "")
        self._target_name = str(target_name or "")
        self._target_guid = str(target_guid or "")
        self._status = str(status or "")
        if background is not None and not background.isNull():
            self._bg = background
            # BitBlt is the truth for letterbox aspect (probe can disagree).
            self._set_client_size(background.width(), background.height())
        else:
            self._set_client_size(client_w, client_h)
        # Build ATK log line like etview: [ATK] name -> tgt
        log = ""
        for atk in self._attacks:
            an = str(atk.get("attacker_name") or "").strip()
            tn = str(atk.get("tgt_name") or "").strip()
            if an or tn:
                log = f"[ATK] {an or '?'} → {tn or '?'}"
                break
        if not log and self._target_name:
            log = f"[ATK] {self._leader_name or 'leader'} → {self._target_name}"
        self._atk_log = log
        self.update()

    def clear_background(self) -> None:
        self._bg = None
        self.update()

    def _map(self, sx: float, sy: float) -> tuple[float, float]:
        """Map game client pixels → widget pixels (letterboxed)."""
        w = float(self.width())
        h = float(self.height())
        scale = min(w / self._client_w, h / self._client_h)
        ox = (w - self._client_w * scale) * 0.5
        oy = (h - self._client_h * scale) * 0.5
        return ox + sx * scale, oy + sy * scale

    def _is_leader(self, ent: dict[str, Any]) -> bool:
        if self._leader_guid:
            a = _guid_key(ent.get("guid"))
            b = _guid_key(self._leader_guid)
            if a is not None and b is not None and a == b:
                return True
        want = _fold(self._leader_name)
        if want and _fold(ent.get("name")) == want:
            return str(ent.get("class") or "") == "Player"
        return False

    def _is_leader_target(self, ent: dict[str, Any]) -> bool:
        if self._target_guid:
            a = _guid_key(ent.get("guid"))
            b = _guid_key(self._target_guid)
            if a is not None and b is not None and a == b:
                return True
        want = _fold(self._target_name)
        if want and _fold(ent.get("name")) == want:
            cls = str(ent.get("class") or "")
            return cls in ("Monster", "SummonedMonster")
        return False

    def paintEvent(self, _event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillRect(self.rect(), QColor(17, 17, 17))

        # Optional game capture underlay (etview BitBlt).
        if self._bg is not None and not self._bg.isNull():
            w = float(self.width())
            h = float(self.height())
            scale = min(w / self._client_w, h / self._client_h)
            dw = self._client_w * scale
            dh = self._client_h * scale
            ox = (w - dw) * 0.5
            oy = (h - dh) * 0.5
            painter.drawImage(
                int(ox),
                int(oy),
                self._bg.scaled(
                    int(dw),
                    int(dh),
                    Qt.AspectRatioMode.IgnoreAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                ),
            )

        # Attack lines first (under markers), etview orange.
        for atk in self._attacks:
            ax, ay, tx, ty = atk.get("ax"), atk.get("ay"), atk.get("tx"), atk.get("ty")
            if None in (ax, ay, tx, ty):
                continue
            x0, y0 = self._map(float(ax), float(ay))
            x1, y1 = self._map(float(tx), float(ty))
            painter.setPen(QPen(_ATK, 2))
            painter.drawLine(QPointF(x0, y0), QPointF(x1, y1))
            self._draw_cross_x(painter, x1, y1, 7, _ATK_X)

        for ent in self._entities:
            x, y = self._map(float(ent["sx"]), float(ent["sy"]))
            colour = _color_for(ent)
            leader = self._is_leader(ent)
            tgt = self._is_leader_target(ent)
            if leader:
                painter.setPen(QPen(_LEADER_RING, 3))
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(x, y), 14, 14)
            if tgt:
                self._draw_cross_x(painter, x, y, 9, _LEADER_TGT)
            self._draw_marker(painter, x, y, colour)
            # Names only — no class labels (Monster / NPC / Player / …).
            name = str(ent.get("name") or "").strip()
            if leader and name:
                name = f"{name} [L]"
            elif tgt and name:
                name = f"{name} [ATK]"
            elif leader:
                name = "[L]"
            elif tgt:
                name = "[ATK]"
            if name:
                self._draw_label(painter, x, y - 18, name, colour)

        # HUD strip
        painter.setPen(QColor(220, 220, 220))
        font = QFont(painter.font())
        font.setPointSize(max(9, font.pointSize()))
        painter.setFont(font)
        hud = self._status or "etview"
        if self._atk_log:
            hud = f"{hud}   {self._atk_log}"
        painter.drawText(
            self.rect().adjusted(8, 6, -8, -8),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
            hud,
        )
        painter.end()

    @staticmethod
    def _draw_marker(painter: QPainter, x: float, y: float, colour: QColor) -> None:
        """etview marker(): circle r=8 + crosshair arms."""
        painter.setPen(QPen(colour, 2))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(x, y), 8, 8)
        painter.drawLine(QPointF(x - 6, y), QPointF(x + 6, y))
        painter.drawLine(QPointF(x, y - 6), QPointF(x, y + 6))

    @staticmethod
    def _draw_cross_x(
        painter: QPainter, x: float, y: float, length: int, colour: QColor
    ) -> None:
        painter.setPen(QPen(colour, 2))
        painter.drawLine(
            QPointF(x - length, y - length), QPointF(x + length, y + length)
        )
        painter.drawLine(
            QPointF(x - length, y + length), QPointF(x + length, y - length)
        )

    @staticmethod
    def _draw_label(
        painter: QPainter, x: float, y: float, text: str, colour: QColor
    ) -> None:
        if not text:
            return
        # Shadow like etview textOut (8-neighbor black).
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                if dx == 0 and dy == 0:
                    continue
                painter.setPen(_LABEL_SHADOW)
                painter.drawText(int(x + dx), int(y + dy), text)
        painter.setPen(colour)
        painter.drawText(int(x), int(y), text)


__all__ = ["PartyEtView", "capture_lc_client"]
