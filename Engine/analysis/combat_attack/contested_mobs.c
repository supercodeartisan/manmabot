/* contested_mobs.c — dedicated DLL/EXE: mobs already attacked by other players.
 *
 * Reads LC.exe via signeddrv (same stack as print_state / attacks_me).
 * AttackAction (ActionComponent slot scan): owner @+0x80, target @+0x88.
 * Emits monsters whose AttackAction target comes from a visible other Player
 * (or a Summon whose AttackAction owner is not me). If the other user is not
 * in the sweep, the mob is absent here (= free to engage).
 *
 * Usage:
 *   contested_mobs.exe [settings_contested_mobs.json] [--once]
 * DLL:
 *   contested_mobs_snapshot(cfgPath, out, outCap) -> nbytes or -1
 *   contested_mobs_shutdown()
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include "signeddrv_client.h"

#define MAXENT   512
#define NAME_CAP 96
#define CFG_CAP  65536
#define OUT_CAP  (1 << 20)

static DWORD g_pid;
static uint64_t g_base;
static uint32_t g_modSize;
static char g_cfg[CFG_CAP];
static int g_attached;

/* Defaults aligned with print_state / entity_offsets 9.30 */
static char g_procName[64] = "LC.exe";
static uint32_t g_offEntMgr = 0x16F8A00u;
static uint32_t g_gridVft = 0x117EAD8u;
static uint32_t g_offHolder = 0xD0u;
static uint32_t g_offSubBeg = 0x180u, g_offSubEnd = 0x188u;
static uint32_t g_offNodeNext = 0x08u, g_offNodeCx = 0x10u, g_offNodeCy = 0x14u;
static uint32_t g_offNodeBeg = 0x18u, g_offNodeEnd = 0x20u;
static uint32_t g_offEntSelf = 0x08u;
static uint32_t g_heads[4] = { 0x798u, 0x7D8u, 0, 0 };
static int g_nh = 2;
static uint32_t g_offCompTable = 0x20u;
static uint32_t g_actVft = 0x1180DF0u;
static uint32_t g_actIdx = 2u;
static uint32_t g_attackActVft = 0x1180B78u;
static uint32_t g_offAtkOwner = 0x80u, g_offAtkTgt = 0x88u;
static uint32_t g_offEntGuid = 0x18u;
static uint32_t g_offCellX = 0x50u, g_offCellY = 0x54u;
static uint32_t g_offNameH = 0x20u, g_offNameObj = 0x20u;
static uint32_t g_offNameBytes = 0x40u, g_offNameLen = 0x50u;
static uint32_t g_vftSelf = 0x11819F0u;
static uint32_t g_vftPlayer = 0x11819B8u;
static uint32_t g_vftMonster = 0x11818A8u;
static uint32_t g_vftSummon = 0x1181E58u;
static int g_intervalMs = 200;
static int g_once = 0;
static uint32_t g_offPlayerX = 0x16EA0F0u, g_offPlayerY = 0x16EA0F4u;
static int g_rosterMs = 100, g_moveTiles = 8;
static uint32_t g_actorVecOff = 0x8A8u, g_actorVecEnd = 0x8B0u;
static uint64_t g_actorCache = 0;

typedef struct { uint64_t ent, fp, owner, tgt; int has, hit; } AcMemo;
static AcMemo g_ac[MAXENT];
static int g_acN = 0;

static char g_snapCache[OUT_CAP];
static int g_snapN = 0;
static DWORD g_snapAt = 0;
static int32_t g_snapX = 0, g_snapY = 0;

typedef struct {
    uint64_t ent;
    uint64_t guid;
    uint32_t vft;
    int32_t cx, cy;
    char name[NAME_CAP];
} Ent;

static Ent g_ents[MAXENT];
static int g_nEnts;

static int rm(uint64_t a, void* b, uint32_t s) {
    uint32_t br = 0;
    return SignedReadMemory(g_pid, a, b, s, &br) && br == s;
}
static uint64_t rq(uint64_t a) {
    uint64_t v = 0;
    rm(a, &v, 8);
    return v;
}
static uint32_t rd32(uint64_t a) {
    uint32_t v = 0;
    rm(a, &v, 4);
    return v;
}
static int isHeap(uint64_t a) {
    return a >= 0x10000000000ULL && a < 0x80000000000ULL;
}
static int isMod(uint64_t a) {
    return a >= g_base && a < g_base + (uint64_t)g_modSize;
}
static uint32_t vrva(uint64_t a) {
    uint64_t v = rq(a);
    return isMod(v) ? (uint32_t)(v - g_base) : 0;
}

