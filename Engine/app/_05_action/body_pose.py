"""Live body action at ActionComponent+0xC0, and the command at +0x58.

Standing is BreathAction (0x11EB4D8, bodyact VFT_BREATHACT). A failed read is None, not standing.
HP/MP come from the status HUD (char_offsets ST_*), with the encoded
CharacterData status used when that decode succeeds. Level uses that same
status (LEVEL), then the HUD ST_LEVEL. Exp percent is the module f64
ExperiencePct64.
"""
from __future__ import annotations

import ctypes
import json
import struct
import time
from ctypes import wintypes
from pathlib import Path

BREATH_VFT = 0x11EB4D8
MOVE_VFTS = frozenset({0x11EB7B8, 0x11EB770})  # MovingAction, MovingBackAction
BODY = {
    0x11EB4D8: "stand",
    0x11EB7B8: "walk",
    0x11EB770: "walkback",
    0x11EB490: "attack",
    0x11EB718: "actionbase",
    0x11EB5B0: "turn",
    0x11EB3B8: "spell",
    0x11EB400: "death",
    0x11EB568: "death",
    0x11EB448: "damaged",
    0x11EB520: "damaged",
    0x11EB370: "effect",
}
CMD = {
    0x11EBA50: "move",
    0x11EBBD0: "attack",
    0x11EBA88: "interact",
}

_k32 = ctypes.WinDLL("kernel32", use_last_error=True)
_k32.CreateFileW.restype = wintypes.HANDLE
_k32.CreateFileW.argtypes = [
    wintypes.LPCWSTR,
    wintypes.DWORD,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HANDLE,
]
_k32.CloseHandle.restype = wintypes.BOOL
_k32.CloseHandle.argtypes = [wintypes.HANDLE]
_k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
_k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
_k32.DeviceIoControl.restype = wintypes.BOOL
_k32.DeviceIoControl.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
    ctypes.c_void_p,
]
# Shared with the in-process monitor. An exclusive open loses to whichever
# side attached first and then every later read stays empty.
_FILE_SHARE_READ_WRITE = 0x1 | 0x2
_handle = None
_pid = 0
_base = 0
_size = 0
_me = 0
_pose_fail_key: str | None = None


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


# Entity list that owns MyPlayer. entity_offsets.txt overrides these.
# The walk/stand class numbers above are not enough: this chain is how the
# body slot is found. A stale manager or MyPlayer id makes every read fail.
_FIND = {
    "MGR": 0x16ED640,
    "ACTOR_VFT": 0x11E9430,
    "MY_PLAYER": 0x11EC4C8,
}
_find_ready = False


def _load_find() -> None:
    """Manager, actor list, and MyPlayer id from the live entity table."""
    global _find_ready
    if _find_ready:
        return
    path = Path(__file__).resolve().parents[2] / "analysis" / "entities" / "entity_offsets.txt"
    if path.is_file():
        classes = ""
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            text = line.strip()
            if not text or text.startswith("#") or "=" not in text:
                continue
            key, raw = text.split("=", 1)
            key = key.strip()
            raw = raw.strip()
            if key == "CLASSES":
                classes = raw
                continue
            if key not in ("MGR", "ACTOR_VFT"):
                continue
            try:
                _FIND[key] = int(raw, 0)
            except ValueError:
                continue
        for part in classes.split(","):
            rva, _, name = part.partition(":")
            if name.strip() != "MyPlayer":
                continue
            try:
                _FIND["MY_PLAYER"] = int(rva.strip(), 16)
            except ValueError:
                pass
            break
    _find_ready = True


def _is_my_player(ent: int) -> bool:
    if not _heap(ent) or _vrva(ent) != _FIND["MY_PLAYER"]:
        return False
    # Live entity rows are self-referential at +8.
    return _q(_pid, ent + 8) == ent


