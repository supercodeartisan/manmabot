"""Live body action at ActionComponent+0xC8, and the command at +0x58.

The action slot is read directly, the same walk ``fix/single-version`` uses.
Standing is BreathAction (0x11E0550). A failed read is None, not standing.
HP, MP, level, and exp come from dll/realtime_monitor.dll.
"""
from __future__ import annotations

import ctypes
import json
import struct
import time
from ctypes import wintypes
from pathlib import Path

BREATH_VFT = 0x11E0550
MOVE_VFTS = frozenset({0x11E0680, 0x11E0638})  # MovingAction, MovingBackAction
BODY = {
    0x11E0550: "stand",
    0x11E0680: "walk",
    0x11E0638: "walkback",
    0x11E0508: "attack",
    0x11E05E0: "actionbase",
    0x11E04C0: "turn",
    0x11E02C8: "spell",
    0x11E0310: "death",
    0x11E03E8: "death",
    0x11E0358: "damaged",
    0x11E0598: "damaged",
    0x11E03A0: "effect",
}
CMD = {
    0x11E0910: "move",
    0x11E0A90: "attack",
    0x11E0948: "interact",
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
# Shared with print_state. An exclusive open loses to whichever side
# attached first and then every later read stays empty.
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
    "MGR": 0x16EB6F0,
    "ACTOR_VFT": 0x11DE3E8,
    "MY_PLAYER": 0x11E1388,
}
_find_ready = False


def _load_find() -> None:
    """Manager, actor list, and MyPlayer id from the live entity table."""
    global _find_ready
    if _find_ready:
        return
    path = Path(__file__).resolve().parents[2] / "analysis" / "registry" / "entity_offsets.txt"
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
    act = _q(_pid, ac + 0xC8)
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
    "MGR": 0x16F8A00,
    "CD_VFT": 0x11F90D8,
    "CD_OFF": 0x498,
    "VFT_STATUS": 0x11F90B8,
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
_EXP_RVA = 0x1641B00
_exp_ready = False
_ANALYSIS = Path(__file__).resolve().parents[2] / "analysis"


def _u32(value: int) -> int:
    return value & 0xFFFFFFFF


def _load_hud() -> None:
    global _hud_ready
    if _hud_ready:
        return
    table = _ANALYSIS / "registry" / "char_offsets.txt"
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


def _opt_int(raw: dict, *keys: str) -> int | None:
    for key in keys:
        if key not in raw or raw[key] is None:
            continue
        try:
            return int(raw[key])
        except (TypeError, ValueError):
            continue
    return None


def _monitor_player() -> dict | None:
    """Player block from the process monitor. Does not start charread."""
    snap = None
    try:
        from app._01_perception import sensors as sensor_mod

        live = sensor_mod._SHARED
        if live is not None:
            snap = live.pull_player(fresh=False)
    except Exception:
        snap = None
    if not isinstance(snap, dict):
        try:
            from session.player_monitor import shared_monitor

            snap = shared_monitor().snapshot(fresh=False)
        except Exception:
            return None
    if not isinstance(snap, dict):
        return None
    raw = snap.get("player")
    if isinstance(raw, dict):
        return raw
    return None


def read_vitals() -> dict | None:
    """Live HP/MP from realtime_monitor. None when that sample is missing."""
    raw = _monitor_player()
    if not raw:
        return None
    return {
        "hp": _opt_int(raw, "hp"),
        "max_hp": _opt_int(raw, "maxHp", "max_hp"),
        "mp": _opt_int(raw, "mp"),
        "max_mp": _opt_int(raw, "maxMp", "max_mp"),
    }


def _load_exp_rva() -> None:
    global _exp_ready, _EXP_RVA
    if _exp_ready:
        return
    path = _ANALYSIS / "registry" / "offsets.json"
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
    """Live level and exp percent from realtime_monitor."""
    raw = _monitor_player()
    if not raw:
        return None
    exp = raw.get("expPct")
    if exp is None:
        exp = raw.get("exp_percent")
    try:
        exp_percent = float(exp) if exp is not None else None
    except (TypeError, ValueError):
        exp_percent = None
    return {"level": _opt_int(raw, "level", "lv"), "exp_percent": exp_percent}


def _bind_action_vfts() -> None:
    """Action class ids follow the dropped registry, not a baked table."""
    global BREATH_VFT, MOVE_VFTS, BODY, CMD
    try:
        from app._01_perception.registry_apply import parse_registry, source_registry
    except Exception:
        return
    path = source_registry()
    if path is None:
        return
    reg = parse_registry(path)

    def take(key: str) -> int:
        raw = reg.get(key)
        if not raw:
            return 0
        try:
            return int(raw, 0)
        except ValueError:
            return 0

    labels = (
        ("VFT_BREATHACT", "stand"),
        ("VFT_MOVINGACT", "walk"),
        ("VFT_MOVINGBACK", "walkback"),
        ("VFT_ATTACKACT", "attack"),
        ("VFT_ACTIONBASE", "actionbase"),
        ("VFT_CHANGEDIR", "turn"),
        ("VFT_SPELLACT", "spell"),
        ("VFT_DEATH", "death"),
        ("VFT_DEADBODY", "death"),
        ("VFT_DAMAGEDACTION", "damaged"),
        ("VFT_DAMAGEDREACTION", "damaged"),
        ("VFT_EFFECTACTION", "effect"),
    )
    body: dict[int, str] = {}
    for key, label in labels:
        value = take(key)
        if value:
            body[value] = label
    if body:
        BODY = body
    breath = take("VFT_BREATHACT")
    if breath:
        BREATH_VFT = breath
    moving = {value for value in (take("VFT_MOVINGACT"), take("VFT_MOVINGBACK")) if value}
    if moving:
        MOVE_VFTS = frozenset(moving)
    commands = {
        take("VFT_CMDMOVE"): "move",
        take("VFT_CMDATTACK"): "attack",
        take("VFT_CMDINTERACT"): "interact",
    }
    commands.pop(0, None)
    if commands:
        CMD = commands
    mgr = take("MGR")
    actor = take("VFT_ACTORSUBS")
    me = take("VFT_SELF")
    if mgr:
        _FIND["MGR"] = mgr
    if actor:
        _FIND["ACTOR_VFT"] = actor
    if me:
        _FIND["MY_PLAYER"] = me


_bind_action_vfts()
