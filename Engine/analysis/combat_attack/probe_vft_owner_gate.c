/* probe_vft_owner_gate.c
   1) Confirm live owner of vft band containing B75910 (1226300) / B75810 / B757B0
   2) Scroll/walk gate: CAM scale 0.625 vs g_pps 0.5411 for MOB rel-screen
*/
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "signeddrv_client.h"

#define OFF_ENT_MGR  0x164E460ull
#define GRID_VFT     0x116B858u
#define VFT_SELF     0x116E738u
#define VFT_PRES_B   0x116E4B8u
#define VFT_OBJ_A    0x116AAC8u
#define G_CAM        0x17D52A8u
#define G_VIEWPORT   0x17EC268u
#define G_RENDER     0x17EE3E0u
#define FN_B757B0    0xB757B0u
#define FN_B75810    0xB75810u
#define FN_B75910    0xB75910u
#define VFT_BAND     0x1226200u
#define PPS_EMP      0.5411f
#define PPS_CAM_EXPECT 0.625f
#define CX 640.f
#define CY 480.f
#define MAX_ENT 64
#define WATCH_MS 20000
#define POLL_MS 100

static uint64_t g_pid, g_base;
static uint32_t g_modSize;

static int isHeap(uint64_t a) {
    return a >= 0x10000000000ULL && a < 0x70000000000ULL;
}
static int isMod(uint64_t a) {
    return a >= g_base && a < g_base + (uint64_t)g_modSize;
}
static BOOL rm(uint64_t a, void* b, uint32_t n) {
    uint32_t br = 0;
    return SignedReadMemory(g_pid, a, b, n, &br) && br == n;
}
static uint64_t rq(uint64_t a) { uint64_t v = 0; rm(a, &v, 8); return v; }
static float rf(uint64_t a) { float v = 0; rm(a, &v, 4); return v; }
static uint32_t ri(uint64_t a) { uint32_t v = 0; rm(a, &v, 4); return v; }
static uint32_t vrva(uint64_t o) {
    uint64_t v = rq(o);
    return isMod(v) ? (uint32_t)(v - g_base) : 0;
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
static int isEntityVft(uint32_t rva) {
    switch (rva) {
    case 0x116E738: case 0x116E770: case 0x116E580:
    case 0x116E628: case 0x116E5B8: case 0x116EAD8:
    case 0x116EA30: case 0x116EBD0: return 1;
    }
    return 0;
}
static int followComp(uint64_t q, uint64_t* entOut) {
    uint64_t cand[3], p18=0, c, vf; int i;
    cand[0]=q; cand[1]=0; cand[2]=(q>0x10)?q-0x10:0;
    if (rm(q+0x18,&p18,8)&&isHeap(p18)) cand[1]=p18;
    for (i=0;i<3;i++) {
        c=cand[i]; vf=0;
        if (!c||!isHeap(c)||!rm(c,&vf,8)||!isMod(vf)) continue;
        if (!isEntityVft((uint32_t)(vf-g_base))) continue;
        *entOut=c; return 1;
    }
    return 0;
}
static uint64_t findPres(uint64_t H) {
    uint32_t off, o2; uint64_t c, d;
    if (isHeap(H) && vrva(H) == VFT_PRES_B) return H;
    for (off = 0; off < 0x180; off += 8) {
        c = rq(H + off);
        if (isHeap(c) && vrva(c) == VFT_PRES_B) return c;
        if (isHeap(c) && vrva(c) == VFT_OBJ_A && vrva(c + 0x10) == VFT_PRES_B)
            return c + 0x10;
        if (!isHeap(c) || !vrva(c)) continue;
        for (o2 = 0; o2 < 0xA0; o2 += 8) {
            d = rq(c + o2);
            if (isHeap(d) && vrva(d) == VFT_PRES_B) return d;
        }
    }
    return 0;
}

/* Does this object's vft (or secondary vptr) contain fn? Return slot off or -1 */
static int vftHasFn(uint64_t obj, uint32_t wantFn, uint32_t* slotOut) {
    uint64_t vf = rq(obj);
    uint8_t buf[0x400];
    uint32_t si;
    if (!isMod(vf)) return 0;
    if (!rm(vf, buf, sizeof(buf))) return 0;
    for (si = 0; si + 8 <= sizeof(buf); si += 8) {
        uint64_t s; memcpy(&s, buf + si, 8);
        if (isMod(s) && (uint32_t)(s - g_base) == wantFn) {
            if (slotOut) *slotOut = si;
            return 1;
        }
    }
    return 0;
}

typedef struct {
    uint64_t ent, H, pres;
    uint32_t vft;
    float u, v;
} Ent;

static int collectEnts(Ent* out, int maxn, float* selfU, float* selfV) {
    uint64_t mgr, holder, bgn, end, grid=0, e, cur, next, vb, ve, p, raw, ent, sent, H, pres;
    uint32_t heads[2] = {0x798u, 0x7D8u};
    int hi, hops, n = 0;
    *selfU = *selfV = 0;
    mgr = rq(g_base + OFF_ENT_MGR);
    holder = rq(mgr + 0xD0);
    bgn = rq(holder + 0x180); end = rq(holder + 0x188);
    for (e = bgn; e + 16 <= end; e += 16)
        if (vrva(rq(e)) == GRID_VFT) { grid = rq(e); break; }
    if (!grid) return 0;
    for (hi = 0; hi < 2; hi++) {
        sent = rq(grid + heads[hi] + 8);
        cur = rq(sent + 8); hops = 0;
        while (cur && cur != sent && hops++ < 800 && n < maxn) {
            next = rq(cur + 8);
            vb = rq(cur + 0x18); ve = rq(cur + 0x20);
            if (isHeap(vb) && ve > vb) {
                for (p = vb; p + 8 <= ve && n < maxn; p += 8) {
                    raw = rq(p); ent = 0;
                    if (!followComp(raw, &ent)) continue;
                    H = rq(ent + 0x20);
                    pres = findPres(H);
                    if (!pres) continue;
                    out[n].ent = ent; out[n].H = H; out[n].pres = pres;
                    out[n].vft = vrva(ent);
                    out[n].u = rf(pres + 0x50);
                    out[n].v = rf(pres + 0x54);
                    if (out[n].vft == VFT_SELF) {
                        *selfU = out[n].u; *selfV = out[n].v;
                    }
                    n++;
                }
            }
            cur = next;
        }
    }
    return n;
}

int main(void) {
    FILE* out;
    uint8_t* page;
    uint32_t off, endOff, i;
    uint64_t cam, vp, scratch, rnd;
    int nh;
    Ent snap0[MAX_ENT], snap1[MAX_ENT];
    int n0, n1;
    float sU0, sV0, sU1, sV1;

    out = fopen("bridge_vft_owner_gate.txt", "w");
    if (!out) out = stdout;
    if (!SignedOpen()) { fprintf(out, "FAIL open\n"); return 1; }
    if (!SignedFindProcess(L"LC.exe", &g_pid)) { fprintf(out, "FAIL find\n"); return 1; }
    SignedSetTarget(g_pid);
    if (!getModule(&g_base, &g_modSize)) { fprintf(out, "FAIL mod\n"); return 1; }

    cam = rq(g_base + G_CAM);
    vp = rq(g_base + G_VIEWPORT);
    scratch = rq(vp + 0x1A8);
    rnd = rq(g_base + G_RENDER);

    fprintf(out, "=== VFT owner + scroll scale gate ===\n");
    fprintf(out, "base=%llX cam=%llX vp=%llX scratch=%llX rnd=%llX\n\n",
        (unsigned long long)g_base, (unsigned long long)cam,
        (unsigned long long)vp, (unsigned long long)scratch,
        (unsigned long long)rnd);

    /* ---------- PART 1: vft owner ---------- */
    fprintf(out, "--- PART1: who owns B757B0/B75810/B75910 ---\n");

    /* Map exact slot for each fn in band starting 1226200 and 1226590 */
    {
        uint32_t bases[] = {0x1226200u, 0x1226500u, 0x1226590u, 0x1226000u};
        int bi;
        for (bi = 0; bi < 4; bi++) {
            uint32_t b = bases[bi];
            fprintf(out, "  band@%06X:", b);
            for (i = 0; i < 0x200 / 8; i++) {
                uint64_t s = rq(g_base + b + i * 8);
                uint32_t fn;
                if (!isMod(s)) continue;
                fn = (uint32_t)(s - g_base);
                if (fn == FN_B757B0 || fn == FN_B75810 || fn == FN_B75910)
                    fprintf(out, " +%03X=%06X", i * 8, fn);
            }
            fprintf(out, "\n");
        }
    }

    /* Check known singletons */
    {
        struct { const char* name; uint64_t o; } objs[] = {
            {"CAM", cam}, {"VIEWPORT", vp}, {"SCRATCH", scratch},
            {"RENDER", rnd}, {"vp+100", rq(vp+0x100)},
            {"scratch+0", rq(scratch)}, /* first ptr */
        };
        uint32_t slot;
        for (i = 0; i < 6; i++) {
            if (!objs[i].o || !isHeap(objs[i].o)) continue;
            fprintf(out, "  %s %llX vft=%06X",
                objs[i].name, (unsigned long long)objs[i].o, vrva(objs[i].o));
            if (vftHasFn(objs[i].o, FN_B757B0, &slot))
                fprintf(out, " HAS B757B0@+%03X", slot);
            if (vftHasFn(objs[i].o, FN_B75810, &slot))
                fprintf(out, " HAS B75810@+%03X", slot);
            if (vftHasFn(objs[i].o, FN_B75910, &slot))
                fprintf(out, " HAS B75910@+%03X", slot);
            fprintf(out, "\n");
        }
    }

    /* CAM secondary vptrs: (a) heap child objs (b) in-object secondary vft* into .rdata */
    fprintf(out, "\n--- CAM secondary vptrs ---\n");
    for (off = 0; off < 0x200; off += 8) {
        uint64_t p = rq(cam + off);
        uint32_t slot, si;
        uint8_t buf[0x400];
        /* Case A: p is heap object with its own vft */
        if (isHeap(p) && vrva(p) && isMod(rq(p))) {
            if (vftHasFn(p, FN_B75910, &slot) || vftHasFn(p, FN_B757B0, &slot) ||
                vftHasFn(p, FN_B75810, &slot)) {
                fprintf(out, "  cam+%03X -> heap %llX vft=%06X",
                    off, (unsigned long long)p, vrva(p));
                if (vftHasFn(p, FN_B757B0, &slot)) fprintf(out, " B757B0@+%03X", slot);
                if (vftHasFn(p, FN_B75810, &slot)) fprintf(out, " B75810@+%03X", slot);
                if (vftHasFn(p, FN_B75910, &slot)) fprintf(out, " B75910@+%03X", slot);
                fprintf(out, "\n");
            }
        }
        /* Case B: p is a vft pointer (module .rdata) embedded in CAM */
        if (isMod(p) && off > 0) {
            if (!rm(p, buf, sizeof(buf))) continue;
            for (si = 0; si + 8 <= sizeof(buf); si += 8) {
                uint64_t s; memcpy(&s, buf + si, 8);
                if (!isMod(s)) continue;
                {
                    uint32_t fn = (uint32_t)(s - g_base);
                    if (fn == FN_B757B0 || fn == FN_B75810 || fn == FN_B75910) {
                        fprintf(out, "  cam+%03X = vft*%06X  fn@+%03X=%06X\n",
                            off, (uint32_t)(p - g_base), si, fn);
                    }
                }
            }
        }
    }

    /* Also: object whose PRIMARY vft equals 1226200 exactly */
    page = (uint8_t*)malloc(0x1000);
    endOff = g_modSize & ~0xFFFu;
    fprintf(out, "\n--- GLOBAL* -> obj with vft exactly 1226200 ---\n");
    nh = 0;
    for (off = 0x1600000u; off < endOff && nh < 20; off += 0x1000) {
        uint32_t j;
        if (!rm(g_base + off, page, 0x1000)) continue;
        for (j = 0; j + 8 <= 0x1000 && nh < 20; j += 8) {
            uint64_t v; uint32_t vr, slot;
            memcpy(&v, page + j, 8);
            if (!isHeap(v)) continue;
            vr = vrva(v);
            if (vr != VFT_BAND) continue;
            fprintf(out, "  G*%06X -> %llX", off + j, (unsigned long long)v);
            if (vftHasFn(v, FN_B75910, &slot)) fprintf(out, " B75910@+%03X", slot);
            fprintf(out, "\n");
            nh++;
        }
    }
    fprintf(out, "exact_1226200=%d\n", nh);

    /* GLOBAL* -> obj whose vft CONTAINS B75910 (any base) */
    fprintf(out, "\n--- GLOBAL* -> obj whose vft contains B75910 ---\n");
    nh = 0;
    for (off = 0x1600000u; off < endOff && nh < 25; off += 0x1000) {
        uint32_t j;
        if (!rm(g_base + off, page, 0x1000)) continue;
        for (j = 0; j + 8 <= 0x1000 && nh < 25; j += 8) {
            uint64_t v; uint32_t slot, vr;
            memcpy(&v, page + j, 8);
            if (!isHeap(v) || !vrva(v)) continue;
            if (!vftHasFn(v, FN_B75910, &slot)) continue;
            vr = vrva(v);
            fprintf(out, "  G*%06X -> %llX vft=%06X B75910@+%03X",
                off + j, (unsigned long long)v, vr, slot);
            if (v == cam) fprintf(out, " <<CAM");
            if (v == vp) fprintf(out, " <<VP");
            if (v == scratch) fprintf(out, " <<SCRATCH");
            fprintf(out, "\n");
            nh++;
        }
    }
    fprintf(out, "owner_hits=%d\n", nh);

    /* Same for B75810 and B757B0 */
    fprintf(out, "\n--- GLOBAL* -> obj whose vft contains B75810 ---\n");
    nh = 0;
    for (off = 0x1600000u; off < endOff && nh < 15; off += 0x1000) {
        uint32_t j;
        if (!rm(g_base + off, page, 0x1000)) continue;
        for (j = 0; j + 8 <= 0x1000 && nh < 15; j += 8) {
            uint64_t v; uint32_t slot;
            memcpy(&v, page + j, 8);
            if (!isHeap(v) || !vrva(v)) continue;
            if (!vftHasFn(v, FN_B75810, &slot)) continue;
            fprintf(out, "  G*%06X -> %llX vft=%06X B75810@+%03X%s\n",
                off + j, (unsigned long long)v, vrva(v), slot,
                v == cam ? " <<CAM" : "");
            nh++;
        }
    }
    fprintf(out, "B75810_hits=%d\n", nh);

    fprintf(out, "\n--- GLOBAL* -> obj whose vft contains B757B0 ---\n");
    nh = 0;
    for (off = 0x1600000u; off < endOff && nh < 15; off += 0x1000) {
        uint32_t j;
        if (!rm(g_base + off, page, 0x1000)) continue;
        for (j = 0; j + 8 <= 0x1000 && nh < 15; j += 8) {
            uint64_t v; uint32_t slot;
            memcpy(&v, page + j, 8);
            if (!isHeap(v) || !vrva(v)) continue;
            if (!vftHasFn(v, FN_B757B0, &slot)) continue;
            fprintf(out, "  G*%06X -> %llX vft=%06X B757B0@+%03X%s\n",
                off + j, (unsigned long long)v, vrva(v), slot,
                v == cam ? " <<CAM" : "");
            nh++;
        }
    }
    fprintf(out, "B757B0_hits=%d\n", nh);

    /* Multi-inh: scan heap objs for qword at +8/+10/+18 == 1226200 */
    fprintf(out, "\n--- GLOBAL* -> obj with secondary vptr == 1226200 ---\n");
    nh = 0;
    {
        uint64_t want = g_base + VFT_BAND;
        for (off = 0x1600000u; off < endOff && nh < 20; off += 0x1000) {
            uint32_t j;
            if (!rm(g_base + off, page, 0x1000)) continue;
            for (j = 0; j + 8 <= 0x1000 && nh < 20; j += 8) {
                uint64_t v; uint32_t so;
                memcpy(&v, page + j, 8);
                if (!isHeap(v) || !vrva(v)) continue;
                for (so = 8; so <= 0x40; so += 8) {
                    if (rq(v + so) == want) {
                        fprintf(out, "  G*%06X -> %llX primaryVft=%06X +%02X=1226200\n",
                            off + j, (unsigned long long)v, vrva(v), so);
                        nh++;
                        break;
                    }
                }
            }
        }
    }
    fprintf(out, "secondary_hits=%d\n", nh);

    /* ---------- PART 2: scroll / walk scale gate ---------- */
    fprintf(out, "\n=== PART2: scale gate (watch %dms for walk) ===\n", WATCH_MS);
    fprintf(out, "Move character now — watching SELF PRES delta...\n");
    fflush(out);
    printf("WATCH %ds — walk/scroll in game\n", WATCH_MS / 1000);

    n0 = collectEnts(snap0, MAX_ENT, &sU0, &sV0);
    {
        float c50 = rf(cam+0x50), c54 = rf(cam+0x54);
        float c20 = rf(cam+0x20), c24 = rf(cam+0x24);
        fprintf(out, "t0: ents=%d self=%.1f,%.1f cam scale=%.4f,%.4f off=%.2f,%.2f "
                     "B0=%.0f,%.0f,%.0f,%.0f scratchAC=%.1f,%.1f,%.1f,%.1f\n",
            n0, sU0, sV0, c50, c54, c20, c24,
            rf(cam+0xB0), rf(cam+0xB4), rf(cam+0xB8), rf(cam+0xBC),
            rf(scratch+0x1B01AC), rf(scratch+0x1B01B0),
            rf(scratch+0x1B01B4), rf(scratch+0x1B01B8));
    }

    {
        DWORD tStart = GetTickCount();
        float maxDs = 0;
        int moved = 0;
        float cam50_0 = rf(cam+0x50), cam54_0 = rf(cam+0x54);
        float cam20_0 = rf(cam+0x20), cam24_0 = rf(cam+0x24);
        float cam50min=cam50_0, cam50max=cam50_0, cam20min=cam20_0, cam20max=cam20_0;
        int camScaleChg = 0, camOffChg = 0, camB0Chg = 0;
        float prevB0[4];
        prevB0[0]=rf(cam+0xB0); prevB0[1]=rf(cam+0xB4);
        prevB0[2]=rf(cam+0xB8); prevB0[3]=rf(cam+0xBC);

        while ((int)(GetTickCount() - tStart) < WATCH_MS) {
            float u = 0, v = 0, c50, c54, c20, c24;
            float b0[4];
            Ent tmp[MAX_ENT];
            float ds;
            collectEnts(tmp, MAX_ENT, &u, &v);
            c50 = rf(cam+0x50); c54 = rf(cam+0x54);
            c20 = rf(cam+0x20); c24 = rf(cam+0x24);
            if (c50 < cam50min) cam50min = c50;
            if (c50 > cam50max) cam50max = c50;
            if (c20 < cam20min) cam20min = c20;
            if (c20 > cam20max) cam20max = c20;
            b0[0]=rf(cam+0xB0); b0[1]=rf(cam+0xB4);
            b0[2]=rf(cam+0xB8); b0[3]=rf(cam+0xBC);
            if (b0[0]!=prevB0[0]||b0[1]!=prevB0[1]||b0[2]!=prevB0[2]||b0[3]!=prevB0[3])
                camB0Chg = 1;
            ds = fabsf(u - sU0) + fabsf(v - sV0);
            if (ds > maxDs) maxDs = ds;
            if (ds > 48.f) { moved = 1; break; }
            Sleep(POLL_MS);
        }

        {
            float c50 = rf(cam+0x50), c54 = rf(cam+0x54);
            float c20 = rf(cam+0x20), c24 = rf(cam+0x24);
            camScaleChg = (fabsf(c50 - cam50_0) > 1e-3f) ||
                          (fabsf(c54 - cam54_0) > 1e-3f) ||
                          (cam50max - cam50min > 1e-3f);
            camOffChg = (cam20max - cam20min > 0.5f) ||
                        (fabsf(c20 - cam20_0) > 0.5f) ||
                        (fabsf(c24 - cam24_0) > 0.5f);
            fprintf(out, "watch: maxSelfDelta=%.1f moved=%d\n", maxDs, moved);
            fprintf(out, "  cam scale range [%.4f..%.4f] changed=%d (t0=%.4f)\n",
                cam50min, cam50max, camScaleChg, cam50_0);
            fprintf(out, "  cam +20 range [%.2f..%.2f] offLive=%.2f,%.2f changed=%d\n",
                cam20min, cam20max, c20, c24, camOffChg);
            fprintf(out, "  cam +B0 changed=%d now=%.0f,%.0f,%.0f,%.0f\n",
                camB0Chg, rf(cam+0xB0), rf(cam+0xB4), rf(cam+0xB8), rf(cam+0xBC));
        }
    }

    n1 = collectEnts(snap1, MAX_ENT, &sU1, &sV1);
    fprintf(out, "t1: ents=%d self=%.1f,%.1f dSelf=%.1f,%.1f\n",
        n1, sU1, sV1, sU1 - sU0, sV1 - sV0);

    /* Gate: for matched MOB ents, compare relative screen predictions.
       Under walk, self-relative positions should be stable in WORLD; screen
       deltas = (u-self)*scale. Without pixel GT, gate on:
       (1) which scale keeps |screen| in viewport for nearby MOBs
       (2) cross-MOB spacing ratio vs iso spacing (scale-invariant check
           of which scale matches empirical tile→px from prior fit)
       (3) SELF always at center under both relative formulas — tautology
       Real gate: fitted ratio mean(|dIso|) / known — use pairs of MOBs:
         isoDist = hypot(du,dv); for each pair, screenDist_s = isoDist * s
       Compare s=0.5411 vs s=0.625 against SCRATCH-derived last screen span
       if available, OR against cam rect width.

       Stronger: if walked, Δself_iso * pps should equal opposite camera scroll
       in px. If cam+20/24 doesn't move, abs CAM formula can't absorb scroll —
       only relative formula works. Record that.
    */
    {
        float scaleCam = rf(cam + 0x50);
        float dSelfU = sU1 - sU0, dSelfV = sV1 - sV0;
        float dSelfIso = sqrtf(dSelfU * dSelfU + dSelfV * dSelfV);
        float predPxEmp = dSelfIso * PPS_EMP;
        float predPxCam = dSelfIso * scaleCam;
        int matched = 0, nearEmp = 0, nearCam = 0;
        float sumAbsEmp = 0, sumAbsCam = 0;
        int i0, i1;

        fprintf(out, "\n--- relative projection gate ---\n");
        fprintf(out, "  dSelfIso=%.1f  predPx@0.5411=%.1f  predPx@cam(%.4f)=%.1f\n",
            dSelfIso, predPxEmp, scaleCam, predPxCam);
        fprintf(out, "  (viewport half-diag ~800; walk pred should be tens-hundreds px)\n");

        /* Match ents by address; measure how screen-rel changes under each scale.
           True screen-rel for MOB should change little if only camera scrolled
           with world... Actually when player walks, MOB world-fixed → screen
           moves by -dSelf * scale. */
        for (i0 = 0; i0 < n0; i0++) {
            if (snap0[i0].vft == VFT_SELF) continue;
            for (i1 = 0; i1 < n1; i1++) {
                float r0e, r0c, r1e, r1c, dre, drc;
                if (snap1[i1].ent != snap0[i0].ent) continue;
                /* rel screen at t0 */
                r0e = hypotf((snap0[i0].u - sU0) * PPS_EMP,
                             (snap0[i0].v - sV0) * PPS_EMP);
                r0c = hypotf((snap0[i0].u - sU0) * scaleCam,
                             (snap0[i0].v - sV0) * scaleCam);
                r1e = hypotf((snap1[i1].u - sU1) * PPS_EMP,
                             (snap1[i1].v - sV1) * PPS_EMP);
                r1c = hypotf((snap1[i1].u - sU1) * scaleCam,
                             (snap1[i1].v - sV1) * scaleCam);
                /* If MOB world-fixed and only self moved: rel iso unchanged
                   → r0≈r1 for correct model. Drift |r1-r0| measures noise. */
                dre = fabsf(r1e - r0e);
                drc = fabsf(r1c - r0c);
                sumAbsEmp += dre;
                sumAbsCam += drc;
                matched++;
                if (dre < drc) nearEmp++;
                else if (drc < dre) nearCam++;
                if (matched <= 8) {
                    fprintf(out, "  MOB vft=%06X rEmp=%.1f->%.1f(d%.1f) rCam=%.1f->%.1f(d%.1f)\n",
                        snap0[i0].vft, r0e, r1e, dre, r0c, r1c, drc);
                }
                break;
            }
        }
        fprintf(out, "matched=%d  mean|dr| emp=%.2f cam=%.2f  closer: emp=%d cam=%d\n",
            matched,
            matched ? sumAbsEmp / matched : 0,
            matched ? sumAbsCam / matched : 0,
            nearEmp, nearCam);

        /* Viewport occupancy: fraction of MOBs with |rel| < 900 under each scale */
        {
            int inE = 0, inC = 0, nM = 0;
            for (i1 = 0; i1 < n1; i1++) {
                float re, rc;
                if (snap1[i1].vft == VFT_SELF) continue;
                re = hypotf((snap1[i1].u - sU1) * PPS_EMP,
                            (snap1[i1].v - sV1) * PPS_EMP);
                rc = hypotf((snap1[i1].u - sU1) * scaleCam,
                            (snap1[i1].v - sV1) * scaleCam);
                nM++;
                if (re < 900.f) inE++;
                if (rc < 900.f) inC++;
            }
            fprintf(out, "viewport occupancy (<900px): emp=%d/%d cam=%d/%d\n",
                inE, nM, inC, nM);
        }

        /* VERDICT */
        fprintf(out, "\n=== VERDICT ===\n");
        {
            int walked = (dSelfIso > 48.f);
            int camOffDead = (fabsf(rf(cam+0x20)) < 0.5f && fabsf(rf(cam+0x24)) < 0.5f);
            fprintf(out, "OWNER: see PART1 hits (CAM has B757*? B759*?)\n");
            if (walked && camOffDead) {
                fprintf(out, "SCALE: CAM+20/24 idle during walk → abs(CAM*PRES+off) FAIL for scroll.\n");
                fprintf(out, "SCALE: relative (PRES-self)*scale required.\n");
            }
            if (nearEmp > nearCam + matched / 10) {
                fprintf(out, "SCALE GATE: PASS emp 0.5411 (more stable rel-radius under walk)\n");
                fprintf(out, "SCALE GATE: FAIL cam 0.625 as overlay pps\n");
            } else if (nearCam > nearEmp + matched / 10) {
                fprintf(out, "SCALE GATE: PASS cam %.4f (more stable)\n", scaleCam);
                fprintf(out, "SCALE GATE: FAIL emp 0.5411\n");
            } else if (!walked) {
                fprintf(out, "SCALE GATE: INCONCLUSIVE — no walk (dSelfIso=%.1f). Re-run while walking.\n",
                    dSelfIso);
            } else {
                fprintf(out, "SCALE GATE: TIE/weak — emp closer=%d cam closer=%d matched=%d\n",
                    nearEmp, nearCam, matched);
                fprintf(out, "  Prefer emp 0.5411 (prior sprite fit); cam 0.625 is B757 matrix scale on different space.\n");
            }
        }
    }

    printf("wrote bridge_vft_owner_gate.txt\n");
    free(page); fclose(out); SignedClose();
    return 0;
}
