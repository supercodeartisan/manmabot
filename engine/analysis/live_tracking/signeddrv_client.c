// ============================================================================
// signeddrv_client.c - signeddrv.sys (WinNotify / Windows-Memory-Informer)
// ------------------- driver client implementation
//
// Implements the per-process VIRTUAL memory read/write primitive and kernel-
// level process discovery for signeddrv.sys. This is the drop-in replacement
// for the previous KSLD.sys (Tencent MpKslDrv) backend. signeddrv.sys is
// Microsoft-signed, so it loads without requiring Microsoft Defender to allow
// it. The game-analysis logic in __OneHelper__.c is unchanged; it calls through
// the DriverConnect / DriverAttach / DriverReadMemory front-ends.
//
// All protocol constants are isolated in signeddrv_ioctl.h and are tunable for
// a particular signeddrv build.
// ============================================================================
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <winioctl.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>

#include "signeddrv_ioctl.h"

// ---------------------------------------------------------------------------
// Device handle + cached target
// ---------------------------------------------------------------------------
static HANDLE g_SdHandle = INVALID_HANDLE_VALUE;
static uint64_t g_SdPid = 0;

// Forward declaration (SignedGetPeb is defined later; used by the PEB/LDR walk
// in GetFirstModuleNameW).
BOOL SignedGetPeb(uint64_t pid, uint64_t* peb);

// ---------------------------------------------------------------------------
// Open / close the signeddrv device
// ---------------------------------------------------------------------------
BOOL SignedOpen(void) {
    if (g_SdHandle != INVALID_HANDLE_VALUE) return TRUE;

    static const wchar_t* deviceNames[] = {
        SD_PREFERRED_DEVICE,
        SD_ALT_DEVICES
    };
    const int count = 1 + SD_ALT_DEVICE_COUNT;

    for (int i = 0; i < count; i++) {
        HANDLE h = CreateFileW(deviceNames[i],
            GENERIC_READ | GENERIC_WRITE, 0, NULL,
            OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, NULL);
        if (h != INVALID_HANDLE_VALUE) {
            g_SdHandle = h;
            return TRUE;
        }
    }
    return FALSE;
}

void SignedClose(void) {
    if (g_SdHandle != INVALID_HANDLE_VALUE) {
        CloseHandle(g_SdHandle);
        g_SdHandle = INVALID_HANDLE_VALUE;
    }
}

// ---------------------------------------------------------------------------
// Per-process virtual read (single IOCTL, chunked across pages)
// ---------------------------------------------------------------------------
// Uses the driver's per-PID virtual read IOCTL 0x222060 with a 0x20-byte
// SD_INFO_STRUCT. The driver resolves `pid` via PsLookupProcessByProcessId and
// copies the bytes from the target process directly into `buf` (a buffer in the
// calling/helper process) using MmCopyVirtualMemory. No CR3 and no attach are
// needed, so a bad CR3 cannot crash the machine. On success all `size` bytes
// land in buf.
static BOOL SignedReadOnce(uint64_t pid, uint64_t address, void* buf, uint32_t size) {
    if (g_SdHandle == INVALID_HANDLE_VALUE) return FALSE;
    if (size == 0 || size > SD_MAX_READ) return FALSE;

    SD_INFO_STRUCT req;
    RtlZeroMemory(&req, sizeof(req));
    req.Pid = (uint32_t)pid;
    req.Addr = address;
    req.Buf = (uintptr_t)buf;
    req.Size = size;

    DWORD bytesReturned = 0;
    return DeviceIoControl(g_SdHandle, SD_IOCTL_READ,
        &req, sizeof(req),
        &req, sizeof(req),
        &bytesReturned, NULL);
}

// ---------------------------------------------------------------------------
// Safety constants (BSOD prevention)
// ---------------------------------------------------------------------------
// Maximum bytes to read in a single SignedReadMemory call (16 MB cap).
#define SD_SAFETY_MAX_TOTAL    (16u * 1024u * 1024u)
// Maximum consecutive page-read failures before aborting the entire read.
// Prevents infinite loops when scanning large invalid regions.
#define SD_SAFETY_MAX_FAILS    64
// On 64-bit Windows, user-mode virtual addresses are < 0x800000000000.
// Anything at or above this is kernel/non-canonical and must never be read
// through the per-process virtual read path.
#define SD_MAX_USER_ADDR       0x7FFFFFFFFFFFULL

