/* probe_drop_still_gone.c — after Item drop, detect Monsters that
   STOP (cell fixed) then DISAPPEAR; dump Entity attrs around that arc.
   Pipeline per drop:
     1) New Item vft 0x116E5B8 = clock
     2) Enroll nearby Monsters (DROP_NEAR cells)
     3) Watch each: moving -> still (cell unchanged STILL_MS) -> gone
     4) On gone: diff Entity blob (pre-drop / last-moving / still) vs last still
   Usage: probe_drop_still_gone.exe [seconds=180]
   Out: drop_still_gone.log  drop_still_gone.csv  DROP_STILL_GONE_REPORT.md
*/
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "signeddrv_client.h"

#define OFF_PLAYER_X 0x164E310u
#define OFF_PLAYER_Y 0x164E314u
#define OFF_ENT_MGR  0x164E460u
#define GRID_VFT     0x116B858u
#define VFT_MONSTER  0x116E628u
#define VFT_SUMMON   0x116EBD0u
#define VFT_ITEM     0x116E5B8u
#define MAX_ENT      80
#define ENT_BLOB     0x120u
#define POLL_MS      25
#define CELL_RAD     130
#define DROP_NEAR    14
#define STILL_MS     400      /* cell must hold this long to count as stopped */
#define WATCH_MS     12000    /* watch enrolled mobs after drop */
#define TRACK_MAX    96

static DWORD g_pid;
static uint64_t g_base;
static uint32_t g_modSize;
static DWORD g_t0;
static FILE* g_log;
static FILE* g_csv;

static int isHeap(uint64_t a) {
    return a >= 0x10000000000ULL && a < 0x70000000000ULL;
}
static int isMod(uint64_t a) { return a >= g_base && a < g_base + g_modSize; }
static int rm(uint64_t a, void* b, uint32_t n) {
    uint32_t br = 0; return SignedReadMemory(g_pid, a, b, n, &br) && br == n;
}
static uint64_t rq(uint64_t a) { uint64_t v = 0; rm(a, &v, 8); return v; }
static uint32_t rd(uint64_t a) { uint32_t v = 0; rm(a, &v, 4); return v; }
static uint32_t vrva(uint64_t o) {
    uint64_t v = 0; if (!rm(o, &v, 8) || !isMod(v)) return 0;
    return (uint32_t)(v - g_base);
}
static DWORD findPid(const wchar_t* name) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    PROCESSENTRY32W pe; pe.dwSize = sizeof(pe); DWORD pid = 0;
    if (Process32FirstW(snap, &pe)) do {
        if (_wcsicmp(pe.szExeFile, name) == 0) { pid = pe.th32ProcessID; break; }
    } while (Process32NextW(snap, &pe));
    CloseHandle(snap); return pid;
}
static int getModule(uint64_t* base, uint32_t* size) {
    uint64_t peb=0,ldr=0,lh=0,cur=0,ent=0,db=0,img=0; uint32_t b=0,ds=0;
    if (!SignedGetPeb(g_pid,&peb)||!peb) return 0;
    if (SignedReadMemory(g_pid,peb+0x10,&img,8,&b)&&b==8&&img) {
        uint32_t e=0,sz=0;
        if (SignedReadMemory(g_pid,img+0x3C,&e,4,&b)&&b==4&&e<0x1000 &&
            SignedReadMemory(g_pid,img+e+0x50,&sz,4,&b)&&b==4&&sz) {
            *base=img; *size=sz; return 1;
        }
    }
    if (!(SignedReadMemory(g_pid,peb+0x18,&ldr,8,&b)&&b==8)||!ldr) return 0;
    if (!(SignedReadMemory(g_pid,ldr+0x20,&lh,8,&b)&&b==8)) return 0;
    cur=lh;
    while (cur && cur!=(ldr+0x20)) {
        ent=cur-0x10; db=0; ds=0;
        if ((SignedReadMemory(g_pid,ent+0x30,&db,8,&b)&&b==8&&db) &&
            (SignedReadMemory(g_pid,ent+0x40,&ds,4,&b)&&b==4&&ds)) {
            *base=db; *size=ds; return 1;
        }
        if (!(SignedReadMemory(g_pid,cur,&cur,8,&b)&&b==8)) return 0;
    }
    return 0;
}
static int isMob(uint32_t r) {
    return r == VFT_MONSTER || r == VFT_SUMMON || r == 0x1162430u || r == 0x1162390u;
}
static int isItem(uint32_t r) { return r == VFT_ITEM || r == 0x1162408u; }
static int isEnt(uint32_t r) {
    switch (r) {
    case 0x116E738: case 0x116E770: case 0x116E580: case 0x116E628:
    case 0x116E5B8: case 0x11624A8: case 0x1162430: case 0x11624D0:
    case 0x11624F8: case 0x116EAD8: case 0x116EA30: case 0x116EBD0:
    case 0x1162408: return 1;
    }
    return 0;
}
static int followComp(uint64_t q, uint64_t* entOut) {
    uint64_t cand[3] = { q, 0, (q > 0x10) ? q - 0x10 : 0 };
    uint64_t p18 = 0;
    if (rm(q + 0x18, &p18, 8) && isHeap(p18)) cand[1] = p18;
    for (int i = 0; i < 3; i++) {
        uint64_t c = cand[i]; uint32_t rv = c ? vrva(c) : 0;
        if (rv && isEnt(rv)) { *entOut = c; return 1; }
    }
    return 0;
}

