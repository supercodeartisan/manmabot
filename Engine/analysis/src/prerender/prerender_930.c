/* prerender_930.c — race which MyPlayer fields flip BEFORE AC+0xC0
 * ===========================================================================
 *  AC+0xC0 = late/logical Action*. Pre-render candidates (ranked):
 *    1) H+0x40 sprite / nested frame ints
 *    2) H+0x80 ActorInput (hash)
 *    3) CTL+0x58 cmd (intent)
 *    4) H+0x148 lineage::Frame refs
 *    5) Action+0x74 frame counter
 *
 *  8ms poll. On body (AC+0xC0) flip, dump last ~500ms ring.
 *  usage: prerender_930.exe [registry] [secs]
 *  out:   <exe>\out\prerender_out.txt
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <mmsystem.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"
#pragma comment(lib, "winmm.lib")

#define POLL_MS 8
#define RING_N 64
#define H_SPRITE_OFF 0x40u
#define H_INPUT_OFF 0x80u
#define H_FRAME_OFF 0x148u
#define ACT_FRAME_OFF 0x74u
#define AC_SCAN 0x140u
#define BLK_HASH 0xC0u

typedef struct {
    double t_ms;
    uint32_t body, cmd;
    uint32_t spr_vft, spr_hash, spr_i10, spr_i18; /* H+0x40 obj + nested ints */
    uint32_t inp_vft, inp_hash;
    uint32_t frm_vft, frm_hash; /* H+0x148 first Frame ref target */
    uint32_t act_frame;
    uint32_t ac_extra, ac_extra_off;
} Sample;

static Sample g_ring[RING_N];
static int g_ring_i, g_ring_n;

/* AB stats: on each body flip, how far ahead did spr/cmd/inp last change? */
static int g_n_body_flip;
static int g_spr_lead_n, g_cmd_lead_n, g_inp_lead_n;
static double g_spr_lead_sum, g_cmd_lead_sum, g_inp_lead_sum;
static double g_spr_lead_max, g_cmd_lead_max, g_inp_lead_max;

static uint32_t fnv1a(const uint8_t *p, uint32_t n)
{
    uint32_t h = 2166136261u;
    for (uint32_t i = 0; i < n; i++) {
        h ^= p[i];
        h *= 16777619u;
    }
    return h;
}

static int isActionVft(uint32_t v)
{
    if (!v) return 0;
    return v == LC_VFT_BREATHACT || v == LC_VFT_MOVINGACT || v == LC_VFT_MOVINGBACK ||
           v == LC_VFT_ATTACKACT || v == LC_VFT_ACTIONBASE || v == LC_VFT_SPELLACT ||
           v == LC_VFT_DAMAGEDACTION || v == LC_VFT_DAMAGEDREACTION ||
           v == LC_VFT_DEATH || v == LC_VFT_DEADBODY || v == LC_VFT_CHANGEDIR ||
           v == LC_VFT_EFFECTACTION;
}

/* Follow ptr at obj+off if heap; else treat obj+off as inline dword. */
static uint32_t nestedU32(uint64_t obj, uint32_t off)
{
    uint64_t p = q64(obj + off);
    if (isHeap(p))
        return d32(p);
    return d32(obj + off);
}

