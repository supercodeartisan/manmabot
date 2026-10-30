"""Read-only poll of the live command slot during a pickup.

Logs controller+0x58, ActionComponent+0xC8, and InteractionComponent
qword changes. Does not send input.
"""
import ctypes
from ctypes import wintypes
import struct
import sys
import time

PID = 29708
OUT = r"d:\ManmabotV1_final_final_final\Engine\analysis\combat_attack\interact_probe_out.txt"
SECONDS = 90
POLL_S = 0.015

NAMES = {
    0x11F4A18: "MoveCommand",
    0x11F4A50: "InteractCommand",
    0x11F4B98: "AttackCommand",
    0x11F4B68: "ActorController",
    0x11F4650: "BreathAction",
    0x11F4780: "MovingAction",
    0x11F4410: "AttackAction",
    0x11F4338: "SpellAction",
    0x11F43C8: "DamagedAction",
    0x11F4698: "DamagedReaction",
    0x11F4380: "DeathAction",
    0x11F44E8: "DeadBody",
    0x11F4738: "MovingBackAction",
    0x11F4530: "ChangeDirection",
    0x11F44A0: "EffectAction",
    0x11F46E0: "ActionBase",
    0x11E10B8: "Item",
    0x11E12A8: "MyPlayer",
    0x11E0E28: "InteractionComponent",
    0x11F48D0: "ActionComponent",
    0x11E1270: "Player",
    0x11E1160: "Monster",
}

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
h = k32.CreateFileW(
    "\\\\.\\WinNotify", 0x80000000 | 0x40000000, 0, None, 3, 0, None
)


