/* hotbar_listen.c — HudSlotDataSubsystem reader (24 slots).
 *
 * Chain: mgr=*(BASE+MGR) → holder+0xD0 → sub[HSD_IDX]+HSD_ADJ
 * Map: std::map<int,Slot*>  key=0..23
 *   0-7  = F1 / F5-F12
 *   8-15 = F2 / F5-F12
 *   16-23= F3 / F5-F12
 * SPELL name is "힐(4/0)" → JSON name="힐", label="힐(4/0)"
 * ITEM name from nametable; count from inventory uid join.
 *
 * Offsets: skill_offsets.txt then ../inventories/inventory_offsets.txt (MSG_*).
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../entities/signeddrv_client.h"
#include "nametable.h"

static DWORD g_pid = 0;
static uint64_t g_base = 0;
static uint64_t g_modSize = 0;
static int g_dllMode = 0;
static char g_offsetsPathBuf[MAX_PATH] = "skill_offsets.txt";

#define LOG(fmt, ...) do { if (!g_dllMode) fprintf(stderr, fmt, ##__VA_ARGS__); } while (0)

static uint32_t MGR = 0x1668860, HOLDER = 0xD0, SUB_BEG = 0x180, SUB_END = 0x188;
static uint32_t HSD_IDX = 30, HSD_ADJ = 0x18, HSD_VFT = 0x1182F48, HSD_VFT2 = 0x1182EF8;
static uint32_t MAP_HEAD = 0x08, MAP_SIZE = 0x10;
static uint32_t N_L = 0x00, N_R = 0x10, N_NIL = 0x19, N_KEY = 0x20, N_VAL = 0x28;
static uint32_t V_TYPE = 0x08, V_RAW = 0x00, V_ID = 0xC0, V_CFG = 0x0C, V_T10 = 0x10;
static uint32_t V_STRLEN = 0x40, V_STR = 0x30;

static uint32_t INV_MGR = 0x1668860, INV_VFT = 0x11C6BE8;
static uint32_t INV_VEC_BEG = 0x3D8, INV_VEC_END = 0x3E0;
static uint32_t IT_ID = 0x18, IT_COUNT = 0x38, IT_FMT = 0x68, IT_TMPL = 0x20;
static uint32_t IT_ENCH = 0x3C, IT_VFT = 0x11C6640;

static int rm(uint64_t a, void* b, uint32_t s) {
    uint32_t br = 0;
    return SignedReadMemory(g_pid, a, b, s, &br) && br == s;
}
static uint64_t q64(uint64_t a) { uint64_t v = 0; rm(a, &v, 8); return v; }
static uint32_t d32(uint64_t a) { uint32_t v = 0; rm(a, &v, 4); return v; }
static uint8_t d8(uint64_t a) { uint8_t v = 0; rm(a, &v, 1); return v; }
static int isHeap(uint64_t a) { return a >= 0x10000000000ULL && a < 0x70000000000ULL; }
static int isMod(uint64_t a) { return g_base && g_modSize && a >= g_base && a < g_base + g_modSize; }
static uint32_t vrva(uint64_t o) { uint64_t v = q64(o); return isMod(v) ? (uint32_t)(v - g_base) : 0; }

static DWORD findPid(const wchar_t* name) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32W pe; pe.dwSize = sizeof(pe);
    DWORD pid = 0;
    if (snap == INVALID_HANDLE_VALUE) return 0;
    if (Process32FirstW(snap, &pe)) do {
        if (_wcsicmp(pe.szExeFile, name) == 0) { pid = pe.th32ProcessID; break; }
    } while (Process32NextW(snap, &pe));
    CloseHandle(snap);
    return pid;
}

static int getModuleBase(uint64_t* base) {
    uint64_t peb = 0, ldr = 0, listHead = 0, cur = 0, img = 0;
    if (!SignedGetPeb(g_pid, &peb) || !peb) return 0;
    if (rm(peb + 0x10, &img, 8) && img) { *base = img; return 1; }
    if (!rm(peb + 0x18, &ldr, 8) || !ldr) return 0;
    if (!rm(ldr + 0x20, &listHead, 8) || !listHead) return 0;
    cur = listHead;
    for (int g = 0; g < 5000 && cur && cur != (ldr + 0x20); g++) {
        uint64_t entry = cur - 0x10, dllBase = 0;
        if (rm(entry + 0x30, &dllBase, 8) && dllBase) { *base = dllBase; return 1; }
        if (!rm(cur, &cur, 8)) return 0;
    }
    return 0;
}

static void resolveModuleSize(void) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPMODULE | TH32CS_SNAPMODULE32, g_pid);
    if (snap != INVALID_HANDLE_VALUE) {
        MODULEENTRY32W me; me.dwSize = sizeof(me);
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
    if (!g_modSize) g_modSize = 0x4000000ULL;
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

static int fileExists(const char* path) {
    FILE* f = fopen(path, "r");
    if (!f) return 0;
    fclose(f);
    return 1;
}

static void loadSkillReg(const char* path) {
    FILE* f;
    char line[256];
    if (!path || !path[0]) return;
    f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof(line), f)) {
        char* p = strchr(line, '=');
        char* k;
        if (!p) continue;
        *p = 0;
        k = line;
        while (*k == ' ' || *k == '\t') k++;
        {
            char* ke = k + strlen(k);
            while (ke > k && (ke[-1] == ' ' || ke[-1] == '\t' || ke[-1] == '\n' || ke[-1] == '\r')) *--ke = 0;
        }
        /* HSD_IDX is decimal. Every other key is hex (0x optional). */
        if (!strcmp(k, "HSD_IDX")) HSD_IDX = (uint32_t)strtoul(p + 1, 0, 0);
        else if (!strcmp(k, "MGR")) MGR = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "HOLDER_OFF")) HOLDER = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "SUBLIST_BEG")) SUB_BEG = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "SUBLIST_END")) SUB_END = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "HSD_ADJ")) HSD_ADJ = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "HSD_VFT")) HSD_VFT = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "HSD_VFT2")) HSD_VFT2 = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "MAP_HEAD")) MAP_HEAD = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "MAP_SIZE")) MAP_SIZE = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "N_L")) N_L = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "N_R")) N_R = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "N_NIL")) N_NIL = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "N_KEY")) N_KEY = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "N_VAL")) N_VAL = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "V_TYPE")) V_TYPE = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "V_RAW")) V_RAW = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "V_ID")) V_ID = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "V_CFG")) V_CFG = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "V_T10")) V_T10 = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "V_STRLEN")) V_STRLEN = (uint32_t)strtoul(p + 1, 0, 16);
        else if (!strcmp(k, "V_STR")) V_STR = (uint32_t)strtoul(p + 1, 0, 16);
    }
    fclose(f);
}

