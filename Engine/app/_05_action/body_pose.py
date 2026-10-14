"""Live body action at ActionComponent+0xC0, and the command at +0x58.

Standing is BreathAction (0x11E02F8). A failed read is None, not standing.
HP/MP come from the status HUD (char_offsets ST_*), with the encoded
CharacterData status used when that decode succeeds.
"""
from __future__ import annotations

import ctypes
import struct
import time
from ctypes import wintypes
from pathlib import Path

BREATH_VFT = 0x11E02F8
MOVE_VFTS = frozenset({0x11E0590, 0x11E0548})  # MovingAction, MovingBackAction
BODY = {
    0x11E02F8: "stand",
    0x11E0590: "walk",
    0x11E04A8: "attack",
    0x11E04F0: "actionbase",
    0x11E0220: "turn",
    0x11E0190: "default",
    0x11E03D0: "spell",
    0x11E0340: "death",
    0x11E0418: "damaged",
    0x11E01D8: "shop",
    0x11E0548: "walkback",
    0x11E02B0: "effect",
    0x11E0148: "fixedframe",
    0x11E0388: "npcstate",
    0x11E0268: "zapwand",
}
CMD = {
    0x11E0830: "move",
    0x11E09B0: "attack",
    0x11E0868: "interact",
}

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_handle = None
_pid = 0
_base = 0
_size = 0
_me = 0


class _PROCESSENTRY32W(ctypes.Structure):
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
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def label(table: dict[int, str], rva: int) -> str:
    if not rva:
        return "none"
    return table.get(rva, "vft_%X" % rva)


def _heap(addr: int) -> bool:
    return 0x10000000000 <= addr < 0x80000000000


def _read(pid: int, addr: int, size: int) -> bytes | None:
    if _handle is None:
        return None
    buf = ctypes.create_string_buffer(size)
    req = struct.pack("<IIQQQ", pid, 0, addr, ctypes.addressof(buf), size)
    br = wintypes.DWORD()
    ok = _k32.DeviceIoControl(
        _handle, 0x222060, req, len(req), req, len(req), ctypes.byref(br), None
    )
    return buf.raw if ok else None


def _q(pid: int, addr: int) -> int:
    blob = _read(pid, addr, 8)
    return struct.unpack("<Q", blob)[0] if blob else 0


def _d(pid: int, addr: int) -> int:
    blob = _read(pid, addr, 4)
    return struct.unpack("<I", blob)[0] if blob else 0


def _vrva(obj: int) -> int:
    value = _q(_pid, obj)
    if _base <= value < _base + _size:
        return value - _base
    return 0


def _find_pid() -> int:
    snap = _k32.CreateToolhelp32Snapshot(0x2, 0)
    if snap in (ctypes.c_void_p(-1).value, -1, None, 0):
        return 0
    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
    pid = 0
    if _k32.Process32FirstW(snap, ctypes.byref(entry)):
        while True:
            if entry.szExeFile.lower() == "lc.exe":
                pid = int(entry.th32ProcessID)
                break
            if not _k32.Process32NextW(snap, ctypes.byref(entry)):
                break
    _k32.CloseHandle(snap)
    return pid


def _module_base(pid: int) -> tuple[int, int]:
    peb_in = struct.pack("<IIQ", pid, 0, 0)
    out = ctypes.create_string_buffer(peb_in)
    br = wintypes.DWORD()
    ok = _k32.DeviceIoControl(
        _handle, 0x22204C, peb_in, len(peb_in), out, len(peb_in), ctypes.byref(br), None
    )
    if not ok:
        return 0, 0
    peb = struct.unpack_from("<Q", out.raw, 8)[0]
    ldr = _q(pid, peb + 0x18)
    head = _q(pid, ldr + 0x20)
    cur = head
    for _ in range(8):
        entity = cur - 0x10
        base = _q(pid, entity + 0x30)
        size = _d(pid, entity + 0x40)
        if base and size:
            return base, size
        cur = _q(pid, cur)
        if not cur or cur == head:
            break
    return 0, 0


