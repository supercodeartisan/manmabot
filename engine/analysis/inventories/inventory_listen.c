// ============================================================================
// inventory_listen.c - ONE-SHOT inventory reader for LC.exe (named pipe)
// ----------------------------------------------------------------------------
// Reads the live bag via the signed driver (same pipe protocol as
// realtime_monitor_full --pipe). Items come from InventorySubsystem
// sub[26] + vector (inventory_offsets.txt). Names use the static FNV
// table first; a heap scan is only a fallback for missed mids.
// Writes inv.json after a successful scan.
//
// Protocol (one JSON line per request, as realtime_monitor_full):
//   "ping"              -> {"cmd":"ping","pong":true,"pid":"..."}
//   "inventory"         -> full scan + {"cmd":"inventory", ...items...}
//
// JSON file inv.json is written after every successful inventory scan.
//
// ItemEntity heap objects are found by vtable signature
// (ItemEntityVtableRva) in committed private heap. The dword at +0x44 is a
// per-kind group, not bag order. Slot is the item's index in the inventory
// pointer array (object base or +8/+0x10/... aliases), same as inventory_reader.
// ============================================================================
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <io.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include "signeddrv_client.h"

// ---------------------------------------------------------------------------
// Tunables
// ---------------------------------------------------------------------------
#define MAX_ITEMS          512
#define MAX_STRIDES        1024

#define PIPE_NAME          L"\\\\.\\pipe\\inv_listen"
#define PIPE_IN_BUFSIZE    0x10000

// Heap/valid ranges (overridable from offsets.json).
#define HEAP_WIN           0x10000
#define COARSE_STRIDE      0x20000000ULL   /* 512MB coarse-map stride */
#define COARSE_SAMPLES     2
#define FINE_STEP          0x100000ULL     /* cap on a hole skip (1MB) */
#define PAGE_PROBE         0x1000
#define MAX_WINDOWS        16384           /* hit windows kept for the container pass */
#define MAX_DRIVER_READS   120000          /* item scan + name-key scan */
#define MAX_PROBE_STEPS    8192
#define VALID_PTR_LO       0x10000000000ULL
#define VALID_PTR_HI       0x40000000000ULL

// ItemEntity field offsets (JSON then inventory_offsets.txt).
// id = ITEM_CFG +0x30 — Python shop matching uses this, not instance/tmpl.
static uint64_t offItemEntityVtable = 0x11C6640ULL;  // LC.exe+ITEM_VFT (26.09.23b)
static uint32_t oItemStruct = 0x08, oItemId = 0x30, oItemCount = 0x38, oItemGuid = 0x10;
static uint32_t oItemKind = 0x44;                   // per-kind/group (NOT bag slot)
static uint32_t oItemFmt = 0x68;                    // inline format SSO (holds "$N (count)")

// Static id -> ($token, name) fallback. Live names come from the client's
// "1_<msgid>" key map (see resolveItemNames); this table is only a backup.
typedef struct { uint32_t id; const char* tok; const char* name; } ItemName;
static const ItemName ITEM_NAMES[] = {
    {    5, "$4",   "아데나" },
    {    7, "$61",  "화살" },
    {   24, "$67",  "양초" },
    {   27, "$174", "말하는 두루마기" },
    {   31, "$69",  "몽둥이" },
    {   42, "$74",  "도리깨" },
};
static const char* itemNameFor(uint32_t id) {
    for (size_t i = 0; i < sizeof(ITEM_NAMES) / sizeof(ITEM_NAMES[0]); i++)
        if (ITEM_NAMES[i].id == id) return ITEM_NAMES[i].name;
    return NULL;
}
static const char* itemTokFor(uint32_t id) {
    for (size_t i = 0; i < sizeof(ITEM_NAMES) / sizeof(ITEM_NAMES[0]); i++)
        if (ITEM_NAMES[i].id == id) return ITEM_NAMES[i].tok;
    return NULL;
}

// Ranges: defaults above, overridable from offsets.json (strings).
static uint64_t g_heapLo = 0, g_heapHi = 0;
static uint64_t g_validPtrLo = VALID_PTR_LO, g_validPtrHi = VALID_PTR_HI;

/* InventorySubsystem chain (T7). TXT overlay wins after a service patch. */
static uint32_t invMgr = 0x1668860u, invHolder = 0xD0u;
static uint32_t invSubBeg = 0x180u, invSubEnd = 0x188u;
static uint32_t invSubIdx = 26, invSubVft = 0x11C6BE8u;
static uint32_t invVecBeg = 0x3D8u, invVecEnd = 0x3E0u;

/* Static name table (FNV-1a). Heap scan is fallback only. */
static uint32_t msgAnchorRva = 0x1668888u;
static uint32_t msgRecNext = 0x00, msgRecName = 0x38;
static uint32_t msgNameKr = 0x00, msgNameTw = 0x08;
static uint32_t msgNodeLang = 0x10, msgNodeText = 0x30;
static uint32_t msgBucketStride = 0x10, msgBucketMask = 0xFFFFu;
static uint64_t msgFnvOffset = 0xcbf29ce484222325ULL;
static uint64_t msgFnvPrime = 0x100000001b3ULL;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
static DWORD    g_pid = 0;
static uint64_t g_base = 0;
static uint64_t g_modSize = 0;
static int      g_serveMode = 0;         // --serve: JSON line protocol on stdin/stdout
static int      g_pipeMode = 0;          // --pipe: named-pipe server (\\.\pipe\inv_listen)
static int      g_dllMode = 0;           // in-process DLL (no console / pipe)

#define LOG(fmt, ...) do { \
    if (g_dllMode) break; \
    if (g_serveMode) fprintf(stderr, fmt, ##__VA_ARGS__); \
    else printf(fmt, ##__VA_ARGS__); \
} while (0)

// ---------------------------------------------------------------------------
// Low-level helpers
// ---------------------------------------------------------------------------
static DWORD findPid(const wchar_t* name) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    PROCESSENTRY32W pe; pe.dwSize = sizeof(pe);
    DWORD pid = 0;
    if (Process32FirstW(snap, &pe)) do {
        if (_wcsicmp(pe.szExeFile, name) == 0) { pid = pe.th32ProcessID; break; }
    } while (Process32NextW(snap, &pe));
    CloseHandle(snap);
    return pid;
}

static BOOL readMem(uint64_t addr, void* buf, uint32_t size) {
    uint32_t br = 0;
    return SignedReadMemory(g_pid, addr, buf, size, &br) && br == size;
}

/* Same PEB walk as print_state / realtime_monitor (no SignedGetImageBase). */
static int getModuleBase(uint64_t* base) {
    uint64_t peb = 0, ldr = 0, listHead = 0, cur = 0, img = 0;
    if (!SignedGetPeb(g_pid, &peb) || !peb) return 0;
    if (readMem(peb + 0x10, &img, 8) && img) {
        *base = img;
        return 1;
    }
    if (!readMem(peb + 0x18, &ldr, 8) || !ldr) return 0;
    if (!readMem(ldr + 0x20, &listHead, 8) || !listHead) return 0;
    cur = listHead;
    for (int guard = 0; guard < 5000 && cur && cur != (ldr + 0x20); guard++) {
        uint64_t entry = cur - 0x10;
        uint64_t dllBase = 0;
        if (readMem(entry + 0x30, &dllBase, 8) && dllBase) { *base = dllBase; return 1; }
        if (!readMem(cur, &cur, 8)) return 0;
    }
    return 0;
}

// Match a "  \"key\": <decimal>" line and return the integer value, else -1.
static long long jsonNum(const char* line, const char* key) {
    char k[64];
    long long v = 0;
    if (sscanf(line, "  \"%63[^\"]\": %lld", k, &v) == 2 && strcmp(k, key) == 0) return v;
    return -1;
}

// String-valued JSON numbers ("0x..." or decimal); presence-based variant
// so explicit "0" can override defaults (needed to disable HeapLo/Hi).
static int jsonU64Key(const char* line, const char* key, uint64_t* out) {
    char k[64], vstr[64];
    if (sscanf(line, "  \"%63[^\"]\": \"%63[^\"]\"", k, vstr) == 2 && strcmp(k, key) == 0) {
        *out = strtoull(vstr, NULL, 0);
        return 1;
    }
    return 0;
}

static uint64_t jsonU64(const char* line, const char* key) {
    uint64_t h = 0;
    if (jsonU64Key(line, key, &h)) return h;
    long long v = jsonNum(line, key);
    return (v > 0) ? (uint64_t)v : 0;
}