static void loadInvReg(const char* path) {
    FILE* f;
    char L[256];
    if (!path || !path[0]) return;
    f = fopen(path, "r");
    if (!f) return;
    while (fgets(L, sizeof(L), f)) {
        char* p = strchr(L, '=');
        char* k;
        if (!p) continue;
        *p = 0;
        k = L;
        while (*k == ' ' || *k == '\t') k++;
        {
            char* t;
            for (t = k; *t; t++) if (*t == ' ' || *t == '\t') { *t = 0; break; }
        }
        if (!strcmp(k, "MGR")) INV_MGR = (uint32_t)strtoul(p + 1, 0, 0);
        else if (!strcmp(k, "INV_VFT")) INV_VFT = (uint32_t)strtoul(p + 1, 0, 0);
        else if (!strcmp(k, "INV_VEC_BEG")) INV_VEC_BEG = (uint32_t)strtoul(p + 1, 0, 0);
        else if (!strcmp(k, "INV_VEC_END")) INV_VEC_END = (uint32_t)strtoul(p + 1, 0, 0);
        else if (!strcmp(k, "ITEM_ID")) IT_ID = (uint32_t)strtoul(p + 1, 0, 0);
        else if (!strcmp(k, "ITEM_TEMPLATE")) IT_TMPL = (uint32_t)strtoul(p + 1, 0, 0);
        else if (!strcmp(k, "ITEM_COUNT")) IT_COUNT = (uint32_t)strtoul(p + 1, 0, 0);
        else if (!strcmp(k, "ITEM_ENCHANT")) IT_ENCH = (uint32_t)strtoul(p + 1, 0, 0);
        else if (!strcmp(k, "ITEM_FMT")) IT_FMT = (uint32_t)strtoul(p + 1, 0, 0);
        else if (!strcmp(k, "ITEM_VFT")) IT_VFT = (uint32_t)strtoul(p + 1, 0, 0);
    }
    fclose(f);
}

static void loadAllOffsets(const char* skillPath) {
    char inv[MAX_PATH];
    loadSkillReg(skillPath);
    siblingPath(skillPath, "inventory_offsets.txt", inv, sizeof(inv));
    if (!fileExists(inv))
        siblingPath(skillPath, "..\\inventories\\inventory_offsets.txt", inv, sizeof(inv));
    loadInvReg(inv);
}