typedef struct {
    uint64_t ent;
    uint32_t vft;
    int32_t cx, cy;
    uint8_t eb[ENT_BLOB];
    uint8_t ok;
} EntSnap;

typedef struct {
    DWORD t;
    int nm, ni;
    EntSnap mob[MAX_ENT];
    EntSnap item[MAX_ENT];
} Frame;

static Frame g_cur;

static int sweep(Frame* F) {
    memset(F, 0, sizeof(*F));
    F->t = GetTickCount();
    uint64_t mgr = rq(g_base + OFF_ENT_MGR);
    if (!isHeap(mgr)) return 0;
    uint64_t holder = rq(mgr + 0xD0);
    uint8_t grd = 0; rm(mgr + 0xD8, &grd, 1);
    if (grd != 1 || !isHeap(holder)) return 0;
    uint64_t bgn = rq(holder + 0x180), end = rq(holder + 0x188), best = 0;
    for (uint64_t e = bgn; e + 16 <= end; e += 16)
        if (vrva(rq(e)) == GRID_VFT) { best = rq(e); break; }
    if (!best) return 0;
    uint32_t px = rd(g_base + OFF_PLAYER_X), py = rd(g_base + OFF_PLAYER_Y);
    int heads[2] = { 0x798, 0x7D8 };
    for (int hi = 0; hi < 2; hi++) {
        uint8_t hb[0x40]; if (!rm(best + heads[hi], hb, sizeof(hb))) continue;
        uint64_t sent = *(uint64_t*)(hb + 8), cur = 0;
        if (!rm(sent + 8, &cur, 8)) continue;
        int hops = 0;
        while (cur && cur != sent && isHeap(cur) && hops++ < 1100) {
            uint8_t nb[0x30]; if (!rm(cur, nb, sizeof(nb))) break;
            uint64_t next = *(uint64_t*)(nb + 8);
            int32_t cx = *(int32_t*)(nb + 0x10), cy = *(int32_t*)(nb + 0x14);
            uint64_t vb = *(uint64_t*)(nb + 0x18), ve = *(uint64_t*)(nb + 0x20);
            cur = next;
            if (abs(cx - (int)px) > CELL_RAD || abs(cy - (int)py) > CELL_RAD) continue;
            if (!isHeap(vb) || ve < vb || (ve - vb) > 0x1000) continue;
            for (uint64_t p = vb; p + 8 <= ve; p += 8) {
                uint64_t q = 0, ent = 0;
                if (!rm(p, &q, 8) || !isHeap(q) || !followComp(q, &ent)) continue;
                uint32_t vft = vrva(ent);
                if (isMob(vft) && F->nm < MAX_ENT) {
                    int dup = 0;
                    for (int i = 0; i < F->nm; i++) if (F->mob[i].ent == ent) dup = 1;
                    if (dup) continue;
                    EntSnap* S = &F->mob[F->nm];
                    S->ent = ent; S->vft = vft; S->cx = cx; S->cy = cy;
                    S->ok = rm(ent, S->eb, ENT_BLOB) ? 1 : 0;
                    F->nm++;
                } else if (isItem(vft) && F->ni < MAX_ENT) {
                    int dup = 0;
                    for (int i = 0; i < F->ni; i++) if (F->item[i].ent == ent) dup = 1;
                    if (dup) continue;
                    EntSnap* S = &F->item[F->ni];
                    S->ent = ent; S->vft = vft; S->cx = cx; S->cy = cy;
                    S->ok = rm(ent, S->eb, ENT_BLOB) ? 1 : 0;
                    F->ni++;
                }
            }
        }
    }
    return F->nm + F->ni;
}

