/* probe_drop_attr.c — live signeddrv: watch Item drops, then detect which
   Entity attributes change on nearby Monsters (no alive/dead assumption).
   Method:
     - Ring-buffer ~5s of Monster Entity[0x120] + cell
     - New Item vft 0x116E5B8 = DROP clock
     - For every Monster within DROP_NEAR cells of the drop:
         compare oldest-in-window snap vs newest snap (and vs current);
         log every changed aligned u16/u32 field
     - Aggregate: offsets that change on >=N drops / nearby mobs
   Usage: probe_drop_attr.exe [seconds=180]
   Out: drop_attr_events.log  drop_attr.csv  DROP_ATTR_REPORT.md
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
#define MAX_ENT      72
#define ENT_BLOB     0x120u
#define HIST         250
#define POLL_MS      20
#define CELL_RAD     120
#define DROP_NEAR    12
#define LOOKBACK_MS  4000

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

/* per-offset: how many (drop,mob) pairs saw this u32 change */
static int g_drops;
static int g_pairs;          /* drop x nearby-mob examined */
static int g_pairs_changed;  /* pairs with >=1 byte change */
static int g_pairs_vanish;
static int g_u32_chg[ENT_BLOB / 4];
static int g_u16_chg[ENT_BLOB / 2];

static void onDrop(EntSnap* item, Frame* cur) {
    g_drops++;
    DWORD t = cur->t - g_t0;
    uint16_t ilo = item->ok ? *(uint16_t*)(item->eb + 0x18) : 0;
    uint16_t ihi = item->ok ? *(uint16_t*)(item->eb + 0x1A) : 0;

    fprintf(g_log,
        "\n===== DROP#%d t=%lums item=0x%llX cell=(%d,%d) item+18=%u +1A=%u =====\n",
        g_drops, (unsigned long)t, (unsigned long long)item->ent,
        item->cx, item->cy, ilo, ihi);
    printf("DROP#%d t=%lums cell=(%d,%d) +1A=%u\n",
        g_drops, (unsigned long)t, item->cx, item->cy, ihi);

    /* unique mob ents seen near drop cell in lookback OR currently near */
    uint64_t cands[MAX_ENT];
    int nc = 0;
    for (int age = 0; age < g_hcount; age++) {
        Frame* F = histAt(age);
        if (!F || (cur->t - F->t) > LOOKBACK_MS) break;
        for (int i = 0; i < F->nm; i++) {
            EntSnap* M = &F->mob[i];
            if (abs(M->cx - item->cx) > DROP_NEAR || abs(M->cy - item->cy) > DROP_NEAR)
                continue;
            int dup = 0;
            for (int k = 0; k < nc; k++) if (cands[k] == M->ent) dup = 1;
            if (!dup && nc < MAX_ENT) cands[nc++] = M->ent;
        }
    }

    if (nc == 0) {
        fprintf(g_log, "  (no Monster within %d cells in last %dms)\n", DROP_NEAR, LOOKBACK_MS);
        fflush(g_log);
        return;
    }

    for (int ci = 0; ci < nc; ci++) {
        uint64_t ent = cands[ci];
        /* oldest ok snap in window, newest ok snap in window */
        EntSnap* oldest = NULL; DWORD oldestT = 0;
        EntSnap* newest = NULL; DWORD newestT = 0;
        for (int age = g_hcount - 1; age >= 0; age--) {
            Frame* F = histAt(age);
            if (!F || (cur->t - F->t) > LOOKBACK_MS) continue;
            EntSnap* M = findMob(F, ent);
            if (!M || !M->ok) continue;
            if (!oldest) { oldest = M; oldestT = F->t; }
            newest = M; newestT = F->t;
        }
        /* also current frame */
        EntSnap* nowM = findMob(cur, ent);
        if (nowM && nowM->ok) { newest = nowM; newestT = cur->t; }

        g_pairs++;
        if (!oldest) continue;

        if (!newest || (newest == oldest && !nowM)) {
            /* vanished: was present earlier, gone now */
            if (!nowM) {
                g_pairs_vanish++;
                fprintf(g_log,
                    "  MOB vanish ent=0x%llX last_cell=(%d,%d) last+18=%u +1A=%u "
                    "(present %lums ago, gone at drop)\n",
                    (unsigned long long)ent, oldest->cx, oldest->cy,
                    *(uint16_t*)(oldest->eb + 0x18), *(uint16_t*)(oldest->eb + 0x1A),
                    (unsigned long)(cur->t - oldestT));
                fprintf(g_csv, "%d,vanish,%lu,0x%llX,0x%llX,-,0,-,%u,gone\n",
                    g_drops, (unsigned long)t,
                    (unsigned long long)ent, (unsigned long long)item->ent,
                    *(uint16_t*)(oldest->eb + 0x18));
                printf("  mob 0x%llX VANISHED\n", (unsigned long long)ent);
            }
            continue;
        }

        /* diff oldest -> newest */
        int nchg = 0;
        fprintf(g_log,
            "  MOB ent=0x%llX vft=0x%X cell=(%d,%d)->(%d,%d) window %lums..%lums\n",
            (unsigned long long)ent, oldest->vft,
            oldest->cx, oldest->cy, newest->cx, newest->cy,
            (unsigned long)(oldestT - g_t0), (unsigned long)(newestT - g_t0));
        fprintf(g_log, "    key before: +04=%u +18=%u +1A=%u\n",
            *(uint32_t*)(oldest->eb + 4),
            *(uint16_t*)(oldest->eb + 0x18),
            *(uint16_t*)(oldest->eb + 0x1A));
        fprintf(g_log, "    key after:  +04=%u +18=%u +1A=%u\n",
            *(uint32_t*)(newest->eb + 4),
            *(uint16_t*)(newest->eb + 0x18),
            *(uint16_t*)(newest->eb + 0x1A));

        for (int o = 0; o + 4 <= ENT_BLOB; o += 4) {
            uint32_t a = *(uint32_t*)(oldest->eb + o);
            uint32_t b = *(uint32_t*)(newest->eb + o);
            if (a == b) continue;
            nchg++;
            g_u32_chg[o / 4]++;
            fprintf(g_log, "    +0x%03X.u32: %u(0x%X) -> %u(0x%X)\n", o, a, a, b, b);
            fprintf(g_csv, "%d,chg,%lu,0x%llX,0x%llX,ent,0x%03X,u32,%u,%u\n",
                g_drops, (unsigned long)t,
                (unsigned long long)ent, (unsigned long long)item->ent, o, a, b);
        }
        /* also note u16-only half changes for +0x18/+0x1A clarity */
        for (int o = 0; o + 2 <= ENT_BLOB; o += 2) {
            uint16_t a = *(uint16_t*)(oldest->eb + o);
            uint16_t b = *(uint16_t*)(newest->eb + o);
            if (a == b) continue;
            /* count only if not already covered as full u32 equal change both halves —
               still count for report */
            g_u16_chg[o / 2]++;
            if ((o % 4) != 0) {
                /* high half of a dword — still log if u32 already logged; skip duplicate log */
            }
        }

        if (nchg > 0) {
            g_pairs_changed++;
            printf("  mob 0x%llX CHANGED %d dwords  +18 %u->%u  +1A %u->%u\n",
                (unsigned long long)ent, nchg,
                *(uint16_t*)(oldest->eb + 0x18), *(uint16_t*)(newest->eb + 0x18),
                *(uint16_t*)(oldest->eb + 0x1A), *(uint16_t*)(newest->eb + 0x1A));
        } else {
            fprintf(g_log, "    (no Entity[0..0x%X] change in window)\n", ENT_BLOB);
            printf("  mob 0x%llX no change in window\n", (unsigned long long)ent);
        }
    }
    fflush(g_log);
    fflush(g_csv);
}