static void siblingPath(const char* src, const char* name, char* out, int cap) {
    const char* slash;
    int n;
    if (!out || cap < 2) return;
    out[0] = 0;
    if (!src || !src[0]) {
        strncpy(out, name, (size_t)cap - 1);
        out[cap - 1] = 0;
        return;
    }
    slash = strrchr(src, '\\');
    if (!slash) slash = strrchr(src, '/');
    if (!slash) {
        strncpy(out, name, (size_t)cap - 1);
        out[cap - 1] = 0;
        return;
    }
    n = (int)(slash - src + 1);
    if (n >= cap) n = cap - 1;
    memcpy(out, src, (size_t)n);
    out[n] = 0;
    strncat(out, name, (size_t)cap - strlen(out) - 1);
}

static void loadInvOffsets(const char* path) {
    FILE* f;
    char line[512];
    if (!path || !path[0]) return;
    f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof(line), f)) {
        char* p;
        char* k;
        char* ke;
        unsigned long v;
        if ((p = strchr(line, '\n'))) *p = 0;
        if ((p = strchr(line, '\r'))) *p = 0;
        p = strchr(line, '=');
        if (!p) continue;
        *p = 0;
        k = line;
        while (*k == ' ' || *k == '\t') k++;
        ke = k + strlen(k);
        while (ke > k && (ke[-1] == ' ' || ke[-1] == '\t')) *--ke = 0;
        v = strtoul(p + 1, 0, 0);
        if (!strcmp(k, "MGR")) invMgr = (uint32_t)v;
        else if (!strcmp(k, "HOLDER_OFF")) invHolder = (uint32_t)v;
        else if (!strcmp(k, "SUBLIST_BEG")) invSubBeg = (uint32_t)v;
        else if (!strcmp(k, "SUBLIST_END")) invSubEnd = (uint32_t)v;
        else if (!strcmp(k, "INV_SUB_IDX")) invSubIdx = (uint32_t)v;
        else if (!strcmp(k, "INV_VFT")) invSubVft = (uint32_t)v;
        else if (!strcmp(k, "INV_VEC_BEG")) invVecBeg = (uint32_t)v;
        else if (!strcmp(k, "INV_VEC_END")) invVecEnd = (uint32_t)v;
        else if (!strcmp(k, "ITEM_VFT")) offItemEntityVtable = (uint64_t)v;
        else if (!strcmp(k, "ITEM_CFG")) oItemId = (uint32_t)v;
        else if (!strcmp(k, "ITEM_COUNT")) oItemCount = (uint32_t)v;
        else if (!strcmp(k, "ITEM_KIND")) oItemKind = (uint32_t)v;
        else if (!strcmp(k, "ITEM_FMT")) oItemFmt = (uint32_t)v;
        else if (!strcmp(k, "MSG_ANCHOR_RVA")) msgAnchorRva = (uint32_t)v;
        else if (!strcmp(k, "MSG_REC_NEXT")) msgRecNext = (uint32_t)v;
        else if (!strcmp(k, "MSG_REC_NAME")) msgRecName = (uint32_t)v;
        else if (!strcmp(k, "MSG_NAME_KR")) msgNameKr = (uint32_t)v;
        else if (!strcmp(k, "MSG_NAME_TW")) msgNameTw = (uint32_t)v;
        else if (!strcmp(k, "MSG_NODE_LANG")) msgNodeLang = (uint32_t)v;
        else if (!strcmp(k, "MSG_NODE_TEXT")) msgNodeText = (uint32_t)v;
        else if (!strcmp(k, "MSG_BUCKET_STRIDE")) msgBucketStride = (uint32_t)v;
        else if (!strcmp(k, "MSG_BUCKET_MASK")) msgBucketMask = (uint32_t)v;
        else if (!strcmp(k, "MSG_FNV_OFFSET")) msgFnvOffset = strtoull(p + 1, 0, 0);
        else if (!strcmp(k, "MSG_FNV_PRIME")) msgFnvPrime = strtoull(p + 1, 0, 0);
    }
    fclose(f);
}

static void loadOffsets(const char* path) {
    const char* file = (path && path[0]) ? path : "offsets.json";
    FILE* f = fopen(file, "r");
    if (f) {
        char line[512];
        long long v;
        uint64_t h;
        while (fgets(line, sizeof(line), f)) {
            if ((h = jsonU64(line, "ItemEntityVtableRva")) > 0) offItemEntityVtable = h;
            if ((v = jsonNum(line, "ItemEntityId")) >= 0)       oItemId = (uint32_t)v;
            if ((v = jsonNum(line, "ItemEntityQuantity")) >= 0) oItemCount = (uint32_t)v;
            if ((v = jsonNum(line, "ItemEntityGuid")) >= 0)     oItemGuid = (uint32_t)v;
            /* ItemEntitySlot historically named the +0x44 dword; it is kind/group. */
            if ((v = jsonNum(line, "ItemEntityKind")) >= 0)     oItemKind = (uint32_t)v;
            else if ((v = jsonNum(line, "ItemEntitySlot")) >= 0) oItemKind = (uint32_t)v;
            if ((v = jsonNum(line, "ItemEntityFmt")) >= 0)      oItemFmt = (uint32_t)v;
            if ((v = jsonNum(line, "ItemStructSize")) > 0)      oItemStruct = (uint32_t)v;
            if (jsonU64Key(line, "HeapLo", &h)) g_heapLo = h;
            if (jsonU64Key(line, "HeapHi", &h)) g_heapHi = h;
            if ((h = jsonU64(line, "ValidPtrLo")) > 0) g_validPtrLo = h;
            if ((h = jsonU64(line, "ValidPtrHi")) > 0) g_validPtrHi = h;
        }
        fclose(f);
    }
    {
        char reg[MAX_PATH];
        siblingPath(file, "inventory_offsets.txt", reg, sizeof(reg));
        loadInvOffsets(reg);
    }
}

// ---------------------------------------------------------------------------
// Inventory read
// ---------------------------------------------------------------------------
typedef struct {
    uint64_t addr;
    uint32_t id;
    uint32_t count;
    uint32_t kind;      // +0x44 per-kind/group (not bag order)
    uint64_t node;      // +0x10 self-link (== addr + oItemGuid)
    int      slot;
    char     fmt[64];   // "$N" / "$A: $B" from format SSO at +0x68
    char     name[96];     // KR (Hangul)
    char     name_tw[96];  // TW (Traditional Chinese / Taiwan)
    char     name_cn[96];  // CN (Simplified Chinese) — empty if locale pack not loaded
    char     name_en[96];  // EN/US — empty if locale pack not loaded
} InvItem;

static int inHeapRange(uint64_t p);

// Parse the "$N" token out of an inline format SSO read into buf (the bytes
// at obj+oItemFmt; up to max bytes). SSO layout: { buf[16], size, cap }.
static int fmtTokenFromSso(const uint8_t* buf, int max, char* out, int outSz) {
    if (max < 0x20) return -1;
    uint32_t size = *(uint32_t*)(buf + 0x10);
    uint32_t cap  = *(uint32_t*)(buf + 0x18);
    if (size == 0 || size > 0x100 || cap > 0x40) { out[0] = 0; return -1; }
    const char* p;
    char heap[0x100];
    if (cap <= 0xF) {
        p = (const char*)buf;
    } else {
        // Out-of-line buffer: first qword of the SSO is the heap pointer.
        // Only follow it when it lands in the configured heap band. A random
        // qword here is often a kernel or non-canonical address, and asking
        // the driver to copy that freezes the machine.
        uint64_t hp = *(uint64_t*)buf;
        if (!inHeapRange(hp) || hp + size < hp || !inHeapRange(hp + size - 1))
            { out[0] = 0; return -1; }
        if (!readMem(hp, heap, size)) { out[0] = 0; return -1; }
        p = heap;
    }
    // Token is a "$" followed by digits (e.g. "$69 (count)").
    for (uint32_t i = 0; i + 1 < size; i++) {
        if (p[i] == '$' && p[i + 1] >= '0' && p[i + 1] <= '9') {
            uint32_t k = i;
            while (k < size && k - i < (uint32_t)(outSz - 1) && p[k] != '(' && p[k] != '\r' && p[k] != '\n') {
                out[k - i] = p[k];
                k++;
            }
            out[k - i] = 0;
            return 0;
        }
    }
    out[0] = 0;
    return -1;
}

// Resolve display strings: token from the item's own format SSO.
static void resolveItemInfo(InvItem* it) {
    uint8_t sso[0x20];
    it->fmt[0] = 0;
    it->name[0] = 0;
    if (readMem(it->addr + oItemFmt, sso, sizeof(sso)))
        fmtTokenFromSso(sso, (int)sizeof(sso), it->fmt, (int)sizeof(it->fmt));
}

// Driver-read budget. Counting failed reads matters: each one still enters
// the kernel, and an unbounded sweep of unmapped VA is what locks the machine.
static int g_drvReads = 0;
static int g_budgetHit = 0;

// Canonical user VA. The heap base moves on every game restart, so this is
// not limited to the old 1TB-4TB band.
static int inHeapRange(uint64_t p) {
    return p >= 0x10000ULL && p <= 0x00007FFFFFFFFFFFULL;
}

