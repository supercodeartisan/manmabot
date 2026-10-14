/* probe_drop_death.c — death signal via ITEM DROP clock (signeddrv).
   1) Ring-buffer Monster snapshots (~5s).
   2) New Item (vft 0x116E5B8) = drop event.
   3) Victim = nearby Monster that was ALIVE (bit0=1) in history, then
      became DEAD (bit0=0) or vanished before/at the drop.
   4) Dump Entity diffs at the alive->dead transition (not at drop time).
   Usage: probe_drop_death.exe [seconds=180]
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
#define MAX_ENT      64
#define ENT_BLOB     0x100u       /* focus low offsets; smaller = more hist */
#define HIST         256          /* ~5s at 20ms */
#define POLL_MS      20
#define CELL_RAD     110
#define DROP_NEAR    10
#define LOOKBACK_MS  5000

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

static Frame g_hist[HIST];
static int g_hpos, g_hcount;

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

static int sweepFrame(Frame* F) {
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
        while (cur && cur != sent && isHeap(cur) && hops++ < 1000) {
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

static Frame* histAt(int age) {
    if (age < 0 || age >= g_hcount) return NULL;
    int i = g_hpos - 1 - age;
    while (i < 0) i += HIST;
    return &g_hist[i];
}
static EntSnap* findMob(Frame* F, uint64_t ent) {
    if (!F) return NULL;
    for (int i = 0; i < F->nm; i++) if (F->mob[i].ent == ent) return &F->mob[i];
    return NULL;
}

static int g_drops, g_kills, g_bit0_events, g_vanish_events;
static int g_eflip[ENT_BLOB];
static int g_trans_ms_sum, g_trans_n; /* drop_t - death_t */

static void dumpTransition(int dropId, DWORD dropT, EntSnap* item,
                           EntSnap* aliveSnap, DWORD aliveT,
                           EntSnap* deadSnap, DWORD deadT, int vanished) {
    g_kills++;
    uint16_t alo = *(uint16_t*)(aliveSnap->eb + 0x18);
    uint16_t ahi = *(uint16_t*)(aliveSnap->eb + 0x1A);
    int dt = (int)(dropT - deadT);

    fprintf(g_log,
        "  DEATH_SIGNAL t_alive=%lu t_dead=%lu t_drop=%lu  "
        "(death->drop lag=%dms)%s\n"
        "  mob=0x%llX vft=0x%X cell=(%d,%d)\n"
        "  ALIVE +04=%u +18.lo=%u bit0=%d +1A=%u\n",
        (unsigned long)(aliveT - g_t0), (unsigned long)(deadT - g_t0),
        (unsigned long)(dropT - g_t0), dt,
        vanished ? "  [VANISHED]" : "",
        (unsigned long long)aliveSnap->ent, aliveSnap->vft,
        aliveSnap->cx, aliveSnap->cy,
        *(uint32_t*)(aliveSnap->eb + 4), alo, alo & 1, ahi);

    printf("  DEATH signal: +18 bit0 1->0  lag_to_drop=%dms mob=0x%llX%s\n",
        dt, (unsigned long long)aliveSnap->ent, vanished ? " VANISH" : "");

    if (vanished) {
        g_vanish_events++;
        fprintf(g_log, "  DEAD: entity left grid (no after blob)\n");
        fprintf(g_csv, "%d,vanish,%lu,0x%llX,0x%llX,ent,0x018,u16,%u,gone\n",
            dropId, (unsigned long)(dropT - g_t0),
            (unsigned long long)aliveSnap->ent, (unsigned long long)item->ent, alo);
        fflush(g_log); fflush(g_csv);
        return;
    }

    uint16_t dlo = *(uint16_t*)(deadSnap->eb + 0x18);
    uint16_t dhi = *(uint16_t*)(deadSnap->eb + 0x1A);
    fprintf(g_log, "  DEAD  +04=%u +18.lo=%u bit0=%d +1A=%u\n",
        *(uint32_t*)(deadSnap->eb + 4), dlo, dlo & 1, dhi);

    if ((alo & 1) && !(dlo & 1)) g_bit0_events++;
    g_trans_ms_sum += dt;
    g_trans_n++;

    fprintf(g_log, "  Entity diffs (alive -> first dead):\n");
    int nchg = 0;
    for (int o = 0; o < ENT_BLOB; o++) {
        if (aliveSnap->eb[o] == deadSnap->eb[o]) continue;
        g_eflip[o]++;
        nchg++;
        if ((o % 4) == 0 && o + 4 <= ENT_BLOB) {
            uint32_t o32 = *(uint32_t*)(aliveSnap->eb + o);
            uint32_t n32 = *(uint32_t*)(deadSnap->eb + o);
            fprintf(g_log, "    +0x%03X: %u(0x%X) -> %u(0x%X)\n", o, o32, o32, n32, n32);
            fprintf(g_csv, "%d,alive_to_dead,%lu,0x%llX,0x%llX,ent,0x%03X,u32,%u,%u\n",
                dropId, (unsigned long)(dropT - g_t0),
                (unsigned long long)aliveSnap->ent, (unsigned long long)item->ent,
                o, o32, n32);
        } else if ((o % 2) == 0) {
            uint16_t o16 = *(uint16_t*)(aliveSnap->eb + o);
            uint16_t n16 = *(uint16_t*)(deadSnap->eb + o);
            fprintf(g_log, "    +0x%03X.u16: %u -> %u\n", o, o16, n16);
            fprintf(g_csv, "%d,alive_to_dead,%lu,0x%llX,0x%llX,ent,0x%03X,u16,%u,%u\n",
                dropId, (unsigned long)(dropT - g_t0),
                (unsigned long long)aliveSnap->ent, (unsigned long long)item->ent,
                o, o16, n16);
        }
    }
    fprintf(g_log, "  (%d bytes changed at death transition)\n", nchg);
    fflush(g_log); fflush(g_csv);
}

static void onItemDrop(EntSnap* item, Frame* cur) {
    g_drops++;
    DWORD dropT = cur->t;
    uint16_t ilo = item->ok ? *(uint16_t*)(item->eb + 0x18) : 0;
    uint16_t ihi = item->ok ? *(uint16_t*)(item->eb + 0x1A) : 0;

    fprintf(g_log,
        "\n===== DROP#%d  t=%lums  item=0x%llX  cell=(%d,%d)  "
        "item+18=%u +1A=%u =====\n",
        g_drops, (unsigned long)(dropT - g_t0),
        (unsigned long long)item->ent, item->cx, item->cy, ilo, ihi);
    printf("DROP#%d t=%lums item cell=(%d,%d) +1A=%u\n",
        g_drops, (unsigned long)(dropT - g_t0), item->cx, item->cy, ihi);

    /* Candidates: mob ents that appeared ALIVE near drop in lookback */
    uint64_t cands[MAX_ENT];
    int nc = 0;
    for (int age = 0; age < g_hcount; age++) {
        Frame* F = histAt(age);
        if (!F || (dropT - F->t) > LOOKBACK_MS) break;
        for (int i = 0; i < F->nm; i++) {
            EntSnap* M = &F->mob[i];
            if (!M->ok) continue;
            if (abs(M->cx - item->cx) > DROP_NEAR || abs(M->cy - item->cy) > DROP_NEAR)
                continue;
            uint16_t lo = *(uint16_t*)(M->eb + 0x18);
            if ((lo & 1) == 0) continue; /* only track ones that were alive */
            int dup = 0;
            for (int k = 0; k < nc; k++) if (cands[k] == M->ent) dup = 1;
            if (!dup && nc < MAX_ENT) cands[nc++] = M->ent;
        }
    }

    if (nc == 0) {
        fprintf(g_log, "  no ALIVE Monster near drop in last %dms "
            "(loot may be delayed past history, or corpse-only zone)\n", LOOKBACK_MS);
        fflush(g_log);
        return;
    }

    /* For each candidate: find last alive snap + first dead/missing snap */
    int bestLag = 0x7FFFFFFF;
    int found = 0;
    EntSnap bestAlive, bestDead;
    DWORD bestAliveT = 0, bestDeadT = 0;
    int bestVanish = 0;
    uint64_t bestEnt = 0;

    for (int ci = 0; ci < nc; ci++) {
        uint64_t ent = cands[ci];
        EntSnap* lastAlive = NULL; DWORD lastAliveT = 0;
        EntSnap* firstDead = NULL; DWORD firstDeadT = 0;
        int vanished = 0;

        /* age increases = older. Walk from old to new conceptually via reverse ages */
        for (int age = g_hcount - 1; age >= 0; age--) {
            Frame* F = histAt(age);
            if (!F || (dropT - F->t) > LOOKBACK_MS) continue;
            EntSnap* M = findMob(F, ent);
            if (!M || !M->ok) {
                if (lastAlive && !firstDead) {
                    vanished = 1;
                    firstDeadT = F->t;
                }
                continue;
            }
            uint16_t lo = *(uint16_t*)(M->eb + 0x18);
            if (lo & 1) {
                lastAlive = M;
                lastAliveT = F->t;
                firstDead = NULL;
                vanished = 0;
            } else if (lastAlive && !firstDead) {
                firstDead = M;
                firstDeadT = F->t;
                vanished = 0;
            }
        }

        if (!lastAlive) continue;
        if (!firstDead && !vanished) {
            /* still alive at drop — skip (not the killer victim) */
            continue;
        }

        int lag = (int)(dropT - (vanished ? firstDeadT : firstDeadT));
        if (lag < 0) lag = 0;
        /* prefer smaller lag to drop, then closer cell */
        if (!found || lag < bestLag) {
            found = 1;
            bestLag = lag;
            bestAlive = *lastAlive;
            bestAliveT = lastAliveT;
            bestVanish = vanished;
            bestEnt = ent;
            if (!vanished && firstDead) {
                bestDead = *firstDead;
                bestDeadT = firstDeadT;
            } else {
                bestDeadT = firstDeadT;
            }
        }
    }

    if (!found) {
        fprintf(g_log, "  %d alive-near candidates, but none flipped to dead "
            "before drop (death may be outside lookback)\n", nc);
        fflush(g_log);
        return;
    }

    (void)bestEnt;
    dumpTransition(g_drops, dropT, item, &bestAlive, bestAliveT,
                   bestVanish ? NULL : &bestDead, bestDeadT, bestVanish);
}

int main(int argc, char** argv) {
    int secs = 180;
    if (argc >= 2) secs = atoi(argv[1]);
    if (secs < 30) secs = 30;
    if (secs > 900) secs = 900;

    printf("=== DROP-ANCHORED DEATH (v2: find alive->dead BEFORE loot) ===\n");
    printf("Kill monsters that drop ground items.\n");
    if (!SignedOpen()) { printf("SignedOpen FAIL\n"); return 1; }
    g_pid = findPid(L"LC.exe");
    if (!g_pid || !getModule(&g_base, &g_modSize)) {
        printf("attach FAIL\n"); SignedClose(); return 1;
    }
    printf("pid=%lu base=0x%llX %ds Item=0x%X Monster=0x%X\n\n",
        (unsigned long)g_pid, (unsigned long long)g_base, secs, VFT_ITEM, VFT_MONSTER);

    g_log = fopen("drop_death_events.log", "w");
    g_csv = fopen("drop_death.csv", "w");
    if (!g_log || !g_csv) { printf("log fail\n"); return 1; }
    fprintf(g_csv, "drop,kind,t_ms,mob,item,region,off,width,old,new\n");
    fprintf(g_log, "drop_death v2 start\n");

    g_t0 = GetTickCount();
    DWORD tEnd = g_t0 + (DWORD)secs * 1000u;
    DWORD lastStat = g_t0;

    Frame warm; sweepFrame(&warm);
    for (int i = 0; i < warm.ni; i++) addKnown(warm.item[i].ent);
    printf("warmup mobs=%d items_seeded=%d\n", warm.nm, warm.ni);

    while (GetTickCount() < tEnd) {
        Frame cur;
        sweepFrame(&cur);
        g_hist[g_hpos] = cur;
        g_hpos = (g_hpos + 1) % HIST;
        if (g_hcount < HIST) g_hcount++;

        for (int i = 0; i < cur.ni; i++) {
            if (knowItem(cur.item[i].ent)) continue;
            addKnown(cur.item[i].ent);
            onItemDrop(&cur.item[i], &cur);
        }

        DWORD now = GetTickCount();
        if (now - lastStat >= 2000) {
            printf("[+%lus] M=%d I=%d drops=%d kills=%d bit0_deaths=%d\n",
                (unsigned long)((now - g_t0) / 1000), cur.nm, cur.ni,
                g_drops, g_kills, g_bit0_events);
            lastStat = now;
        }
        Sleep(POLL_MS);
    }

    FILE* out = fopen("DROP_DEATH_REPORT.md", "w");
    if (!out) out = stdout;
    fprintf(out, "# Drop-anchored death signal (v2)\n\n");
    fprintf(out, "- drops: **%d** | kills with alive->dead: **%d**\n", g_drops, g_kills);
    fprintf(out, "- bit0 1->0 at transition: **%d**\n", g_bit0_events);
    fprintf(out, "- vanished at transition: %d\n", g_vanish_events);
    if (g_trans_n > 0)
        fprintf(out, "- avg lag death->drop: **%d ms**\n\n", g_trans_ms_sum / g_trans_n);
    else
        fprintf(out, "\n");

    int need = g_bit0_events; /* consensus among captured transitions with after */
    if (need > 0) {
        fprintf(out, "## Offsets changed on ALL bit0-death captures (%d)\n\n", need);
        for (int o = 0; o < ENT_BLOB; o++) {
            if (g_eflip[o] >= need)
                fprintf(out, "- `Entity+0x%03X` (%d/%d)\n", o, g_eflip[o], need);
        }
        int thr = (need * 3 + 3) / 4;
        fprintf(out, "\n### >=75%%\n\n");
        for (int o = 0; o < ENT_BLOB; o++)
            if (g_eflip[o] >= thr && g_eflip[o] < need)
                fprintf(out, "- `Entity+0x%03X` (%d/%d)\n", o, g_eflip[o], need);
    } else {
        fprintf(out, "No alive->dead transitions captured before drops.\n"
            "Kill monsters **that leave ground loot**, stay in range.\n");
    }

    fprintf(out, "\n## Conclusion template\n\n");
    fprintf(out, "Clock = new Item `0x116E5B8`. Death signal searched as "
        "Monster state change **before** that clock.\n");
    fprintf(out, "\nLogs: `drop_death_events.log`, `drop_death.csv`\n");

    if (out != stdout) { fclose(out); printf("\nwrote DROP_DEATH_REPORT.md\n"); }
    fclose(g_log); fclose(g_csv);
    printf("done drops=%d kills=%d bit0=%d\n", g_drops, g_kills, g_bit0_events);
    SignedClose();
    return 0;
}
