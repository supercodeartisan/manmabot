/* probe_my_anim.c — poll MyPlayer action/anim candidates while walk/stand.
 *
 * Samples (change-log + 1s heartbeat):
 *   - ActorControllerComponent (+0x58 active cmd VFT)
 *   - ActionComponent slot VFTs (heap ptrs with module vft in AC scan)
 *   - AC+0x40 dword, AC+0x49 dead byte
 *   - cell from PRES_B +0x40/+0x44 (and global PLAYER_X/Y if set)
 *
 * Usage:
 *   probe_my_anim.exe [entity_offsets.txt] [seconds]
 * Default: ../entities/entity_offsets.txt , 90 seconds.
 * Log: probe_my_anim_out.txt (cwd)
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

#define MAX_SLOT 48
#define AC_SCAN  0x140u
#define H_SCAN   0x300u

static DWORD g_pid;
static uint64_t g_base;
static uint32_t g_modSize;
static FILE* g_log;

static uint32_t g_offEntMgr = 0x16DEE80u;
static uint32_t g_offHolder = 0xD0u;
static uint32_t g_offSubBeg = 0x180u;
static uint32_t g_gridVft = 0x11DE3B8u;
static uint32_t g_actorVecOff = 0x8A8u, g_actorVecEnd = 0x8B0u;
static uint32_t g_heads[4] = { 0x798u, 0x7D8u, 0, 0 };
static int g_nh = 2;
static uint32_t g_offNodeNext = 0x08u, g_offNodeBeg = 0x18u, g_offNodeEnd = 0x20u;
static uint32_t g_offEntGuid = 0x18u;
static uint32_t g_offCompTable = 0x20u;
static uint32_t g_actVft = 0x11EB908u;
static uint32_t g_actIdx = 2u;
static uint32_t g_vftSelf = 0x11EC4C8u;
static uint32_t g_vftCtl = 0x11EBBA0u;
static uint32_t g_vftAttackAct = 0x11EB490u;
static uint32_t g_vftDeath = 0x11EB400u;
static uint32_t g_vftDeadBody = 0x11EB568u;
static uint32_t g_vftBreath = 0x11EB4D8u;
/* bodyact: AC+0xC0 / Controller+0x58. */
static uint32_t g_vftCmdMove = 0x11EBA50u;   /* MoveCommand */
static uint32_t g_vftCmdAtk  = 0x11EBBD0u;   /* AttackCommand */
static uint32_t g_vftMoveAct = 0x11EB7B8u;   /* MovingAction */
static uint32_t g_vftBrief   = 0x11EB5B0u;   /* ChangeDirection */
static uint32_t g_baitOff = 0x40u, g_deadByte = 0x49u;
static uint32_t g_offPlayerX = 0x16DED30u, g_offPlayerY = 0x16DED34u;
static uint32_t g_offPresCellX = 0x40u, g_offPresCellY = 0x44u;
static uint32_t g_ctlCmdOff = 0x58u;
static uint32_t g_hCtlHint = 0x90u;

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
static uint8_t rd8(uint64_t a) {
    uint8_t v = 0;
    rm(a, &v, 1);
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

static void plog(const char* fmt, ...) {
    va_list ap;
    va_start(ap, fmt);
    vprintf(fmt, ap);
    va_end(ap);
    if (g_log) {
        va_start(ap, fmt);
        vfprintf(g_log, fmt, ap);
        va_end(ap);
        fflush(g_log);
    }
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

static DWORD findPid(void) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32W pe;
    DWORD pid = 0;
    if (snap == INVALID_HANDLE_VALUE) return 0;
    pe.dwSize = sizeof(pe);
    if (Process32FirstW(snap, &pe)) {
        do {
            if (_wcsicmp(pe.szExeFile, L"LC.exe") == 0) {
                pid = pe.th32ProcessID;
                break;
            }
        } while (Process32NextW(snap, &pe));
    }
    CloseHandle(snap);
    return pid;
}

static const char* tagVft(uint32_t v) {
    if (v == g_actVft) return "ActionComponent";
    if (v == g_vftCtl) return "ActorController";
    if (v == g_vftAttackAct) return "AttackAction";
    if (v == g_vftDeath) return "DeathAction";
    if (v == g_vftDeadBody) return "AppearDeadBody";
    if (v == g_vftBreath) return "BreathAction";
    if (v == g_vftCmdMove) return "MoveCommand";
    if (v == g_vftCmdAtk) return "AttackCommand";
    if (v == g_vftMoveAct) return "MovingAction";
    if (v == g_vftBrief) return "ChangeDirection";
    if (v == g_vftSelf) return "MyPlayer";
    return "?";
}

static void loadOffsets(const char* path) {
    FILE* f;
    char line[512];
    if (!path || !path[0]) return;
    f = fopen(path, "r");
    if (!f) {
        plog("WARN: cannot open offsets %s\n", path);
        return;
    }
    while (fgets(line, sizeof(line), f)) {
        char* p;
        if ((p = strchr(line, '\n'))) *p = 0;
        if ((p = strchr(line, '\r'))) *p = 0;
        if (!strncmp(line, "MGR=", 4)) g_offEntMgr = (uint32_t)strtoul(line + 4, 0, 16);
        else if (!strncmp(line, "HOLDER_OFF=", 11)) g_offHolder = (uint32_t)strtoul(line + 11, 0, 16);
        else if (!strncmp(line, "SUBLIST_BEG=", 12)) g_offSubBeg = (uint32_t)strtoul(line + 12, 0, 16);
        else if (!strncmp(line, "ACTOR_VFT=", 10)) g_gridVft = (uint32_t)strtoul(line + 10, 0, 16);
        else if (!strncmp(line, "ACTOR_VEC_OFF=", 14)) g_actorVecOff = (uint32_t)strtoul(line + 14, 0, 16);
        else if (!strncmp(line, "ACTOR_VEC_END=", 14)) g_actorVecEnd = (uint32_t)strtoul(line + 14, 0, 16);
        else if (!strncmp(line, "MAP_HEADS=", 10)) {
            char* s = line + 10;
            g_nh = 0;
            while (*s && g_nh < 4) {
                g_heads[g_nh++] = (uint32_t)strtoul(s, &s, 16);
                if (*s == ',') s++;
            }
        }
        else if (!strncmp(line, "NODE_NEXT=", 10)) g_offNodeNext = (uint32_t)strtoul(line + 10, 0, 16);
        else if (!strncmp(line, "NODE_BEG=", 9)) g_offNodeBeg = (uint32_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "NODE_END=", 9)) g_offNodeEnd = (uint32_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "ENT_GUID=", 9)) g_offEntGuid = (uint32_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "COMP_TABLE=", 11)) g_offCompTable = (uint32_t)strtoul(line + 11, 0, 16);
        else if (!strncmp(line, "ACT_VFT=", 8)) g_actVft = (uint32_t)strtoul(line + 8, 0, 16);
        else if (!strncmp(line, "ACT_IDX=", 8)) g_actIdx = (uint32_t)strtoul(line + 8, 0, 16);
        else if (!strncmp(line, "ACT_BAIT_OFF=", 13)) g_baitOff = (uint32_t)strtoul(line + 13, 0, 16);
        else if (!strncmp(line, "ACT_DEAD_BYTE=", 14)) g_deadByte = (uint32_t)strtoul(line + 14, 0, 16);
        else if (!strncmp(line, "DEATH_VFT=", 10)) g_vftDeath = (uint32_t)strtoul(line + 10, 0, 16);
        else if (!strncmp(line, "DEADBODY_VFT=", 13)) g_vftDeadBody = (uint32_t)strtoul(line + 13, 0, 16);
        else if (!strncmp(line, "PLAYER_X=", 9)) g_offPlayerX = (uint32_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "PLAYER_Y=", 9)) g_offPlayerY = (uint32_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "CLASSES=", 8)) {
            char* s = line + 8;
            while (*s) {
                uint32_t v = (uint32_t)strtoul(s, &s, 16);
                if (*s == ':') {
                    s++;
                    if (!strncmp(s, "MyPlayer", 8) || !strncmp(s, "SELF", 4)) g_vftSelf = v;
                    else if (!strncmp(s, "ActionComponent", 15)) g_actVft = v;
                    else if (!strncmp(s, "DeathAction", 11)) g_vftDeath = v;
                    else if (!strncmp(s, "AppearDeadBody", 14)) g_vftDeadBody = v;
                }
                while (*s && *s != ',') s++;
                if (*s == ',') s++;
            }
        }
    }
    fclose(f);
}

