import ctypes
import logging
import os
import struct
import tempfile
from ctypes import wintypes

from hollow.process_hollowing import (
    CONTEXT86, CONTEXT_FULL_X86, CREATE_SUSPENDED, MACHINE_X86,
    MEM_COMMIT, MEM_RESERVE, PAGE_READWRITE,
    PROCESS_BASIC_INFORMATION, PROCESS_BASIC_INFORMATION_CLASS,
    PROCESS_WOW64_INFORMATION, STARTUPINFO, PROCESS_INFORMATION,
    aligned_context, k32, ntdll, parse_pe,
)

logger = logging.getLogger(__name__)

SVCHOST_32 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                           "SysWOW64", "svchost.exe")
SVCHOST_64 = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                           "System32", "svchost.exe")

def _pick_host():
    return os.environ.get("HEBOT_HOST") or (
        SVCHOST_32 if os.path.exists(SVCHOST_32) else SVCHOST_64)

BOT_LOADER_X86 = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                               "loader", "svchost.exe")
if not os.path.isfile(BOT_LOADER_X86):
    BOT_LOADER_X86 = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                                   "loader", "bot_loader_x86.exe")
STILL_ACTIVE = 259
DUPLICATE_SAME_ACCESS = 0x00000002

SEC_IMAGE = 0x01000000
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
SECTION_ALL_ACCESS = 0x000F001F
VIEW_UNMAP = 1
MEM_IMAGE_UNMAP = 0x40000000  # placeholder, not used

_LAST_HOST = {"handle": None, "pid": None}


def _setup_prototypes():
    k32.CreateProcessW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR,
                                   wintypes.LPVOID, wintypes.LPVOID,
                                   wintypes.BOOL, wintypes.DWORD,
                                   wintypes.LPVOID, wintypes.LPCWSTR,
                                   ctypes.c_void_p, ctypes.c_void_p]
    k32.CreateProcessW.restype = wintypes.BOOL
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                wintypes.HANDLE]
    k32.CreateFileW.restype = wintypes.HANDLE
    k32.ResumeThread.argtypes = [wintypes.HANDLE]
    k32.ResumeThread.restype = wintypes.DWORD
    k32.Wow64GetThreadContext.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    k32.Wow64GetThreadContext.restype = wintypes.BOOL
    k32.Wow64SetThreadContext.argtypes = [wintypes.HANDLE, wintypes.LPVOID]
    k32.Wow64SetThreadContext.restype = wintypes.BOOL
    k32.GetThreadContext.restype = wintypes.BOOL
    k32.SetThreadContext.restype = wintypes.BOOL
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.GetExitCodeProcess.restype = wintypes.BOOL
    k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.TerminateProcess.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    k32.GetCurrentProcess.argtypes = []
    k32.GetCurrentProcess.restype = wintypes.HANDLE
    k32.DuplicateHandle.argtypes = [wintypes.HANDLE, wintypes.HANDLE,
                                    wintypes.HANDLE,
                                    ctypes.POINTER(wintypes.HANDLE),
                                    wintypes.DWORD, wintypes.BOOL,
                                    wintypes.DWORD]
    k32.DuplicateHandle.restype = wintypes.BOOL
    ntdll.NtQueryInformationProcess.argtypes = [wintypes.HANDLE, ctypes.c_uint,
                                                ctypes.c_void_p, wintypes.ULONG,
                                                ctypes.POINTER(wintypes.ULONG)]
    ntdll.NtQueryInformationProcess.restype = ctypes.c_long
    ntdll.NtUnmapViewOfSection.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
    ntdll.NtUnmapViewOfSection.restype = ctypes.c_long
    ntdll.NtCreateSection.argtypes = [ctypes.POINTER(wintypes.HANDLE),
                                      wintypes.DWORD, wintypes.LPVOID,
                                      ctypes.POINTER(ctypes.c_uint64),
                                      wintypes.DWORD, wintypes.DWORD,
                                      wintypes.HANDLE]
    ntdll.NtCreateSection.restype = ctypes.c_long
    ntdll.NtMapViewOfSection.argtypes = [wintypes.HANDLE, wintypes.HANDLE,
                                         ctypes.POINTER(ctypes.c_void_p),
                                         ctypes.c_size_t, ctypes.c_size_t,
                                         ctypes.POINTER(ctypes.c_uint64),
                                         ctypes.POINTER(ctypes.c_size_t),
                                         wintypes.DWORD, wintypes.DWORD,
                                         wintypes.DWORD]
    ntdll.NtMapViewOfSection.restype = ctypes.c_long