static uint64_t findHSD(void) {
    uint64_t mgr, holder, b, e, sub = 0;
    if (!g_base) return 0;
    mgr = q64(g_base + MGR);
    if (!isHeap(mgr)) return 0;
    holder = q64(mgr + HOLDER);
    if (!isHeap(holder)) return 0;
    b = q64(holder + SUB_BEG);
    e = q64(holder + SUB_END);
    if (b + 16ull * HSD_IDX + 16 <= e) sub = q64(b + 16ull * HSD_IDX);
    if (isHeap(sub)) {
        uint64_t h = sub + HSD_ADJ;
        if (vrva(h) == HSD_VFT) return h;
        if (vrva(sub) == HSD_VFT2) {
            uint64_t h2 = sub + HSD_ADJ;
            if (vrva(h2) == HSD_VFT) return h2;
        }
    }
    for (uint64_t x = b; x + 16 <= e; x += 16) {
        uint64_t s = q64(x);
        if (!isHeap(s)) continue;
        if (vrva(s + HSD_ADJ) == HSD_VFT) return s + HSD_ADJ;
    }
    return 0;
}

typedef struct { int slot, type; uint32_t id, cfg, raw, t10; char name[160]; } SL;
static SL g_s[128];
static int g_n = 0;

typedef struct { uint32_t uid, tmpl, count, enchant; char name[160]; } InvItem;
static InvItem g_inv[512];
static int g_invn = 0;
static NtCtx* g_nt = 0;

static void buildInvMap(void) {
    uint64_t mgr, holder, b, e, inv = 0, vb, ve, nn;
    uint64_t seen[512];
    int ns = 0;
    g_invn = 0;
    mgr = q64(g_base + INV_MGR);
    if (!isHeap(mgr)) return;
    holder = q64(mgr + HOLDER);
    if (!isHeap(holder)) return;
    b = q64(holder + SUB_BEG);
    e = q64(holder + SUB_END);
    for (uint64_t x = b; x + 16 <= e; x += 16) {
        uint64_t s = q64(x);
        if (vrva(s) == INV_VFT) { inv = s; break; }
    }
    if (!inv) return;
    vb = q64(inv + INV_VEC_BEG);
    ve = q64(inv + INV_VEC_END);
    if (!isHeap(vb) || ve <= vb || (ve - vb) > 0x20000) return;
    nn = (ve - vb) / 8;
    for (uint64_t k = 0; k < nn && ns < 512; k++) {
        uint64_t it = q64(vb + k * 8);
        int d = 0, z;
        InvItem* o;
        char fmt[128] = {0};
        uint32_t ln;
        if (!isHeap(it) || vrva(it) != IT_VFT) continue;
        for (z = 0; z < ns; z++) if (seen[z] == it) { d = 1; break; }
        if (d) continue;
        seen[ns++] = it;
        o = &g_inv[g_invn++];
        o->uid = d32(it + IT_ID);
        o->tmpl = d32(it + IT_TMPL);
        o->count = d32(it + IT_COUNT);
        o->enchant = d32(it + IT_ENCH);
        o->name[0] = 0;
        ln = d32(it + IT_FMT + 0x10);
        if (ln >= 1 && ln < 127) {
            uint64_t sp = (ln > 15) ? q64(it + IT_FMT) : (it + IT_FMT);
            uint8_t bb[128];
            if (rm(sp, bb, ln)) { memcpy(fmt, bb, ln); fmt[ln] = 0; }
        }
        if (g_nt && strchr(fmt, '$')) ntResolveFmt(g_nt, fmt, o->name, (int)sizeof(o->name));
        else strncpy(o->name, fmt, sizeof(o->name) - 1);
    }
}

static InvItem* invByUid(uint32_t uid) {
    int i;
    for (i = 0; i < g_invn; i++) if (g_inv[i].uid == uid) return &g_inv[i];
    return 0;
}