/* Optional LC930 registry overlay for controller / breath / attackact. */
static void loadRegistry(const char* path) {
    FILE* f;
    char line[512];
    if (!path || !path[0]) return;
    f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof(line), f)) {
        char* p;
        if ((p = strchr(line, '\n'))) *p = 0;
        if ((p = strchr(line, '\r'))) *p = 0;
        if (!strncmp(line, "VFT_ACTORCTL=", 13)) g_vftCtl = (uint32_t)strtoul(line + 13, 0, 16);
        else if (!strncmp(line, "VFT_ATTACKACT=", 14)) g_vftAttackAct = (uint32_t)strtoul(line + 14, 0, 16);
        else if (!strncmp(line, "VFT_BREATHACT=", 14)) g_vftBreath = (uint32_t)strtoul(line + 14, 0, 16);
        else if (!strncmp(line, "VFT_MOVINGACT=", 14)) g_vftMoveAct = (uint32_t)strtoul(line + 14, 0, 16);
        else if (!strncmp(line, "VFT_CHANGEDIR=", 14)) g_vftBrief = (uint32_t)strtoul(line + 14, 0, 16);
        else if (!strncmp(line, "VFT_CMDMOVE=", 12)) g_vftCmdMove = (uint32_t)strtoul(line + 12, 0, 16);
        else if (!strncmp(line, "VFT_CMDATTACK=", 14)) g_vftCmdAtk = (uint32_t)strtoul(line + 14, 0, 16);
        else if (!strncmp(line, "VFT_AC=", 7)) g_actVft = (uint32_t)strtoul(line + 7, 0, 16);
        else if (!strncmp(line, "VFT_SELF=", 9)) g_vftSelf = (uint32_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "VFT_MYPLAYER=", 13)) g_vftSelf = (uint32_t)strtoul(line + 13, 0, 16);
    }
    fclose(f);
}

