import ctypes
import logging
import os
import struct
import threading
from ctypes import wintypes

logger = logging.getLogger(__name__)

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
ntdll = ctypes.WinDLL("ntdll")

SYSTEM_EXTENDED_HANDLE_INFORMATION = 64
PROCESS_DUP_HANDLE = 0x0040
DUPLICATE_CLOSE_SOURCE = 0x00000001
OBJECT_NAME_INFORMATION = 1
OBJECT_TYPE_INFORMATION = 2
ObjectTypes = {"Event", "Section", "File", "Mutant", "Semaphore"}

_setup_done = False


def _setup():
    global _setup_done
    if _setup_done:
        return
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE,
                                    wintypes.HANDLE,
                                    ctypes.POINTER(wintypes.HANDLE),
                                    wintypes.DWORD, wintypes.BOOL,
                                    wintypes.DWORD]
    k32.DuplicateHandle.restype = wintypes.BOOL
    ntdll.NtQuerySystemInformation.argtypes = [ctypes.c_uint, wintypes.LPVOID,
                                               wintypes.ULONG,
                                               ctypes.POINTER(wintypes.ULONG)]
    ntdll.NtQuerySystemInformation.restype = ctypes.c_long
    ntdll.NtQueryObject.argtypes = [wintypes.HANDLE, ctypes.c_uint,
                                    wintypes.LPVOID, wintypes.ULONG,
                                    ctypes.POINTER(wintypes.ULONG)]
    ntdll.NtQueryObject.restype = ctypes.c_long
    _setup_done = True


def _query_with_timeout(func, h, info_class, timeout=0.5):
    """Run NtQueryObject in a worker thread; some handle types hang."""
    box = {}

    def work():
        size = 1024
        for _ in range(6):
            buf = ctypes.create_string_buffer(size)
            ret = wintypes.ULONG(0)
            st = func(h, info_class, buf, size, ctypes.byref(ret))
            if st == 0xC0000004:          # STATUS_INFO_LENGTH_MISMATCH
                size *= 2
                continue
            box["st"] = st
            box["buf"] = buf.raw[:ret.value or size]
            box["base"] = ctypes.addressof(buf)
            return
        box["st"] = -1
    t = threading.Thread(target=work, daemon=True)
    t.start()
    t.join(timeout)
    if t.is_alive() or "st" not in box or box["st"] != 0:
        return None
    raw = box["buf"]
    if len(raw) < 8:
        return None
    str_len, _ = struct.unpack_from("<HH", raw, 0)
    ptr = struct.unpack_from("<Q", raw, 8)[0]
    off = ptr - box["base"]
    if off < 0 or off + str_len > len(raw):
        return None
    try:
        return raw[off:off + str_len].decode("utf-16-le", errors="replace")
    except Exception:
        return None


def _enumerate_system_handles():
    """Yield (pid, handle, object_type_index, granted_access) tuples."""
    _setup()
    size = 0x400000
    buf = None
    for _ in range(8):
        buf = ctypes.create_string_buffer(size)
        ret = wintypes.ULONG(0)
        ntdll.NtQuerySystemInformation(
            SYSTEM_EXTENDED_HANDLE_INFORMATION, buf, size, ctypes.byref(ret))
        # Some builds return success with partial data - trust RequiredSize
        if ret.value and ret.value > size:
            size = ret.value + 65536
            continue
        break
    if buf is None:
        return []

    data = buf.raw
    # SYSTEM_HANDLE_INFORMATION_EX header: ULONG_PTR NumberOfHandles,
    # ULONG_PTR Reserved -> 16 bytes on x64
    count = struct.unpack_from("<Q", data, 0)[0]
    out = []
    off = 16
    # SYSTEM_HANDLE_TABLE_ENTRY_INFO_EX (x64): Object(8) Pid(8) Handle(8)
    # GrantedAccess(4) BackTrace(2) TypeIndex(2) Attributes(4) Reserved(4)
    walked = 0
    for _ in range(count):
        if off + 40 > len(data):
            break
        pid, handle = struct.unpack_from("<QQ", data, off + 8)
        access = struct.unpack_from("<I", data, off + 24)[0]
        type_idx = struct.unpack_from("<H", data, off + 30)[0]
        out.append((pid, handle, type_idx, access))
        off += 40
        walked += 1
    if walked < count:
        logger.warning(f"[handles] table truncated ({walked}/{count})")
    return out


class _RemoteDup:
    """Context manager duplicating a remote handle into our process."""

    def __init__(self, proc_h, remote_h):
        self.proc_h = proc_h
        self.remote_h = remote_h
        self.local_h = None

    def __enter__(self):
        d = wintypes.HANDLE(0)
        if not k32.DuplicateHandle(self.proc_h,
                                   wintypes.HANDLE(self.remote_h),
                                   k32.GetCurrentProcess(),
                                   ctypes.byref(d), 0, False, 0):
            return None
        self.local_h = d.value
        return self.local_h

    def __exit__(self, *a):
        if self.local_h:
            k32.CloseHandle(self.local_h)
        return False