def _find_my_player() -> int:
    _load_find()
    mgr = _q(_pid, _base + _FIND["MGR"])
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
        if _heap(sub) and _vrva(sub) == _FIND["ACTOR_VFT"]:
            actor = sub
            break
    if not actor:
        return 0
    vb = _q(_pid, actor + 0x8A8)
    ve = _q(_pid, actor + 0x8B0)
    if _heap(vb) and ve > vb and (ve - vb) < 0x200000:
        for index in range(min(8000, (ve - vb) // 16)):
            ent = _q(_pid, vb + index * 16)
            if _is_my_player(ent):
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
                    if _is_my_player(ent):
                        return ent
            cur = _q(_pid, cur + 0x08)
    return 0


def _handle_live(handle) -> bool:
    return handle not in (None, 0, -1, ctypes.c_void_p(-1).value)


def _log_pose_fail(key: str, text: str) -> None:
    """One line per distinct failure until a later read succeeds."""
    global _pose_fail_key
    if _pose_fail_key == key:
        return
    _pose_fail_key = key
    try:
        from app.bot_log import event

        event("pose", "%s", text)
    except Exception:
        return


def _log_pose_ok() -> None:
    global _pose_fail_key
    _pose_fail_key = None


def _close_handle() -> None:
    global _handle
    if _handle_live(_handle):
        _k32.CloseHandle(_handle)
    _handle = None


def _drop_locate() -> None:
    global _base, _size, _me
    _base = 0
    _size = 0
    _me = 0


def _ensure() -> bool:
    """Open WinNotify and resolve LC.exe. False leaves the action slot unread.

    The handle is not treated as ready until the module base is known. A
    failed base walk is retried on the next call instead of sticking for
    the life of the process.
    """
    global _handle, _pid, _base, _size, _me
    if _handle_live(_handle) and _pid and _base and _size:
        return True
    pid = _find_pid()
    if not pid:
        _log_pose_fail("nopid", "body pose: lc.exe not found")
        return False
    if _pid and pid != _pid:
        _close_handle()
        _drop_locate()
        _pid = 0
    if not _handle_live(_handle):
        handle = _k32.CreateFileW(
            "\\\\.\\WinNotify",
            0x80000000 | 0x40000000,
            _FILE_SHARE_READ_WRITE,
            None,
            3,
            0,
            None,
        )
        if not _handle_live(handle):
            err = int(ctypes.get_last_error())
            _log_pose_fail(
                f"open:{err}",
                f"body pose: WinNotify open failed winerr={err}",
            )
            return False
        _handle = handle
        _pid = pid
        _drop_locate()
    if not _base or not _size:
        _base, _size = _module_base(pid)
        _me = 0
    if not _base or not _size:
        err = int(ctypes.get_last_error())
        _log_pose_fail(
            f"base:{err}",
            f"body pose: module base unread winerr={err}",
        )
        return False
    _pid = pid
    return True


def _read_slots() -> tuple[int | None, int | None]:
    """(body vft, command vft) from the cached player. None if that walk fails."""
    global _me
    _load_find()
    if not _me or _vrva(_me) != _FIND["MY_PLAYER"]:
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


def _relocate() -> bool:
    """Walk the module and player again after an empty slot. The handle stays."""
    global _pid, _base, _size, _me
    pid = _find_pid()
    if not pid:
        _log_pose_fail("nopid", "body pose: lc.exe not found")
        return False
    if pid != _pid:
        _close_handle()
        _pid = 0
        _drop_locate()
        return _ensure()
    _me = 0
    _base, _size = _module_base(pid)
    if not _base or not _size:
        err = int(ctypes.get_last_error())
        _log_pose_fail(
            f"base:{err}",
            f"body pose: module base unread winerr={err}",
        )
        return False
    return True


def read_action() -> tuple[int | None, int | None]:
    """(body vft, command vft). None means that slot could not be read."""
    if not _ensure():
        return None, None
    body, cmd = _read_slots()
    if body is not None:
        _log_pose_ok()
        return body, cmd
    # A base or player cached while the game was still coming up used to
    # stick until the process exited. Drop it and walk once more.
    if not _relocate():
        return None, None
    body, cmd = _read_slots()
    if body is None:
        _log_pose_fail("slot", "body pose: action slot unread")
        return None, None
    _log_pose_ok()
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
    "ST_LEVEL": 0x2C,
    "LEVEL": 0x248,
    "HP": 0x2B8,
    "MP": 0x2D0,
    "MAXMP": 0x2DC,
}
_hud_ready = False
_status_addr = 0
_status_checked = 0.0
_EXP_RVA = 0x1636BD0
_exp_ready = False
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


def _load_exp_rva() -> None:
    global _exp_ready, _EXP_RVA
    if _exp_ready:
        return
    path = _ANALYSIS / "offsets.json"
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            value = data.get("ExperiencePct64")
            if isinstance(value, int) and value > 0:
                _EXP_RVA = value
        except (OSError, ValueError):
            pass
    _exp_ready = True


def _level_ok(value: int | None) -> int | None:
    if value is None or not (1 <= int(value) <= 255):
        return None
    return int(value)


def read_progress() -> dict | None:
    """Live level and exp percent (0–100). None when the game driver is not open.

    Level prefers the encoded CharacterData field, then the HUD block.
    Exp percent is the live ExperiencePct64 double.
    """
    if not _ensure():
        return None
    _load_hud()
    _load_exp_rva()
    level = None
    block = _read(_pid, _base + _HUD["ST_BLOCK"], 0x40)
    if block:
        level = _level_ok(_hud_u32(block, _HUD["ST_LEVEL"]))
    status = _find_status()
    if status:
        decoded = _level_ok(_decode(status, _HUD["LEVEL"]))
        if decoded is not None:
            level = decoded
    exp = None
    blob = _read(_pid, _base + _EXP_RVA, 8)
    if blob:
        value = struct.unpack("<d", blob)[0]
        # A stale address can be a subnormal that still falls inside 0..100
        # and then prints as 0.00%. Exact 0 is a real empty bar.
        if value == value and (value == 0.0 or 1e-4 <= value <= 100.0):
            exp = float(value)
    return {"level": level, "exp_percent": exp}