static EntSnap* findMob(Frame* F, uint64_t ent) {
    for (int i = 0; i < F->nm; i++) if (F->mob[i].ent == ent) return &F->mob[i];
    return NULL;
}

#define ITEM_MAX 512
static uint64_t g_knownItem[ITEM_MAX];
static int g_nKnown;
static int knowItem(uint64_t e) {
    for (int i = 0; i < g_nKnown; i++) if (g_knownItem[i] == e) return 1;
    return 0;
}
static void addKnown(uint64_t e) {
    if (knowItem(e) || g_nKnown >= ITEM_MAX) return;
    g_knownItem[g_nKnown++] = e;
}

/* Watch state for a mob enrolled at a drop */
typedef enum { WS_ACTIVE = 0, WS_STILL = 1, WS_DONE = 2 } WState;
typedef struct {
    uint8_t used;
    uint8_t reported;
    WState st;
    int dropId;
    uint64_t ent;
    uint64_t item;
    int32_t dropCx, dropCy;
    DWORD enrollT;
    DWORD expireT;
    /* snapshots */
    uint8_t haveEnroll, haveMove, haveStill;
    EntSnap atEnroll;   /* first sight after drop */
    EntSnap atMove;     /* last time cell changed */
    EntSnap atStill;   /* while stopped */
    int32_t lastCx, lastCy;
    DWORD cellSince;    /* when current cell started */
    DWORD stillSince;   /* when entered WS_STILL */
} Watch;

static Watch g_w[TRACK_MAX];
static int g_drops;
static int g_enrolled;
static int g_still_then_gone;   /* the target pattern */
static int g_gone_without_still;
static int g_expired_still;     /* still but never gone within WATCH_MS */
static int g_u32_chg[ENT_BLOB / 4]; /* diffs enroll/move -> still, on still-then-gone */

static Watch* allocWatch(void) {
    for (int i = 0; i < TRACK_MAX; i++) if (!g_w[i].used) {
        memset(&g_w[i], 0, sizeof(Watch));
        g_w[i].used = 1;
        return &g_w[i];
    }
    /* reuse oldest done/expired */
    int bi = 0;
    for (int i = 1; i < TRACK_MAX; i++)
        if (g_w[i].enrollT < g_w[bi].enrollT) bi = i;
    memset(&g_w[bi], 0, sizeof(Watch));
    g_w[bi].used = 1;
    return &g_w[bi];
}

static void logDiff(const char* tag, int dropId, Watch* W,
                    const EntSnap* a, const EntSnap* b) {
    if (!a || !b || !a->ok || !b->ok) return;
    fprintf(g_log, "  DIFF %s:\n", tag);
    for (int o = 0; o + 4 <= ENT_BLOB; o += 4) {
        uint32_t x = *(uint32_t*)(a->eb + o);
        uint32_t y = *(uint32_t*)(b->eb + o);
        if (x == y) continue;
        if (strcmp(tag, "enroll_to_still") == 0 || strcmp(tag, "move_to_still") == 0)
            g_u32_chg[o / 4]++;
        fprintf(g_log, "    +0x%03X: %u(0x%X) -> %u(0x%X)\n", o, x, x, y, y);
        fprintf(g_csv, "%d,%s,%lu,0x%llX,0x%llX,0x%03X,%u,%u\n",
            dropId, tag, (unsigned long)(GetTickCount() - g_t0),
            (unsigned long long)W->ent, (unsigned long long)W->item, o, x, y);
    }
}