def list_target_handles(pid, want_types=None):
    """All open handles of `pid`; optionally filtered by type name.

    Returns list of dicts: {handle, type, name}.
    """
    _setup()
    proc_h = k32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
    if not proc_h:
        err = ctypes.get_last_error()
        if err != 87:  # process exited mid-scan; not interesting
            logger.warning(f"[handles] OpenProcess({pid}) failed err={err}")
        return []

    results = []
    try:
        for hpid, h, type_idx, access in _enumerate_system_handles():
            if hpid != pid:
                continue
            with _RemoteDup(proc_h, h) as local:
                if not local:
                    continue
                tname = _query_with_timeout(ntdll.NtQueryObject, local, OBJECT_TYPE_INFORMATION)
                if not tname:
                    continue
                if want_types and tname not in want_types:
                    continue
                name = None
                if tname in ("File", "Mutant"):
                    name = _query_with_timeout(ntdll.NtQueryObject,
                                               local, OBJECT_NAME_INFORMATION,
                                               timeout=0.5)
                results.append({"handle": h, "type": tname,
                                "name": name, "access": access})
    finally:
        k32.CloseHandle(proc_h)
    return results


def close_remote_handle(pid, handle):
    """Force-close `handle` inside process `pid`. Returns True on success."""
    _setup()
    proc_h = k32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
    if not proc_h:
        return False
    try:
        d = wintypes.HANDLE(0)
        ok = k32.DuplicateHandle(proc_h, wintypes.HANDLE(handle),
                                 k32.GetCurrentProcess(), ctypes.byref(d),
                                 0, False, DUPLICATE_CLOSE_SOURCE)
        if ok and d.value:
            k32.CloseHandle(d)
        return bool(ok)
    finally:
        k32.CloseHandle(proc_h)


def unlock_purple_single_instance(pid):
    """Release the app's single-instance lock handles so further instances
    can acquire their own.

    Close policy (strict):
      - type File/Mutant/Event/Section
      - has a resolvable name
      - NOT the NamedPipe root directory itself
      - NOT a well-known Windows service pipe (matched on LAST segment,
        since NT paths are \\Device\\NamedPipe\\<svc>)
      - NOT .NET/WIL runtime infrastructure objects
    """
    _setup()
    # Matched against the LAST path segment of the object name
    system_suffixes = (
        "wkssvc", "ntsvcs", "scerpc", "epmapper", "eventlog", "atsvc",
        "srvsvc", "winreg", "spoolss", "lsass", "samss", "mspq", "pipeng",
        "routerfixup", "svcctl", "trkwks", "w32time_alt", "keysvc",
    )
    infra_markers = (
        "wilstaging", "wilerror", "cor_private", "cor_sxs", "cpfate",
        "_p0", "_p0h", "dotnet", ".net", "sm0:", "mscoree", "clr_",
    )

    def last_seg(low):
        return low.rstrip("\\").rsplit("\\", 1)[-1]

    closed = []
    for hinfo in list_target_handles(
            pid, want_types={"File", "Mutant", "Event", "Section"}):
        name = hinfo.get("name")
        if not name:
            continue
        low = name.lower()
        t = hinfo["type"]

        if t == "File":
            # Never touch the pipe namespace root directory handle
            if low.rstrip("\\") == "\\device\\namedpipe":
                continue
            if "\\namedpipe\\" not in low and "\\pipe\\" not in low:
                continue
        elif t == "Mutant":
            # Only the app-specific lock mutex (e.g. ...\BaseNamedObjects\
            # Purple or Lineage). NEVER global infra like DBWinMutex / DDraw / Wil*.
            seg = last_seg(low)
            if "purple" not in seg and "lineage" not in seg:
                continue
        else:
            # Events/Sections: skip entirely - too risky, mostly infra
            continue

        seg = last_seg(low)
        if seg in system_suffixes:
            continue
        if any(m in low for m in infra_markers):
            continue

        if close_remote_handle(pid, hinfo["handle"]):
            closed.append((t, name))

    if closed:
        logger.info(f"[unlock] PID {pid}: released "
                    f"{len(closed)} candidate handle(s)")
        for t, n in closed:
            logger.info(f"[unlock]   {t}: {n}")
    return closed


def purge_locks_across_instances(image_name="purple.exe",
                                 lock_markers=("purple", "lineage")):
    """Pre-launch sweep: find every running <image_name> process still
    holding an app-specific lock mutex and release those handles, so the
    NEXT instance can acquire it even when launched immediately.

    Only Mutant handles whose LAST NAME SEGMENT contains one of
    lock_markers are touched - everything else is left alone.
    """
    _setup()
    out = os.popen(f'tasklist /FI "IMAGENAME eq {image_name}" '
                   f'/FO CSV /NH').read()
    pids = set()
    for line in out.splitlines():
        if image_name.lower() in line.lower():
            try:
                pids.add(int(line.split('","')[1]))
            except Exception:
                pass

    released = 0
    for pid in sorted(pids):
        for hinfo in list_target_handles(pid, want_types={"Mutant"}):
            name = (hinfo.get("name") or "").lower()
            seg = name.rstrip("\\").rsplit("\\", 1)[-1]
            if not any(m in seg for m in lock_markers):
                continue
            if close_remote_handle(pid, hinfo["handle"]):
                released += 1
                logger.info(f"[purge] PID {pid}: released "
                            f"Mutant {hinfo.get('name')}")
    return released


def dump_target_handles(pid, path):
    """Write every named handle of pid to a text file (diagnostics)."""
    try:
        rows = list_target_handles(pid)
        with open(path, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(f"{r['type']:12s} 0x{r['handle']:08X} "
                        f"acc=0x{r['access']:08X} name={r.get('name')}\n")
        return len(rows)
    except Exception as e:
        logger.warning(f"[dump] failed: {e}")
        return -1
