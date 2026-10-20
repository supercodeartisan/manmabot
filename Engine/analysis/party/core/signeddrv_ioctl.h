// ============================================================================
// signeddrv_ioctl.h - Tunable signeddrv.sys (WinNotify / Windows-Memory-Informer)
// protocol layer
// ----------------------------------------------------------------------------
// signeddrv.sys is a Microsoft-signed memory driver (Windows-Memory-Informer /
// "WinNotify" by hoangprod). It exposes per-process virtual-memory primitives
// and kernel-level process discovery. Unlike KSLD.sys (Tencent MpKslDrv),
// signeddrv.sys is digitally signed such that it loads without requiring
// Microsoft Defender to allow it, so it is appropriate for the helper.
//
// The helper uses the driver's per-PID virtual read path: IOCTL 0x222060 with a
// 0x20-byte SD_INFO_STRUCT. The driver resolves the process by PID via
// PsLookupProcessByProcessId and copies with MmCopyVirtualMemory:
//
//     MmCopyVirtualMemory(SourceProcess = EPROC(pid),
//                         SourceAddress = Addr,            // remote address
//                         TargetProcess = IoGetCurrentProcess(),
//                         TargetAddress = Buf,             // caller's buffer
//                         BufferSize    = Size,
//                         PreviousMode  = 0, &BytesRead);
//
// This is the safe, crash-free path: no page-walk and no KeStackAttachProcess,
// so no caller-supplied CR3 is needed and the machine cannot fault.
//
// NOTE on the CR3-based IOCTLs: 0x222000 (READ) / 0x222004 (COPY) require a
// caller-supplied CR3 (field +0x20). 0x222000 returns STATUS_ACCESS_DENIED
// (0xC0000022) when CR3 == 0 - there is NO PID-attach fallback. A non-zero CR3
// makes the driver page-walk physical memory, which can fault the machine if the
// CR3 is bad. The helper has no safe CR3 source and therefore does NOT use
// 0x222000. 0x222014 is an unreliable CR3 finder and is NOT used.
//
// This header isolates ALL driver constants (device name, IOCTL codes, request
// buffer layouts) so they can be tuned once a working constant set is confirmed
// on a live system.
//
// CONFIRMED PROTOCOL (static RE of the signeddrv.sys dispatch + live probe)
// ----------------------------------------------------------------------------
// Device      : \Device\WinNotify  ->  \\.\WinNotify
// Request     : the request struct is passed as the DeviceIoControl input
//               buffer (same buffer may be passed as output). The dispatch
//               switch matches the IoControlCode and reads the struct from the
//               IOCTL buffer (METHOD_BUFFERED-style shared buffer).
//
//  0x222000  CR3 READ (in 0x28)      { Flag@0, Dst@8, Src@0x10, Size@0x18,
//                                     CR3@0x20 }. REQUIRES CR3 != 0 (page-walk),
//                                     else STATUS_ACCESS_DENIED. NOT used.
//  0x222004  CR3 COPY (in 0x28)       { ... CR3@0x20 } (sub_140002E3C). NOT used.
//  0x222008  MODULE (in 0x20)         validates MZ/PE at +0x10 via a CR3
//                                     page-walk; module base returned @ +0x10
//                                     (0xC000000D if +0x10 == 0). Requires a
//                                     valid CR3.
//  0x22200C  MODULE-NAME LOOKUP (in 0x18); DANGEROUS. First qword @0 is
//                                     dereferenced as a POINTER to a module name
//                                     and matched against SystemModuleInformation
//                                     (handler sub_1400016D8); result @ +0x10.
//                                     NOT a PEB lookup - sending a PID here makes
//                                     the driver deref the PID as a pointer and
//                                     BSOD the machine. NEVER use.
//  0x222010  PROCESS_ID (in 8)        value ignored; scans a hardcoded list for a
//                                     "ConT"/0x200000 marker; PID @ +0.
//                                     Not usable as name->PID (see SignedFindProcess).
//  0x222014  CR3-FINDER (in 0x18)     { Pid @0, out @8, flag @0x10 }; CR3 @ +8.
//                                     Unreliable / dangerous (see above). Not used.
//  0x22201C / 0x222020  (in 4)        no-op STATUS_SUCCESS.
//  0x222024  HANDSHAKE (in 0x18)      writes magic 0x191919 @ +8 and 0x212121 @ +0x10.
//  0x222040  (in 0x38)                struct-copy passthrough (0x30 bytes from
//                                     the input buffer, written back).
//  0x222044  (in 0x18)                sub_140003200 { A @0, B @8, C @0x10 }.
//  0x222048  GET_IMAGE_BASE (in 0x10) { Pid @0 }; base @ +8
//                                     (PsLookupProcessByProcessId +
//                                     PsGetProcessSectionBaseAddress).
//  0x22204C  GET_PEB (in 0x10)        { Pid (dword) @0 }; PEB @ +8
//                                     (PsLookupProcessByProcessId +
//                                     PsGetProcessPeb). THE PEB LOOKUP TO USE.
//  0x222050  (in 0x10)                calls 0x140001854 then slot 0x140004140.
//  0x222054  (in 0xC)                 sub_140001E48 { A@0, B@4, C@8, D@0xA }.
//  0x222058  ALLOC_VIRTUAL (in 0x28)  attach + ZwAllocateVirtualMemory
//                                     in target (BaseAddress @8, RegionSize @0x10,
//                                     AllocationType @0x18, Protect @0x20).
//  0x22205C  PROTECT_VIRTUAL (in 0x20) attach + ZwProtectVirtualMemory
//                                     in target (Base @8, RegionSize @0x10,
//                                     NewProtect @0x18, OldProtect @0x1c).
//  0x222060  PER-PID VIRTUAL READ (in 0x20)  sub_140002B78: IoGetCurrentProcess +
//                                     PsLookupProcessByProcessId +
//                                     MmCopyVirtualMemory(pid, Addr -> Buf).
//                                     Safe, no CR3, no attach.
//                                     THE READ THE HELPER USES.
//  anything else                     dispatch default: STATUS_SUCCESS.
// ============================================================================
#ifndef SIGNEDDRV_IOCTL_H
#define SIGNEDDRV_IOCTL_H