static int tryRead(uint8_t* buf, uint64_t addr, uint32_t size, uint32_t* br) {
    if (br) *br = 0;
    if (g_drvReads >= MAX_DRIVER_READS) {
        if (!g_budgetHit) {
            g_budgetHit = 1;
            LOG("WARNING: driver read budget (%d) reached; scan truncated\n", MAX_DRIVER_READS);
        }
        return 0;
    }
    if (!inHeapRange(addr) || size == 0 || addr + (uint64_t)size < addr) return 0;
    if (!inHeapRange(addr + (uint64_t)size - 1)) return 0;
    g_drvReads++;
    return SignedReadMemory(g_pid, addr, buf, size, br) && br && *br >= size;
}

// Probe readable 512MB strides in the heap band (2 x 4KB samples per stride).
// A miss is one page, not a 64KB copy. Returns stride bases (sa).
static int probeStrides(uint64_t* strides, int max) {
    int n = 0;
    uint8_t* spb = (uint8_t*)malloc(PAGE_PROBE);
    if (!spb) return 0;
    int ranged = (g_heapLo && g_heapHi && g_heapHi > g_heapLo);
    uint64_t lo = ranged ? g_heapLo : g_validPtrLo;
    uint64_t hi = ranged ? g_heapHi : g_validPtrHi;
    uint64_t sa = lo & ~(COARSE_STRIDE - 1);
    for (int step = 0; step < MAX_PROBE_STEPS && sa < hi && n < max; step++) {
        int hit = 0;
        int samples = ranged ? 1 : COARSE_SAMPLES;
        for (int sm = 0; sm < samples && !hit; sm++) {
            uint64_t pa = sa + (uint64_t)sm * (COARSE_STRIDE / COARSE_SAMPLES);
            if (pa < lo) pa = lo;
            if (pa >= hi) break;
            uint32_t sbr = 0;
            if (tryRead(spb, pa, PAGE_PROBE, &sbr)) hit = 1;
        }
        if (hit) strides[n++] = sa;
        if (sa > UINT64_MAX - COARSE_STRIDE) break;
        sa += COARSE_STRIDE;
    }
    free(spb);
    return n;
}

// Known item signatures for post-scan validation
typedef struct { uint32_t id; uint32_t minCount; const char* fmtPrefix; } KnownItem;
static const KnownItem KNOWN_ITEMS[] = {
    {5,  1000, "$4"},    // 아데나 - high count, fmt $4
    {7,  100,  "$61"},   // 화살 - medium count, fmt $61
    {24, 1,    "$67"},   // 양초
    {27, 1,    "$174"},  // 말하는 두루마기
    {31, 1,    "$69"},   // 몽둥이
    {42, 1,    "$74"},   // 도리깨
};

// Post-scan validation: check if known items were found
static void validateScanResults(const InvItem* items, int nItems) {
    int found = 0;
    for (size_t k = 0; k < sizeof(KNOWN_ITEMS)/sizeof(KNOWN_ITEMS[0]); k++) {
        for (int i = 0; i < nItems; i++) {
            if (items[i].id == KNOWN_ITEMS[k].id &&
                items[i].count >= KNOWN_ITEMS[k].minCount &&
                strstr(items[i].fmt, KNOWN_ITEMS[k].fmtPrefix)) {
                found++;
                break;
            }
        }
    }
    if (found < (int)(sizeof(KNOWN_ITEMS)/sizeof(KNOWN_ITEMS[0]))) {
        LOG("WARNING: only %d/%zu known items found (adena/arrows may be in different container)\n",
            found, sizeof(KNOWN_ITEMS)/sizeof(KNOWN_ITEMS[0]));
    } else {
        LOG("All %d known items validated\n", found);
    }
}

// Scan one window for ItemEntity vtable rows; validate layout + self-link.
static void scanWindowItems(const uint8_t* win, uint32_t br, uint64_t winAddr,
                            InvItem* items, int* nItems, int max) {
    uint64_t target = offItemEntityVtable ? (g_base + offItemEntityVtable) : 0;
    if (!target) return;
    uint32_t need = 0x40;
    if (oItemGuid + 8 > need) need = oItemGuid + 8;
    if (oItemId + 4 > need) need = oItemId + 4;
    if (oItemCount + 4 > need) need = oItemCount + 4;
    if (oItemKind + 4 > need) need = oItemKind + 4;
    for (uint32_t i = 0; i + need <= br && *nItems < max; i += 8) {
        if (*(uint64_t*)(win + i) != target) continue;
        uint64_t obj = winAddr + i;
        uint64_t node = *(uint64_t*)(win + i + oItemGuid);
        if (node != obj + oItemGuid) continue;
        uint32_t id  = *(uint32_t*)(win + i + oItemId);
        uint32_t cnt = *(uint32_t*)(win + i + oItemCount);
        uint32_t kind = *(uint32_t*)(win + i + oItemKind);
        if (id == 0 || id > 500000) {
            LOG("  [filter] id out of range: %u\n", id);
            continue;
        }
        if (cnt == 0 || cnt > 1000000) continue;
        int dup = 0;
        for (int d = 0; d < *nItems; d++)
            if (items[d].addr == obj) { dup = 1; break; }
        if (dup) continue;
        InvItem* it = &items[(*nItems)++];
        it->addr = obj;
        it->id = id;
        it->count = cnt;
        it->kind = kind;
        it->node = node;
        it->slot = -1;
        resolveItemInfo(it);
    }
}

// Record a committed window in ascending order. Duplicates (from a backfill
// that overlaps a window already kept) are ignored.
static int appendWindow(uint64_t* wins, int* nWin, uint64_t addr) {
    if (*nWin >= MAX_WINDOWS) return 0;
    if (*nWin > 0 && addr <= wins[*nWin - 1]) return 0;
    wins[(*nWin)++] = addr;
    return 1;
}

// "$4" / "$61" fallback. The token is searched only inside a window we already
// read. The parent object is either in that window or one small read just
// before it. Raw qwords are never treated as pointers.
static void scanWindowTokens(const uint8_t* win, uint32_t br, uint64_t winAddr,
                             InvItem* items, int* nItems, int max) {
    static const char* toks[] = { "$4", "$61" };
    uint32_t need = oItemGuid + 8;
    if (oItemId + 4 > need) need = oItemId + 4;
    if (oItemCount + 4 > need) need = oItemCount + 4;
    if (oItemKind + 4 > need) need = oItemKind + 4;
    if (need > 0x80) return;
    for (int t = 0; t < 2; t++) {
        size_t tlen = strlen(toks[t]);
        uint32_t i = 0;
        while (i < br && *nItems < max) {
            const void* hit = memchr(win + i, '$', (size_t)br - i);
            if (!hit) break;
            uint32_t k = (uint32_t)((const uint8_t*)hit - win);
            if (k + (uint32_t)tlen <= br && memcmp(win + k, toks[t], tlen) == 0) {
                int moreDigit = k + (uint32_t)tlen < br &&
                    win[k + tlen] >= '0' && win[k + tlen] <= '9';
                if (!moreDigit && winAddr + k >= oItemFmt) {
                    uint64_t obj = winAddr + k - oItemFmt;
                    const uint8_t* base = NULL;
                    uint8_t hdr[0x80];
                    if (obj >= winAddr && obj + need <= winAddr + br)
                        base = win + (uint32_t)(obj - winAddr);
                    else if (inHeapRange(obj)) {
                        uint32_t brh = 0;
                        if (tryRead(hdr, obj, need, &brh)) base = hdr;
                    }
                    if (base) {
                        uint64_t node = *(uint64_t*)(base + oItemGuid);
                        uint32_t id = *(uint32_t*)(base + oItemId);
                        uint32_t cnt = *(uint32_t*)(base + oItemCount);
                        uint32_t kind = *(uint32_t*)(base + oItemKind);
                        if (node == obj + oItemGuid && id > 0 && id <= 500000 &&
                            cnt > 0 && cnt <= 1000000) {
                            int dup = 0;
                            for (int d = 0; d < *nItems; d++)
                                if (items[d].addr == obj) { dup = 1; break; }
                            if (!dup) {
                                InvItem* it = &items[(*nItems)++];
                                it->addr = obj; it->id = id; it->count = cnt;
                                it->kind = kind; it->node = node; it->slot = -1;
                                strncpy(it->fmt, toks[t], sizeof(it->fmt) - 1);
                                it->fmt[sizeof(it->fmt) - 1] = 0;
                                LOG("  [token-scan] found id=%u cnt=%u kind=%u fmt=%s\n",
                                    id, cnt, kind, toks[t]);
                            }
                        }
                    }
                }
            }
            i = k + 1;
        }
    }
}

