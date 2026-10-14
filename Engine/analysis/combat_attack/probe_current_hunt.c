/* probe_current_hunt.c — find the drawer's CURRENT foot / tick-dur.
   Direction: do NOT reconstruct wall-clock t. Find what moves BETWEEN
   PRES from→to edges (geometric between, or tick rising).

   Scopes per SELF (and optional neighbors):
     - PRES blob 0x000..0x1FF
     - H-chain objects (2 hops)
     - one pointer hop from those objects
   Scores mid-step only (from!=to and from/to stable). */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "signeddrv_client.h"

#define OFF_PLAYER_X 0x164E310
#define OFF_PLAYER_Y 0x164E314
#define OFF_ENT_MGR  0x164E460
#define GRID_VFT     0x116B858u
#define VFT_SELF     0x116E738u
#define VFT_A        0x116AAC8u
#define VFT_RSS      0x116AAE0u
#define BLOB         0x200u
#define MAX_OBJ      96
#define MAX_HIT      64

static DWORD g_pid; static uint64_t g_base; static uint32_t g_modSize;
static int isHeap(uint64_t a) {
    return a >= 0x10000000000ULL && a < 0x70000000000ULL;
}
static int isMod(uint64_t a) { return a >= g_base && a < g_base + g_modSize; }
static BOOL rm(uint64_t a, void* b, uint32_t n) {
    uint32_t br = 0; return SignedReadMemory(g_pid, a, b, n, &br) && br == n;
}
static uint64_t rq(uint64_t a) { uint64_t v = 0; rm(a, &v, 8); return v; }
static uint32_t rd(uint64_t a) { uint32_t v = 0; rm(a, &v, 4); return v; }
static float rf(uint64_t a) { float v = 0; rm(a, &v, 4); return v; }
static uint32_t vrva(uint64_t o) {
    uint64_t v = rq(o); return isMod(v) ? (uint32_t)(v - g_base) : 0;
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
    uint64_t peb=0,ldr=0,listHead=0,cur=0,entry=0,dllBase=0; uint32_t b=0,dllSize=0;
    if (!SignedGetPeb(g_pid,&peb)||!peb) return 0;
    if (!(SignedReadMemory(g_pid,peb+0x18,&ldr,8,&b)&&b==8)) return 0;
    if (!(SignedReadMemory(g_pid,ldr+0x20,&listHead,8,&b)&&b==8)) return 0;
    cur=listHead;
    while (cur && cur!=(ldr+0x20)) {
        entry=cur-0x10; dllBase=0; dllSize=0;
        if ((SignedReadMemory(g_pid,entry+0x30,&dllBase,8,&b)&&b==8&&dllBase) &&
            (SignedReadMemory(g_pid,entry+0x40,&dllSize,4,&b)&&b==4&&dllSize)) {
            *base=dllBase; *size=dllSize; return 1;
        }
        if (!(SignedReadMemory(g_pid,cur,&cur,8,&b)&&b==8)) return 0;
    }
    return 0;
}
static uint64_t findByVft(uint64_t ent, uint32_t want) {
    uint64_t H = rq(ent + 0x20);
    if (!isHeap(H)) return 0;
    for (uint32_t off = 0; off < 0x120; off += 8) {
        uint64_t p = rq(H + off);
        if (!isHeap(p)) continue;
        if (vrva(p) == want) return p;
        for (uint32_t o2 = 0; o2 < 0xA0; o2 += 8) {
            uint64_t c = rq(p + o2);
            if (isHeap(c) && vrva(c) == want) return c;
        }
    }
    return 0;
}
static uint64_t findSelf(void) {
    uint64_t mgr = rq(g_base + OFF_ENT_MGR);
    uint8_t g = 0; rm(mgr + 0xD8, &g, 1);
    if (!isHeap(mgr) || g != 1) return 0;
    uint64_t holder = rq(mgr + 0xD0);
    uint64_t bgn = rq(holder + 0x180), end = rq(holder + 0x188);
    uint64_t grid = 0;
    for (uint64_t e = bgn; e + 16 <= end; e += 16)
        if (vrva(rq(e)) == GRID_VFT) { grid = rq(e); break; }
    if (!grid) return 0;
    uint32_t px = rd(g_base + OFF_PLAYER_X), py = rd(g_base + OFF_PLAYER_Y);
    uint32_t heads[2] = { 0x798u, 0x7D8u };
    for (int hi = 0; hi < 2; hi++) {
        uint64_t sent = rq(grid + heads[hi] + 8), cur = rq(sent + 8);
        int hops = 0;
        while (cur && cur != sent && hops++ < 512) {
            uint64_t next = rq(cur + 8);
            int32_t cx = (int32_t)rd(cur + 0x10), cy = (int32_t)rd(cur + 0x14);
            uint64_t vb = rq(cur + 0x18), ve = rq(cur + 0x20);
            if (isHeap(vb) && ve > vb)
                for (uint64_t p = vb; p + 8 <= ve; p += 8) {
                    uint64_t q = rq(p);
                    if (!isHeap(q) || rq(q + 8) != q) continue;
                    if (vrva(q) == VFT_SELF &&
                        abs(cx - (int)px) + abs(cy - (int)py) < 4)
                        return q;
                }
            cur = next;
        }
    }
    return 0;
}

