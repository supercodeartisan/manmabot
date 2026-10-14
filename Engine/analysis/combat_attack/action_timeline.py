"""Read-only timeline of the live body action and command.

Logs a line only when ActionComponent+0xC0 or ActorController+0x58
changes class. Does not send input.
"""
import ctypes
from ctypes import wintypes
import struct
import sys
import time

OUT = r"d:\ManmabotV1_final_final_final\Engine\analysis\combat_attack\action_timeline.txt"
SECONDS = 300
POLL_S = 0.02

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

k32 = ctypes.WinDLL("kernel32", use_last_error=True)


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
        ("szExeFile", wintypes.WCHAR * 260),
    ]


def find_pid():
    snap = k32.CreateToolhelp32Snapshot(0x2, 0)
    if snap == ctypes.c_void_p(-1).value or snap == -1:
        return 0
    pe = PROCESSENTRY32W()
    pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
    pid = 0
    if k32.Process32FirstW(snap, ctypes.byref(pe)):
        while True:
            if pe.szExeFile.lower() == "lc.exe":
                pid = pe.th32ProcessID
                break
            if not k32.Process32NextW(snap, ctypes.byref(pe)):
                break
    k32.CloseHandle(snap)
    return pid


def read(h, pid, addr, size):
    buf = ctypes.create_string_buffer(size)
    req = struct.pack("<IIQQQ", pid, 0, addr, ctypes.addressof(buf), size)
    br = wintypes.DWORD()
    ok = k32.DeviceIoControl(
        h, 0x222060, req, len(req), req, len(req), ctypes.byref(br), None
    )
    return buf.raw if ok else None


def q(h, pid, addr):
    b = read(h, pid, addr, 8)
    return struct.unpack("<Q", b)[0] if b else 0


def d(h, pid, addr):
    b = read(h, pid, addr, 4)
    return struct.unpack("<I", b)[0] if b else 0


def heap(a):
    return 0x10000000000 <= a < 0x80000000000


def label(table, rva):
    if not rva:
        return "none"
    return table.get(rva, "vft_%X" % rva)


def module_base(h, pid):
    peb_in = struct.pack("<IIQ", pid, 0, 0)
    out = ctypes.create_string_buffer(peb_in)
    br = wintypes.DWORD()
    ok = k32.DeviceIoControl(
        h, 0x22204C, peb_in, len(peb_in), out, len(peb_in), ctypes.byref(br), None
    )
    if not ok:
        return 0, 0
    peb = struct.unpack_from("<Q", out.raw, 8)[0]
    ldr = q(h, pid, peb + 0x18)
    head = q(h, pid, ldr + 0x20)
    cur = head
    for _ in range(8):
        e = cur - 0x10
        db = q(h, pid, e + 0x30)
        ds = d(h, pid, e + 0x40)
        if db and ds:
            return db, ds
        cur = q(h, pid, cur)
        if not cur or cur == head:
            break
    return 0, 0


def vrva(h, pid, base, size, obj):
    v = q(h, pid, obj)
    if base <= v < base + size:
        return v - base
    return 0