static void onStillThenGone(Watch* W, DWORD now) {
    g_still_then_gone++;
    DWORD t = now - g_t0;
    uint16_t lo = W->haveStill ? *(uint16_t*)(W->atStill.eb + 0x18) : 0;
    uint16_t hi = W->haveStill ? *(uint16_t*)(W->atStill.eb + 0x1A) : 0;
    fprintf(g_log,
        "\n***** STILL_THEN_GONE #%d  drop=%d  t=%lums  ent=0x%llX  item=0x%llX\n"
        "  drop_cell=(%d,%d)  still_cell=(%d,%d)  still_for=%lums  "
        "enroll->gone=%lums\n"
        "  still +04=%u +18=%u +1A=%u\n",
        g_still_then_gone, W->dropId, (unsigned long)t,
        (unsigned long long)W->ent, (unsigned long long)W->item,
        W->dropCx, W->dropCy, W->lastCx, W->lastCy,
        (unsigned long)(now - W->stillSince),
        (unsigned long)(now - W->enrollT),
        W->haveStill ? *(uint32_t*)(W->atStill.eb + 4) : 0, lo, hi);
    printf("STILL_THEN_GONE #%d drop=%d ent=0x%llX cell=(%d,%d) still=%lums +18=%u +1A=%u\n",
        g_still_then_gone, W->dropId, (unsigned long long)W->ent,
        W->lastCx, W->lastCy, (unsigned long)(now - W->stillSince), lo, hi);

    if (W->haveEnroll && W->haveStill)
        logDiff("enroll_to_still", W->dropId, W, &W->atEnroll, &W->atStill);
    if (W->haveMove && W->haveStill)
        logDiff("move_to_still", W->dropId, W, &W->atMove, &W->atStill);

    fprintf(g_csv, "%d,still_then_gone,%lu,0x%llX,0x%llX,-1,%u,%u\n",
        W->dropId, (unsigned long)t,
        (unsigned long long)W->ent, (unsigned long long)W->item, lo, hi);
    fflush(g_log);
    fflush(g_csv);
}

static void enrollFromDrop(EntSnap* item, Frame* F) {
    g_drops++;
    DWORD now = F->t;
    fprintf(g_log,
        "\n===== DROP#%d t=%lums item=0x%llX cell=(%d,%d) =====\n",
        g_drops, (unsigned long)(now - g_t0),
        (unsigned long long)item->ent, item->cx, item->cy);
    printf("DROP#%d t=%lums cell=(%d,%d)\n",
        g_drops, (unsigned long)(now - g_t0), item->cx, item->cy);

    int n = 0;
    for (int i = 0; i < F->nm; i++) {
        EntSnap* M = &F->mob[i];
        if (abs(M->cx - item->cx) > DROP_NEAR || abs(M->cy - item->cy) > DROP_NEAR)
            continue;
        /* already watching? */
        int dup = 0;
        for (int k = 0; k < TRACK_MAX; k++)
            if (g_w[k].used && !g_w[k].reported && g_w[k].ent == M->ent) dup = 1;
        if (dup) continue;

        Watch* W = allocWatch();
        W->dropId = g_drops;
        W->ent = M->ent;
        W->item = item->ent;
        W->dropCx = item->cx; W->dropCy = item->cy;
        W->enrollT = now;
        W->expireT = now + WATCH_MS;
        W->st = WS_ACTIVE;
        W->atEnroll = *M;
        W->haveEnroll = M->ok;
        W->atMove = *M;
        W->haveMove = M->ok;
        W->lastCx = M->cx; W->lastCy = M->cy;
        W->cellSince = now;
        g_enrolled++;
        n++;
        fprintf(g_log, "  enroll mob=0x%llX cell=(%d,%d) +18=%u +1A=%u\n",
            (unsigned long long)M->ent, M->cx, M->cy,
            M->ok ? *(uint16_t*)(M->eb + 0x18) : 0,
            M->ok ? *(uint16_t*)(M->eb + 0x1A) : 0);
    }
    fprintf(g_log, "  enrolled %d nearby mobs (watch %dms, still>=%dms)\n",
        n, WATCH_MS, STILL_MS);
    fflush(g_log);
    printf("  enrolled %d mobs\n", n);
}