typedef struct {
    uint64_t addr;
    uint32_t vft;
    uint8_t prev[BLOB];
    int have;
    /* mid-step scores per dword index */
    int betweenU[BLOB/4];   /* float strictly between fromU and toU, changed */
    int betweenV[BLOB/4];
    int towardTo[BLOB/4];   /* moved closer to to on that axis */
    int unitRise[BLOB/4];
    int tickRise[BLOB/4];   /* u32 +1..8 */
    int fChg[BLOB/4];
    int dirtyHit;           /* +0x100/+0x150/+0x161 seen as 1 while mid */
} Watch;

static Watch g_w[MAX_OBJ];
static int g_wn;
static uint64_t g_addrs[MAX_OBJ];

static int addObj(uint64_t a) {
    if (!isHeap(a)) return 0;
    for (int i = 0; i < g_wn; i++) if (g_addrs[i] == a) return 0;
    if (g_wn >= MAX_OBJ) return 0;
    g_addrs[g_wn] = a;
    memset(&g_w[g_wn], 0, sizeof(g_w[0]));
    g_w[g_wn].addr = a;
    g_w[g_wn].vft = vrva(a);
    g_wn++;
    return 1;
}
static void collectAround(uint64_t ent, uint64_t pa) {
    g_wn = 0;
    addObj(ent);
    addObj(pa);
    uint64_t H = rq(ent + 0x20);
    if (isHeap(H)) addObj(H);
    /* H slots + children */
    if (isHeap(H)) {
        for (uint32_t off = 0; off < 0x120; off += 8) {
            uint64_t p = rq(H + off);
            if (!isHeap(p)) continue;
            addObj(p);
            for (uint32_t o2 = 0; o2 < 0xA0; o2 += 8) {
                uint64_t c = rq(p + o2);
                addObj(c);
            }
        }
    }
    /* pointer hop from PRES */
    if (pa) {
        for (uint32_t off = 0x08; off < 0x100; off += 8) {
            uint64_t p = rq(pa + off);
            addObj(p);
        }
    }
    /* entity pointer hop */
    for (uint32_t off = 0x10; off < 0x80; off += 8) {
        uint64_t p = rq(ent + off);
        addObj(p);
    }
}

static int between(float x, float a, float b) {
    float lo = a < b ? a : b, hi = a > b ? a : b;
    return (x > lo + 0.75f && x < hi - 0.75f);
}
static float dist1(float x, float t) { return fabsf(x - t); }

static void sampleMid(float fu, float fv, float tu, float tv) {
    for (int i = 0; i < g_wn; i++) {
        Watch* w = &g_w[i];
        uint8_t cur[BLOB];
        if (!rm(w->addr, cur, BLOB)) continue;
        if (w->have) {
            /* dirty triad */
            if (cur[0x100] == 1 || cur[0x150] == 1 || cur[0x161] == 1)
                w->dirtyHit++;
            for (uint32_t off = 4; off < BLOB; off += 4) {
                float cf, pf; uint32_t cu, pu;
                memcpy(&cf, cur + off, 4); memcpy(&pf, w->prev + off, 4);
                memcpy(&cu, cur + off, 4); memcpy(&pu, w->prev + off, 4);
                if (memcmp(cur + off, w->prev + off, 4) == 0) continue;
                int idx = (int)(off / 4);
                if (isfinite(cf) && isfinite(pf) && fabsf(cf - pf) > 1e-5f &&
                    fabsf(cf) < 1e7f) {
                    w->fChg[idx]++;
                    if (cf >= -0.01f && cf <= 1.01f && pf >= -0.01f && pf <= 1.01f && cf > pf)
                        w->unitRise[idx]++;
                    int bu = between(cf, fu, tu);
                    int bv = between(cf, fv, tv);
                    if (bu) {
                        w->betweenU[idx]++;
                        if (dist1(cf, tu) + 1e-3f < dist1(pf, tu)) w->towardTo[idx]++;
                    }
                    if (bv) {
                        w->betweenV[idx]++;
                        if (dist1(cf, tv) + 1e-3f < dist1(pf, tv)) w->towardTo[idx]++;
                    }
                }
                if (cu != pu && cu > pu && (cu - pu) <= 8 && cu < 200000u)
                    w->tickRise[idx]++;
            }
        }
        memcpy(w->prev, cur, BLOB);
        w->have = 1;
    }
}