static void walk(uint64_t node, uint64_t header, int depth) {
    SL* s;
    uint64_t val;
    uint32_t ln;
    if (!node || node == header || g_n >= 128 || depth > 40) return;
    if (d8(node + N_NIL)) return;
    walk(q64(node + N_L), header, depth + 1);
    s = &g_s[g_n];
    s->slot = (int)d32(node + N_KEY);
    s->name[0] = 0;
    s->type = 0;
    s->id = s->cfg = s->raw = s->t10 = 0;
    val = q64(node + N_VAL);
    if (isHeap(val)) {
        s->type = (int)d32(val + V_TYPE);
        s->raw = d32(val + V_RAW);
        s->id = d32(val + V_ID);
        s->cfg = d32(val + V_CFG);
        s->t10 = d32(val + V_T10);
        ln = d32(val + V_STRLEN);
        if (ln >= 1 && ln < 159) {
            uint64_t sp = (ln > 15) ? q64(val + V_STR) : (val + V_STR);
            uint8_t b[160];
            if (rm(sp, b, ln)) { memcpy(s->name, b, ln); s->name[ln] = 0; }
        }
    }
    g_n++;
    walk(q64(node + N_R), header, depth + 1);
}

static void spellBaseName(const char* src, char* out, int cap) {
    int n;
    char* p;
    if (!out || cap < 2) return;
    strncpy(out, src ? src : "", (size_t)cap - 1);
    out[cap - 1] = 0;
    n = (int)strlen(out);
    if (n < 4 || out[n - 1] != ')') return;
    p = strrchr(out, '(');
    if (!p || p <= out) return;
    {
        char* q = p + 1;
        if (*q < '0' || *q > '9') return;
        while (*q >= '0' && *q <= '9') q++;
        if (*q != '/') return;
        q++;
        if (*q < '0' || *q > '9') return;
        while (*q >= '0' && *q <= '9') q++;
        if (*q != ')' || q[1] != 0) return;
    }
    while (p > out && p[-1] == ' ') p--;
    *p = 0;
}

static const char* slotKey(int slot) {
    static const char* keys[8] = { "f5", "f6", "f7", "f8", "f9", "f10", "f11", "f12" };
    if (slot < 0) return "f5";
    return keys[slot % 8];
}

static void jsonStr(FILE* f, const char* s) {
    fputc('"', f);
    for (; s && *s; s++) {
        unsigned char c = (unsigned char)*s;
        if (c == '"' || c == '\\') { fputc('\\', f); fputc((char)c, f); }
        else if (c >= 32) fputc((char)c, f);
    }
    fputc('"', f);
}

static SL* slotOf(int slot) {
    int i;
    for (i = 0; i < g_n; i++) if (g_s[i].slot == slot) return &g_s[i];
    return 0;
}

static void writeHotbarJson(FILE* f) {
    int slot, first = 1;
    fprintf(f, "{\"n\":24,\"slots\":[");
    for (slot = 0; slot < 24; slot++) {
        SL* s = slotOf(slot);
        int box = slot / 8 + 1;
        const char* key = slotKey(slot);
        const char* kind = "EMPTY";
        char label[200] = {0};
        char name[200] = {0};
        uint32_t cnt = 0, cfg = 0, uid = 0;
        if (s) {
            cfg = s->cfg;
            uid = s->raw;
            if (s->type == 1) kind = "SPELL";
            else if (s->type == 2) {
                if (s->raw && s->raw != 0xFFFFFFFFu) kind = "ITEM";
                else if (s->raw == 0xFFFFFFFFu) kind = "EMPTY";
                else kind = "STALE";
            } else if (s->raw == 0xFFFFFFFFu) kind = "EMPTY";
            else kind = "?";

            if (s->type == 2 && s->raw && s->raw != 0xFFFFFFFFu) {
                InvItem* iu = invByUid(s->raw);
                if (iu) {
                    strncpy(label, iu->name, sizeof(label) - 1);
                    cnt = iu->count;
                } else if (strchr(s->name, '$') && g_nt)
                    ntResolveFmt(g_nt, s->name, label, (int)sizeof(label));
                else
                    strncpy(label, s->name, sizeof(label) - 1);
                strncpy(name, label, sizeof(name) - 1);
            } else {
                if (strchr(s->name, '$') && g_nt)
                    ntResolveFmt(g_nt, s->name, label, (int)sizeof(label));
                else
                    strncpy(label, s->name, sizeof(label) - 1);
                if (s->type == 1) spellBaseName(label, name, (int)sizeof(name));
                else strncpy(name, label, sizeof(name) - 1);
            }
        }
        if (!first) fputc(',', f);
        first = 0;
        fprintf(f, "{\"slot\":%d,\"index\":%d,\"box\":%d,\"key\":\"%s\",\"type\":\"%s\",",
            slot, slot + 1, box, key, kind);
        fprintf(f, "\"name\":"); jsonStr(f, name);
        fprintf(f, ",\"label\":"); jsonStr(f, label);
        fprintf(f, ",\"count\":%u,\"cfg\":%u,\"uid\":%u}", cnt, cfg, uid);
    }
    fprintf(f, "]}");
}