// Walk one coarse stride. Unmapped space is probed with a single 4KB read
// every 1MB. Only a megabyte whose first page is committed is read in full.
static void sweepBand(uint64_t blo, uint64_t bhi, uint8_t* win, uint64_t* wins, int* nWin,
                      int* nRead, InvItem* items, int* nItems, int maxItems) {
    uint64_t pa = blo;
    while (pa < bhi && g_drvReads < MAX_DRIVER_READS) {
        uint32_t br = 0;
        if (!tryRead(win, pa, PAGE_PROBE, &br)) {
            if (pa > UINT64_MAX - FINE_STEP) break;
            pa += FINE_STEP;
            continue;
        }
        uint64_t end = pa + FINE_STEP;
        if (end < pa || end > bhi) end = bhi;
        for (uint64_t wa = pa; wa < end && g_drvReads < MAX_DRIVER_READS; wa += HEAP_WIN) {
            uint32_t brw = 0;
            if (!tryRead(win, wa, HEAP_WIN, &brw)) continue;
            (*nRead)++;
            int before = *nItems;
            scanWindowItems(win, brw, wa, items, nItems, maxItems);
            scanWindowTokens(win, brw, wa, items, nItems, maxItems);
            if (*nItems > before) appendWindow(wins, nWin, wa);
        }
        pa = end;
    }
}

// Walk one VirtualQueryEx region. The region is already committed, so every
// 64KB is a real page — no probe of unmapped address space.
static void scanSpan(uint64_t blo, uint64_t bhi, uint8_t* win, uint64_t* wins, int* nWin,
                     int* nRead, InvItem* items, int* nItems, int maxItems) {
    for (uint64_t addr = blo; addr < bhi && g_drvReads < MAX_DRIVER_READS; ) {
        uint64_t remain = bhi - addr;
        uint32_t want = remain > HEAP_WIN ? (uint32_t)HEAP_WIN : (uint32_t)remain;
        if (want < 0x80) break;
        uint32_t br = 0;
        if (!tryRead(win, addr, want, &br)) { addr += want; continue; }
        (*nRead)++;
        int before = *nItems;
        scanWindowItems(win, br, addr, items, nItems, maxItems);
        scanWindowTokens(win, br, addr, items, nItems, maxItems);
        /* Keep only windows that held an item. The container pass re-reads
           these; storing every 64KB window used to stop the scan at 1GB. */
        if (*nItems > before) appendWindow(wins, nWin, addr);
        addr += want;
    }
}

#define MAX_SPANS 4096
typedef struct { uint64_t base; uint64_t size; } HeapSpan;

static int protectReadable(DWORD prot) {
    if (prot & 0x100) return 0;
    switch (prot & 0xFF) {
        case 0x02: case 0x04: case 0x08:
        case 0x10: case 0x20: case 0x40: case 0x80:
            return 1;
    }
    return 0;
}

static int regionOverlapsModule(uint64_t base, uint64_t size) {
    if (!g_base || !g_modSize || !size) return 0;
    uint64_t end = base + size;
    return base < g_base + g_modSize && end > g_base;
}

// Committed private regions outside LC.exe. This is the live heap; its base
// changes every time the game restarts. Same walk as inventory_list, with
// the bytes read through the driver.
static int enumHeapSpans(HeapSpan* out, int max) {
    HANDLE hp = OpenProcess(PROCESS_QUERY_INFORMATION, FALSE, g_pid);
    if (!hp) hp = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, g_pid);
    if (!hp) {
        LOG("OpenProcess QUERY failed error=%u\n", GetLastError());
        return 0;
    }
    MEMORY_BASIC_INFORMATION mbi;
    uint64_t addr = 0;
    int n = 0;
    while (n < max) {
        SIZE_T got = VirtualQueryEx(hp, (LPCVOID)(uintptr_t)addr, &mbi, sizeof(mbi));
        if (!got) break;
        uint64_t base = (uint64_t)(uintptr_t)mbi.BaseAddress;
        uint64_t sz = (uint64_t)mbi.RegionSize;
        if (!sz) break;
        if (mbi.State == 0x1000 && mbi.Type == 0x20000 &&
            protectReadable(mbi.Protect) && sz >= 0x1000 && sz < 0x80000000ULL &&
            inHeapRange(base) && !regionOverlapsModule(base, sz)) {
            out[n].base = base;
            out[n].size = sz;
            n++;
        }
        uint64_t next = base + sz;
        if (next <= addr) break;
        addr = next;
        if (addr >= 0x0000800000000000ULL) break;
    }
    CloseHandle(hp);
    return n;
}

/* Pointer-array slot order, matching inventory_reader._find_inventory_list.
   A qword may point at the object or at +8/+0x10/+0x18/+0x20/+0x28/+0x30.
   Slot is the order those pointers appear, not the dword at +0x44. */
enum { ALIAS_HASH = 4096 };
typedef struct { uint64_t key; int item; } AliasSlot;

static uint32_t aliasHash(uint64_t k) {
    k ^= k >> 30;
    k *= 0xbf58476d1ce4e5b9ULL;
    k ^= k >> 27;
    return (uint32_t)k & (ALIAS_HASH - 1);
}

static int aliasLookup(const AliasSlot* tab, uint64_t key) {
    if (!key) return -1;
    uint32_t h = aliasHash(key);
    for (int n = 0; n < ALIAS_HASH; n++) {
        uint32_t s = (h + (uint32_t)n) & (ALIAS_HASH - 1);
        if (tab[s].item < 0) return -1;
        if (tab[s].key == key) return tab[s].item;
    }
    return -1;
}

static void aliasInsert(AliasSlot* tab, uint64_t key, int item) {
    if (!key) return;
    uint32_t h = aliasHash(key);
    for (int n = 0; n < ALIAS_HASH; n++) {
        uint32_t s = (h + (uint32_t)n) & (ALIAS_HASH - 1);
        if (tab[s].item < 0 || tab[s].key == key) {
            tab[s].key = key;
            tab[s].item = item;
            return;
        }
    }
}

static void assignSlotsFromList(uint8_t* win, const HeapSpan* spans, int nSpans,
                                InvItem* items, int nItems,
                                uint64_t* vecBase, uint64_t* vecEnd, int* nVec) {
    static const uint32_t kDelta[] = { 0, 8, 0x10, 0x18, 0x20, 0x28, 0x30 };
    if (nItems <= 0) return;
    AliasSlot* tab = (AliasSlot*)malloc(sizeof(AliasSlot) * ALIAS_HASH);
    int* runSlot = (int*)malloc(sizeof(int) * (size_t)nItems);
    int* bestSlot = (int*)malloc(sizeof(int) * (size_t)nItems);
    if (!tab || !runSlot || !bestSlot) { free(tab); free(runSlot); free(bestSlot); return; }
    for (int i = 0; i < ALIAS_HASH; i++) tab[i].item = -1;
    for (int i = 0; i < nItems; i++) {
        items[i].slot = -1;
        bestSlot[i] = -1;
        for (int d = 0; d < 7; d++)
            aliasInsert(tab, items[i].addr + kDelta[d], i);
    }

    int minCover = nItems < 4 ? nItems : 4;
    int bestScore = -1, bestCover = 0, bestLen = 0;
    uint64_t bestBase = 0;

    for (int s = 0; s < nSpans && g_drvReads < MAX_DRIVER_READS; s++) {
        int inRun = 0, runLen = 0, runCover = 0, gapn = 0;
        uint64_t runBase = 0, gapq[2] = { 0, 0 };
        uint64_t blo = spans[s].base, bhi = spans[s].base + spans[s].size;

        for (uint64_t addr = blo; addr < bhi && g_drvReads < MAX_DRIVER_READS; ) {
            uint64_t remain = bhi - addr;
            uint32_t want = remain > HEAP_WIN ? (uint32_t)HEAP_WIN : (uint32_t)remain;
            if (want < 8) break;
            uint32_t br = 0;
            if (!tryRead(win, addr, want, &br)) {
                inRun = 0;
                addr += want;
                continue;
            }
            for (uint32_t i = 0; i + 8 <= br; i += 8) {
                uint64_t v = *(uint64_t*)(win + i);
                int item = aliasLookup(tab, v);
                if (item >= 0) {
                    int ok = !inRun || gapn == 0;
                    if (!ok && gapn <= 2) {
                        ok = 1;
                        for (int g = 0; g < gapn; g++)
                            if (gapq[g] != 0) ok = 0;
                    }
                    if (inRun && !ok) inRun = 0;
                    if (!inRun) {
                        inRun = 1;
                        runBase = addr + i;
                        runLen = 0;
                        runCover = 0;
                        for (int k = 0; k < nItems; k++) runSlot[k] = -1;
                    } else if (gapn > 0) {
                        runLen += gapn;
                    }
                    runLen++;
                    if (runSlot[item] < 0) runSlot[item] = runCover++;
                    gapn = 0;

                    if (runCover >= minCover) {
                        int diff = runLen - runCover;
                        if (diff < 0) diff = -diff;
                        int sc = runCover * 1000 - diff * 150;
                        if (runCover == nItems) sc += 5000;
                        if (sc > bestScore) {
                            bestScore = sc;
                            bestCover = runCover;
                            bestLen = runLen;
                            bestBase = runBase;
                            for (int k = 0; k < nItems; k++) bestSlot[k] = runSlot[k];
                        }
                    }
                } else if (inRun) {
                    if (gapn < 2) gapq[gapn] = v;
                    gapn++;
                }
            }
            addr += want;
        }
    }

    if (bestCover > 0) {
        for (int i = 0; i < nItems; i++) items[i].slot = bestSlot[i];
        *vecBase = bestBase;
        *vecEnd = bestBase + (uint64_t)bestLen * 8;
        *nVec = bestCover;
        LOG("inventory list 0x%llX qwords=%d slotted=%d/%d\n",
            (unsigned long long)bestBase, bestLen, bestCover, nItems);
    } else {
        LOG("no inventory pointer list\n");
    }
    free(bestSlot);
    free(runSlot);
    free(tab);
}