static uint64_t findActorSub(void) {
    uint64_t mgr = rq(g_base + g_offEntMgr);
    uint64_t holder, beg, end;
    int i, n;
    if (!isHeap(mgr)) return 0;
    holder = rq(mgr + g_offHolder);
    if (!isHeap(holder)) return 0;
    beg = rq(holder + g_offSubBeg);
    end = rq(holder + g_offSubBeg + 8);
    if (!isHeap(beg) || end <= beg) return 0;
    n = (int)((end - beg) / 16);
    if (n < 1 || n > 128) n = 64;
    for (i = 0; i < n; i++) {
        uint64_t sub = rq(beg + (uint64_t)i * 16);
        if (isHeap(sub) && vrva(sub) == g_gridVft) return sub;
    }
    return 0;
}

static int tryEnt(uint64_t e, uint64_t* outMe) {
    if (!isHeap(e)) return 0;
    if (vrva(e) != g_vftSelf) return 0;
    *outMe = e;
    return 1;
}

static uint64_t findMyPlayer(void) {
    uint64_t actor = findActorSub();
    uint64_t me = 0;
    int hi;
    if (!actor) return 0;
    /* Flat vector first */
    {
        uint64_t vb = rq(actor + g_actorVecOff);
        uint64_t ve = rq(actor + g_actorVecEnd);
        if (isHeap(vb) && isHeap(ve) && ve > vb && (ve - vb) < 0x200000) {
            int n = (int)((ve - vb) / 16);
            int i;
            for (i = 0; i < n && i < 8000; i++) {
                uint64_t e = rq(vb + (uint64_t)i * 16);
                if (tryEnt(e, &me)) return me;
            }
        }
    }
    for (hi = 0; hi < g_nh; hi++) {
        uint64_t sent = rq(actor + g_heads[hi] + 8);
        uint64_t cur;
        int g = 0;
        if (!isHeap(sent)) continue;
        cur = rq(sent + g_offNodeNext);
        while (isHeap(cur) && cur != sent && g++ < 4000) {
            uint64_t vb = rq(cur + g_offNodeBeg);
            uint64_t ve = rq(cur + g_offNodeEnd);
            if (isHeap(vb) && isHeap(ve) && ve >= vb) {
                int n = (int)((ve - vb) / 8);
                int i;
                if (n > 0 && n < 5000) {
                    for (i = 0; i < n; i++) {
                        if (tryEnt(rq(vb + (uint64_t)i * 8), &me)) return me;
                    }
                }
            }
            cur = rq(cur + g_offNodeNext);
        }
    }
    return 0;
}

static uint64_t actionComp(uint64_t e) {
    uint64_t tb = rq(e + g_offCompTable);
    uint64_t te = rq(e + g_offCompTable + 8);
    uint64_t ac;
    if (!isHeap(tb) || te <= tb || (te - tb) < (uint64_t)(g_actIdx + 1) * 8)
        return 0;
    ac = rq(tb + (uint64_t)g_actIdx * 8);
    if (isHeap(ac) && vrva(ac) == g_actVft) return ac;
    /* fallback: H+0x10 style */
    {
        uint64_t H = rq(e + 0x20);
        uint64_t ac2 = isHeap(H) ? rq(H + 0x10) : 0;
        if (isHeap(ac2) && vrva(ac2) == g_actVft) return ac2;
    }
    return isHeap(ac) ? ac : 0;
}