def write_loader_config(account_idx, purple_path):
    temp_dir = tempfile.gettempdir()
    config_path = os.path.join(temp_dir, f"hebot_loader_{account_idx}.txt")
    normalized = os.path.normpath(purple_path)
    with open(config_path, "w") as f:
        f.write(normalized + "\n")
    return config_path


def _prepare_payload_file(loader_path):
    """Write a sanitized copy of the payload with dangerous optional-header
    data directories stripped (Load Config idx=10 -> dangling GuardCF /
    SecurityCookie RVAs crash the modern loader during CFG init when built
    with /NODEFAULTLIB). Returns path to the sanitized temp file."""
    with open(loader_path, "rb") as f:
        data = bytearray(f.read())
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    opt = e_lfanew + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    dd_off = opt + (0x70 if magic == 0x20B else 0x60)
    # index 10 = IMAGE_DIRECTORY_ENTRY_LOAD_CONFIG
    struct.pack_into("<II", data, dd_off + 10 * 8, 0, 0)

    tmp = loader_path + ".sanitized.exe"
    with open(tmp, "wb") as f:
        f.write(bytes(data))
    return tmp


def _get_wow64_peb(h_proc):
    peb32 = ctypes.c_void_p(0)
    rl = wintypes.ULONG(0)
    st = ntdll.NtQueryInformationProcess(
        h_proc, PROCESS_WOW64_INFORMATION,
        ctypes.byref(peb32), ctypes.sizeof(peb32), ctypes.byref(rl))
    if st != 0 or not peb32.value:
        return 0
    return peb32.value


def _read_remote(h_proc, addr, size):
    buf = ctypes.create_string_buffer(size)
    n = ctypes.c_size_t(0)
    if not k32.ReadProcessMemory(h_proc, ctypes.c_void_p(addr),
                                 buf, size, ctypes.byref(n)):
        return None
    return buf.raw[:n.value]


def _read_remote_u32(h_proc, addr):
    buf = ctypes.create_string_buffer(4)
    n = ctypes.c_size_t(0)
    if not k32.ReadProcessMemory(h_proc, ctypes.c_void_p(addr),
                                 buf, 4, ctypes.byref(n)):
        return 0
    return struct.unpack("<I", buf.raw[:4])[0]


def _write_remote(h_proc, addr, data):
    wr = ctypes.c_size_t(0)
    return k32.WriteProcessMemory(h_proc, ctypes.c_void_p(addr),
                                  bytes(data), len(data), ctypes.byref(wr))