static int cmpItem(const void* a, const void* b) {
    const InvItem* x = (const InvItem*)a;
    const InvItem* y = (const InvItem*)b;
    int sx = x->slot < 0 ? 100000 : x->slot;
    int sy = y->slot < 0 ? 100000 : y->slot;
    if (sx != sy) return sx - sy;
    if (x->addr < y->addr) return -1;
    if (x->addr > y->addr) return 1;
    return 0;
}

/* Read an MSVC-style SSO at ssoAddr into out. Returns length, or -1. */
static int readSsoString(uint64_t ssoAddr, char* out, int outSz) {
    uint8_t hdr[0x20];
    if (outSz < 2 || !readMem(ssoAddr, hdr, sizeof(hdr))) return -1;
    uint64_t size = *(uint64_t*)(hdr + 0x10);
    uint64_t cap = *(uint64_t*)(hdr + 0x18);
    if (size == 0 || size > 200 || cap > 0x100000) return -1;
    if ((int)size >= outSz) size = (uint64_t)(outSz - 1);
    if (cap <= 0xF) {
        memcpy(out, hdr, (size_t)size);
    } else {
        uint64_t p = *(uint64_t*)hdr;
        if (!inHeapRange(p) || !readMem(p, out, (uint32_t)size)) return -1;
    }
    out[size] = 0;
    return (int)size;
}

/* Name node: lang SSO at +0x10, UTF-8 text SSO at +0x30. */
static int readLangNodeText(uint64_t node, const char* wantLang, char* out, int outSz) {
    char lang[8];
    if (readSsoString(node + 0x10, lang, (int)sizeof(lang)) < 0) return -1;
    if (wantLang && strcmp(lang, wantLang) != 0) return -1;
    return readSsoString(node + 0x30, out, outSz);
}

enum { MAX_MSG_NAMES = 256 };
typedef struct {
    uint32_t mid;
    char kr[96];
    char tw[96];
    char cn[96];
    char en[96];
} MsgName;

/* 0x90 string-table entry: KR node at +0x00, TW at +0x40 on this client.
   Also scan every qword for CN/EN/US/ZH if a locale pack is present. */
static void fillLangsFromEntry(uint64_t entry, MsgName* m) {
    uint8_t buf[0x90];
    if (!readMem(entry, buf, sizeof(buf))) return;

    uint64_t krN = *(uint64_t*)(buf + 0x00);
    uint64_t twN = *(uint64_t*)(buf + 0x40);
    if (inHeapRange(krN) && !m->kr[0])
        readLangNodeText(krN, "KR", m->kr, (int)sizeof(m->kr));
    if (inHeapRange(twN) && !m->tw[0])
        readLangNodeText(twN, "TW", m->tw, (int)sizeof(m->tw));

    for (uint32_t o = 0; o + 8 <= sizeof(buf); o += 8) {
        uint64_t p = *(uint64_t*)(buf + o);
        if (!inHeapRange(p)) continue;
        char lang[8], text[96];
        if (readSsoString(p + 0x10, lang, (int)sizeof(lang)) < 0) continue;
        size_t llen = strlen(lang);
        if (llen < 2 || llen > 3) continue;
        if (readSsoString(p + 0x30, text, (int)sizeof(text)) <= 0) continue;
        if (strcmp(lang, "KR") == 0) {
            if (!m->kr[0]) { strncpy(m->kr, text, sizeof(m->kr) - 1); m->kr[sizeof(m->kr) - 1] = 0; }
        } else if (strcmp(lang, "TW") == 0 || strcmp(lang, "HK") == 0) {
            if (!m->tw[0]) { strncpy(m->tw, text, sizeof(m->tw) - 1); m->tw[sizeof(m->tw) - 1] = 0; }
        } else if (strcmp(lang, "CN") == 0 || strcmp(lang, "ZH") == 0) {
            if (!m->cn[0]) { strncpy(m->cn, text, sizeof(m->cn) - 1); m->cn[sizeof(m->cn) - 1] = 0; }
        } else if (strcmp(lang, "EN") == 0 || strcmp(lang, "US") == 0) {
            if (!m->en[0]) { strncpy(m->en, text, sizeof(m->en) - 1); m->en[sizeof(m->en) - 1] = 0; }
        }
    }

    /* KR node +0x00 often peers to TW when +0x40 was empty. */
    if (!m->tw[0] && inHeapRange(krN)) {
        uint64_t peer = 0;
        if (readMem(krN, &peer, 8) && inHeapRange(peer))
            readLangNodeText(peer, "TW", m->tw, (int)sizeof(m->tw));
    }
}

static const char* msgNameField(const MsgName* m, int which) {
    if (which == 1) return m->tw;
    if (which == 2) return m->cn;
    if (which == 3) return m->en;
    return m->kr;
}

static void joinFmtNames(const char* fmt, const MsgName* map, int nWant, int which,
                         char* out, int outSz) {
    int o = 0, parts = 0;
    out[0] = 0;
    const char* p = fmt;
    while (*p && o + 1 < outSz) {
        if (*p == '$' && p[1] >= '0' && p[1] <= '9') {
            uint32_t mid = 0;
            p++;
            while (*p >= '0' && *p <= '9') {
                mid = mid * 10u + (uint32_t)(*p - '0');
                p++;
            }
            const char* nm = NULL;
            for (int t = 0; t < nWant; t++) {
                if (map[t].mid != mid) continue;
                const char* f = msgNameField(&map[t], which);
                if (f && f[0]) { nm = f; break; }
            }
            if (!nm) continue;
            if (parts && o + 2 < outSz) { out[o++] = ':'; out[o++] = ' '; }
            while (*nm && o + 1 < outSz) out[o++] = *nm++;
            out[o] = 0;
            parts++;
            continue;
        }
        p++;
    }
}

/* The client looks up item display text with key "1_<msgid>" (inline SSO).
   key+0x38 -> 0x90 string-table entry: KR @ +0x00, TW @ +0x40.
   Only used for mids the static FNV path missed. */