static uint64_t findController(uint64_t e, uint32_t* foundAtOff) {
    uint64_t H = rq(e + 0x20);
    uint32_t o;
    *foundAtOff = 0;
    if (!isHeap(H)) return 0;
    /* hint H+0x90 */
    {
        uint64_t ctl = rq(H + g_hCtlHint);
        if (isHeap(ctl) && vrva(ctl) == g_vftCtl) {
            *foundAtOff = g_hCtlHint;
            return ctl;
        }
    }
    for (o = 0; o < H_SCAN; o += 8) {
        uint64_t obj = rq(H + o);
        if (isHeap(obj) && vrva(obj) == g_vftCtl) {
            *foundAtOff = o;
            return obj;
        }
    }
    /* also scan component vector */
    {
        uint64_t tb = rq(e + g_offCompTable);
        uint64_t te = rq(e + g_offCompTable + 8);
        if (isHeap(tb) && te > tb && (te - tb) < 0x1000) {
            int n = (int)((te - tb) / 8);
            int i;
            for (i = 0; i < n; i++) {
                uint64_t obj = rq(tb + (uint64_t)i * 8);
                if (isHeap(obj) && vrva(obj) == g_vftCtl) {
                    *foundAtOff = 0xC000u + (uint32_t)i;
                    return obj;
                }
            }
        }
    }
    return 0;
}

typedef struct {
    int32_t cellx, celly;
    int32_t globx, globy;
    uint32_t ctlOff;
    uint32_t cmdVft;
    uint64_t cmdPtr;
    uint32_t bait;
    uint8_t dead;
    int nSlots;
    uint32_t slotOff[MAX_SLOT];
    uint32_t slotVft[MAX_SLOT];
    uint64_t slotObj[MAX_SLOT];
} Sample;

static void readCell(uint64_t e, int32_t* cx, int32_t* cy) {
    uint64_t H = rq(e + 0x20);
    uint64_t prb;
    *cx = -1;
    *cy = -1;
    if (!isHeap(H)) return;
    prb = rq(H);
    if (!isHeap(prb)) prb = H; /* sometimes H itself holds transform */
    *cx = (int32_t)rd32(prb + g_offPresCellX);
    *cy = (int32_t)rd32(prb + g_offPresCellY);
}

static void sampleMe(uint64_t me, Sample* S) {
    uint64_t ac, ctl;
    uint32_t o;
    memset(S, 0, sizeof(*S));
    S->cellx = S->celly = -1;
    S->globx = (int32_t)rd32(g_base + g_offPlayerX);
    S->globy = (int32_t)rd32(g_base + g_offPlayerY);
    readCell(me, &S->cellx, &S->celly);

    ctl = findController(me, &S->ctlOff);
    if (ctl) {
        S->cmdPtr = rq(ctl + g_ctlCmdOff);
        if (isHeap(S->cmdPtr) || isMod(S->cmdPtr))
            S->cmdVft = vrva(S->cmdPtr);
        else if (S->cmdPtr)
            S->cmdVft = 0xFFFFFFFFu; /* non-null non-vft */
    }

    ac = actionComp(me);
    if (ac) {
        S->bait = rd32(ac + g_baitOff);
        S->dead = rd8(ac + g_deadByte);
        for (o = 0; o < AC_SCAN && S->nSlots < MAX_SLOT; o += 8) {
            uint64_t w = rq(ac + o);
            uint32_t v;
            if (!isHeap(w)) continue;
            v = vrva(w);
            if (!v) continue;
            S->slotOff[S->nSlots] = o;
            S->slotVft[S->nSlots] = v;
            S->slotObj[S->nSlots] = w;
            S->nSlots++;
        }
    }
}

static int sampleEq(const Sample* a, const Sample* b) {
    int i;
    if (a->cmdVft != b->cmdVft) return 0;
    if (a->bait != b->bait || a->dead != b->dead) return 0;
    if (a->cellx != b->cellx || a->celly != b->celly) return 0;
    if (a->nSlots != b->nSlots) return 0;
    for (i = 0; i < a->nSlots; i++) {
        if (a->slotOff[i] != b->slotOff[i] || a->slotVft[i] != b->slotVft[i])
            return 0;
    }
    return 1;
}