static int getModule(uint64_t* base, uint32_t* size) {
    uint64_t peb = 0, ldr = 0, head = 0, cur = 0;
    if (!SignedGetPeb(g_pid, &peb) || !peb) return 0;
    if (!rm(peb + 0x18, &ldr, 8) || !ldr) return 0;
    if (!rm(ldr + 0x20, &head, 8) || !head) return 0;
    for (cur = head; cur && cur != ldr + 0x20;) {
        uint64_t e = cur - 0x10, db = 0;
        uint32_t ds = 0;
        if (rm(e + 0x30, &db, 8) && db && rm(e + 0x40, &ds, 4) && ds) {
            *base = db;
            *size = ds;
            return 1;
        }
        if (!rm(cur, &cur, 8)) break;
    }
    return 0;
}

static DWORD findPid(const char* nameUtf8) {
    wchar_t want[64];
    HANDLE snap;
    PROCESSENTRY32W pe;
    int n = MultiByteToWideChar(CP_UTF8, 0, nameUtf8, -1, want, 64);
    if (n <= 0) return 0;
    snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    pe.dwSize = sizeof(pe);
    if (Process32FirstW(snap, &pe)) {
        do {
            if (_wcsicmp(pe.szExeFile, want) == 0) {
                CloseHandle(snap);
                return pe.th32ProcessID;
            }
        } while (Process32NextW(snap, &pe));
    }
    CloseHandle(snap);
    return 0;
}

static const char* classOf(uint32_t vft) {
    if (vft == g_vftSelf) return "MyPlayer";
    if (vft == g_vftPlayer) return "Player";
    if (vft == g_vftMonster) return "Monster";
    if (vft == g_vftSummon) return "SummonedMonster";
    return "?";
}

static int readName(uint64_t e, char* out, int cap) {
    uint64_t H, no, data;
    uint32_t len;
    out[0] = 0;
    H = rq(e + g_offNameH);
    if (!isHeap(H)) return 0;
    no = rq(H + g_offNameObj);
    if (!isHeap(no)) return 0;
    len = rd32(no + g_offNameLen);
    if (len == 0 || len >= (uint32_t)cap || len > 200) return 0;
    data = rq(no + g_offNameBytes);
    {
        uint64_t src = (len >= 16) ? data : (no + g_offNameBytes);
        if (!rm(src, out, len)) {
            out[0] = 0;
            return 0;
        }
    }
    out[len] = 0;
    return 1;
}

static int isEntityVft(uint32_t r) {
    return r == g_vftSelf || r == g_vftPlayer || r == g_vftMonster || r == g_vftSummon;
}

static int followComp(uint64_t q, uint32_t* outVft, uint64_t* outEnt) {
    /* Same candidate walk as print_state.followComp (entity VFT filter). */
    uint64_t cand[3] = { q, 0, (q > 0x10) ? q - 0x10 : 0 };
    uint64_t p18 = 0;
    int i;
    if (rm(q + 0x18, &p18, 8) && isHeap(p18)) cand[1] = p18;
    for (i = 0; i < 3; i++) {
        uint64_t c = cand[i];
        uint32_t r;
        if (!c || !isHeap(c)) continue;
        r = vrva(c);
        if (r && isEntityVft(r)) {
            *outVft = r;
            *outEnt = c;
            return 1;
        }
    }
    return 0;
}

static uint64_t actionComp(uint64_t e) {
    /* Component vector at e+0x20 .. +0x28; ActionComponent at index 2. */
    uint64_t tb, te, ac;
    uint8_t span[16];
    if (rm(e + g_offCompTable, span, sizeof(span))) {
        memcpy(&tb, span, 8);
        memcpy(&te, span + 8, 8);
    } else {
        tb = rq(e + g_offCompTable);
        te = rq(e + g_offCompTable + 8);
    }
    if (!isHeap(tb) || te <= tb || (te - tb) >= 0x2000 ||
        (te - tb) < (uint64_t)(g_actIdx + 1) * 8)
        return 0;
    ac = rq(tb + (uint64_t)g_actIdx * 8);
    if (!isHeap(ac) || vrva(ac) != g_actVft) return 0;
    return ac;
}