static void resolveItemNames(uint8_t* win, const HeapSpan* spans, int nSpans,
                             InvItem* items, int nItems) {
    if (nItems <= 0 || nSpans <= 0) return;

    uint32_t want[MAX_MSG_NAMES];
    int nWant = 0;
    for (int i = 0; i < nItems; i++) {
        if (items[i].name[0]) continue;
        const char* p = items[i].fmt;
        while (*p) {
            if (*p == '$' && p[1] >= '0' && p[1] <= '9') {
                uint32_t mid = 0;
                p++;
                while (*p >= '0' && *p <= '9') {
                    mid = mid * 10u + (uint32_t)(*p - '0');
                    p++;
                }
                if (mid && nWant < MAX_MSG_NAMES) {
                    int dup = 0;
                    for (int k = 0; k < nWant; k++)
                        if (want[k] == mid) { dup = 1; break; }
                    if (!dup) want[nWant++] = mid;
                }
                continue;
            }
            p++;
        }
    }
    if (!nWant) return;

    MsgName* map = (MsgName*)calloc((size_t)nWant, sizeof(MsgName));
    if (!map) return;
    for (int i = 0; i < nWant; i++) map[i].mid = want[i];

    int filled = 0, filledTw = 0, filledCn = 0, filledEn = 0;
    for (int s = 0; s < nSpans && filled < nWant && g_drvReads < MAX_DRIVER_READS; s++) {
        uint64_t blo = spans[s].base, bhi = spans[s].base + spans[s].size;
        for (uint64_t addr = blo; addr < bhi && filled < nWant && g_drvReads < MAX_DRIVER_READS; ) {
            uint64_t remain = bhi - addr;
            uint32_t wantn = remain > HEAP_WIN ? (uint32_t)HEAP_WIN : (uint32_t)remain;
            if (wantn < 0x40) break;
            uint32_t br = 0;
            if (!tryRead(win, addr, wantn, &br) || br < 0x40) { addr += wantn; continue; }
            for (uint32_t i = 0; i + 0x40 <= br; i++) {
                if (win[i] != '1' || win[i + 1] != '_') continue;
                uint32_t k = i + 2;
                uint32_t mid = 0;
                while (k < i + 16 && k < br && win[k] >= '0' && win[k] <= '9') {
                    mid = mid * 10u + (uint32_t)(win[k] - '0');
                    k++;
                }
                if (mid == 0 || k == i + 2) continue;
                if (i + 0x20 > br) continue;
                uint64_t size = *(uint64_t*)(win + i + 0x10);
                uint64_t cap = *(uint64_t*)(win + i + 0x18);
                if (size != (uint64_t)(k - i) || cap != 0xF) continue;
                int padOk = 1;
                for (uint32_t z = k; z < i + 16 && z < br; z++)
                    if (win[z]) { padOk = 0; break; }
                if (!padOk) continue;

                int mi = -1;
                for (int t = 0; t < nWant; t++)
                    if (map[t].mid == mid) { mi = t; break; }
                if (mi < 0 || map[mi].kr[0]) continue;

                uint64_t entryPtr = *(uint64_t*)(win + i + 0x38);
                if (!inHeapRange(entryPtr)) continue;
                fillLangsFromEntry(entryPtr, &map[mi]);
                if (map[mi].kr[0]) filled++;
                if (map[mi].tw[0]) filledTw++;
                if (map[mi].cn[0]) filledCn++;
                if (map[mi].en[0]) filledEn++;
            }
            addr += wantn;
        }
    }
    LOG("name keys resolved: KR %d/%d TW %d CN %d EN %d\n",
        filled, nWant, filledTw, filledCn, filledEn);

    for (int i = 0; i < nItems; i++) {
        if (items[i].name[0]) continue;
        joinFmtNames(items[i].fmt, map, nWant, 0, items[i].name, (int)sizeof(items[i].name));
        joinFmtNames(items[i].fmt, map, nWant, 1, items[i].name_tw, (int)sizeof(items[i].name_tw));
        joinFmtNames(items[i].fmt, map, nWant, 2, items[i].name_cn, (int)sizeof(items[i].name_cn));
        joinFmtNames(items[i].fmt, map, nWant, 3, items[i].name_en, (int)sizeof(items[i].name_en));
        if (!items[i].name[0]) {
            const char* fb = itemNameFor(items[i].id);
            if (fb) {
                strncpy(items[i].name, fb, sizeof(items[i].name) - 1);
                items[i].name[sizeof(items[i].name) - 1] = 0;
            }
        }
    }
    free(map);
}

static uint64_t q64(uint64_t a) {
    uint64_t v = 0;
    return readMem(a, &v, 8) ? v : 0;
}
static uint32_t d32(uint64_t a) {
    uint32_t v = 0;
    return readMem(a, &v, 4) ? v : 0;
}
static int isStructHeap(uint64_t a) {
    return a >= 0x10000000000ULL && a < 0x70000000000ULL;
}
static uint32_t vrva(uint64_t obj) {
    uint64_t v = q64(obj);
    if (!g_base || !g_modSize || v < g_base || v >= g_base + g_modSize) return 0;
    return (uint32_t)(v - g_base);
}

static uint64_t fnv1aKey(uint32_t mid) {
    char s[24];
    int n = snprintf(s, sizeof(s), "1_%u", mid);
    uint64_t h = msgFnvOffset;
    int i;
    for (i = 0; i < n; i++) {
        h ^= (unsigned char)s[i];
        h *= msgFnvPrime;
    }
    return h;
}

static uint32_t recMidOf(uint64_t rec) {
    uint8_t h[0x20];
    uint64_t size, i;
    uint32_t m = 0;
    if (!readMem(rec + 0x10, h, sizeof(h))) return 0;
    if (h[0] != '1' || h[1] != '_') return 0;
    size = *(uint64_t*)(h + 0x10);
    if (size < 3 || size > 12) return 0;
    for (i = 2; i < size; i++) {
        if (h[i] < '0' || h[i] > '9') return 0;
        m = m * 10u + (uint32_t)(h[i] - '0');
    }
    return m;
}

static int msgNameStatic(uint32_t mid, char* out, int outSz, char* twOut, int twSz) {
    uint64_t anchor, rec;
    int steps;
    if (!msgAnchorRva || !g_base || mid == 0) return 0;
    anchor = q64(g_base + msgAnchorRva);
    if (!isStructHeap(anchor)) return 0;
    rec = q64(anchor + (fnv1aKey(mid) & msgBucketMask) * (uint64_t)msgBucketStride);
    for (steps = 0; isStructHeap(rec) && steps < 64; steps++) {
        if (recMidOf(rec) == mid) {
            uint64_t nxt = q64(rec + msgRecName);
            uint64_t kr, tw;
            int ok = 0;
            char lang[8];
            if (!isStructHeap(nxt)) return 0;
            kr = q64(nxt + msgNameKr);
            tw = q64(nxt + msgNameTw);
            if (isStructHeap(kr)) {
                if (readSsoString(kr + msgNodeLang, lang, (int)sizeof(lang)) > 0 &&
                    readSsoString(kr + msgNodeText, out, outSz) > 0)
                    ok = 1;
            }
            if (twOut && twSz > 0 && isStructHeap(tw))
                readSsoString(tw + msgNodeText, twOut, twSz);
            return ok;
        }
        {
            uint64_t nx = q64(rec + msgRecNext);
            if (nx == rec) break;
            rec = nx;
        }
    }
    return 0;
}

static int applyStaticNames(InvItem* items, int nItems) {
    int filled = 0, i;
    if (!msgAnchorRva) return 0;
    for (i = 0; i < nItems; i++) {
        const char* p = items[i].fmt;
        char krJoin[96] = {0}, twJoin[96] = {0};
        int krOff = 0, twOff = 0, parts = 0, failed = 0;
        items[i].name[0] = items[i].name_tw[0] = 0;
        items[i].name_cn[0] = items[i].name_en[0] = 0;
        while (*p) {
            if (*p == '$' && p[1] >= '0' && p[1] <= '9') {
                uint32_t mid = 0;
                char kr[96] = {0}, tw[96] = {0};
                p++;
                while (*p >= '0' && *p <= '9') {
                    mid = mid * 10u + (uint32_t)(*p - '0');
                    p++;
                }
                if (!mid || !msgNameStatic(mid, kr, (int)sizeof(kr), tw, (int)sizeof(tw)) || !kr[0]) {
                    failed = 1;
                    continue;
                }
                if (parts && krOff + 2 < (int)sizeof(krJoin)) {
                    krJoin[krOff++] = ':';
                    krJoin[krOff++] = ' ';
                }
                {
                    const char* s = kr;
                    while (*s && krOff + 1 < (int)sizeof(krJoin)) krJoin[krOff++] = *s++;
                    krJoin[krOff] = 0;
                }
                if (tw[0]) {
                    if (parts && twOff + 2 < (int)sizeof(twJoin)) {
                        twJoin[twOff++] = ':';
                        twJoin[twOff++] = ' ';
                    }
                    {
                        const char* s = tw;
                        while (*s && twOff + 1 < (int)sizeof(twJoin)) twJoin[twOff++] = *s++;
                        twJoin[twOff] = 0;
                    }
                }
                parts++;
                continue;
            }
            p++;
        }
        if (krJoin[0] && !failed) {
            strncpy(items[i].name, krJoin, sizeof(items[i].name) - 1);
            strncpy(items[i].name_tw, twJoin, sizeof(items[i].name_tw) - 1);
            filled++;
        }
    }
    LOG("static names: %d/%d (anchor=0x%X)\n", filled, nItems, msgAnchorRva);
    return filled;
}

static uint64_t findInventorySub(void) {
    uint64_t mgr, holder, bgn, end, byIdx = 0;
    long i, subs;
    if (!g_base) return 0;
    mgr = q64(g_base + invMgr);
    if (!isStructHeap(mgr)) return 0;
    holder = q64(mgr + invHolder);
    if (!isStructHeap(holder)) return 0;
    bgn = q64(holder + invSubBeg);
    end = q64(holder + invSubEnd);
    if (!isStructHeap(bgn) || end <= bgn) return 0;
    subs = (long)((end - bgn) / 16);
    if (subs < 0 || subs > 128) return 0;
    for (i = 0; i < subs; i++) {
        uint64_t s = q64(bgn + 16ull * (uint64_t)i);
        if (!isStructHeap(s)) continue;
        if (vrva(s) == invSubVft) return s;
        if (i == (long)invSubIdx) byIdx = s;
    }
    if (byIdx && vrva(byIdx)) return byIdx;
    return 0;
}