static void emitSample(DWORD t0, const Sample* S, const char* why) {
    int i;
    plog("[%u]%s glob=(%d,%d) cell=(%d,%d) ctlOff=0x%X cmdVft=0x%X(%s) bait=0x%X dead=%u slots=%d\n",
         (unsigned)(GetTickCount() - t0), why,
         (int)S->globx, (int)S->globy, (int)S->cellx, (int)S->celly,
         (unsigned)S->ctlOff, (unsigned)S->cmdVft, tagVft(S->cmdVft),
         (unsigned)S->bait, (unsigned)S->dead, S->nSlots);
    if (S->cmdPtr && S->cmdVft) {
        plog("  cmd+0x10=0x%llX cmd+0x18=0x%llX\n",
             (unsigned long long)rq(S->cmdPtr + 0x10),
             (unsigned long long)rq(S->cmdPtr + 0x18));
    }
    for (i = 0; i < S->nSlots; i++) {
        plog("  ac+0x%02X vft=0x%X %s",
             (unsigned)S->slotOff[i], (unsigned)S->slotVft[i], tagVft(S->slotVft[i]));
        if (S->slotVft[i] == g_vftAttackAct && S->slotObj[i]) {
            plog(" owner=0x%llX tgt=0x%llX",
                 (unsigned long long)rq(S->slotObj[i] + 0x80),
                 (unsigned long long)rq(S->slotObj[i] + 0x88));
        }
        plog("\n");
    }
}

int main(int argc, char** argv) {
    const char* offPath = "..\\entities\\entity_offsets.txt";
    const char* regPath = "..\\lc930\\registry\\LC930_REGISTRY.txt";
    int seconds = 90;
    uint64_t me;
    Sample prev, cur;
    DWORD t0, lastHb;
    int changes = 0;

    SetConsoleOutputCP(CP_UTF8);
    if (argc >= 2 && argv[1][0]) offPath = argv[1];
    if (argc >= 3) seconds = atoi(argv[2]);
    if (seconds < 5) seconds = 5;

    g_log = fopen("probe_my_anim_loot_out.txt", "w");
    if (!g_log) g_log = fopen("probe_my_anim_out.txt", "w");
    loadOffsets(offPath);
    loadRegistry(regPath);

    g_pid = findPid();
    if (!g_pid) {
        plog("no LC.exe\n");
        return 1;
    }
    if (!SignedOpen()) {
        plog("driver fail\n");
        return 1;
    }
    SignedSetTarget(g_pid);
    if (!getModule(&g_base, &g_modSize)) {
        plog("module fail\n");
        SignedClose();
        return 1;
    }

    plog("BASE=0x%llX pid=%u seconds=%d\n", (unsigned long long)g_base, (unsigned)g_pid, seconds);
    plog("VFT self=0x%X ac=0x%X ctl=0x%X atk=0x%X breath=0x%X moveCmd=0x%X moveAct=0x%X\n",
         g_vftSelf, g_actVft, g_vftCtl, g_vftAttackAct, g_vftBreath,
         g_vftCmdMove, g_vftMoveAct);
    plog("offsets=%s\n", offPath);

    me = findMyPlayer();
    if (!me) {
        plog("MyPlayer not found — stand in-world and retry\n");
        SignedClose();
        return 1;
    }
    plog("me=0x%llX guid=0x%llX\n",
         (unsigned long long)me, (unsigned long long)rq(me + g_offEntGuid));
    plog("=== START WALK/STAND/ATTACK/LOOT NOW ===\n");
    plog("Poll ~50ms; log on change + 1s heartbeat. Ctrl+C or wait %ds.\n", seconds);

    t0 = GetTickCount();
    lastHb = t0;
    memset(&prev, 0, sizeof(prev));
    sampleMe(me, &prev);
    emitSample(t0, &prev, " INIT");

    while ((int)(GetTickCount() - t0) < seconds * 1000) {
        DWORD now;
        me = findMyPlayer();
        if (!me) {
            Sleep(50);
            continue;
        }
        sampleMe(me, &cur);
        now = GetTickCount();
        if (!sampleEq(&cur, &prev)) {
            changes++;
            emitSample(t0, &cur, " CHG");
            prev = cur;
        } else if (now - lastHb >= 1000) {
            emitSample(t0, &cur, " HB");
            lastHb = now;
        }
        Sleep(50);
    }

    plog("=== DONE changes=%d ===\n", changes);
    SignedClose();
    if (g_log) fclose(g_log);
    return 0;
}