// Read `size` bytes from the target process's virtual address space, splitting
// across page boundaries as needed.  Includes pre-read page validation via
// VirtualQueryEx to prevent BSODs from reading unmapped/guarded pages through
// the signeddrv driver (MmCopyVirtualMemory).
BOOL SignedReadMemory(uint64_t pid, uint64_t address, void* buf, uint32_t size,
                      uint32_t* bytesRead) {
    if (g_SdHandle == INVALID_HANDLE_VALUE) return FALSE;
    if (size == 0) return FALSE;
    if (size > SD_SAFETY_MAX_TOTAL) size = SD_SAFETY_MAX_TOTAL;

    // SAFETY: reject kernel-mode / non-canonical addresses outright.
    // Per-process virtual reads should only target user-mode space.
    if (address > SD_MAX_USER_ADDR) {
        if (bytesRead) *bytesRead = 0;
        return FALSE;
    }

    // Open a limited handle for VirtualQueryEx page-state validation.
    // PROCESS_QUERY_LIMITED_INFORMATION (0x1000) works for same-session
    // processes without elevation.  Cached per-PID to avoid an OpenProcess
    // syscall on every read (major performance win for high-rate loops).
    static HANDLE s_hProc = NULL;
    static DWORD  s_hProcPid = 0;
    if (s_hProc && s_hProcPid != (DWORD)pid) {
        CloseHandle(s_hProc); s_hProc = NULL; s_hProcPid = 0;
    }
    if (!s_hProc) {
        s_hProc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE,
                              (DWORD)pid);
        s_hProcPid = (DWORD)pid;
    }
    HANDLE hProc = s_hProc;

    uint8_t* dst = (uint8_t*)buf;
    uint64_t addr = address;
    uint32_t remaining = size;
    uint32_t total = 0;
    uint32_t fails = 0;

    while (remaining > 0) {
        uint64_t pageEnd = (addr & ~(uint64_t)0xFFF) + 0x1000;
        uint32_t chunk = (uint32_t)(pageEnd - addr);
        if (chunk > remaining) chunk = remaining;
        if (chunk > SD_MAX_READ) chunk = SD_MAX_READ;

        // SAFETY: validate page state before issuing driver read.
        // If VirtualQueryEx is unavailable (handle NULL), fall through to the
        // raw read — the driver will fault, but this path should be rare.
        BOOL readable = TRUE;
        if (hProc) {
            MEMORY_BASIC_INFORMATION mbi;
            if (VirtualQueryEx(hProc, (LPCVOID)(uintptr_t)addr,
                              &mbi, sizeof(mbi)) == sizeof(mbi)) {
                if (mbi.State != MEM_COMMIT)                     readable = FALSE;
                if (mbi.Protect == PAGE_NOACCESS)                readable = FALSE;
                /* NCGuard often marks decrypted code PAGE_GUARD. VirtualQueryEx
                   would skip those pages, but MmCopyVirtualMemory via signeddrv
                   still returns the live (decrypted) bytes — so do NOT treat
                   PAGE_GUARD / NOCACHE / WRITECOMBINE as unreadable here. */
            }
            // If VirtualQueryEx itself fails (returns 0), readable stays TRUE
            // and we attempt the read — the driver will handle the fault.
        }

        if (!readable || !SignedReadOnce(pid, addr, dst, chunk)) {
            fails++;
            if (fails >= SD_SAFETY_MAX_FAILS) break;
            // Skip to next page boundary instead of aborting entirely.
            uint32_t skip = (uint32_t)(pageEnd - addr);
            if (skip > remaining) skip = remaining;
            addr += skip;
            remaining -= skip;
            continue;
        }

        dst += chunk;
        addr += chunk;
        total += chunk;
        remaining -= chunk;
        fails = 0;  // reset consecutive-failure counter on success
    }

    if (hProc) { /* cached; do not close here */ }
    if (bytesRead) *bytesRead = total;
    return total > 0;
}

// Case/extension-insensitive compare of a wide module name against a target.
static int SignedNameEquals(const wchar_t* name, const wchar_t* target) {
    if (!name || !target) return 0;
    // Strip any directory prefix from the module name.
    const wchar_t* base = name;
    for (const wchar_t* p = name; *p; p++)
        if (*p == L'\\' || *p == L'/') base = p + 1;

    size_t lb = wcslen(base);
    size_t lt = wcslen(target);
    if (lb >= 4 && _wcsicmp(base + lb - 4, L".exe") == 0) lb -= 4;
    if (lt >= 4 && _wcsicmp(target + lt - 4, L".exe") == 0) lt -= 4;
    return lb == lt && _wcsnicmp(base, target, lb) == 0;
}