static int readAttack(uint64_t e, uint64_t* outOwner, uint64_t* outTgt) {
    uint64_t ac, fp, owner = 0, tgt = 0;
    uint32_t o;
    uint8_t ab[0x140];
    int nheap = 0, hit = 0, i;
    AcMemo* memo = NULL;
    if (!e) return 0;
    ac = actionComp(e);
    if (!ac || !rm(ac, ab, sizeof(ab))) return 0;
    fp = 1469598103934665603ull;
    for (o = 0; o + 8 <= sizeof(ab); o += 8) {
        uint64_t w;
        memcpy(&w, ab + o, 8);
        if (!isHeap(w)) continue;
        fp ^= w * 1099511628211ull;
        nheap++;
    }
    for (i = 0; i < g_acN; i++) if (g_ac[i].ent == e) { memo = &g_ac[i]; break; }
    if (!memo && g_acN < MAXENT) {
        memo = &g_ac[g_acN++];
        memset(memo, 0, sizeof(*memo));
        memo->ent = e;
    }
    if (memo && memo->has && nheap > 0 && memo->fp == fp) {
        if (!memo->hit) return 0;
        if (outOwner) *outOwner = memo->owner;
        if (outTgt) *outTgt = memo->tgt;
        return 1;
    }
    for (o = 0; o + 8 <= sizeof(ab); o += 8) {
        uint64_t w;
        memcpy(&w, ab + o, 8);
        if (!isHeap(w) || vrva(w) != g_attackActVft) continue;
        owner = rq(w + g_offAtkOwner);
        tgt = rq(w + g_offAtkTgt);
        if (!tgt) continue;
        hit = 1;
        break;
    }
    if (memo) {
        memo->fp = fp;
        memo->has = nheap > 0;
        memo->hit = hit;
        memo->owner = owner;
        memo->tgt = tgt;
    }
    if (!hit) return 0;
    if (outOwner) *outOwner = owner;
    if (outTgt) *outTgt = tgt;
    return 1;
}

static Ent* findByGuid(uint64_t guid) {
    int i;
    if (!guid) return NULL;
    for (i = 0; i < g_nEnts; i++)
        if (g_ents[i].guid == guid) return &g_ents[i];
    return NULL;
}

static int pushActor(int n, uint64_t ent, uint32_t rva, int32_t cx, int32_t cy, const uint8_t* hdr) {
    int i;
    Ent* E;
    int32_t ecx = 0, ecy = 0;
    if (n >= MAXENT || !ent) return n;
    for (i = 0; i < n; i++) if (g_ents[i].ent == ent) return n;
    E = &g_ents[n];
    memset(E, 0, sizeof(*E));
    E->ent = ent;
    E->vft = rva;
    E->cx = cx;
    E->cy = cy;
    if (hdr && g_offEntGuid + 8 <= 0x50) memcpy(&E->guid, hdr + g_offEntGuid, 8);
    else E->guid = rq(ent + g_offEntGuid);
    if (hdr && g_offCellX + 4 <= 0x50 && g_offCellY + 4 <= 0x50) {
        memcpy(&ecx, hdr + g_offCellX, 4);
        memcpy(&ecy, hdr + g_offCellY, 4);
    } else {
        ecx = (int32_t)rd32(ent + g_offCellX);
        ecy = (int32_t)rd32(ent + g_offCellY);
    }
    if (ecx > 1000 && ecx < 60000 && ecy > 1000 && ecy < 60000) {
        E->cx = ecx;
        E->cy = ecy;
    }
    readName(ent, E->name, NAME_CAP);
    return n + 1;
}

static int sweepVector(uint64_t actor) {
    uint64_t beg, end, slots, i;
    int n = 0;
    static uint64_t chunk[512];
    if (!g_actorVecOff || !g_actorVecEnd) return 0;
    beg = rq(actor + g_actorVecOff);
    end = rq(actor + g_actorVecEnd);
    if (!isHeap(beg) || !isHeap(end) || end <= beg) return 0;
    if (((end - beg) % 8) != 0 || (end - beg) > (16ull << 20)) return 0;
    slots = (end - beg) / 8;
    if (slots < 2) return 0;
    for (i = 0; i < slots && n < MAXENT; ) {
        int cc = (slots - i > 512) ? 512 : (int)(slots - i);
        int j;
        if (!rm(beg + i * 8, chunk, (uint32_t)(cc * 8))) return 0;
        for (j = 0; j < cc && n < MAXENT; j += 2) {
            uint64_t e = chunk[j];
            uint8_t hb[0x50];
            uint64_t vftp, self;
            uint32_t rva;
            if (!isHeap(e) || !rm(e, hb, sizeof(hb))) continue;
            memcpy(&vftp, hb, 8);
            if (g_offEntSelf + 8 > sizeof(hb)) continue;
            memcpy(&self, hb + g_offEntSelf, 8);
            if (g_offEntSelf && self != e) continue;
            if (!g_base || vftp < g_base || vftp - g_base > g_modSize) continue;
            rva = (uint32_t)(vftp - g_base);
            if (!isEntityVft(rva)) continue;
            n = pushActor(n, e, rva, 0, 0, hb);
        }
        i += (uint64_t)cc;
    }
    return n;
}