def _find_my_player() -> int:
    mgr = _q(_pid, _base + 0x16DEE80)
    if not _heap(mgr):
        return 0
    holder = _q(_pid, mgr + 0xD0)
    if not _heap(holder):
        return 0
    beg = _q(_pid, holder + 0x180)
    end = _q(_pid, holder + 0x188)
    if not _heap(beg) or end <= beg:
        return 0
    actor = 0
    count = min(64, (end - beg) // 16)
    for index in range(count):
        sub = _q(_pid, beg + index * 16)
        if _heap(sub) and _vrva(sub) == 0x11DE3B8:
            actor = sub
            break
    if not actor:
        return 0
    vb = _q(_pid, actor + 0x8A8)
    ve = _q(_pid, actor + 0x8B0)
    if _heap(vb) and ve > vb and (ve - vb) < 0x200000:
        for index in range(min(8000, (ve - vb) // 16)):
            ent = _q(_pid, vb + index * 16)
            if _heap(ent) and _vrva(ent) == 0x11E12A8:
                return ent
    for head in (0x798, 0x7D8):
        sent = _q(_pid, actor + head + 8)
        if not _heap(sent):
            continue
        cur = _q(_pid, sent + 0x08)
        guard = 0
        while _heap(cur) and cur != sent and guard < 4000:
            guard += 1
            b = _q(_pid, cur + 0x18)
            e = _q(_pid, cur + 0x20)
            if _heap(b) and _heap(e) and e >= b:
                for index in range(min(5000, (e - b) // 8)):
                    ent = _q(_pid, b + index * 8)
                    if _heap(ent) and _vrva(ent) == 0x11E12A8:
                        return ent
            cur = _q(_pid, cur + 0x08)
    return 0


def _ensure() -> bool:
    global _handle, _pid, _base, _size, _me
    if _handle not in (None, 0, -1, ctypes.c_void_p(-1).value):
        return True
    pid = _find_pid()
    handle = _k32.CreateFileW(
        "\\\\.\\WinNotify", 0x80000000 | 0x40000000, 0, None, 3, 0, None
    )
    if not pid or handle in (None, 0, -1, ctypes.c_void_p(-1).value):
        return False
    _handle = handle
    _pid = pid
    _base, _size = _module_base(pid)
    _me = 0
    return bool(_base and _size)


def read_action() -> tuple[int | None, int | None]:
    """(body vft, command vft). None means that slot could not be read."""
    global _me
    if not _ensure():
        return None, None
    if not _me or _vrva(_me) != 0x11E12A8:
        _me = _find_my_player()
    if not _me:
        return None, None
    table = _q(_pid, _me + 0x20)
    if not _heap(table):
        return None, None
    ac = _q(_pid, table + 16)
    ctl = _q(_pid, table + 0x90)
    if not _heap(ac):
        return None, None
    act = _q(_pid, ac + 0xC0)
    body = _vrva(act) if _heap(act) else None
    if body is None:
        return None, None
    cmd = 0
    if _heap(ctl):
        command = _q(_pid, ctl + 0x58)
        cmd = _vrva(command) if _heap(command) else 0
    return body, cmd


def body_is_moving() -> bool | None:
    """True when the body is MovingAction or MovingBackAction.

    None when the action slot could not be read.
    """
    body, _cmd = read_action()
    if body is None:
        return None
    return body in MOVE_VFTS


def body_is_standing() -> bool | None:
    """True when the body is BreathAction. None when the read fails."""
    body, _cmd = read_action()
    if body is None:
        return None
    return body == BREATH_VFT


# HUD block + encoded status. char_offsets.txt overrides these defaults.
_HUD = {
    "ST_BLOCK": 0x16DED20,
    "ST_HP": 0x1C,
    "ST_MAXHP": 0x20,
    "ST_MP": 0x24,
    "ST_MAXMP": 0x28,
    "MGR": 0x16DEE80,
    "CD_VFT": 0x11E4F38,
    "CD_OFF": 0x498,
    "VFT_STATUS": 0x11E4F08,
    "K_XOR": 0x2F8B1064,
    "K_MUL": 0x7F4A7C15,
    "HOLDER_OFF": 0xD0,
    "SUBLIST_BEG": 0x180,
    "SUBLIST_END": 0x188,
    "HP": 0x2B8,
    "MP": 0x2D0,
    "MAXMP": 0x2DC,
}
_hud_ready = False
_status_addr = 0
_status_checked = 0.0
_ANALYSIS = Path(__file__).resolve().parents[2] / "analysis"


def _u32(value: int) -> int:
    return value & 0xFFFFFFFF


def _load_hud() -> None:
    global _hud_ready
    if _hud_ready:
        return
    table = _ANALYSIS / "char_offsets.txt"
    if table.is_file():
        for line in table.read_text(encoding="utf-8", errors="replace").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, raw = text.split("=", 1)
            key = key.strip()
            if key not in _HUD:
                continue
            try:
                _HUD[key] = int(raw.strip(), 0)
            except ValueError:
                continue
    _hud_ready = True


def _decode(obj: int, off: int) -> int | None:
    blob = _read(_pid, obj + off, 12)
    if not blob:
        return None
    key, mid, check = struct.unpack("<3I", blob)
    mixed = _u32(mid ^ key)
    expect = _u32(_u32(key + _HUD["K_XOR"]) ^ _u32(~mixed))
    if check != expect:
        return None
    return _u32(mixed - _u32(_u32(key * _HUD["K_MUL"]) ^ _HUD["K_XOR"]))


def _find_status() -> int:
    """CharacterData status object. Cached while its vft still matches."""
    global _status_addr, _status_checked
    now = time.monotonic()
    if (
        _status_addr
        and now - _status_checked < 1.0
        and _vrva(_status_addr) == _HUD["VFT_STATUS"]
    ):
        return _status_addr
    _status_checked = now
    _status_addr = 0
    mgr = _q(_pid, _base + _HUD["MGR"])
    if not _heap(mgr):
        return 0
    holder = _q(_pid, mgr + _HUD["HOLDER_OFF"])
    if not _heap(holder):
        return 0
    begin = _q(_pid, holder + _HUD["SUBLIST_BEG"])
    end = _q(_pid, holder + _HUD["SUBLIST_END"])
    if not _heap(begin) or end <= begin:
        return 0
    count = min(64, (end - begin) // 16)
    for index in range(count):
        sub = _q(_pid, begin + index * 16)
        if not _heap(sub) or _vrva(sub) != _HUD["CD_VFT"]:
            continue
        status = sub + _HUD["CD_OFF"]
        if _vrva(status) == _HUD["VFT_STATUS"]:
            _status_addr = status
            return status
    return 0


def _hud_u32(blob: bytes, off: int) -> int | None:
    if off < 0 or off + 4 > len(blob):
        return None
    return struct.unpack_from("<I", blob, off)[0]


def read_vitals() -> dict | None:
    """Live HP/MP. None when the game driver is not open."""
    if not _ensure():
        return None
    _load_hud()
    block = _read(_pid, _base + _HUD["ST_BLOCK"], 0x40)
    hp = max_hp = mp = max_mp = None
    if block:
        hp = _hud_u32(block, _HUD["ST_HP"])
        max_hp = _hud_u32(block, _HUD["ST_MAXHP"])
        mp = _hud_u32(block, _HUD["ST_MP"])
        max_mp = _hud_u32(block, _HUD["ST_MAXMP"])
    status = _find_status()
    if status:
        decoded_hp = _decode(status, _HUD["HP"])
        decoded_mp = _decode(status, _HUD["MP"])
        decoded_max_mp = _decode(status, _HUD["MAXMP"])
        if decoded_hp:
            hp = decoded_hp
        if decoded_mp is not None:
            mp = decoded_mp
        if decoded_max_mp:
            max_mp = decoded_max_mp
    if (
        hp is not None
        and max_hp is not None
        and (hp > 2_000_000 or max_hp > 2_000_000 or (max_hp and hp > max_hp * 2))
    ):
        hp = max_hp = None
    if mp is not None and max_mp is not None and (
        mp > 2_000_000 or max_mp > 2_000_000 or (max_mp and mp > max_mp * 2)
    ):
        mp = max_mp = None
    return {
        "hp": hp,
        "max_hp": max_hp,
        "mp": mp,
        "max_mp": max_mp,
    }