int main(int argc, char** argv) {
    int secs = 180;
    if (argc >= 2) secs = atoi(argv[1]);
    if (secs < 30) secs = 30;
    if (secs > 900) secs = 900;

    printf("=== DROP ATTR SCAN — kill monsters that drop items ===\n");
    if (!SignedOpen()) { printf("SignedOpen FAIL\n"); return 1; }
    g_pid = findPid(L"LC.exe");
    if (!g_pid || !getModule(&g_base, &g_modSize)) {
        printf("attach FAIL\n"); SignedClose(); return 1;
    }
    printf("pid=%lu base=0x%llX %ds  Item=0x%X Monster=0x%X\n",
        (unsigned long)g_pid, (unsigned long long)g_base, secs, VFT_ITEM, VFT_MONSTER);
    printf("On each NEW ground item: diff nearby Monster Entity fields.\n\n");

    g_log = fopen("drop_attr_events.log", "w");
    g_csv = fopen("drop_attr.csv", "w");
    if (!g_log || !g_csv) { printf("log fail\n"); return 1; }
    fprintf(g_csv, "drop,kind,t_ms,mob,item,region,off,width,old,new\n");
    fprintf(g_log, "drop_attr start (no alive/dead assumption)\n");

    g_t0 = GetTickCount();
    DWORD tEnd = g_t0 + (DWORD)secs * 1000u;
    DWORD lastStat = g_t0;

    Frame warm; sweepFrame(&warm);
    for (int i = 0; i < warm.ni; i++) addKnown(warm.item[i].ent);
    printf("warmup: mobs=%d items_seeded=%d\n", warm.nm, warm.ni);

    while (GetTickCount() < tEnd) {
        Frame cur;
        sweepFrame(&cur);
        g_hist[g_hpos] = cur;
        g_hpos = (g_hpos + 1) % HIST;
        if (g_hcount < HIST) g_hcount++;

        for (int i = 0; i < cur.ni; i++) {
            if (knowItem(cur.item[i].ent)) continue;
            addKnown(cur.item[i].ent);
            onDrop(&cur.item[i], &cur);
        }

        DWORD now = GetTickCount();
        if (now - lastStat >= 2000) {
            printf("[+%lus] M=%d I=%d drops=%d pairs=%d changed=%d vanish=%d\n",
                (unsigned long)((now - g_t0) / 1000), cur.nm, cur.ni,
                g_drops, g_pairs, g_pairs_changed, g_pairs_vanish);
            lastStat = now;
        }
        Sleep(POLL_MS);
    }

    FILE* out = fopen("DROP_ATTR_REPORT.md", "w");
    if (!out) out = stdout;
    fprintf(out, "# Drop-anchored Monster attribute changes\n\n");
    fprintf(out, "- drops: **%d**\n", g_drops);
    fprintf(out, "- nearby mob pairs examined: **%d**\n", g_pairs);
    fprintf(out, "- pairs with Entity dword changes: **%d**\n", g_pairs_changed);
    fprintf(out, "- pairs vanished: **%d**\n\n", g_pairs_vanish);

    fprintf(out, "## Entity u32 offsets changed (count of pairs)\n\n");
    fprintf(out, "| offset | pairs_changed |\n|--------|---------------|\n");
    int shown = 0;
    /* sort by count descending via simple selection */
    for (int pass = 0; pass < 40; pass++) {
        int best = -1, bi = -1;
        for (int i = 0; i < ENT_BLOB / 4; i++) {
            int used = 0;
            /* find max not yet printed — just print all with count>0 sorted */
            (void)used;
        }
        (void)best; (void)bi;
    }
    /* print all non-zero sorted bubble of indices */
    int idx[ENT_BLOB / 4];
    int nidx = 0;
    for (int i = 0; i < ENT_BLOB / 4; i++) if (g_u32_chg[i] > 0) idx[nidx++] = i;
    for (int a = 0; a < nidx; a++)
        for (int b = a + 1; b < nidx; b++)
            if (g_u32_chg[idx[b]] > g_u32_chg[idx[a]]) {
                int tmp = idx[a]; idx[a] = idx[b]; idx[b] = tmp;
            }
    for (int k = 0; k < nidx; k++) {
        int i = idx[k];
        fprintf(out, "| `Entity+0x%03X` | %d |\n", i * 4, g_u32_chg[i]);
        shown++;
    }
    if (!shown) fprintf(out, "| (none) | 0 |\n");

    fprintf(out, "\n## Note\n\n");
    fprintf(out, "No alive/dead label assumed. Clock = new Item `0x116E5B8`. "
        "Diff = oldest vs newest Monster snapshot within %dms of drop cell.\n", LOOKBACK_MS);
    fprintf(out, "\nFiles: `drop_attr_events.log`, `drop_attr.csv`\n");

    if (out != stdout) {
        fclose(out);
        printf("\nwrote DROP_ATTR_REPORT.md\n");
    }
    fclose(g_log);
    fclose(g_csv);
    printf("done drops=%d changed_pairs=%d\n", g_drops, g_pairs_changed);
    SignedClose();
    (void)g_u16_chg;
    return 0;
}