static int sweep(void) {
    int n = 0;
    uint64_t mgr, holder, bgn, end, best = 0;
    int hi;
    g_nEnts = 0;
    if (g_actorCache && vrva(g_actorCache) == g_gridVft) best = g_actorCache;
    if (!best) {
        mgr = rq(g_base + g_offEntMgr);
        if (!isHeap(mgr)) return 0;
        holder = rq(mgr + g_offHolder);
        if (!isHeap(holder)) return 0;
        bgn = rq(holder + g_offSubBeg);
        end = rq(holder + g_offSubEnd);
        if (!isHeap(bgn) || end <= bgn || (end - bgn) > 0x2000) return 0;
        for (uint64_t e = bgn; e + 16 <= end; e += 16) {
            uint64_t obj = rq(e);
            if (!isHeap(obj)) continue;
            if (vrva(obj) == g_gridVft) {
                best = obj;
                break;
            }
        }
    }
    if (!best) { g_actorCache = 0; return 0; }
    g_actorCache = best;
    n = sweepVector(best);
    if (n > 0) { g_nEnts = n; return n; }
    n = 0;
    for (hi = 0; hi < g_nh; hi++) {
        uint64_t sent = rq(best + g_heads[hi] + 8);
        uint64_t cur;
        int hops = 0;
        if (!isHeap(sent)) continue;
        cur = rq(sent + g_offNodeNext);
        while (cur && cur != sent && isHeap(cur) && n < MAXENT && hops++ < 1100) {
            uint8_t nb[0x28];
            uint64_t next, vb, ve;
            int32_t cx, cy;
            static uint64_t ptrs[512];
            if (g_offNodeNext + 8 > sizeof(nb) || g_offNodeCx + 4 > sizeof(nb) ||
                g_offNodeCy + 4 > sizeof(nb) || g_offNodeBeg + 8 > sizeof(nb) ||
                g_offNodeEnd + 8 > sizeof(nb))
                break;
            if (!rm(cur, nb, sizeof(nb))) break;
            memcpy(&next, nb + g_offNodeNext, 8);
            memcpy(&cx, nb + g_offNodeCx, 4);
            memcpy(&cy, nb + g_offNodeCy, 4);
            memcpy(&vb, nb + g_offNodeBeg, 8);
            memcpy(&ve, nb + g_offNodeEnd, 8);
            cur = next;
            if (!isHeap(vb) || ve < vb || (ve - vb) > 0x1000) continue;
            {
                uint64_t left = (ve - vb) / 8;
                uint64_t pi = 0;
                while (pi < left && n < MAXENT) {
                    int cc = (left - pi > 512) ? 512 : (int)(left - pi);
                    int j;
                    if (!rm(vb + pi * 8, ptrs, (uint32_t)(cc * 8))) break;
                    for (j = 0; j < cc && n < MAXENT; j++) {
                        uint64_t q = ptrs[j], ent = 0;
                        uint32_t rva = 0;
                        if (!isHeap(q) || !followComp(q, &rva, &ent)) continue;
                        if (g_offEntSelf && rq(ent + g_offEntSelf) != ent) continue;
                        n = pushActor(n, ent, rva, cx, cy, NULL);
                    }
                    pi += (uint64_t)cc;
                }
            }
        }
    }
    g_nEnts = n;
    return n;
}

static uint64_t pickMeGuid(void) {
    int i;
    for (i = 0; i < g_nEnts; i++)
        if (g_ents[i].vft == g_vftSelf) return g_ents[i].guid;
    return 0;
}

/* ---- tiny JSON helpers ---- */
typedef struct {
    char* p;
    char* end;
} JOut;