// One-shot bag read: InventorySubsystem vector, then name keys for bag mids.
static int inventoryScan(InvItem* items, int max, uint64_t* vecBase, uint64_t* vecEnd, int* nVec) {
    uint64_t inv, vb, ve, nn, k;
    int nItems = 0;
    *nVec = 0; *vecBase = 0; *vecEnd = 0;
    g_drvReads = 0;
    g_budgetHit = 0;

    inv = findInventorySub();
    if (!inv) {
        LOG("InventorySubsystem not found (check inventory_offsets.txt)\n");
        return 0;
    }
    vb = q64(inv + invVecBeg);
    ve = q64(inv + invVecEnd);
    *vecBase = vb;
    *vecEnd = ve;
    if (isStructHeap(vb) && ve > vb && (ve - vb) <= 0x10000) {
        nn = (ve - vb) / 8;
        *nVec = (int)nn;
        for (k = 0; k < nn && nItems < max; k++) {
            uint64_t e = q64(vb + k * 8);
            uint32_t id, cnt, kind;
            int d, dup = 0;
            InvItem* it;
            if (!isStructHeap(e)) continue;
            if (offItemEntityVtable && vrva(e) != (uint32_t)offItemEntityVtable) continue;
            for (d = 0; d < nItems; d++)
                if (items[d].addr == e) { dup = 1; break; }
            if (dup) continue;
            id = d32(e + oItemId);
            cnt = d32(e + oItemCount);
            kind = d32(e + oItemKind);
            if (id == 0 || id > 500000) continue;
            if (cnt == 0 || cnt > 1000000) continue;
            it = &items[nItems++];
            memset(it, 0, sizeof(*it));
            it->addr = e;
            it->id = id;
            it->count = cnt;
            it->kind = kind;
            it->node = e + oItemGuid;
            it->slot = nItems - 1;
            resolveItemInfo(it);
        }
    }
    LOG("structure bag inv=0x%llX items=%d vec=%d vft=0x%llX\n",
        (unsigned long long)inv, nItems, *nVec,
        (unsigned long long)offItemEntityVtable);

    applyStaticNames(items, nItems);
    {
        int missing = 0, i;
        for (i = 0; i < nItems; i++)
            if (!items[i].name[0]) missing++;
        if (missing > 0) {
            uint8_t* win = (uint8_t*)malloc(HEAP_WIN);
            HeapSpan* spans = (HeapSpan*)malloc(sizeof(HeapSpan) * (size_t)MAX_SPANS);
            if (win && spans) {
                int nSpans = enumHeapSpans(spans, MAX_SPANS);
                if (nSpans > 0)
                    resolveItemNames(win, spans, nSpans, items, nItems);
            }
            free(spans);
            free(win);
        }
    }
    LOG("driver reads total: %d\n", g_drvReads);
    return nItems;
}

// ---------------------------------------------------------------------------
// JSON output
// ---------------------------------------------------------------------------
static void writeInvJson(FILE* f, int scanSec, uint64_t vecBase, uint64_t vecEnd, int nVec,
                         const InvItem* items, int nItems) {
    fprintf(f, "{\n  \"pid\": %lu,\n  \"base\": \"0x%llX\",\n  \"scanSec\": %d.%03d,\n",
        (unsigned long)g_pid, (unsigned long long)g_base, scanSec / 1000, scanSec % 1000);
    fprintf(f, "  \"nVec\": %d,\n", nVec);
    fprintf(f, "  \"container\": {\"base\": \"0x%llX\", \"end\": \"0x%llX\", \"entries\": %d},\n",
        (unsigned long long)vecBase, (unsigned long long)vecEnd, nVec);
    fprintf(f, "  \"items\": [\n");
    for (int i = 0; i < nItems; i++) {
fprintf(f, "    {\"slot\": %d, \"id\": %u, \"count\": %u, \"kind\": %u, \"fmt\": \"%s\", \"name\": \"%s\", \"name_tw\": \"%s\", \"name_cn\": \"%s\", \"name_en\": \"%s\", \"guid\": \"0x%llX\", \"va\": \"0x%llX\"}%s\n",
        items[i].slot, items[i].id, items[i].count, items[i].kind,
        items[i].fmt[0] ? items[i].fmt : "?",
        items[i].name, items[i].name_tw, items[i].name_cn, items[i].name_en,
        (unsigned long long)items[i].node, (unsigned long long)items[i].addr,
        i + 1 < nItems ? "," : "");
    }
    fprintf(f, "  ]\n}\n");
}

static void writeInvCompact(FILE* out, int scanSec, uint64_t vecBase, uint64_t vecEnd, int nVec,
                            const InvItem* items, int nItems) {
    fprintf(out, "{\"cmd\":\"inventory\",\"pid\":%lu,\"base\":\"0x%llX\",\"scanSec\":%d.%03d,"
        "\"nVec\":%d,\"container\":{\"base\":\"0x%llX\",\"end\":\"0x%llX\",\"entries\":%d},\"items\":[",
        (unsigned long)g_pid, (unsigned long long)g_base, scanSec / 1000, scanSec % 1000,
        nVec, (unsigned long long)vecBase, (unsigned long long)vecEnd, nVec);
    for (int i = 0; i < nItems; i++) {
        if (i) fprintf(out, ",");
        fprintf(out, "{\"slot\":%d,\"id\":%u,\"count\":%u,\"kind\":%u,\"fmt\":\"%s\",\"name\":\"%s\",\"name_tw\":\"%s\",\"name_cn\":\"%s\",\"name_en\":\"%s\",\"guid\":\"0x%llX\",\"va\":\"0x%llX\"}",
            items[i].slot, items[i].id, items[i].count, items[i].kind,
            items[i].fmt[0] ? items[i].fmt : "?",
            items[i].name, items[i].name_tw, items[i].name_cn, items[i].name_en,
            (unsigned long long)items[i].node, (unsigned long long)items[i].addr);
    }
    fprintf(out, "]}\n");
    fflush(out);
}

static void resolveModuleSize(void);

/* Pid and image base are resolved again on every scan. A game restart gets a
   new process and a new heap; item addresses from the previous run are never reused. */
static int refreshTarget(void) {
    DWORD pid = findPid(L"LC.exe");
    if (!pid) {
        LOG("LC.exe not running\n");
        return 0;
    }
    if (pid != g_pid) {
        LOG("LC.exe restarted: pid %lu -> %lu\n", g_pid, pid);
        g_pid = pid;
        SignedSetTarget(g_pid);
        g_base = 0;
        g_modSize = 0;
    }
    getModuleBase(&g_base);
    resolveModuleSize();
    if (!g_base) {
        LOG("LC.exe image base not found\n");
        return 0;
    }
    return 1;
}

static void runInventoryScanEx(FILE* out, int writeJson) {
    if (!refreshTarget()) {
        fprintf(out, "{\"cmd\":\"inventory\",\"error\":\"LC.exe not running\"}\n");
        fflush(out);
        return;
    }
    InvItem items[MAX_ITEMS];
    memset(items, 0, sizeof(items));
    uint64_t vecBase = 0, vecEnd = 0;
    int nVec = 0;
    LARGE_INTEGER t0, t1, freq;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&t0);
    int nItems = inventoryScan(items, MAX_ITEMS, &vecBase, &vecEnd, &nVec);
    QueryPerformanceCounter(&t1);
    int scanSec = (int)((double)(t1.QuadPart - t0.QuadPart) * 1000.0 / (double)freq.QuadPart);
    validateScanResults(items, nItems);
    if (writeJson && nItems > 0) {
        // Export JSON file (verification against in-game datas).
        FILE* jf = fopen("inv.json", "w");
        if (jf) { writeInvJson(jf, scanSec, vecBase, vecEnd, nVec, items, nItems); fclose(jf); }
        else LOG("cannot open inv.json\n");
    }
    writeInvCompact(out, scanSec, vecBase, vecEnd, nVec, items, nItems);
}

static void runInventoryScan(FILE* out) {
    runInventoryScanEx(out, g_dllMode ? 0 : 1);
}