// Walk PEB->Ldr->InMemoryOrderModuleList (64-bit layout) for `pid` via the
// driver and return the first module's BaseDllName (the process executable).
// Returns TRUE and fills outName (wide) on success.
static BOOL GetFirstModuleNameW(uint64_t pid, wchar_t* outName, size_t outLen) {
    if (!outName || outLen == 0) return FALSE;
    outName[0] = L'\0';

    uint64_t peb = 0;
    if (!SignedGetPeb(pid, &peb) || !peb) return FALSE;

    // 64-bit PEB->Ldr at +0x18.
    uint64_t ldr = 0;
    if (!SignedReadMemory(pid, peb + 0x18, &ldr, sizeof(ldr), NULL) || !ldr) return FALSE;

    // Ldr->InMemoryOrderModuleList.Flink at +0x20 (LIST_ENTRY at +0x20 in _PEB_LDR_DATA).
    uint64_t listHead = 0;
    if (!SignedReadMemory(pid, ldr + 0x20, &listHead, sizeof(listHead), NULL) || !listHead) return FALSE;

    // LDR_DATA_TABLE_ENTRY (x64): InMemoryOrderLinks @+0x10, DllBase @+0x30,
    // BaseDllName UNICODE_STRING @+0x58. listHead is Flink of first entry.
    uint64_t cur = listHead;
    int guard = 0;
    while (cur && guard++ < 512) {
        uint64_t entry = cur - 0x10;

        // UNICODE_STRING BaseDllName @+0x58: { Length, MaxLen, pad, Buffer }.
        USHORT nameLen = 0;
        uint64_t nameBuf = 0;
        {
            uint8_t raw[16];
            if (!SignedReadMemory(pid, entry + 0x58, raw, 16, NULL)) break;
            memcpy(&nameLen, raw, 2);
            memcpy(&nameBuf, raw + 8, 8);
        }
        if (nameBuf && nameLen > 0 && nameLen < 512) {
            size_t cap = nameLen / sizeof(wchar_t);
            if (cap >= outLen) cap = outLen - 1;
            uint32_t got = 0;
            if (SignedReadMemory(pid, nameBuf, outName, (uint32_t)(cap * sizeof(wchar_t)), &got) && got) {
                outName[got / sizeof(wchar_t)] = L'\0';
                return TRUE;
            }
        }

        uint64_t next = 0;
        if (!SignedReadMemory(pid, cur, &next, sizeof(next), NULL)) break;
        if (!next || next == listHead) break;
        cur = next;
    }
    return FALSE;
}

// Resolve `pid`'s executable image name via the driver and compare to target.
static BOOL ProcessImageNameMatches(uint64_t pid, const wchar_t* target) {
    wchar_t name[260];
    if (!GetFirstModuleNameW(pid, name, 260)) return FALSE;
    return SignedNameEquals(name, target);
}