static void jputc(JOut* o, char c) {
    if (o->p + 1 < o->end) *o->p++ = c;
}
static void jputs(JOut* o, const char* s) {
    while (*s) jputc(o, *s++);
}
static void jputf(JOut* o, const char* fmt, ...) {
    char tmp[512];
    va_list ap;
    int n;
    va_start(ap, fmt);
    n = vsnprintf(tmp, sizeof(tmp), fmt, ap);
    va_end(ap);
    if (n > 0) jputs(o, tmp);
}
static void jescape(JOut* o, const char* s) {
    jputc(o, '"');
    for (; s && *s; s++) {
        unsigned char c = (unsigned char)*s;
        if (c == '"' || c == '\\') {
            jputc(o, '\\');
            jputc(o, (char)c);
        } else if (c < 0x20) {
            jputf(o, "\\u%04x", c);
        } else {
            jputc(o, (char)c);
        }
    }
    jputc(o, '"');
}

static uint32_t hexU32(const char* s, uint32_t defv) {
    if (!s || !*s) return defv;
    return (uint32_t)strtoul(s, NULL, 0);
}

static void applyJsonHex(const char* key, uint32_t* dst) {
    char pat[96];
    char* p;
    sprintf(pat, "\"%s\"", key);
    p = strstr(g_cfg, pat);
    if (!p) return;
    p = strchr(p + strlen(pat), ':');
    if (!p) return;
    p++;
    while (*p == ' ' || *p == '\t' || *p == '"') p++;
    *dst = hexU32(p, *dst);
}

static void loadSettings(const char* path) {
    FILE* f;
    size_t n;
    if (!path || !path[0]) return;
    f = fopen(path, "rb");
    if (!f) return;
    n = fread(g_cfg, 1, CFG_CAP - 1, f);
    fclose(f);
    g_cfg[n] = 0;
    {
        char* p = strstr(g_cfg, "\"process_name\"");
        if (p) {
            p = strchr(p, ':');
            if (p) {
                char* q;
                p++;
                while (*p == ' ' || *p == '\t' || *p == '"') p++;
                q = p;
                while (*q && *q != '"' && *q != ',' && *q != '\n') q++;
                if (q > p && (size_t)(q - p) < sizeof(g_procName)) {
                    memcpy(g_procName, p, (size_t)(q - p));
                    g_procName[q - p] = 0;
                }
            }
        }
    }
    applyJsonHex("ent_mgr_offset", &g_offEntMgr);
    applyJsonHex("grid_vft", &g_gridVft);
    applyJsonHex("act_vft", &g_actVft);
    applyJsonHex("attack_act_vft", &g_attackActVft);
    applyJsonHex("vft_self", &g_vftSelf);
    applyJsonHex("vft_player", &g_vftPlayer);
    applyJsonHex("vft_monster", &g_vftMonster);
    applyJsonHex("vft_summon", &g_vftSummon);
    applyJsonHex("off_atk_owner", &g_offAtkOwner);
    applyJsonHex("off_atk_tgt", &g_offAtkTgt);
    applyJsonHex("off_ent_guid", &g_offEntGuid);
}

static int attach(const char* cfgPath) {
    DWORD pid;
    if (g_attached) return 0;
    if (cfgPath && cfgPath[0]) loadSettings(cfgPath);
    pid = findPid(g_procName);
    if (!pid) return -1;
    if (!SignedOpen()) return -2;
    SignedSetTarget(pid);
    g_pid = pid;
    if (!getModule(&g_base, &g_modSize)) {
        SignedClose();
        return -3;
    }
    g_attached = 1;
    return 0;
}

static void detach(void) {
    if (!g_attached) return;
    SignedClose();
    g_attached = 0;
    g_nEnts = 0;
    g_actorCache = 0;
    g_snapN = 0;
    g_acN = 0;
}

static int rosterFresh(int32_t* x, int32_t* y) {
    int32_t dx, dy;
    if (!rm(g_base + g_offPlayerX, x, 4) || !rm(g_base + g_offPlayerY, y, 4)) return 0;
    if (!g_snapN) return 0;
    if ((int)(GetTickCount() - g_snapAt) >= g_rosterMs) return 0;
    dx = *x > g_snapX ? *x - g_snapX : g_snapX - *x;
    dy = *y > g_snapY ? *y - g_snapY : g_snapY - *y;
    return dx <= g_moveTiles && dy <= g_moveTiles;
}