/* scan module image for live RssCore vft instances via PEB heap is too wide;
   instead walk holder subsystems for vft. */
static void tryFindRss(FILE* out) {
    uint64_t mgr = rq(g_base + OFF_ENT_MGR);
    uint64_t holder = rq(mgr + 0xD0);
    uint64_t bgn = rq(holder + 0x180), end = rq(holder + 0x188);
    int n = 0;
    fprintf(out, "holder list scan for RssCore/sprite:\n");
    for (uint64_t e = bgn; e + 16 <= end; e += 16) {
        uint64_t o = rq(e);
        if (!isHeap(o)) continue;
        uint32_t v = vrva(o);
        uint8_t dc = 0; rm(o + 0xDC, &dc, 1);
        uint64_t d0 = rq(o + 0xD0);
        uint32_t cv = isHeap(d0) ? vrva(d0) : 0;
        if (v == VFT_RSS || cv == VFT_RSS || dc == 2) {
            fprintf(out, "  obj=%llX vft=%X dc=%u d0=%llX coreVft=%X\n",
                (unsigned long long)o, v, dc,
                (unsigned long long)d0, cv);
            n++;
            if (cv == VFT_RSS || v == VFT_RSS) {
                uint64_t core = (cv == VFT_RSS) ? d0 : o;
                uint64_t bb = rq(core + 0x180), ee = rq(core + 0x188);
                fprintf(out, "    list begin=%llX end=%llX bytes=%lld\n",
                    (unsigned long long)bb, (unsigned long long)ee,
                    (long long)(ee - bb));
            }
        }
        (void)n;
    }
    /* also note any subsystem with begin/end looking like draw list */
    for (uint64_t e = bgn; e + 16 <= end; e += 16) {
        uint64_t o = rq(e);
        if (!isHeap(o)) continue;
        uint64_t b1 = rq(o + 0x180), e1 = rq(o + 0x188);
        if (isHeap(b1) && e1 > b1 && (e1 - b1) >= 16 && (e1 - b1) <= 0x20000) {
            uint32_t v = vrva(o);
            fprintf(out, "  begin/end cand obj=%llX vft=%X span=%lld\n",
                (unsigned long long)o, v, (long long)(e1 - b1));
        }
    }
}

typedef struct { uint64_t addr; uint32_t vft, off; int score; const char* kind; } Hit;