static int sampleOnce(Sample *S, double t_ms)
{
    memset(S, 0, sizeof *S);
    S->t_ms = t_ms;
    if (!lc_pollSelfBodyFast()) return 0;
    S->body = lc_selfBodyAct;
    S->cmd = lc_selfCmdVft;

    uint64_t e = lc_selfBodyE;
    uint64_t H = q64(e + LC_ENT_H_V);
    if (!isHeap(H)) return 1;

    /* (1) Sprite / UV atlas @ H+0x40 — top pre-render hypothesis */
    {
        uint64_t spr = q64(H + H_SPRITE_OFF);
        if (isHeap(spr)) {
            S->spr_vft = vrva(spr);
            uint8_t blk[BLK_HASH];
            if (rm(spr, blk, sizeof blk))
                S->spr_hash = fnv1a(blk, sizeof blk);
            S->spr_i10 = nestedU32(spr, 0x10);
            S->spr_i18 = nestedU32(spr, 0x18);
        }
    }

    /* (2) ActorInput @ H+0x80 */
    {
        uint64_t inp = q64(H + H_INPUT_OFF);
        if (isHeap(inp)) {
            S->inp_vft = vrva(inp);
            uint8_t blk[BLK_HASH];
            if (rm(inp, blk, sizeof blk))
                S->inp_hash = fnv1a(blk, sizeof blk);
        }
    }

    /* (4) lineage::Frame ref slot @ H+0x148 */
    {
        uint64_t fr = q64(H + H_FRAME_OFF);
        if (isHeap(fr)) {
            /* may be Ref_count wrapper: try +0x00 vft and +0x10 pointee */
            S->frm_vft = vrva(fr);
            uint64_t inner = q64(fr + 0x10);
            uint64_t tgt = isHeap(inner) ? inner : fr;
            uint8_t blk[BLK_HASH];
            if (rm(tgt, blk, sizeof blk))
                S->frm_hash = fnv1a(blk, sizeof blk);
        }
    }

    /* Action+0x74 frame counter */
    if (isHeap(lc_selfAc)) {
        uint64_t ap = q64(lc_selfAc + LC_AC_ACTION_OFF);
        if (isHeap(ap))
            S->act_frame = d32(ap + ACT_FRAME_OFF);
    }

    /* Other AC Action* slots */
    if (isHeap(lc_selfAc)) {
        uint8_t ab[AC_SCAN];
        if (rm(lc_selfAc, ab, sizeof ab)) {
            for (uint32_t o = 0; o + 8 <= AC_SCAN; o += 8) {
                if (o == LC_AC_ACTION_OFF) continue;
                uint64_t w = *(uint64_t *)(ab + o);
                if (!isHeap(w)) continue;
                uint32_t v = vrva(w);
                if (isActionVft(v)) {
                    S->ac_extra = v;
                    S->ac_extra_off = o;
                    break;
                }
            }
        }
    }
    return 1;
}

static int sampleEq(const Sample *a, const Sample *b)
{
    return a->body == b->body && a->cmd == b->cmd &&
           a->spr_vft == b->spr_vft && a->spr_hash == b->spr_hash &&
           a->spr_i10 == b->spr_i10 && a->spr_i18 == b->spr_i18 &&
           a->inp_vft == b->inp_vft && a->inp_hash == b->inp_hash &&
           a->frm_vft == b->frm_vft && a->frm_hash == b->frm_hash &&
           a->act_frame == b->act_frame &&
           a->ac_extra == b->ac_extra && a->ac_extra_off == b->ac_extra_off;
}

static void describeDelta(const Sample *p, const Sample *c, char *out, int n)
{
    out[0] = 0;
    int m = 0;
#define ADD(fmt, ...) do { \
        if (m < n - 1) m += snprintf(out + m, (size_t)(n - m), fmt, ##__VA_ARGS__); \
    } while (0)
    if (p->body != c->body)
        ADD(" body:%s->%s", lc_bodyOf(p->body), lc_bodyOf(c->body));
    if (p->cmd != c->cmd)
        ADD(" cmd:%s->%s", lc_cmdOf(p->cmd), lc_cmdOf(c->cmd));
    if (p->spr_hash != c->spr_hash || p->spr_i10 != c->spr_i10 || p->spr_i18 != c->spr_i18)
        ADD(" spr#:%08X i10=%u->%u i18=%u->%u",
            c->spr_hash, p->spr_i10, c->spr_i10, p->spr_i18, c->spr_i18);
    if (p->inp_hash != c->inp_hash)
        ADD(" inp#:%08X->%08X", p->inp_hash, c->inp_hash);
    if (p->frm_hash != c->frm_hash)
        ADD(" frm#:%08X->%08X", p->frm_hash, c->frm_hash);
    if (p->act_frame != c->act_frame)
        ADD(" aframe:%u->%u", p->act_frame, c->act_frame);
    if (p->ac_extra != c->ac_extra || p->ac_extra_off != c->ac_extra_off)
        ADD(" ac+0x%X:%s", c->ac_extra_off, lc_bodyOf(c->ac_extra));
#undef ADD
}

