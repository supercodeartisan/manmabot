// ============================================================================
// signeddrv_client.h - signeddrv.sys (WinNotify / Windows-Memory-Informer)
// driver client
// ----------------------------------------------------------------------------
// Public API for the signeddrv per-process virtual-memory backend. See
// signeddrv_client.c for implementation details and signeddrv_ioctl.h for the
// tunable protocol layer. This is the drop-in replacement for the previous
// ksld_client (Tencent KSLD / MpKslDrv) backend.
// ============================================================================
#ifndef SIGNEDDRV_CLIENT_H
#define SIGNEDDRV_CLIENT_H

#include <windows.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

// Open / close the signeddrv device (\\.\WinNotify).
BOOL SignedOpen(void);
void SignedClose(void);

// Read `size` bytes from the target process's virtual address space.
BOOL SignedReadMemory(uint64_t pid, uint64_t address, void* buf, uint32_t size,
                      uint32_t* bytesRead);

// Kernel-level process discovery: find a process by name -> PID.
// Enumerates candidate PIDs (id-only snapshot), then for each walks the
// target's PEB->Ldr->InMemoryOrderModuleList via the driver (PEB IOCTL +
// per-process virtual reads) and compares the first module's BaseDllName
// (the process executable) against `processName` (case-insensitive).
BOOL SignedFindProcess(const wchar_t* processName, uint64_t* pid);

// Get the PEB base address of a process via the driver.
BOOL SignedGetPeb(uint64_t pid, uint64_t* peb);

// Get the module base address for a virtual address via the driver.
BOOL SignedGetModuleBase(uint64_t pid, uint64_t address, uint64_t* moduleBase);

// Cache the target PID for later reads.
void SignedSetTarget(uint64_t pid);
uint64_t SignedGetTarget(void);

#ifdef __cplusplus
}
#endif

#endif // SIGNEDDRV_CLIENT_H