#include <windows.h>
#include <winioctl.h>
#include <stdint.h>

// ---------------------------------------------------------------------------
// 1. DEVICE NAME
// ---------------------------------------------------------------------------
#define SD_PREFERRED_DEVICE  L"\\\\.\\WinNotify"
#define SD_ALT_DEVICE_COUNT  2
#define SD_ALT_DEVICES \
    L"\\\\.\\WinNotify", \
    L"\\\\.\\GLOBALROOT\\Device\\WinNotify"

// ---------------------------------------------------------------------------
// 2. IOCTL CODES
// ---------------------------------------------------------------------------
#define SD_IOCTL_READ       0x222060   // per-PID virtual READ (MmCopyVirtualMemory)
#define SD_IOCTL_READ_CR3   0x222000   // CR3-based READ (requires non-zero CR3, not used)
#define SD_IOCTL_WRITE      0x222004   // CR3-based COPY (requires CR3, not used)
#define SD_IOCTL_MODULE     0x222008
#define SD_IOCTL_PEB        0x22204C   // GET_PEB (Pid dword@0, PEB@+8) - REAL PEB ioctl
// 0x22200C is a MODULE-NAME lookup that dereferences input[0] as a string
// pointer (sub_1400016D8). It is NOT a PEB lookup: sending a PID there crashes
// the machine. It must not be used for anything.
#define SD_IOCTL_PROCESS    0x222010
#define SD_IOCTL_0x14       0x222014   // CR3 finder (unreliable, not used)
// 0x222000 (CR3 READ) requires a non-zero CR3 and returns STATUS_ACCESS_DENIED
// with CR3 == 0; the helper has no safe CR3 source and must use SD_IOCTL_READ
// (0x222060) for per-PID virtual reads.

// Max request chunk for a single virtual read (page size). Page-chunking keeps
// each request bounded and gives the caller per-page failure granularity.
#define SD_MAX_READ  0x1000