static void dumpRing(FILE *f, double now, const char *why)
{
    fprintf(f, "---- RING @ %.1fms (%s) last %d ----\n", now, why, g_ring_n);
    int start = (g_ring_i - g_ring_n + RING_N) % RING_N;
    for (int k = 0; k < g_ring_n; k++) {
        const Sample *S = &g_ring[(start + k) % RING_N];
        fprintf(f,
                "  %7.1f body=%-8s cmd=%-7s spr#=%08X i10=%u i18=%u "
                "inp#=%08X frm#=%08X afr=%u ac+0x%X=%s\n",
                S->t_ms, lc_bodyOf(S->body), lc_cmdOf(S->cmd),
                S->spr_hash, S->spr_i10, S->spr_i18,
                S->inp_hash, S->frm_hash, S->act_frame,
                S->ac_extra_off, lc_bodyOf(S->ac_extra));
    }
    fflush(f);
}

static void ringPush(const Sample *S)
{
    g_ring[g_ring_i] = *S;
    g_ring_i = (g_ring_i + 1) % RING_N;
    if (g_ring_n < RING_N) g_ring_n++;
}

/* Forward walk of ring (strictly before body flip): last channel edge times. */
static void scoreLeads(const Sample *bodyNow, FILE *f)
{
    g_n_body_flip++;
    double t0 = bodyNow->t_ms;
    double last_spr = -1, last_cmd = -1, last_inp = -1;
    uint32_t prev_spr = 0, prev_cmd = 0, prev_inp = 0;
    int have = 0;
    int start = (g_ring_i - g_ring_n + RING_N) % RING_N;
    for (int k = 0; k < g_ring_n; k++) {
        const Sample *S = &g_ring[(start + k) % RING_N];
        if (S->t_ms >= t0 - 0.05) break; /* exclude flip sample itself */
        if (!have) {
            prev_spr = S->spr_hash;
            prev_cmd = S->cmd;
            prev_inp = S->inp_hash;
            have = 1;
            continue;
        }
        if (S->spr_hash != prev_spr) {
            last_spr = S->t_ms;
            prev_spr = S->spr_hash;
        }
        if (S->cmd != prev_cmd) {
            last_cmd = S->t_ms;
            prev_cmd = S->cmd;
        }
        if (S->inp_hash != prev_inp) {
            last_inp = S->t_ms;
            prev_inp = S->inp_hash;
        }
    }
    double spr_t = last_spr >= 0 ? t0 - last_spr : -1.0;
    double cmd_t = last_cmd >= 0 ? t0 - last_cmd : -1.0;
    double inp_t = last_inp >= 0 ? t0 - last_inp : -1.0;
    fprintf(f, "  LEAD body@%.1f  spr=%.1fms  cmd=%.1fms  inp=%.1fms\n",
            t0, spr_t, cmd_t, inp_t);
    if (spr_t >= 0) {
        g_spr_lead_n++;
        g_spr_lead_sum += spr_t;
        if (spr_t > g_spr_lead_max) g_spr_lead_max = spr_t;
    }
    if (cmd_t >= 0) {
        g_cmd_lead_n++;
        g_cmd_lead_sum += cmd_t;
        if (cmd_t > g_cmd_lead_max) g_cmd_lead_max = cmd_t;
    }
    if (inp_t >= 0) {
        g_inp_lead_n++;
        g_inp_lead_sum += inp_t;
        if (inp_t > g_inp_lead_max) g_inp_lead_max = inp_t;
    }
}