static int scanHotbar(FILE* out) {
    uint64_t hsd;
    NtCtx nt;
    char invPath[MAX_PATH];

    hsd = findHSD();
    if (!hsd) {
        LOG("HudSlotDataSubsystem not found (run skilllocate.exe)\n");
        if (out) fprintf(out, "{\"error\":\"hsd_missing\",\"n\":0,\"slots\":[]}");
        return 0;
    }
    siblingPath(g_offsetsPathBuf, "..\\inventories\\inventory_offsets.txt", invPath, sizeof(invPath));
    if (!fileExists(invPath))
        siblingPath(g_offsetsPathBuf, "inventory_offsets.txt", invPath, sizeof(invPath));
    ntLoadRegistry(&nt, invPath);
    nt.pid = g_pid;
    nt.base = g_base;
    nt.modSize = (uint32_t)g_modSize;
    g_nt = &nt;
    buildInvMap();
    g_n = 0;
    {
        uint64_t header = q64(hsd + MAP_HEAD);
        if (header) walk(q64(header + 0x08), header, 0);
    }
    if (out) writeHotbarJson(out);
    return 1;
}

static int g_attached = 0;
static int g_offsetsLoaded = 0;

static void hbDetach(void) {
    if (g_attached) SignedClose();
    g_attached = 0;
    g_pid = 0;
    g_base = 0;
    g_modSize = 0;
}

static int hbEnsure(const char* offsetsPath) {
    DWORD pid;
    g_dllMode = 1;
    if (offsetsPath && offsetsPath[0]) {
        strncpy(g_offsetsPathBuf, offsetsPath, sizeof(g_offsetsPathBuf) - 1);
        g_offsetsPathBuf[sizeof(g_offsetsPathBuf) - 1] = 0;
        g_offsetsLoaded = 0;
    }
    if (!g_offsetsLoaded) {
        loadAllOffsets(g_offsetsPathBuf);
        g_offsetsLoaded = 1;
    }
    pid = findPid(L"LC.exe");
    if (!pid) { hbDetach(); return 0; }
    if (g_attached && pid == g_pid) return 1;
    if (g_attached) hbDetach();
    if (!SignedOpen()) return 0;
    g_pid = pid;
    SignedSetTarget(g_pid);
    getModuleBase(&g_base);
    resolveModuleSize();
    if (!g_base) {
        SignedClose();
        g_pid = 0;
        return 0;
    }
    g_attached = 1;
    return 1;
}

__declspec(dllexport) int hotbar_listen_snapshot(const char* offsetsPath, char* out, int outCap) {
    FILE* tf;
    long n;
    size_t got;
    if (!out || outCap < 16) return -1;
    if (!hbEnsure(offsetsPath)) return -1;
    tf = tmpfile();
    if (!tf) return -1;
    if (!scanHotbar(tf)) {
        fclose(tf);
        return -1;
    }
    fflush(tf);
    if (fseek(tf, 0, SEEK_END) != 0) { fclose(tf); return -1; }
    n = ftell(tf);
    if (n < 2 || n >= outCap) { fclose(tf); return -2; }
    fseek(tf, 0, SEEK_SET);
    got = fread(out, 1, (size_t)n, tf);
    fclose(tf);
    if (got < 2) return -1;
    out[got] = 0;
    return (int)got;
}

__declspec(dllexport) void hotbar_listen_shutdown(void) {
    hbDetach();
    g_offsetsLoaded = 0;
}

#ifndef HOTBAR_LISTEN_DLL
int main(int argc, char** argv) {
    (void)argc; (void)argv;
    SetConsoleOutputCP(CP_UTF8);
    if (!SignedOpen()) { printf("driver fail\n"); return 1; }
    g_pid = findPid(L"LC.exe");
    if (!g_pid) { printf("LC.exe not running\n"); SignedClose(); return 1; }
    SignedSetTarget(g_pid);
    getModuleBase(&g_base);
    resolveModuleSize();
    if (!g_base) { printf("module fail\n"); SignedClose(); return 1; }
    loadAllOffsets("skill_offsets.txt");
    LOG("[anchor] mgr=0x%X hsd_vft=0x%X idx=%u adj=0x%X\n", MGR, HSD_VFT, HSD_IDX, HSD_ADJ);
    if (!scanHotbar(stdout)) { SignedClose(); return 1; }
    printf("\n");
    SignedClose();
    return 0;
}
#endif
