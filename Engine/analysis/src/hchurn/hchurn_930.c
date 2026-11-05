/* hchurn_930.c — while body stays MovingAction, which H-chain dwords churn?
 * ===========================================================================
 *  AB found H+0x40 hash dead (n=0). Hunt anim-rate fields: poll 8ms during
 *  walk, count dword changes on H itself + first-level heap children
 *  (H+0x00..0x150 step 8 → obj → dump 0x00..0x100 as u32).
 *
 *  usage: hchurn_930.exe [registry] [secs]
 *  out:   <exe>\out\hchurn_out.txt
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
#define H_SLOTS 0x160u
#define CHILD_LEN 0x100u
#define MAX_KEYS 512

typedef struct {
    uint32_t h_off;   /* H+off → child */
    uint32_t c_off;   /* child+off dword */
    uint32_t changes;
    uint32_t last;
    int have;
} Key;

static Key g_keys[MAX_KEYS];
static int g_nk;

static Key *keyAt(uint32_t ho, uint32_t co)
{
    for (int i = 0; i < g_nk; i++)
        if (g_keys[i].h_off == ho && g_keys[i].c_off == co)
            return &g_keys[i];
    if (g_nk >= MAX_KEYS) return 0;
    Key *K = &g_keys[g_nk++];
    memset(K, 0, sizeof *K);
    K->h_off = ho;
    K->c_off = co;
    return K;
}

static int cmpKey(const void *a, const void *b)
{
    const Key *x = (const Key *)a, *y = (const Key *)b;
    if (y->changes != x->changes) return (int)y->changes - (int)x->changes;
    return 0;
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg = lcreg_resolve("10_5/registry/LC930_REGISTRY.txt",
                                    "registry/LC930_REGISTRY.txt");
    const char *outp = lcreg_outpath("hchurn_out.txt");
    int secs = 45;
    for (int i = 1; i < argc; i++) {
        if (strstr(argv[i], "REGISTRY")) reg = argv[i];
        else if (atoi(argv[i]) > 0) secs = atoi(argv[i]);
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

    fprintf(f, "# hchurn — dword change counts while body==walk\n");
    fprintf(f, "# walk continuously for best signal\n");
    fflush(f);

    LARGE_INTEGER fr, q0, q;
    QueryPerformanceFrequency(&fr);
    QueryPerformanceCounter(&q0);
    timeBeginPeriod(1);

    int walk_ticks = 0, other_ticks = 0;
    printf("hchurn %ds — keep walking\n", secs);

    for (;;) {
        QueryPerformanceCounter(&q);
        double t_ms = (double)(q.QuadPart - q0.QuadPart) * 1000.0 / (double)fr.QuadPart;
        if (t_ms >= (double)secs * 1000.0) break;

        if (!lc_pollSelfBodyFast()) {
            Sleep(POLL_MS);
            continue;
        }
        if (lc_selfBodyAct != LC_VFT_MOVINGACT && lc_selfBodyAct != LC_VFT_MOVINGBACK) {
            other_ticks++;
            Sleep(POLL_MS);
            continue;
        }
        walk_ticks++;

        uint64_t e = lc_selfBodyE;
        uint64_t holder = q64(e + LC_ENT_H_V);
        if (!isHeap(holder)) {
            Sleep(POLL_MS);
            continue;
        }

        for (uint32_t ho = 0; ho < H_SLOTS; ho += 8) {
            uint64_t child = q64(holder + ho);
            if (!isHeap(child)) continue;
            uint8_t blk[CHILD_LEN];
            if (!rm(child, blk, sizeof blk)) continue;
            for (uint32_t co = 0; co + 4 <= CHILD_LEN; co += 4) {
                uint32_t v = *(uint32_t *)(blk + co);
                Key *K = keyAt(ho, co);
                if (!K) continue;
                if (!K->have) {
                    K->last = v;
                    K->have = 1;
                } else if (K->last != v) {
                    K->changes++;
                    K->last = v;
                }
            }
        }
        if ((walk_ticks % 60) == 0)
            printf("\r walk_ticks=%d keys=%d", walk_ticks, g_nk);
        Sleep(POLL_MS);
    }

    timeEndPeriod(1);
    putchar('\n');
    qsort(g_keys, (size_t)g_nk, sizeof(Key), cmpKey);

    fprintf(f, "walk_ticks=%d other_ticks=%d keys=%d\n", walk_ticks, other_ticks, g_nk);
    fprintf(f, "# top churn (H+off child+off changes)\n");
    int shown = 0;
    for (int i = 0; i < g_nk && shown < 40; i++) {
        if (g_keys[i].changes < 3) continue;
        /* skip pure pointers that always look like heap (high bits) — keep all for now */
        fprintf(f, "H+0x%02X +0x%02X  changes=%u  last=0x%08X\n",
                g_keys[i].h_off, g_keys[i].c_off,
                g_keys[i].changes, g_keys[i].last);
        shown++;
    }
    fflush(f);
    fclose(f);
    SignedClose();
    printf("done -> %s  (top %d)\n", outp, shown);
    return 0;
}
