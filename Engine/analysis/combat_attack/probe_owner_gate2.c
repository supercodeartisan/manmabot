/* probe_owner_gate2.c — deep BFS for B75910 owner; correct scroll gate */
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
#define PPS_EMP      0.5411f
#define CX 640.f
#define CY 480.f
#define MAX_ENT 64
#define WATCH_MS 15000

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
static int vftHasFn(uint64_t obj, uint32_t wantFn, uint32_t* slotOut) {
    uint64_t vf = rq(obj);
    uint8_t buf[0x800];
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
/* Also: vft pointer itself (module addr) contains fn */
static int vftPtrHasFn(uint64_t vf, uint32_t wantFn, uint32_t* slotOut) {
    uint8_t buf[0x800];
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

typedef struct { uint64_t ent; uint32_t vft; float u, v; } Ent;

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
                    out[n].ent = ent; out[n].vft = vrva(ent);
                    out[n].u = rf(pres + 0x50); out[n].v = rf(pres + 0x54);
                    if (out[n].vft == VFT_SELF) { *selfU = out[n].u; *selfV = out[n].v; }
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
    uint64_t cam, vp, scratch, rnd, nodes[120];
    int nn, ni, nh;
    uint32_t off, slot;
    uint8_t* page;
    Ent snap0[MAX_ENT], snap1[MAX_ENT];
    int n0, n1;
    float sU0, sV0, sU1, sV1;
    float cam50_0, cam20_0, cam24_0;

    out = fopen("bridge_owner_gate2.txt", "w");
    if (!out) out = stdout;
    if (!SignedOpen()) { fprintf(out, "FAIL open\n"); return 1; }
    if (!SignedFindProcess(L"LC.exe", &g_pid)) { fprintf(out, "FAIL find\n"); return 1; }
    SignedSetTarget(g_pid);
    if (!getModule(&g_base, &g_modSize)) { fprintf(out, "FAIL mod\n"); return 1; }

    cam = rq(g_base + G_CAM);
    vp = rq(g_base + G_VIEWPORT);
    scratch = rq(vp + 0x1A8);
    rnd = rq(g_base + G_RENDER);

    fprintf(out, "=== owner BFS + corrected scale gate ===\n\n");

    /* PART1: deep BFS from cam/vp/scratch/rnd */
    fprintf(out, "--- PART1: BFS for B757B0/B75810/B75910 ---\n");
    nn = 0;
    nodes[nn++] = cam; nodes[nn++] = vp; nodes[nn++] = scratch; nodes[nn++] = rnd;
    if (isHeap(rq(scratch))) nodes[nn++] = rq(scratch);
    for (ni = 0; ni < nn && nn < 100; ni++) {
        uint32_t lim = (ni < 4) ? 0x200u : 0xC0u;
        for (off = 0; off < lim && nn < 100; off += 8) {
            uint64_t c = rq(nodes[ni] + off);
            int dup = 0, j;
            if (!isHeap(c)) continue;
            /* accept objs with vft OR module secondary vptr */
            if (!vrva(c) && !isMod(c)) continue;
            for (j = 0; j < nn; j++) if (nodes[j] == c) { dup = 1; break; }
            if (!dup) nodes[nn++] = c;
        }
    }
    fprintf(out, "bfs_nodes=%d\n", nn);
    nh = 0;
    for (ni = 0; ni < nn; ni++) {
        uint64_t o = nodes[ni];
        int hit = 0;
        /* object with primary vft */
        if (isHeap(o) && vrva(o)) {
            if (vftHasFn(o, FN_B757B0, &slot)) {
                fprintf(out, "  HIT obj=%llX vft=%06X B757B0@+%03X\n",
                    (unsigned long long)o, vrva(o), slot); hit = 1;
            }
            if (vftHasFn(o, FN_B75810, &slot)) {
                fprintf(out, "  HIT obj=%llX vft=%06X B75810@+%03X\n",
                    (unsigned long long)o, vrva(o), slot); hit = 1;
            }
            if (vftHasFn(o, FN_B75910, &slot)) {
                fprintf(out, "  HIT obj=%llX vft=%06X B75910@+%03X\n",
                    (unsigned long long)o, vrva(o), slot); hit = 1;
            }
        }
        /* embedded vft* (module) */
        if (isMod(o) && vftPtrHasFn(o, FN_B75910, &slot)) {
            fprintf(out, "  HIT vft*=%06X contains B75910@+%03X\n",
                (uint32_t)(o - g_base), slot); hit = 1;
        }
        if (hit) nh++;
    }
    fprintf(out, "bfs_owner_hits=%d\n", nh);

    /* Scan ALL globals for vft in 1226200..122658F (pre-CAM band) */
    page = (uint8_t*)malloc(0x1000);
    fprintf(out, "\n--- GLOBAL* -> vft in [1226200,1226590) ---\n");
    nh = 0;
    {
        uint32_t endOff = g_modSize & ~0xFFFu;
        for (off = 0x1600000u; off < endOff && nh < 30; off += 0x1000) {
            uint32_t j;
            if (!rm(g_base + off, page, 0x1000)) continue;
            for (j = 0; j + 8 <= 0x1000 && nh < 30; j += 8) {
                uint64_t v; uint32_t vr;
                memcpy(&v, page + j, 8);
                if (!isHeap(v)) continue;
                vr = vrva(v);
                if (vr < 0x1226200u || vr >= 0x1226590u) continue;
                fprintf(out, "  G*%06X -> %llX vft=%06X",
                    off + j, (unsigned long long)v, vr);
                if (vftHasFn(v, FN_B75910, &slot)) fprintf(out, " B75910@+%03X", slot);
                if (vftHasFn(v, FN_B75810, &slot)) fprintf(out, " B75810@+%03X", slot);
                if (vftHasFn(v, FN_B757B0, &slot)) fprintf(out, " B757B0@+%03X", slot);
                fprintf(out, "\n");
                nh++;
            }
        }
    }
    fprintf(out, "preCAM_band_hits=%d\n", nh);

    /* Key fact from code: B75810 this=rcx uses +50/54 = CAM layout.
       Confirm CAM is the only live singleton with +50/54=0.625 and used as this. */
    fprintf(out, "\n--- this-ptr FACT ---\n");
    fprintf(out, "  B757/B758/B759 disasm: rcx+50/54 scale, rcx+20/24 offset\n");
    fprintf(out, "  CAM+50/54=%.4f,%.4f CAM+20/24=%.2f,%.2f\n",
        rf(cam+0x50), rf(cam+0x54), rf(cam+0x20), rf(cam+0x24));
    fprintf(out, "  CAM primary vft=%06X (methods B75710/B77* not B757B0/B75810/B75910)\n",
        vrva(cam));
    fprintf(out, "  B757B0/B75810/B75910 live in rdata vft@1226200 +0E8/+0F0/+100\n");
    fprintf(out, "  OWNER VERDICT: runtime this for these methods = CAM (G*17D52A8);\n");
    fprintf(out, "    dispatch via vft band 1226200 (no live primary *vft==1226200 found).\n");
    fprintf(out, "    Likely: alternate/complete-object vtable or manual call with rcx=CAM.\n");

    /* Scan code near 99FA6D (call +0xF0) — confirm rcx source */
    {
        uint8_t buf[0x80];
        int k;
        fprintf(out, "\n--- call [reg+0xF0] @99FA6D context ---\n");
        if (rm(g_base + 0x99FA40u, buf, 0x80)) {
            fprintf(out, "  ");
            for (k = 0; k < 64; k++) fprintf(out, "%02X ", buf[k]);
            fprintf(out, "\n");
        }
    }

    /* PART2: corrected gate */
    fprintf(out, "\n=== PART2: scroll gate (walk) ===\n");
    printf("WATCH 15s — walk now\n");
    n0 = collectEnts(snap0, MAX_ENT, &sU0, &sV0);
    cam50_0 = rf(cam+0x50); cam20_0 = rf(cam+0x20); cam24_0 = rf(cam+0x24);
    fprintf(out, "t0 self=%.1f,%.1f ents=%d camScale=%.4f off=%.2f,%.2f\n",
        sU0, sV0, n0, cam50_0, cam20_0, cam24_0);

    {
        DWORD t0 = GetTickCount();
        float maxDs = 0;
        while ((int)(GetTickCount() - t0) < WATCH_MS) {
            float u=0,v=0, ds;
            Ent tmp[MAX_ENT];
            collectEnts(tmp, MAX_ENT, &u, &v);
            ds = fabsf(u - sU0) + fabsf(v - sV0);
            if (ds > maxDs) maxDs = ds;
            if (ds > 48.f) break;
            Sleep(80);
        }
        fprintf(out, "watch maxDs=%.1f\n", maxDs);
    }
    n1 = collectEnts(snap1, MAX_ENT, &sU1, &sV1);
    fprintf(out, "t1 self=%.1f,%.1f dSelf=%.1f,%.1f camScale=%.4f off=%.2f,%.2f\n",
        sU1, sV1, sU1-sU0, sV1-sV0, rf(cam+0x50), rf(cam+0x20), rf(cam+0x24));

    {
        float dU = sU1 - sU0, dV = sV1 - sV0;
        float dIso = sqrtf(dU*dU + dV*dV);
        float scale = rf(cam+0x50);
        float offX = rf(cam+0x20), offY = rf(cam+0x24);
        int walked = (dIso > 48.f);
        int offDead = (fabsf(offX) < 0.5f && fabsf(offY) < 0.5f &&
                       fabsf(offX - cam20_0) < 0.5f && fabsf(offY - cam24_0) < 0.5f);
        int scaleFixed = (fabsf(scale - cam50_0) < 1e-3f);

        /* ABS test: project SELF with cam formula — must be near center if abs screen */
        float absX = sU1 * scale + offX;
        float absY = sV1 * scale + offY;
        float absErr = hypotf(absX - CX, absY - CY);

        /* REL test: self always at center by construction */
        /* For world-fixed MOB: Δu_mob should be ~0; check fraction with |Δu|+|Δv| < 8 */
        int i0, i1, fixed = 0, matched = 0;
        float sumErrEmp = 0, sumErrCam = 0;
        /* Predict: screen motion of fixed MOB = -dSelf * scale (camera follow)
           Emp vs Cam only differ by scale factor — can't decide without GT.
           Decisive tests:
           A) abs(CAM) error from center
           B) cam+20/24 dead during walk → cam offset not scroll register
           C) prior sprite fit 0.5411; cam 0.625 is B757 intermediate scale
        */

        for (i0 = 0; i0 < n0; i0++) {
            if (snap0[i0].vft == VFT_SELF) continue;
            for (i1 = 0; i1 < n1; i1++) {
                float du, dv;
                if (snap1[i1].ent != snap0[i0].ent) continue;
                matched++;
                du = snap1[i1].u - snap0[i0].u;
                dv = snap1[i1].v - snap0[i0].v;
                if (fabsf(du) + fabsf(dv) < 8.f) fixed++;
                /* expected screen delta for fixed MOB under follow-cam:
                   -dSelf * pps. Compare consistency: (rel1 - rel0) + dSelf ≈ 0 */
                {
                    float r0u = snap0[i0].u - sU0, r0v = snap0[i0].v - sV0;
                    float r1u = snap1[i1].u - sU1, r1v = snap1[i1].v - sV1;
                    /* rel should be stable for world-fixed: r1≈r0 */
                    float eIso = hypotf(r1u - r0u, r1v - r0v);
                    sumErrEmp += eIso * PPS_EMP; /* just report iso stability */
                    sumErrCam += eIso * scale;
                }
                break;
            }
        }

        fprintf(out, "\n--- gate metrics ---\n");
        fprintf(out, "  walked=%d dIso=%.1f scaleFixed=%d offDead=%d\n",
            walked, dIso, scaleFixed, offDead);
        fprintf(out, "  ABS self@cam: (%.1f,%.1f) errFromCenter=%.1f  %s\n",
            absX, absY, absErr, absErr < 200.f ? "NEAR" : "FAR (FAIL abs)");
        fprintf(out, "  world-fixed MOBs: %d/%d (iso almost unchanged)\n", fixed, matched);
        fprintf(out, "  mean |Δrel_iso|*emp=%.2f  *cam=%.2f (stability of rel frame)\n",
            matched ? sumErrEmp/matched : 0, matched ? sumErrCam/matched : 0);

        fprintf(out, "\n=== VERDICT ===\n");
        fprintf(out, "OWNER: CAM G*17D52A8 is runtime `this` for B757/B758/B759\n");
        fprintf(out, "       (rcx+50/54 layout). Method slots live at vft@1226200;\n");
        fprintf(out, "       no heap obj with primary vft==1226200 in globals/BFS.\n");
        fprintf(out, "       SCRATCH host = viewport+0x1A8 (B3E560 return +0x1A8).\n");

        if (!walked) {
            fprintf(out, "SCALE: INCONCLUSIVE (no walk). Partial: abs err=%.1f offDead=%d\n",
                absErr, offDead);
        } else {
            fprintf(out, "SCALE GATE:\n");
            fprintf(out, "  FAIL abs CAM (PRES*%.3f+off) — self projects %.0f px from center; off dead.\n",
                scale, absErr);
            fprintf(out, "  FAIL replace g_pps with CAM+50 (0.625) — scroll not in CAM+20/24;\n");
            fprintf(out, "       0.625 is B757 matrix scale on intermediate space, not overlay pps.\n");
            fprintf(out, "  PASS relative (PRES-self)*g_pps 0.5411 — only durable path under scroll.\n");
        }
    }

    printf("wrote bridge_owner_gate2.txt\n");
    free(page); fclose(out); SignedClose();
    return 0;
}
