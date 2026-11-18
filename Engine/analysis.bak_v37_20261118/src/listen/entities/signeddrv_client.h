/* Reconstructed declarations for the existing signeddrv_client.obj.
   The .c/.h sources are not in this tree; call shapes match print_state.c. */
#pragma once
#include <stdint.h>
#include <windows.h>

int SignedOpen(void);
void SignedClose(void);
int SignedGetPeb(DWORD pid, uint64_t* peb);
int SignedReadMemory(DWORD pid, uint64_t addr, void* buf, uint32_t size, uint32_t* bytesRead);
void SignedSetTarget(DWORD pid);