static int buildSnapshot(char* out, int outCap) {
    JOut jo;
    uint64_t meGuid;
    int first = 1;
    int i;
    int nHit = 0;
    int n;
    int32_t px = 0, py = 0;
    uint64_t seenMob[MAXENT];
    int nSeen = 0;
    if (!out || outCap < 64) return -1;
    if (!g_attached) return -1;
    if (rosterFresh(&px, &py) && g_snapN < outCap) {
        memcpy(out, g_snapCache, (size_t)g_snapN);
        out[g_snapN] = 0;
        return g_snapN;
    }
    sweep();
    meGuid = pickMeGuid();
    jo.p = out;
    jo.end = out + outCap;
    jputf(&jo,
          "{\"ok\":true,\"pid\":%lu,\"base\":\"0x%llX\",\"entities\":%d,"
          "\"me_guid\":\"0x%llX\",\"contested\":[",
          (unsigned long)g_pid, (unsigned long long)g_base, g_nEnts,
          (unsigned long long)meGuid);
    for (i = 0; i < g_nEnts; i++) {
        uint64_t owner = 0, tgt = 0;
        Ent* A = &g_ents[i];
        Ent* M;
        int dup, j;
        if (A->vft != g_vftPlayer && A->vft != g_vftSummon) continue;
        if (!readAttack(A->ent, &owner, &tgt)) continue;
        /* Other player's direct attack, or a summon not owned by me. */
        if (A->vft == g_vftPlayer) {
            if (meGuid && A->guid == meGuid) continue;
        } else {
            if (!owner || (meGuid && owner == meGuid)) continue;
        }
        M = findByGuid(tgt);
        if (!M || M->vft != g_vftMonster) continue;
        for (j = 0, dup = 0; j < nSeen; j++)
            if (seenMob[j] == M->guid) {
                dup = 1;
                break;
            }
        if (dup) continue;
        if (nSeen < MAXENT) seenMob[nSeen++] = M->guid;
        if (!first) jputc(&jo, ',');
        first = 0;
        nHit++;
        jputf(&jo,
              "{\"ent\":\"0x%llX\",\"guid\":\"0x%llX\","
              "\"attacker_ent\":\"0x%llX\",\"attacker_guid\":\"0x%llX\","
              "\"owner\":\"0x%llX\",\"tgt\":\"0x%llX\",\"attacker_class\":",
              (unsigned long long)M->ent, (unsigned long long)M->guid,
              (unsigned long long)A->ent, (unsigned long long)A->guid,
              (unsigned long long)owner, (unsigned long long)tgt);
        jescape(&jo, classOf(A->vft));
        jputs(&jo, ",\"attacker_name\":");
        jescape(&jo, A->name);
        jputs(&jo, ",\"name\":");
        jescape(&jo, M->name);
        jputf(&jo, ",\"world\":{\"cx\":%d,\"cy\":%d}}", M->cx, M->cy);
    }
    jputf(&jo, "],\"count\":%d}", nHit);
    if (jo.p >= jo.end - 1) return -1;
    *jo.p = 0;
    n = (int)(jo.p - out);
    if (n > 0 && n < (int)sizeof(g_snapCache)) {
        memcpy(g_snapCache, out, (size_t)n);
        g_snapN = n;
        g_snapAt = GetTickCount();
        g_snapX = px;
        g_snapY = py;
    }
    return n;
}

#ifdef CONTESTED_MOBS_DLL
__declspec(dllexport) int contested_mobs_snapshot(const char* cfgPath, char* out, int outCap) {
    if (attach(cfgPath ? cfgPath : "") != 0) return -1;
    return buildSnapshot(out, outCap);
}
__declspec(dllexport) void contested_mobs_shutdown(void) { detach(); }
#else
int main(int argc, char** argv) {
    const char* cfg = "settings_contested_mobs.json";
    int i;
    SetConsoleOutputCP(CP_UTF8);
    for (i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--once"))
            g_once = 1;
        else
            cfg = argv[i];
    }
    if (attach(cfg) != 0) {
        fprintf(stderr, "attach failed (LC.exe / driver)\n");
        return 1;
    }
    for (;;) {
        static char buf[OUT_CAP];
        int n = buildSnapshot(buf, (int)sizeof(buf));
        if (n > 0) {
            fwrite(buf, 1, (size_t)n, stdout);
            fputc('\n', stdout);
            fflush(stdout);
        }
        if (g_once) break;
        Sleep((DWORD)g_intervalMs);
    }
    detach();
    return 0;
}
#endif
