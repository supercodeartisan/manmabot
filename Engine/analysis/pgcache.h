/* Snapshot page cache in front of SignedReadMemory.
   Include after the signeddrv header. Call pg_reset() at the start of every
   snapshot so the next tick reads live bytes. A hit copies the same bytes a
   fresh read would return. Reads larger than one page bypass the cache, so
   heap-window scans keep their existing call pattern.
   The includer must have declared SignedReadMemory. */
#ifndef PGCACHE_H
#define PGCACHE_H
#include <windows.h>
#include <stdint.h>
#include <string.h>

#define PG_SLOTS 128
#define PG_PAGE  0x1000u

typedef struct PgSlot {
    uint64_t base;
    uint32_t len;
    uint32_t gen;
    uint8_t data[PG_PAGE];
} PgSlot;

static PgSlot g_pgSlots[PG_SLOTS];
static uint32_t g_pgGen = 1;
static HANDLE g_pgProc = NULL;
static DWORD g_pgProcPid = 0;

static void pg_reset(void) {
    g_pgGen++;
    if (g_pgGen == 0) {
        memset(g_pgSlots, 0, sizeof(g_pgSlots));
        g_pgGen = 1;
    }
}

static HANDLE pg_proc(uint64_t pid) {
    if (g_pgProc && g_pgProcPid != (DWORD)pid) {
        CloseHandle(g_pgProc);
        g_pgProc = NULL;
        g_pgProcPid = 0;
    }
    if (!g_pgProc) {
        g_pgProc = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, (DWORD)pid);
        g_pgProcPid = (DWORD)pid;
    }
    return g_pgProc;
}

static PgSlot* pg_slot(uint64_t page, int create) {
    uint32_t i0 = (uint32_t)((page >> 12) & (PG_SLOTS - 1));
    uint32_t i;
    for (i = 0; i < 16; i++) {
        PgSlot* s = &g_pgSlots[(i0 + i) & (PG_SLOTS - 1)];
        if (s->gen == g_pgGen && s->base == page) return s;
        if (create && s->gen != g_pgGen) {
            s->base = page;
            s->len = 0;
            s->gen = g_pgGen;
            return s;
        }
    }
    if (!create) return NULL;
    {
        PgSlot* s = &g_pgSlots[i0];
        s->base = page;
        s->len = 0;
        s->gen = g_pgGen;
        return s;
    }
}

static int pg_fill(uint64_t pid, PgSlot* s) {
    uint32_t want = PG_PAGE;
    uint32_t br = 0;
    HANDLE hp = pg_proc(pid);
    if (hp) {
        MEMORY_BASIC_INFORMATION mbi;
        if (VirtualQueryEx(hp, (LPCVOID)(uintptr_t)s->base, &mbi, sizeof(mbi)) == sizeof(mbi)) {
            uint64_t rend;
            if (mbi.State != MEM_COMMIT || mbi.Protect == PAGE_NOACCESS) return 0;
            rend = (uint64_t)(uintptr_t)mbi.BaseAddress + (uint64_t)mbi.RegionSize;
            if (rend <= s->base) return 0;
            if (rend - s->base < (uint64_t)want) want = (uint32_t)(rend - s->base);
        }
    }
    if (!SignedReadMemory(pid, s->base, s->data, want, &br) || br == 0) return 0;
    s->len = br;
    return 1;
}

static int pg_serve(uint64_t addr, void* buf, uint32_t n) {
    uint8_t* dst = (uint8_t*)buf;
    while (n) {
        uint64_t page = addr & ~(uint64_t)0xFFF;
        uint32_t off = (uint32_t)(addr - page);
        uint32_t chunk = PG_PAGE - off;
        PgSlot* s;
        if (chunk > n) chunk = n;
        s = pg_slot(page, 0);
        if (!s || off + chunk > s->len) return 0;
        memcpy(dst, s->data + off, chunk);
        dst += chunk;
        addr += chunk;
        n -= chunk;
    }
    return 1;
}

/* 1 when n bytes were copied. *drvCalls counts SignedReadMemory invocations. */
static int pg_read(uint64_t pid, uint64_t addr, void* buf, uint32_t n, int* drvCalls) {
    uint64_t a;
    uint32_t left;
    int calls = 0;
    if (drvCalls) *drvCalls = 0;
    if (!buf || !n || !pid) return 0;
    if (n > PG_PAGE) {
        uint32_t br = 0;
        if (drvCalls) *drvCalls = 1;
        return SignedReadMemory(pid, addr, buf, n, &br) && br == n;
    }
    if (pg_serve(addr, buf, n)) return 1;
    a = addr;
    left = n;
    while (left) {
        uint64_t page = a & ~(uint64_t)0xFFF;
        uint32_t off = (uint32_t)(a - page);
        uint32_t chunk = PG_PAGE - off;
        PgSlot* s;
        if (chunk > left) chunk = left;
        s = pg_slot(page, 0);
        if (!s || off + chunk > s->len) {
            uint32_t br = 0;
            s = pg_slot(page, 1);
            calls++;
            if (!s || !pg_fill(pid, s) || off + chunk > s->len) {
                if (drvCalls) *drvCalls = calls + 1;
                return SignedReadMemory(pid, addr, buf, n, &br) && br == n;
            }
        }
        a += chunk;
        left -= chunk;
    }
    if (drvCalls) *drvCalls = calls;
    return pg_serve(addr, buf, n);
}

#endif