static void tickWatches(Frame* F) {
    DWORD now = F->t;
    for (int i = 0; i < TRACK_MAX; i++) {
        Watch* W = &g_w[i];
        if (!W->used || W->reported) continue;

        EntSnap* M = findMob(F, W->ent);

        if (!M) {
            /* gone from grid */
            if (W->st == WS_STILL && !W->reported) {
                onStillThenGone(W, now);
                W->reported = 1;
                W->st = WS_DONE;
            } else if (W->st == WS_ACTIVE && !W->reported) {
                g_gone_without_still++;
                fprintf(g_log,
                    "  GONE_WITHOUT_STILL drop=%d ent=0x%llX t=%lums "
                    "(never held cell >=%dms)\n",
                    W->dropId, (unsigned long long)W->ent,
                    (unsigned long)(now - g_t0), STILL_MS);
                printf("  gone_no_still ent=0x%llX\n", (unsigned long long)W->ent);
                W->reported = 1;
                W->st = WS_DONE;
            }
            continue;
        }

        /* update cell / still detection */
        if (M->cx != W->lastCx || M->cy != W->lastCy) {
            W->lastCx = M->cx; W->lastCy = M->cy;
            W->cellSince = now;
            if (M->ok) { W->atMove = *M; W->haveMove = 1; }
            if (W->st == WS_STILL) W->st = WS_ACTIVE; /* resumed moving */
        } else {
            /* same cell */
            if (W->st == WS_ACTIVE && (now - W->cellSince) >= STILL_MS) {
                W->st = WS_STILL;
                W->stillSince = now;
                if (M->ok) { W->atStill = *M; W->haveStill = 1; }
                fprintf(g_log,
                    "  STILL drop=%d ent=0x%llX cell=(%d,%d) t=%lums +18=%u +1A=%u\n",
                    W->dropId, (unsigned long long)W->ent, M->cx, M->cy,
                    (unsigned long)(now - g_t0),
                    M->ok ? *(uint16_t*)(M->eb + 0x18) : 0,
                    M->ok ? *(uint16_t*)(M->eb + 0x1A) : 0);
                printf("  STILL ent=0x%llX cell=(%d,%d)\n",
                    (unsigned long long)W->ent, M->cx, M->cy);
            } else if (W->st == WS_STILL && M->ok) {
                W->atStill = *M; /* refresh still snap */
                W->haveStill = 1;
            }
        }

        if (now > W->expireT && !W->reported) {
            if (W->st == WS_STILL) {
                g_expired_still++;
                fprintf(g_log,
                    "  EXPIRE_STILL_ALIVE drop=%d ent=0x%llX (still but not gone in %dms)\n",
                    W->dropId, (unsigned long long)W->ent, WATCH_MS);
            }
            W->reported = 1;
            W->st = WS_DONE;
            W->used = 0;
        }
    }
}