def find_my_player(h, pid, base, size):
    mgr = q(h, pid, base + 0x16DEE80)
    if not heap(mgr):
        return 0
    holder = q(h, pid, mgr + 0xD0)
    if not heap(holder):
        return 0
    beg = q(h, pid, holder + 0x180)
    end = q(h, pid, holder + 0x188)
    if not heap(beg) or end <= beg:
        return 0
    actor = 0
    for i in range(min(64, (end - beg) // 16)):
        sub = q(h, pid, beg + i * 16)
        if heap(sub) and vrva(h, pid, base, size, sub) == 0x11DE3B8:
            actor = sub
            break
    if not actor:
        return 0
    vb = q(h, pid, actor + 0x8A8)
    ve = q(h, pid, actor + 0x8B0)
    if heap(vb) and ve > vb and (ve - vb) < 0x200000:
        for i in range(min(8000, (ve - vb) // 16)):
            e = q(h, pid, vb + i * 16)
            if heap(e) and vrva(h, pid, base, size, e) == 0x11E12A8:
                return e
    for head in (0x798, 0x7D8):
        sent = q(h, pid, actor + head + 8)
        if not heap(sent):
            continue
        cur = q(h, pid, sent + 0x08)
        guard = 0
        while heap(cur) and cur != sent and guard < 4000:
            guard += 1
            b = q(h, pid, cur + 0x18)
            e = q(h, pid, cur + 0x20)
            if heap(b) and heap(e) and e >= b:
                for i in range(min(5000, (e - b) // 8)):
                    ent = q(h, pid, b + i * 8)
                    if heap(ent) and vrva(h, pid, base, size, ent) == 0x11E12A8:
                        return ent
            cur = q(h, pid, cur + 0x08)
    return 0


def sample(h, pid, base, size, me):
    table = q(h, pid, me + 0x20)
    if not heap(table):
        return None
    ctl = q(h, pid, table + 0x90)
    ac = q(h, pid, table + 16)
    tr = q(h, pid, table)
    cmd = q(h, pid, ctl + 0x58) if heap(ctl) else 0
    act = q(h, pid, ac + 0xC0) if heap(ac) else 0
    return {
        "cell": (
            d(h, pid, tr + 0x40) if heap(tr) else 0,
            d(h, pid, tr + 0x44) if heap(tr) else 0,
        ),
        "body": vrva(h, pid, base, size, act) if heap(act) else 0,
        "cmd": vrva(h, pid, base, size, cmd) if heap(cmd) else 0,
    }


def clock(ms):
    return "%02d:%02d.%03d" % (ms // 60000, (ms // 1000) % 60, ms % 1000)


def main():
    pid = find_pid()
    h = k32.CreateFileW(
        "\\\\.\\WinNotify", 0x80000000 | 0x40000000, 0, None, 3, 0, None
    )
    if not pid or h == ctypes.c_void_p(-1).value or not h or h == -1:
        print("not ready pid=%s err=%s" % (pid, ctypes.get_last_error()))
        return 1
    base, size = module_base(h, pid)
    log = open(OUT, "w", encoding="utf-8")

    def emit(msg):
        print(msg, flush=True)
        log.write(msg + "\n")
        log.flush()

    emit("pid=%d base=%X seconds=%d" % (pid, base, SECONDS))
    emit("body slot ActionComponent+0xC0   command slot ActorController+0x58")
    me = find_my_player(h, pid, base, size)
    emit("me=%X" % me)
    if not me:
        emit("MyPlayer not found")
        return 1

    t0 = time.perf_counter()
    prev = None
    since = 0
    counts = {}
    deadline = t0 + SECONDS
    while time.perf_counter() < deadline:
        if vrva(h, pid, base, size, me) != 0x11E12A8:
            me = find_my_player(h, pid, base, size)
            emit("refind me=%X" % me)
            if not me:
                time.sleep(0.05)
                continue
        cur = sample(h, pid, base, size, me)
        if cur is None:
            time.sleep(POLL_S)
            continue
        ms = int((time.perf_counter() - t0) * 1000)
        if prev is None or cur["body"] != prev["body"] or cur["cmd"] != prev["cmd"]:
            held = ""
            if prev is not None and cur["body"] != prev["body"]:
                held = "   previous %s %.2fs" % (label(BODY, prev["body"]), (ms - since) / 1000.0)
                counts[prev["body"]] = counts.get(prev["body"], 0) + (ms - since)
            if prev is None or cur["body"] != prev["body"]:
                since = ms
            emit(
                "%s  body %-12s cmd %-10s cell %s%s"
                % (
                    clock(ms),
                    label(BODY, cur["body"]),
                    label(CMD, cur["cmd"]),
                    cur["cell"],
                    held,
                )
            )
            prev = cur
        time.sleep(POLL_S)
    end_ms = int((time.perf_counter() - t0) * 1000)
    if prev is not None:
        counts[prev["body"]] = counts.get(prev["body"], 0) + (end_ms - since)
    emit("DONE")
    for rva, ms in sorted(counts.items(), key=lambda kv: -kv[1]):
        emit("  total %-12s %.2fs" % (label(BODY, rva), ms / 1000.0))
    log.close()
    k32.CloseHandle(h)
    return 0


if __name__ == "__main__":
    sys.exit(main())
