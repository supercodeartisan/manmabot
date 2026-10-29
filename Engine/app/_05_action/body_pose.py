"""Live body action at ActionComponent+0xC0, and the command at +0x58.

Standing is BreathAction (0x11F4650, bodyact VFT_BREATHACT). A failed read is None, not standing.
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

BREATH_VFT = 0x11F4650
MOVE_VFTS = frozenset({0x11F4780, 0x11F4738})  # MovingAction, MovingBackAction
BODY = {
    0x11F4650: "stand",
    0x11F4780: "walk",
    0x11F4738: "walkback",
    0x11F4410: "attack",
    0x11F46E0: "actionbase",
    0x11F4530: "turn",
    0x11F4338: "spell",
    0x11F4380: "death",
    0x11F44E8: "death",
    0x11F43C8: "damaged",
    0x11F4698: "damaged",
    0x11F44A0: "effect",
}
CMD = {
    0x11F4A18: "move",
    0x11F4B98: "attack",
    0x11F4A50: "interact",
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


# Entity list that owns MyPlayer. entity_offsets.txt overrides these.
# The walk/stand class numbers above are not enough: this chain is how the
# body slot is found. A stale manager or MyPlayer id makes every read fail.
_FIND = {
    "MGR": 0x16F8A00,
    "ACTOR_VFT": 0x11F24A8,
    "MY_PLAYER": 0x11F5488,
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
    """(body vft, command vft) from the bodyact module. None when unread."""
    try:
        from app._01_perception.lc_view import body_rvas

        pair = body_rvas()
    except Exception:
        return None, None
    if pair is None:
        return None, None
    return pair


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
_EXP_RVA = 0x1644BF0
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
    """Live HP/MP from the charread module. None when that sample is missing."""
    try:
        from app._01_perception.lc_view import char_vitals

        vitals = char_vitals()
    except Exception:
        return None
    if vitals is None:
        return None
    return {
        "hp": vitals.get("hp"),
        "max_hp": vitals.get("max_hp"),
        "mp": vitals.get("mp"),
        "max_mp": vitals.get("max_mp"),
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
    """Live level and exp percent from the charread module."""
    try:
        from app._01_perception.lc_view import char_vitals

        vitals = char_vitals()
    except Exception:
        return None
    if vitals is None:
        return None
    return {"level": vitals.get("level"), "exp_percent": vitals.get("exp_percent")}


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