// Handle one request line (already trimmed): "ping" -> ack, "inventory" ->
// fresh full heap scan + JSON dataset, anything else -> error JSON.
static void handleRequest(FILE* out, const char* line) {
    if (strstr(line, "ping")) {
        fprintf(out, "{\"cmd\":\"ping\",\"pong\":true,\"pid\":%lu,\"base\":\"0x%llX\"}\n",
            (unsigned long)g_pid, (unsigned long long)g_base);
    } else if (strstr(line, "inventory") || strstr(line, "snapshot")) {
        runInventoryScan(out);
    } else if (strstr(line, "exit") || strstr(line, "quit")) {
        fprintf(out, "{\"cmd\":\"bye\"}\n");
        fflush(out);
    } else {
        fprintf(out, "{\"error\":\"unknown_cmd\",\"raw\":\"%s\"}\n", line);
    }
    fflush(out);
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
static void resolveModuleSize(void) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, g_pid);
    if (snap != INVALID_HANDLE_VALUE) {
        MODULEENTRY32W me;
        me.dwSize = sizeof(me);
        if (Module32FirstW(snap, &me)) {
            do {
                if (_wcsicmp(me.szModule, L"LC.exe") == 0) {
                    g_base = (uint64_t)(uintptr_t)me.modBaseAddr;
                    g_modSize = me.modBaseSize;
                    break;
                }
            } while (Module32NextW(snap, &me));
        }
        CloseHandle(snap);
    }
    if (!g_modSize && g_base) {
        uint8_t pe[0x400];
        if (readMem(g_base, pe, sizeof(pe)) && pe[0] == 'M' && pe[1] == 'Z') {
            uint32_t lfanew = *(uint32_t*)(pe + 0x3C);
            if (lfanew + 0x58 < sizeof(pe)) {
                uint32_t soi = *(uint32_t*)(pe + lfanew + 0x50);
                if (soi > 0x1000 && soi < 0x10000000u) g_modSize = soi;
            }
        }
    }
    if (!g_modSize) g_modSize = 0x4000000ULL;
}

// ---------------------------------------------------------------------------
// In-process DLL API (same pattern as print_state / realtime_monitor).
// Loaded by the bot process. This is not injected into LC.exe.
// ---------------------------------------------------------------------------
static int g_invAttached = 0;
static int g_offsetsLoaded = 0;
static char g_offsetsPathBuf[MAX_PATH] = "offsets.json";

static void invDetach(void) {
    if (g_invAttached) SignedClose();
    g_invAttached = 0;
    g_pid = 0;
    g_base = 0;
    g_modSize = 0;
}

static int invEnsure(const char* offsetsPath) {
    g_dllMode = 1;
    if (offsetsPath && offsetsPath[0]) {
        strncpy(g_offsetsPathBuf, offsetsPath, sizeof(g_offsetsPathBuf) - 1);
        g_offsetsPathBuf[sizeof(g_offsetsPathBuf) - 1] = 0;
        g_offsetsLoaded = 0;
    }
    if (!g_offsetsLoaded) {
        loadOffsets(g_offsetsPathBuf);
        g_offsetsLoaded = 1;
    }
    DWORD pid = findPid(L"LC.exe");
    if (!pid) {
        invDetach();
        return 0;
    }
    if (g_invAttached && pid == g_pid)
        return 1;
    if (g_invAttached)
        invDetach();
    if (!SignedOpen())
        return 0;
    g_pid = pid;
    SignedSetTarget(g_pid);
    getModuleBase(&g_base);
    resolveModuleSize();
    if (!g_base) {
        SignedClose();
        g_pid = 0;
        return 0;
    }
    g_invAttached = 1;
    return 1;
}

/* One bag scan. Returns JSON bytes written to out, or <0 on failure. */
__declspec(dllexport) int inventory_listen_snapshot(const char* offsetsPath, char* out, int outCap) {
    FILE* tf;
    long n;
    size_t got;
    if (!out || outCap < 16)
        return -1;
    if (!invEnsure(offsetsPath))
        return -1;
    tf = tmpfile();
    if (!tf)
        return -1;
    runInventoryScanEx(tf, 0);
    fflush(tf);
    if (fseek(tf, 0, SEEK_END) != 0) {
        fclose(tf);
        return -1;
    }
    n = ftell(tf);
    if (n < 2 || n >= outCap) {
        fclose(tf);
        return -2;
    }
    fseek(tf, 0, SEEK_SET);
    got = fread(out, 1, (size_t)n, tf);
    fclose(tf);
    if (got < 2)
        return -1;
    out[got] = 0;
    return (int)got;
}

__declspec(dllexport) void inventory_listen_shutdown(void) {
    invDetach();
    g_offsetsLoaded = 0;
}

#ifndef INVENTORY_LISTEN_DLL
int main(int argc, char** argv) {
    SetConsoleOutputCP(65001);
    for (int a = 1; a < argc; a++) {
        if (strcmp(argv[a], "--serve") == 0)
            g_serveMode = 1;
        else if (strcmp(argv[a], "--pipe") == 0)
            g_pipeMode = 1;
        else if (strcmp(argv[a], "--help") == 0) {
            printf("usage: inventory_listen [--pipe] [--serve]\n  --pipe : named-pipe server on %ls\n"
                   "  --serve: read requests on stdin, answer on stdout\n"
                   "  default (no flag): one-shot scan to stdout + inv.json\n", PIPE_NAME);
            return 0;
        }
    }
    if (!SignedOpen()) { printf("driver open FAILED\n"); return 1; }
    g_pid = findPid(L"LC.exe");
    if (!g_pid) { printf("LC.exe not running\n"); SignedClose(); return 1; }
    SignedSetTarget(g_pid);

    getModuleBase(&g_base);
    resolveModuleSize();
    if (!g_base) {
        g_base = 0x7FF70EC80000ULL;
        LOG("WARN: image base failed, using fallback base 0x%llX\n", (unsigned long long)g_base);
    }
    LOG("LC.exe pid=%lu base=0x%llX size=0x%llX\n", g_pid, (unsigned long long)g_base,
        (unsigned long long)g_modSize);
    loadOffsets("offsets.json");
    LOG("ItemEntity vft=0x%llX id=+0x%X cnt=+0x%X guid=+0x%X kind=+0x%X fmt=+0x%X slot=inventory-list\n",
        (unsigned long long)offItemEntityVtable, oItemId, oItemCount, oItemGuid, oItemKind, oItemFmt);

    if (g_serveMode || g_pipeMode) {
        if (g_serveMode) {
            LOG("Serve mode active: request -> inventory JSON line on stdout. Ctrl+C to stop.\n");
            char line[4096];
            while (fgets(line, sizeof(line), stdin)) {
                char* e = line + strlen(line);
                while (e > line && (e[-1] == '\n' || e[-1] == '\r')) *--e = '\0';
                if (strstr(line, "exit") || strstr(line, "quit")) {
                    fprintf(stdout, "{\"cmd\":\"bye\"}\n");
                    break;
                }
                handleRequest(stdout, line);
            }
            LOG("stdin closed - shutting down\n");
            SignedClose();
            return 0;
        }

        // --pipe: accept one client at a time, serve JSON-line requests until
        // the client disconnects, then wait for the next connection.
        LOG("Pipe mode active: %ls (run the exe as admin; Python connects here)\n", PIPE_NAME);
        for (;;) {
            HANDLE h = CreateNamedPipeW(PIPE_NAME, PIPE_ACCESS_DUPLEX,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                PIPE_UNLIMITED_INSTANCES, PIPE_IN_BUFSIZE, PIPE_IN_BUFSIZE, 0, NULL);
            if (h == INVALID_HANDLE_VALUE) {
                LOG("CreateNamedPipe failed error=%u\n", GetLastError());
                Sleep(1000);
                continue;
            }
            LOG("Waiting for client...\n");
            BOOL ok = ConnectNamedPipe(h, NULL);
            if (!ok && GetLastError() != ERROR_PIPE_CONNECTED) {
                CloseHandle(h);
                LOG("ConnectNamedPipe failed error=%u\n", GetLastError());
                Sleep(500);
                continue;
            }
            LOG("Client connected\n");

            int fd = _open_osfhandle((intptr_t)h, _O_BINARY);
            FILE* out = fd >= 0 ? _fdopen(fd, "wb") : NULL;
            if (!out) {
                if (fd >= 0) _close(fd); else CloseHandle(h);
                continue;
            }

            char buf[PIPE_IN_BUFSIZE];
            size_t acc = 0;
            while (1) {
                DWORD rd = 0;
                if (!ReadFile(h, buf + acc, (DWORD)(sizeof(buf) - 1 - acc), &rd, NULL) || rd == 0)
                    break;   // client disconnected or pipe closed
                acc += rd;
                buf[acc] = '\0';
                char* nl;
                while (acc > 0 && (nl = (char*)memchr(buf, '\n', acc)) != NULL) {
                    *nl = '\0';
                    char* e = nl;
                    while (e > buf && (e[-1] == '\r')) *--e = '\0';
                    handleRequest(out, buf);
                    size_t used = (size_t)(nl - buf) + 1;
                    memmove(buf, nl + 1, acc - used);
                    acc -= used;
                }
                if (acc >= sizeof(buf) - 1) acc = 0;   // drop oversized junk
            }
            fclose(out);   // closes the pipe handle
            LOG("Client disconnected\n");
        }
    }

    // Default: one-shot scan to stdout + inv.json.
    runInventoryScan(stdout);
    SignedClose();
    return 0;
}
#endif /* INVENTORY_LISTEN_DLL */