def read(pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    req = struct.pack("<IIQQQ", pid, 0, addr, ctypes.addressof(buf), size)
    br = wintypes.DWORD()
    ok = k32.DeviceIoControl(
        h, 0x222060, req, len(req), req, len(req), ctypes.byref(br), None
    )
    return buf.raw if ok else None


def q(pid, addr):
    b = read(pid, addr, 8)
    return struct.unpack("<Q", b)[0] if b else 0


def d(pid, addr):
    b = read(pid, addr, 4)
    return struct.unpack("<I", b)[0] if b else 0


def heap(a):
    return 0x10000000000 <= a < 0x80000000000


def tag(rva):
    if not rva:
        return "0"
    return NAMES.get(rva, "vft_%X" % rva)


def module_base(pid):
    peb_in = struct.pack("<IIQ", pid, 0, 0)
    out = ctypes.create_string_buffer(peb_in)
    br = wintypes.DWORD()
    ok = k32.DeviceIoControl(
        h, 0x22204C, peb_in, len(peb_in), out, len(peb_in), ctypes.byref(br), None
    )
    if not ok:
        return 0, 0
    peb = struct.unpack_from("<Q", out.raw, 8)[0]
    ldr = q(pid, peb + 0x18)
    head = q(pid, ldr + 0x20)
    cur = head
    for _ in range(8):
        e = cur - 0x10
        db = q(pid, e + 0x30)
        ds = d(pid, e + 0x40)
        if db and ds:
            return db, ds
        cur = q(pid, cur)
        if not cur or cur == head:
            break
    return 0, 0


def vrva(pid, base, size, obj):
    v = q(pid, obj)
    if base <= v < base + size:
        return v - base
    return 0


def find_my_player(pid, base, size):
    mgr = q(pid, base + 0x16DEE80)
    if not heap(mgr):
        return 0
    holder = q(pid, mgr + 0xD0)
    if not heap(holder):
        return 0
    beg = q(pid, holder + 0x180)
    end = q(pid, holder + 0x188)
    if not heap(beg) or end <= beg:
        return 0
    n = min(64, (end - beg) // 16)
    actor = 0
    for i in range(n):
        sub = q(pid, beg + i * 16)
        if heap(sub) and vrva(pid, base, size, sub) == 0x11DE3B8:
            actor = sub
            break
    if not actor:
        return 0
    vb = q(pid, actor + 0x8A8)
    ve = q(pid, actor + 0x8B0)
    if heap(vb) and ve > vb and (ve - vb) < 0x200000:
        nn = min(8000, (ve - vb) // 16)
        for i in range(nn):
            e = q(pid, vb + i * 16)
            if heap(e) and vrva(pid, base, size, e) == 0x11E12A8:
                return e
    for head in (0x798, 0x7D8):
        sent = q(pid, actor + head + 8)
        if not heap(sent):
            continue
        cur = q(pid, sent + 0x08)
        guard = 0
        while heap(cur) and cur != sent and guard < 4000:
            guard += 1
            b = q(pid, cur + 0x18)
            e = q(pid, cur + 0x20)
            if heap(b) and heap(e) and e >= b:
                nn = min(5000, (e - b) // 8)
                for i in range(nn):
                    ent = q(pid, b + i * 8)
                    if heap(ent) and vrva(pid, base, size, ent) == 0x11E12A8:
                        return ent
            cur = q(pid, cur + 0x08)
    return 0


def sample(pid, base, size, me):
    table = q(pid, me + 0x20)
    if not heap(table):
        return None
    ctl = q(pid, table + 0x90)
    ac = q(pid, table + 2 * 8)
    ic = q(pid, table + 8 * 8)
    tr = q(pid, table + 0)
    cmd = q(pid, ctl + 0x58) if heap(ctl) else 0
    act = q(pid, ac + 0xC8) if heap(ac) else 0
    cellx = d(pid, tr + 0x40) if heap(tr) else 0
    celly = d(pid, tr + 0x44) if heap(tr) else 0
    cmd_v = vrva(pid, base, size, cmd) if heap(cmd) else 0
    act_v = vrva(pid, base, size, act) if heap(act) else 0
    ic_blob = read(pid, ic, 0x180) if heap(ic) else b""
    cmd_blob = read(pid, cmd, 0xA0) if heap(cmd) else b""
    return {
        "cell": (cellx, celly),
        "cmd": cmd,
        "cmd_v": cmd_v,
        "act": act,
        "act_v": act_v,
        "ic": ic,
        "ic_blob": ic_blob,
        "cmd_blob": cmd_blob,
        "ctl_v": vrva(pid, base, size, ctl) if heap(ctl) else 0,
        "ac_v": vrva(pid, base, size, ac) if heap(ac) else 0,
    }


def ic_changes(prev, cur, pid, base, size):
    if not prev or not cur or len(prev) != len(cur):
        return []
    lines = []
    for off in range(0, len(cur) - 7, 8):
        a = struct.unpack_from("<Q", prev, off)[0]
        b = struct.unpack_from("<Q", cur, off)[0]
        if a == b:
            continue
        extra = ""
        if heap(b):
            v = vrva(pid, base, size, b)
            extra = " " + tag(v)
        lines.append("    ic+%03X %X -> %X%s" % (off, a, b, extra))
    return lines


def cmd_fields(blob, pid, base, size):
    if not blob:
        return ""
    parts = []
    for off in (0x10, 0x18, 0x20, 0x28, 0x30, 0x38, 0x40, 0x48, 0x50, 0x58, 0x80, 0x88):
        if off + 8 > len(blob):
            continue
        val = struct.unpack_from("<Q", blob, off)[0]
        if not val:
            continue
        extra = ""
        if heap(val):
            extra = ":" + tag(vrva(pid, base, size, val))
        parts.append("+%X=%X%s" % (off, val, extra))
    return " ".join(parts)


def main():
    if h == ctypes.c_void_p(-1).value or not h or h == -1:
        print("driver fail", ctypes.get_last_error())
        return 1
    base, size = module_base(PID)
    log = open(OUT, "w", encoding="utf-8")

    def emit(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    emit("pid=%d base=%X size=%X" % (PID, base, size))
    me = find_my_player(PID, base, size)
    emit("me=%X" % me)
    if not me:
        emit("MyPlayer not found")
        return 1
    t0 = time.perf_counter()
    prev = None
    body_since = 0
    n_base = 0
    deadline = t0 + SECONDS

    def dump_body(cur):
        act = cur["act"]
        blob = read(PID, act, 0x80) if heap(act) else None
        emit("    act=%X vft=%X" % (act, cur["act_v"]))
        if blob:
            for off in range(0, 0x80, 8):
                val = struct.unpack_from("<Q", blob, off)[0]
                if not val:
                    continue
                extra = ""
                if heap(val):
                    extra = " " + tag(vrva(PID, base, size, val))
                elif base <= val < base + size:
                    extra = " mod+%X" % (val - base)
                emit("    act+%02X %X%s" % (off, val, extra))
        ac = q(PID, q(PID, me + 0x20) + 16)
        raw = read(PID, ac, 0x140) if heap(ac) else None
        if not raw:
            return
        for off in range(0, 0x140, 8):
            w = struct.unpack_from("<Q", raw, off)[0]
            if not heap(w):
                continue
            v = vrva(PID, base, size, w)
            if v:
                emit("    ac+%02X %s" % (off, tag(v)))

    while time.perf_counter() < deadline:
        if vrva(PID, base, size, me) != 0x11E12A8:
            me = find_my_player(PID, base, size)
            emit("refind me=%X" % me)
            if not me:
                time.sleep(0.05)
                continue
        cur = sample(PID, base, size, me)
        if cur is None:
            time.sleep(POLL_S)
            continue
        ms = int((time.perf_counter() - t0) * 1000)
        if prev is None:
            emit(
                "[%d] INIT cell=%s cmd=%s body=%s"
                % (ms, cur["cell"], tag(cur["cmd_v"]), tag(cur["act_v"]))
            )
            if cur["act_v"] == 0x11F46E0:
                n_base += 1
                dump_body(cur)
            prev = cur
            body_since = ms
        else:
            body_changed = cur["act_v"] != prev["act_v"]
            cmd_changed = cur["cmd_v"] != prev["cmd_v"]
            if body_changed or cmd_changed:
                extra = ""
                if body_changed:
                    extra = "  (prev body %s %dms)" % (tag(prev["act_v"]), ms - body_since)
                emit(
                    "[%d] cell=%s cmd=%s body=%s%s"
                    % (ms, cur["cell"], tag(cur["cmd_v"]), tag(cur["act_v"]), extra)
                )
                if body_changed and cur["act_v"] == 0x11F46E0:
                    n_base += 1
                    dump_body(cur)
                if body_changed:
                    body_since = ms
                prev = cur
        time.sleep(POLL_S)
    emit("DONE actionbase=%d" % n_base)
    log.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