static void writeSummary(FILE *f)
{
    fprintf(f, "\n==== AB SUMMARY (body flips=%d) ====\n", g_n_body_flip);
    fprintf(f, "  spr lead: n=%d  avg=%.1f  max=%.1f\n",
            g_spr_lead_n,
            g_spr_lead_n ? g_spr_lead_sum / g_spr_lead_n : 0.0,
            g_spr_lead_max);
    fprintf(f, "  cmd lead: n=%d  avg=%.1f  max=%.1f\n",
            g_cmd_lead_n,
            g_cmd_lead_n ? g_cmd_lead_sum / g_cmd_lead_n : 0.0,
            g_cmd_lead_max);
    fprintf(f, "  inp lead: n=%d  avg=%.1f  max=%.1f\n",
            g_inp_lead_n,
            g_inp_lead_n ? g_inp_lead_sum / g_inp_lead_n : 0.0,
            g_inp_lead_max);
    fprintf(f, "  interpret: large avg lead => channel updates before AC+0xC0\n");
    fprintf(f, "             n≈0 => channel not a precursor (or co-timed)\n");
    fflush(f);
    printf("\nAB SUMMARY body_flips=%d  spr_avg=%.0f  cmd_avg=%.0f  inp_avg=%.0f\n",
           g_n_body_flip,
           g_spr_lead_n ? g_spr_lead_sum / g_spr_lead_n : 0.0,
           g_cmd_lead_n ? g_cmd_lead_sum / g_cmd_lead_n : 0.0,
           g_inp_lead_n ? g_inp_lead_sum / g_inp_lead_n : 0.0);
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg = lcreg_resolve("10_5/registry/LC930_REGISTRY.txt",
                                    "registry/LC930_REGISTRY.txt");
    const char *outp = lcreg_outpath("prerender_out.txt");
    int secs = 60;
    for (int i = 1; i < argc; i++) {
        if (strstr(argv[i], "REGISTRY") || strstr(argv[i], ".txt")) {
            if (strstr(argv[i], "REGISTRY")) reg = argv[i];
            else if (strstr(argv[i], "prerender") || strstr(argv[i], "out"))
                outp = argv[i];
        } else if (atoi(argv[i]) > 0)
            secs = atoi(argv[i]);
    }
    lcreg_load_first(reg, "registry/LC930_REGISTRY.txt");
    lc_reg_apply();

    if (lc_attach()) return 1;
    if (!lc_anchor()) {
        fprintf(stderr, "anchor fail\n");
        return 2;
    }

    lcreg_mkdir_for(outp);
    FILE *f = fopen(outp, "w");
    if (!f) return 4;

    fprintf(f, "# prerender race vs AC+0xC0\n");
    fprintf(f, "# channels: body cmd spr(H+0x40) inp(H+0x80) frm(H+0x148) aframe ac_extra\n");
    fprintf(f, "# poll=%dms — walk / attack / pickup\n", POLL_MS);
    fflush(f);

    LARGE_INTEGER fr, q0, q;
    QueryPerformanceFrequency(&fr);
    QueryPerformanceCounter(&q0);

    Sample prev, cur;
    memset(&prev, 0, sizeof prev);
    timeBeginPeriod(1);
    printf("prerender: %ds -> %s\n", secs, outp);

    for (;;) {
        QueryPerformanceCounter(&q);
        double t_ms = (double)(q.QuadPart - q0.QuadPart) * 1000.0 / (double)fr.QuadPart;
        if (secs && t_ms >= (double)secs * 1000.0) break;

        g_ioctl = 0;
        if (!sampleOnce(&cur, t_ms)) {
            Sleep(POLL_MS);
            continue;
        }
        ringPush(&cur);

        if (!sampleEq(&prev, &cur)) {
            char delta[320];
            describeDelta(&prev, &cur, delta, (int)sizeof delta);
            fprintf(f, "[%.1f] CHG%s  io=%llu\n",
                    t_ms, delta, (unsigned long long)g_ioctl);
            printf("\r[%.0f] %-70s", t_ms, delta);
            fflush(stdout);
            if (prev.body != cur.body) {
                dumpRing(f, t_ms, "body-flip");
                scoreLeads(&cur, f);
            }
            fflush(f);
            prev = cur;
        }
        Sleep(POLL_MS);
    }

    timeEndPeriod(1);
    putchar('\n');
    dumpRing(f, 0, "final");
    writeSummary(f);
    fclose(f);
    SignedClose();
    printf("done -> %s\n", outp);
    return 0;
}