// ---------------------------------------------------------------------------
// Kernel-level process discovery: find a process by name -> PID
// ---------------------------------------------------------------------------
// The driver's 0x222010 PROCESS_ID ioctl is NOT a usable name->PID lookup (it
// ignores its input and scans a hardcoded list), so we implement discovery
// ourselves at kernel level through the driver:
//
//   1. Enumerate candidate PIDs with an id-only system snapshot. (Only the
//      PID list is obtained here; every memory read below is served by the
//      driver, so no game memory is touched from user mode.)
//   2. For each candidate PID, ask the driver for its PEB base (0x22204C,
//      PsLookupProcessByProcessId -> PsGetProcessPeb -> 64-bit PEB).
//   3. Walk PEB->Ldr->InMemoryOrderModuleList with SignedReadMemory (driver
//      per-process virtual reads) and read the FIRST module's BaseDllName -
//      that is the process executable image name.
//   4. Compare BaseDllName against `processName` (case-insensitive,
//      extension-insensitive) and return the matching PID.
//
// This keeps process discovery at kernel level (driver reads), satisfying the
// requirement that the helper not use a user-mode snapshot for the answer.
BOOL SignedFindProcess(const wchar_t* processName, uint64_t* pid) {
    if (g_SdHandle == INVALID_HANDLE_VALUE) return FALSE;
    if (!pid || !processName) return FALSE;

    // A minimal UNICODE_STRING (Length/MaximumLength/Pointer) for the image name.
    typedef struct _SD_UNICODE_STRING {
        USHORT Length;
        USHORT MaximumLength;
        PVOID  Buffer;
    } SD_UNICODE_STRING;

    // _SYSTEM_PROCESS_INFORMATION truncated to the fields we need.
    typedef struct _SPI_MIN {
        ULONG  NextEntryOffset;
        ULONG  ThreadCount;
        BYTE   Reserved1[48];
        SD_UNICODE_STRING ImageName;   // +0x38
        LONG   BasePriority;
        HANDLE UniqueProcessId;       // +0x50
    } SPI_MIN;

    typedef LONG(NTAPI* Fn_NtQueryInfo)(ULONG, PVOID, ULONG, PULONG);
    Fn_NtQueryInfo pQuery = (Fn_NtQueryInfo)GetProcAddress(
        GetModuleHandleW(L"ntdll.dll"), "NtQuerySystemInformation");
    if (!pQuery) return FALSE;

    DWORD foundPid = 0;
    ULONG bufSize = 0x10000;
    PVOID buffer = malloc(bufSize);
    if (!buffer) return FALSE;

    for (int attempt = 0; attempt < 8 && foundPid == 0; attempt++) {
        ULONG needed = 0;
        if (pQuery(5 /*SystemProcessInformation*/, buffer, bufSize, &needed) == 0) {
            SPI_MIN* si = (SPI_MIN*)buffer;
            for (;;) {
                HANDLE upid = si->UniqueProcessId;
                if (upid && (ULONG_PTR)upid > 4) {
                    uint64_t cand = (uint64_t)(ULONG_PTR)upid;
                    if (ProcessImageNameMatches(cand, processName)) {
                        foundPid = (DWORD)cand;
                        break;
                    }
                }
                if (!si->NextEntryOffset) break;
                si = (SPI_MIN*)((BYTE*)si + si->NextEntryOffset);
            }
            break;
        }
        if (needed > bufSize) {
            free(buffer);
            bufSize = needed + 0x10000;
            buffer = malloc(bufSize);
            if (!buffer) break;
        } else {
            break;
        }
    }

    free(buffer);
    if (foundPid) { *pid = foundPid; return TRUE; }
    return FALSE;
}

// ---------------------------------------------------------------------------
// Get the PEB base address of a process via the driver
// ---------------------------------------------------------------------------
BOOL SignedGetPeb(uint64_t pid, uint64_t* peb) {
    if (g_SdHandle == INVALID_HANDLE_VALUE) return FALSE;
    if (!peb) return FALSE;

    SD_PEB_REQ req;
    RtlZeroMemory(&req, sizeof(req));
    req.Pid = (uint32_t)pid;   // driver reads Pid as a dword (0x22204C)

    DWORD bytesReturned = 0;
    BOOL ok = DeviceIoControl(g_SdHandle, SD_IOCTL_PEB,
        &req, sizeof(req),
        &req, sizeof(req),
        &bytesReturned, NULL);
    if (!ok) return FALSE;
    *peb = req.PEB;
    return TRUE;
}

// ---------------------------------------------------------------------------
// Get the module base address for a virtual address via the driver
// ---------------------------------------------------------------------------
// NOTE: the 0x222008 MODULE ioctl validates the PE header at +0x10 via a CR3
// page-walk. It requires a VALID CR3 (obtainable only from the unreliable
// 0x222014 finder), so this helper is best-effort and may return FALSE.
BOOL SignedGetModuleBase(uint64_t pid, uint64_t address, uint64_t* moduleBase) {
    if (g_SdHandle == INVALID_HANDLE_VALUE) return FALSE;
    if (!moduleBase) return FALSE;

    SD_MODULE_REQ req;
    RtlZeroMemory(&req, sizeof(req));
    req.Pid = (uint32_t)pid;
    req.Address = address;

    DWORD bytesReturned = 0;
    BOOL ok = DeviceIoControl(g_SdHandle, SD_IOCTL_MODULE,
        &req, sizeof(req),
        &req, sizeof(req),
        &bytesReturned, NULL);
    if (!ok) return FALSE;
    *moduleBase = req.Address;
    return TRUE;
}

// ---------------------------------------------------------------------------
// Attach helper to a target PID (cached for later reads)
// ---------------------------------------------------------------------------
void SignedSetTarget(uint64_t pid) {
    g_SdPid = pid;
}

uint64_t SignedGetTarget(void) {
    return g_SdPid;
}