// ---------------------------------------------------------------------------
// 3. REQUEST / RESPONSE BUFFER LAYOUTS (confirmed)
// ---------------------------------------------------------------------------
// Per-process virtual READ - IOCTL 0x222060 (0x20 bytes in).
// The driver's handler (sub_140002B78) does IoGetCurrentProcess +
// PsLookupProcessByProcessId + MmCopyVirtualMemory and copies `Size` bytes from
// `Addr` (in the target process) into `Buf` (in the calling/helper process).
// No CR3 and no attach are needed. The data lands directly at `Buf`; the request
// struct is passed as both the input and output buffer.
typedef struct _SD_INFO_STRUCT {
    uint32_t Pid;       // +0x00 target process ID
    uint32_t _pad;      // +0x04
    uint64_t Addr;      // +0x08 target virtual address (read source)
    uint64_t Buf;       // +0x10 user buffer pointer (in calling process, dest)
    uint64_t Size;      // +0x18 bytes to transfer
} SD_INFO_STRUCT;       // total 0x20

// CR3-based READ/COPY layout - IOCTLs 0x222000 / 0x222004 (0x28 bytes). NOT used
// by the helper: 0x222000 REQUIRES a non-zero CR3 (returns STATUS_ACCESS_DENIED
// with CR3 == 0) and page-walks physical memory, which can fault the machine with
// a bad CR3.
typedef struct _SD_CR3_STRUCT {
    uint64_t Flag;      // +0x00 must be non-zero
    uint64_t Dst;       // +0x08 destination (user) VA
    uint64_t Src;       // +0x10 source (kernel/mapped) VA
    uint64_t Size;      // +0x18 bytes to transfer
    uint64_t CR3;       // +0x20 page-table base; MUST be non-zero
} SD_CR3_STRUCT;        // total 0x28

// PEB lookup - IOCTL 0x22204C (0x10 bytes in); PEB written back at +8.
// The driver's handler (sub_140002964) does PsLookupProcessByProcessId +
// PsGetProcessPeb and returns Information = 0x10. NOTE: only the first 4
// bytes (Pid) are input; the driver reads the PEB as a dword PID @ +0.
typedef struct _SD_PEB_REQ {
    uint32_t Pid;       // +0x00 target process ID (dword)
    uint32_t _pad;      // +0x04
    uint64_t PEB;       // +0x08 output: PEB base address
} SD_PEB_REQ;           // total 0x10

// Module-base lookup - IOCTL 0x222008 (0x20 bytes in); module base written
// back at +0x10. Requires a valid CR3 (validates MZ/PE via page-walk).
typedef struct _SD_MODULE_REQ {
    uint32_t Pid;       // +0x00 target process ID
    uint32_t _pad;      // +0x04
    uint64_t _reserved; // +0x08
    uint64_t Address;   // +0x10 address to validate / module base (in/out)
    uint64_t CR3;       // +0x18 page-table base
} SD_MODULE_REQ;        // total 0x20

// Process-name lookup - IOCTL 0x222010 (exactly 8 bytes in). The dispatch does
// `cmp InputBufferLength, 8; jne STATUS_INFO_LENGTH_MISMATCH`, then IGNORES the
// input entirely and scans a HARDCODED process list for a "ConT"/0x200000
// marker (its own launch/worker thread), writing that PID back at +0. It is
// therefore NOT usable as a name->PID API for arbitrary processes.
//
// Kernel-level process discovery is instead implemented in SignedFindProcess()
// by walking the target's PEB/LDR via the driver's PEB IOCTL (0x22204C) and
// per-process virtual reads (SignedReadMemory). See signeddrv_client.c.
typedef struct _SD_PROCESS_REQ {
    uint64_t NamePointer;  // input: SDK placeholder (ignored by the driver)
} SD_PROCESS_REQ;

typedef struct _SD_PROCESS_RESP {
    uint64_t Pid;          // output: placeholder (not used)
} SD_PROCESS_RESP;

#endif // SIGNEDDRV_IOCTL_H