int main(int argc, char** argv) {
    int secs = 25;
    if (argc > 1) secs = atoi(argv[1]);
    if (!SignedOpen()) return 1;
    g_pid = findPid(L"LC.exe");
    if (!g_pid || !getModule(&g_base, &g_modSize)) return 1;

    uint64_t self = findSelf();
    uint64_t pa = findByVft(self, VFT_A);
    printf("=== CURRENT HUNT %ds — WALK ===\n", secs);
    printf("self=%llX PRES=%llX\n", (unsigned long long)self, (unsigned long long)pa);
    if (!self || !pa) { SignedClose(); return 1; }

    collectAround(self, pa);
    printf("watching %d objects\n", g_wn);
    for (int i = 0; i < g_wn && i < 20; i++)
        printf("  [%d] %llX vft=%X\n", i, (unsigned long long)g_w[i].addr, g_w[i].vft);

    FILE* sum = fopen("current_hunt.txt", "w");
    FILE* csv = fopen("current_hunt.csv", "w");
    fprintf(csv, "ms,phase,fu,fv,tu,tv,mid\n");
    tryFindRss(sum);

    float lfu = rf(pa+0x60), lfv = rf(pa+0x64), ltu = rf(pa+0x68), ltv = rf(pa+0x6C);
    DWORD stepBeg = GetTickCount(), tEnd = stepBeg + (DWORD)secs * 1000;
    int midSamples = 0, edges = 0;

    while (GetTickCount() < tEnd) {
        DWORD now = GetTickCount();
        float fu = rf(pa+0x60), fv = rf(pa+0x64), tu = rf(pa+0x68), tv = rf(pa+0x6C);
        int edge = (fabsf(fu-lfu)>0.5f||fabsf(fv-lfv)>0.5f||fabsf(tu-ltu)>0.5f||fabsf(tv-ltv)>0.5f);
        if (edge) {
            edges++;
            stepBeg = now;
            lfu = fu; lfv = fv; ltu = tu; ltv = tv;
            printf("EDGE from=(%.0f,%.0f) to=(%.0f,%.0f)\n", fu, fv, tu, tv);
            /* reset prev so we don't score across edge jump */
            for (int i = 0; i < g_wn; i++) g_w[i].have = 0;
        }
        int mid = (fabsf(fu - tu) > 1.f || fabsf(fv - tv) > 1.f);
        if (mid && !edge) {
            sampleMid(fu, fv, tu, tv);
            midSamples++;
            if ((midSamples % 40) == 0)
                fprintf(csv, "%u,%u,%.2f,%.2f,%.2f,%.2f,1\n",
                    now, now - stepBeg, fu, fv, tu, tv);
        }
        Sleep(4);
    }

    Hit hits[MAX_HIT]; int nh = 0;
    for (int i = 0; i < g_wn; i++) {
        Watch* w = &g_w[i];
        for (uint32_t k = 0; k < BLOB/4; k++) {
            int sc = w->betweenU[k]*8 + w->betweenV[k]*8 + w->towardTo[k]*12
                   + w->tickRise[k]*5 + w->unitRise[k]*3 + w->fChg[k];
            if (sc < 8) continue;
            if (nh >= MAX_HIT) break;
            const char* kind = "chg";
            if (w->towardTo[k] >= 3 && (w->betweenU[k] || w->betweenV[k]))
                kind = "CURRENT?";
            else if (w->tickRise[k] >= 5) kind = "TICK?";
            else if (w->unitRise[k] >= 5) kind = "UNIT01?";
            hits[nh].addr = w->addr; hits[nh].vft = w->vft;
            hits[nh].off = k * 4; hits[nh].score = sc; hits[nh].kind = kind;
            nh++;
        }
    }
    /* sort hits by score */
    for (int a = 0; a < nh; a++)
        for (int b = a + 1; b < nh; b++)
            if (hits[b].score > hits[a].score) {
                Hit t = hits[a]; hits[a] = hits[b]; hits[b] = t;
            }

    printf("\n=== TOP CANDIDATES (midSamples=%d edges=%d) ===\n", midSamples, edges);
    fprintf(sum, "\nmidSamples=%d edges=%d objects=%d\n", midSamples, edges, g_wn);
    int shown = 0;
    for (int i = 0; i < nh && shown < 25; i++) {
        /* skip PRES from/to themselves */
        if (hits[i].addr == pa &&
            (hits[i].off == 0x60 || hits[i].off == 0x64 ||
             hits[i].off == 0x68 || hits[i].off == 0x6C ||
             hits[i].off == 0x88 || hits[i].off == 0x8C ||
             hits[i].off == 0x90 || hits[i].off == 0x94))
            continue;
        Watch* w = NULL;
        for (int j = 0; j < g_wn; j++) if (g_w[j].addr == hits[i].addr) { w = &g_w[j]; break; }
        int idx = (int)(hits[i].off / 4);
        printf("%s score=%d obj=%llX vft=%X +0x%03X  betU=%d betV=%d toward=%d tick=%d unit=%d fChg=%d dirty=%d\n",
            hits[i].kind, hits[i].score,
            (unsigned long long)hits[i].addr, hits[i].vft, hits[i].off,
            w ? w->betweenU[idx] : 0, w ? w->betweenV[idx] : 0,
            w ? w->towardTo[idx] : 0, w ? w->tickRise[idx] : 0,
            w ? w->unitRise[idx] : 0, w ? w->fChg[idx] : 0,
            w ? w->dirtyHit : 0);
        fprintf(sum, "%s score=%d obj=%llX vft=%X +0x%03X betU=%d betV=%d toward=%d tick=%d unit=%d fChg=%d dirty=%d\n",
            hits[i].kind, hits[i].score,
            (unsigned long long)hits[i].addr, hits[i].vft, hits[i].off,
            w ? w->betweenU[idx] : 0, w ? w->betweenV[idx] : 0,
            w ? w->towardTo[idx] : 0, w ? w->tickRise[idx] : 0,
            w ? w->unitRise[idx] : 0, w ? w->fChg[idx] : 0,
            w ? w->dirtyHit : 0);
        shown++;
    }
    if (shown == 0)
        printf("NO mid-step current/tick candidates in watched set.\n");
    printf("wrote current_hunt.txt current_hunt.csv\n");
    if (sum) fclose(sum);
    if (csv) fclose(csv);
    SignedClose();
    return 0;
}