int main(int argc, char** argv) {
    int secs = 180;
    if (argc >= 2) secs = atoi(argv[1]);
    if (secs < 45) secs = 45;
    if (secs > 900) secs = 900;

    printf("=== DROP -> STILL -> GONE tracker ===\n");
    printf("Kill mobs that drop loot; watch corpses stop then despawn.\n");
    if (!SignedOpen()) { printf("SignedOpen FAIL\n"); return 1; }
    g_pid = findPid(L"LC.exe");
    if (!g_pid || !getModule(&g_base, &g_modSize)) {
        printf("attach FAIL\n"); SignedClose(); return 1;
    }
    printf("pid=%lu base=0x%llX %ds  still>=%dms watch=%dms near=%d\n\n",
        (unsigned long)g_pid, (unsigned long long)g_base, secs,
        STILL_MS, WATCH_MS, DROP_NEAR);

    g_log = fopen("drop_still_gone.log", "w");
    g_csv = fopen("drop_still_gone.csv", "w");
    if (!g_log || !g_csv) { printf("log fail\n"); return 1; }
    fprintf(g_csv, "drop,kind,t_ms,mob,item,off,old,new\n");
    fprintf(g_log, "drop_still_gone start\n");

    g_t0 = GetTickCount();
    DWORD tEnd = g_t0 + (DWORD)secs * 1000u;
    DWORD lastStat = g_t0;

    Frame warm; sweep(&warm);
    for (int i = 0; i < warm.ni; i++) addKnown(warm.item[i].ent);
    printf("warmup mobs=%d items_seeded=%d\n", warm.nm, warm.ni);

    while (GetTickCount() < tEnd) {
        sweep(&g_cur);

        for (int i = 0; i < g_cur.ni; i++) {
            if (knowItem(g_cur.item[i].ent)) continue;
            addKnown(g_cur.item[i].ent);
            enrollFromDrop(&g_cur.item[i], &g_cur);
        }
        tickWatches(&g_cur);

        DWORD now = GetTickCount();
        if (now - lastStat >= 2000) {
            int watching = 0, stilling = 0;
            for (int i = 0; i < TRACK_MAX; i++) {
                if (!g_w[i].used || g_w[i].reported) continue;
                watching++;
                if (g_w[i].st == WS_STILL) stilling++;
            }
            printf("[+%lus] M=%d I=%d drops=%d enroll=%d watch=%d still=%d "
                "still_then_gone=%d gone_no_still=%d\n",
                (unsigned long)((now - g_t0) / 1000), g_cur.nm, g_cur.ni,
                g_drops, g_enrolled, watching, stilling,
                g_still_then_gone, g_gone_without_still);
            lastStat = now;
        }
        Sleep(POLL_MS);
    }

    FILE* out = fopen("DROP_STILL_GONE_REPORT.md", "w");
    if (!out) out = stdout;
    fprintf(out, "# Drop -> Still -> Gone\n\n");
    fprintf(out, "- drops: **%d**\n", g_drops);
    fprintf(out, "- enrolled nearby mobs: **%d**\n", g_enrolled);
    fprintf(out, "- **still then gone: %d**\n", g_still_then_gone);
    fprintf(out, "- gone without still: %d\n", g_gone_without_still);
    fprintf(out, "- expired while still (not gone in %dms): %d\n\n", WATCH_MS, g_expired_still);

    fprintf(out, "## Definition\n\n");
    fprintf(out, "After Item drop, Monster within %d cells: cell unchanged "
        ">= %dms (**still**), then absent from grid (**gone**).\n\n", DROP_NEAR, STILL_MS);

    if (g_still_then_gone > 0) {
        fprintf(out, "## Entity u32 changed enroll/move->still (on still-then-gone events)\n\n");
        fprintf(out, "| offset | count |\n|--------|------:|\n");
        int idx[ENT_BLOB / 4], n = 0;
        for (int i = 0; i < ENT_BLOB / 4; i++) if (g_u32_chg[i] > 0) idx[n++] = i;
        for (int a = 0; a < n; a++)
            for (int b = a + 1; b < n; b++)
                if (g_u32_chg[idx[b]] > g_u32_chg[idx[a]]) {
                    int t = idx[a]; idx[a] = idx[b]; idx[b] = t;
                }
        for (int k = 0; k < n; k++)
            fprintf(out, "| `Entity+0x%03X` | %d |\n", idx[k] * 4, g_u32_chg[idx[k]]);
        if (!n) fprintf(out, "| (none) | 0 |\n");
    } else {
        fprintf(out, "No still-then-gone events this run. Kill loot-dropping mobs "
            "and wait for corpse despawn while in range.\n");
    }

    fprintf(out, "\nFiles: `drop_still_gone.log`, `drop_still_gone.csv`\n");
    if (out != stdout) {
        fclose(out);
        printf("\nwrote DROP_STILL_GONE_REPORT.md\n");
    }
    fclose(g_log);
    fclose(g_csv);
    printf("RESULT still_then_gone=%d  gone_no_still=%d  drops=%d\n",
        g_still_then_gone, g_gone_without_still, g_drops);
    SignedClose();
    return 0;
}