def _alloc_remote(h_proc, size):
    addr = k32.VirtualAllocEx(h_proc, None, size,
                              MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    return addr


def _patch_us_field(h_proc, field_addr, wide_bytes):
    """Point a remote UNICODE_STRING (x86: WORD len, WORD max, PTR32 buf)
    at a fresh remote buffer containing wide_bytes (utf-16-le, NUL-term)."""
    cur = _read_remote(h_proc, field_addr, 8)
    if not cur or len(cur) < 8:
        return False
    buf_remote = _alloc_remote(h_proc, len(wide_bytes))
    if not buf_remote:
        return False
    if not _write_remote(h_proc, buf_remote, wide_bytes):
        return False
    us = struct.pack("<HHI", len(wide_bytes) - 2, len(wide_bytes),
                     buf_remote & 0xFFFFFFFF)
    return _write_remote(h_proc, field_addr, us)


def _patch_us_field64(h_proc, field_addr, wide_bytes):
    """Same but for 64-bit UNICODE_STRING (16 bytes: WORD,WORD,pad,QWORD)."""
    cur = _read_remote(h_proc, field_addr, 16)
    if not cur or len(cur) < 16:
        return False
    buf_remote = _alloc_remote(h_proc, len(wide_bytes))
    if not buf_remote:
        return False
    if not _write_remote(h_proc, buf_remote, wide_bytes):
        return False
    us = struct.pack("<HH4xQ", len(wide_bytes) - 2, len(wide_bytes),
                     buf_remote)
    return _write_remote(h_proc, field_addr, us)


def _patch_peb_process_params(h_proc, peb_addr, new_path,
                              peb64_addr=None, new_base=None):
    """Rewrite ImagePathName + CommandLine in BOTH the WOW64 (32-bit) and
    native (64-bit) process parameters; optionally fix 64-bit ImageBase."""
    wide = new_path.encode("utf-16-le") + b"\x00\x00"
    cmdw = f'"{new_path}"'.encode("utf-16-le") + b"\x00\x00"

    ok = True
    params32 = _read_remote_u32(h_proc, peb_addr + 0x10)
    if params32:
        ok &= _patch_us_field(h_proc, params32 + 0x38, wide)
        ok &= _patch_us_field(h_proc, params32 + 0x40, cmdw)
    else:
        logger.warning("[peb] 32-bit ProcessParameters NULL")
        ok = False

    if peb64_addr:
        if new_base:
            _write_remote(h_proc, peb64_addr + 0x10,
                          struct.pack("<Q", new_base))
        raw = _read_remote(h_proc, peb64_addr + 0x20, 8)
        params64 = struct.unpack("<Q", raw)[0] if raw else 0
        if params64:
            ok &= _patch_us_field64(h_proc, params64 + 0x60, wide)
            ok &= _patch_us_field64(h_proc, params64 + 0x70, cmdw)
        else:
            logger.warning("[peb] 64-bit ProcessParameters NULL")

    logger.info(f"[peb] params patched -> {new_path} (ok={bool(ok)})")
    return ok


def hollow_svchost(account_idx, purple_path, payload_path=None):
    """Hollow svchost.exe via SEC_IMAGE section mapping.

    The payload is mapped as a genuine image section, so the Windows
    loader accepts it at PEB->ImageBaseAddress, applies relocations,
    resolves the IAT itself, then dispatches to ctx.Eax (entry point).
    """
    _setup_prototypes()

    loader_path = payload_path or BOT_LOADER_X86
    if not os.path.isfile(loader_path):
        raise RuntimeError(f"Bot loader not found: {loader_path}")

    with open(loader_path, "rb") as f:
        payload = f.read()
    pe = parse_pe(payload)
    if pe is None:
        raise RuntimeError("Invalid bot loader PE")
    if pe["machine"] != MACHINE_X86:
        raise RuntimeError(f"Bot loader must be x86, got 0x{pe['machine']:04X}")

    host = _pick_host()
    config_path = write_loader_config(account_idx, purple_path)
    cmdline = ctypes.create_unicode_buffer(f'"{host}" {account_idx}')
    workdir = ctypes.create_unicode_buffer(tempfile.gettempdir())

    si = STARTUPINFO()
    si.cb = ctypes.sizeof(si)
    pi = PROCESS_INFORMATION()

    if not k32.CreateProcessW(None, cmdline, None, None, False,
                              CREATE_SUSPENDED, None, workdir,
                              ctypes.byref(si), ctypes.byref(pi)):
        err = ctypes.get_last_error()
        raise RuntimeError(f"CreateProcess failed: {err}")

    svchost_pid = pi.dwProcessId
    logger.info(f"[{account_idx}] svchost.exe suspended (PID: {svchost_pid})")

    h_section = wintypes.HANDLE(0)
    try:
        # Textbook hollowing: map payload AT the host's original base.
        # SEC_IMAGE mapping applies relocations transparently, PEB stays
        # consistent (same base), loader resolves imports normally.
        peb_addr = _get_wow64_peb(pi.hProcess)
        if not peb_addr:
            raise RuntimeError("Cannot get WOW64 PEB")
        target_base_int = _read_remote_u32(pi.hProcess, peb_addr + 0x08)
        if not target_base_int:
            raise RuntimeError("Failed reading PEB->ImageBaseAddress")

        ntdll.NtUnmapViewOfSection(pi.hProcess, ctypes.c_void_p(target_base_int))

        # NOTE: keep this file alive for the lifetime of the target process:
        # SEC_IMAGE sections page-in lazily; deleting the backing file
        # prematurely breaks demand paging and crashes the target.
        sanitized = _prepare_payload_file(loader_path)

        GENERIC_READ = 0x80000000
        FILE_SHARE_READ = 0x1
        OPEN_EXISTING = 3
        FILE_ATTRIBUTE_NORMAL = 0x80
        h_file = k32.CreateFileW(sanitized, GENERIC_READ, FILE_SHARE_READ,
                                 None, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL,
                                 None)
        if h_file in (None, wintypes.HANDLE(-1).value, -1):
            raise RuntimeError(
                f"CreateFileW(loader) failed: {ctypes.get_last_error()}")

        status = ntdll.NtCreateSection(ctypes.byref(h_section),
                                       SECTION_ALL_ACCESS, None, None,
                                       PAGE_READONLY, SEC_IMAGE, h_file)
        k32.CloseHandle(h_file)
        if status != 0:
            raise RuntimeError(
                f"NtCreateSection failed: 0x{status & 0xFFFFFFFF:08X}")

        def nt_success(s):
            return 0 <= ctypes.c_long(s).value

        local_base = ctypes.c_void_p(target_base_int)
        view_size = ctypes.c_size_t(0)
        status = ntdll.NtMapViewOfSection(h_section, pi.hProcess,
                                          ctypes.byref(local_base),
                                          0, 0, None,
                                          ctypes.byref(view_size),
                                          VIEW_UNMAP, 0, PAGE_READWRITE)
        if not nt_success(status):
            local_base = ctypes.c_void_p(0)
            view_size = ctypes.c_size_t(0)
            status = ntdll.NtMapViewOfSection(h_section, pi.hProcess,
                                              ctypes.byref(local_base),
                                              0, 0, None,
                                              ctypes.byref(view_size),
                                              VIEW_UNMAP, 0, PAGE_READWRITE)
        if not nt_success(status):
            raise RuntimeError(
                f"NtMapViewOfSection failed: 0x{status & 0xFFFFFFFF:08X}")

        new_base = local_base.value & 0xFFFFFFFF
        logger.info(f"[{account_idx}] Mapped loader image at 0x{new_base:X} "
                    f"(size 0x{view_size.value:X})")

        # WOW64 target from 64-bit python: MUST use Wow64* context APIs,
        # plain Get/SetThreadContext would corrupt the 64-bit CONTEXT.
        ctx = aligned_context(CONTEXT86)
        ctx.ContextFlags = CONTEXT_FULL_X86
        if not k32.Wow64GetThreadContext(pi.hThread, ctypes.byref(ctx)):
            raise RuntimeError("Wow64GetThreadContext failed")

        entry = new_base + pe["entry_rva"]
        ctx.Eax = entry & 0xFFFFFFFF

        if not k32.Wow64SetThreadContext(pi.hThread, ctypes.byref(ctx)):
            raise RuntimeError("Wow64SetThreadContext failed")

        k32.ResumeThread(pi.hThread)
        logger.info(f"[{account_idx}] resumed, bot loader running (entry 0x{entry:X})")

    except Exception:
        try:
            k32.TerminateProcess(pi.hProcess, 1)
        except Exception:
            pass
        raise
    finally:
        dup = wintypes.HANDLE(0)
        if k32.DuplicateHandle(k32.GetCurrentProcess(), pi.hProcess,
                               k32.GetCurrentProcess(), ctypes.byref(dup),
                               0, False, DUPLICATE_SAME_ACCESS):
            _LAST_HOST["handle"] = dup.value
            _LAST_HOST["pid"] = svchost_pid
        k32.CloseHandle(pi.hThread)
        k32.CloseHandle(pi.hProcess)
        if h_section.value:
            k32.CloseHandle(h_section)

    return svchost_pid, config_path

