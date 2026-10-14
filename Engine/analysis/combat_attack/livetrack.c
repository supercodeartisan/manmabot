/* livetrack.c - real-time acquisition daemon for the combined dataset.
 *
 * Follows 9.23\live_tracking\enttrack.c: 2-speed loop
 *   - slow sweep  (default 1000 ms, +-200 ms jitter) : cellmap walk, ledger cache
 *   - fast poll   (default  50 ms, +-10  ms jitter)  : 1 batched IOCTL per entity
 *   - idle slowdown: 250 ms when self has not moved
 * and the A/B pipeline: PRES_B +0x50 (A, committed) -> +0x78 (B, target),
 * commit step 516 ms -> iso_i = A + (B-A) * clamp(dt/516, 0, 1)
 *
 * Emits one JSON record per frame to stdout, and one event record per event.
 * Joined on GUID + world cell + tick, so a single stream carries all four legs:
 *   entity track | attack events | map rect (static join) | item ownership events
 *
 * usage: livetrack.exe [fast_ms=50] [slow_ms=1000] [count=0] [out.jsonl] [root=.]
 */
#define _CRT_SECURE_NO_WARNINGS
#include <stdarg.h>
#include "lcore.h"

static FILE *g_out = NULL;

static void emit(const char *fmt, ...)
{
    va_list ap; va_start(ap, fmt);
    int n = vsnprintf(NULL, 0, fmt, ap);
    va_end(ap);
    if (n < 0) return;
    char *buf = (char *)malloc((size_t)n + 1);
    if (!buf) return;
    va_start(ap, fmt); vsnprintf(buf, (size_t)n + 1, fmt, ap); va_end(ap);
    fputs(buf, stdout);
    if (g_out) { fputs(buf, g_out); fflush(g_out); }
    free(buf);
}

static unsigned long long g_nFrame, g_nEv, g_nAtkMe, g_nMapCh;
static DWORD g_t0;

/* copy s as a quoted JSON string (truncating) */
static char *jq(const char *s)
{
    static char ring[4][96];
    static int  rr = 0;
    char *o = ring[rr = (rr + 1) & 3];
    size_t n = 0;
    o[n++] = '"';
    if (s) for (const unsigned char *p = (const unsigned char *)s; *p && n < 80; p++) {
        if (*p == '"' || *p == '\\') { o[n++] = '\\'; o[n++] = (char)*p; }
        else if (*p < 0x20)           n += (size_t)snprintf(o + n, 90 - n, "\\u%04X", *p);
        else                          o[n++] = (char)*p;
    }
    o[n++] = '"'; o[n] = 0;
    return o;
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lc_dbg = (getenv("LIVETRACK_DBG") != 0);

    int fastMs = argc > 1 ? atoi(argv[1]) : 50;  if (fastMs  < 20) fastMs  = 50;
    int slowMs = argc > 2 ? atoi(argv[2]) : 1000; if (slowMs < 200) slowMs = 1000;
    int count  = argc > 3 ? atoi(argv[3]) : 0;
    const char *outPath = argc > 4 ? argv[4] : NULL;
    const char *root    = argc > 5 ? argv[5] : ".";

    if (lc_attach()) return 1;
    if (!lc_anchor()) { fprintf(stderr, "anchor fail (ActorSubsystem not found by vft 0x117EAD8)\n"); return 2; }

    lc_loadAssets(root);
    if (!gA.nmap) fprintf(stderr, "[warn] dossier.tsv not found under %s/T3_maps\n", root);

    HWND gwnd = lc_findGameWnd((DWORD)g_pid);
    int vw = 800, vh = 600;
    if (gwnd) { RECT r; GetClientRect(gwnd, &r); vw = r.right; vh = r.bottom; }
    LC_VIEW view; lc_viewCalc(&view, vw, vh);

    if (outPath && strcmp(outPath, "-") != 0) {
        g_out = fopen(outPath, "w");
        if (!g_out) { fprintf(stderr, "cannot write %s\n", outPath); return 3; }
    }

    /* initial sweep so the ledger is warm before the first frame */
    static uint64_t ptrs[LC_MAXE];
    int nptr = lc_sweepSlow(ptrs, LC_MAXE);
    lc_pollFast(ptrs, nptr, GetTickCount());
    lc_pick_self();
    if (!lc_meGuid) { fprintf(stderr, "no player found (log in first)\n"); return 4; }

    fprintf(stderr, "[livetrack] pid=%llu BASE=0x%llX actor=0x%llX me=0x%llX\n",
            (unsigned long long)g_pid, (unsigned long long)g_base,
            (unsigned long long)lc_actor, (unsigned long long)lc_meGuid);
    fprintf(stderr, "[livetrack] fast=%dms slow=%dms  step=%.0fms  pps=%.3f vpx=%.1f vpy=%.1f  view %dx%d\n",
            fastMs, slowMs, LC_STEP_MS, LC_PPS, LC_VP_DX, LC_VP_DY, vw, vh);
    fprintf(stderr, "[livetrack] assets: %d maps, %d dungeon entrances, %d exits, %d gate tiles\n",
            gA.nmap, gA.nentr, gA.nexit, gA.ngate);

    g_t0 = GetTickCount();
    static int pRect[4] = { 0, 0, 0, 0 };
    DWORD lastSlow = GetTickCount(), ioLast = g_t0, lastMoved = g_t0;
    unsigned long long ioLastCount = g_ioctl;
    float lastSelfU = 0, lastSelfV = 0; int haveLastSelf = 0;
    srand((unsigned)GetTickCount());

    for (;;) {
        DWORD now = GetTickCount();

        /* --- slow sweep with jitter --- */
        if (now - lastSlow >= (DWORD)(slowMs + (rand() % 400 - 200))) {
            nptr = lc_sweepSlow(ptrs, LC_MAXE);
            lastSlow = now;
        }
        /* --- fast poll --- */
        memcpy(lc_prev, lc_cur, sizeof(LC_E) * lc_nc);
        lc_npc = lc_nc;
        lc_pollFast(ptrs, nptr, now);
        lc_pick_self();

        LC_E *me = lc_findMe();
        int spx = me ? me->cellx : -1, spy = me ? me->celly : -1;

        /* idle detection on the interpolated self iso (enttrack rule) */
        if (me) {
            if (!haveLastSelf) { lastSelfU = me->iU; lastSelfV = me->iV; haveLastSelf = 1; }
            else if (me->iU != lastSelfU || me->iV != lastSelfV) {
                lastSelfU = me->iU; lastSelfV = me->iV; lastMoved = now;
            }
        }

        lc_readMapRect(spx, spy);
        const LC_MAP *cmap = lc_mapValid ? lc_mapByRect(lc_mx0, lc_my0, lc_mx1, lc_my1)
                                          : lc_mapAt(spx, spy);

        /* --- MAP_CHANGE --- */
        if (lc_mapValid) {
            if ((pRect[0] || pRect[1]) &&
                (pRect[0] != lc_mx0 || pRect[1] != lc_my0 ||
                 pRect[2] != lc_mx1 || pRect[3] != lc_my1)) {
                const LC_MAP *a = lc_mapByRect(pRect[0], pRect[1], pRect[2], pRect[3]);
                emit("{\"t\":%u,\"ev\":\"MAP_CHANGE\",\"from\":[%d,%d,%d,%d],\"to\":[%d,%d,%d,%d],"
                     "\"fromName\":%s,\"toName\":%s,\"selfCell\":[%d,%d]}\n",
                     now, pRect[0], pRect[1], pRect[2], pRect[3], lc_mx0, lc_my0, lc_mx1, lc_my1,
                     jq(a ? a->name : "?"), jq(cmap ? cmap->name : "?"), spx, spy);
                g_nEv++; g_nMapCh++;
            }
            pRect[0] = lc_mx0; pRect[1] = lc_my0; pRect[2] = lc_mx1; pRect[3] = lc_my1;
        }

        /* --- entity events --- */
        for (int i = 0; i < lc_nc; i++) {
            LC_E *X = &lc_cur[i], *P = lc_findPrev(X->guid);
            if (!P) {
                if (X->vft == VFT_ITEM)
                    emit("{\"t\":%u,\"ev\":\"ITEM_DROP\",\"guid\":\"0x%llX\",\"type\":%u,\"qty\":%u,\"cell\":[%d,%d],\"name\":%s}\n",
                         now, (unsigned long long)X->guid, X->itemType, X->itemQty,
                         X->cellx, X->celly, jq(X->nm));
                g_nEv++;
                continue;
            }
            if (X->hasAtk && !P->hasAtk) {
                emit("{\"t\":%u,\"ev\":\"ATTACK_START\",\"from\":\"0x%llX\",\"fromName\":%s,"
                     "\"to\":\"0x%llX\",\"toName\":%s,\"toIsMe\":%d,\"cell\":[%d,%d]}\n",
                     now, (unsigned long long)X->guid, jq(X->nm),
                     (unsigned long long)X->atkTgt, jq(lc_nameOfGuid(X->atkTgt)),
                     X->atkTgt == lc_meGuid ? 1 : 0, X->cellx, X->celly);
                if (X->atkTgt == lc_meGuid) g_nAtkMe++;
                g_nEv++;
            } else if (X->hasAtk && P->hasAtk && X->atkTgt != P->atkTgt) {
                emit("{\"t\":%u,\"ev\":\"TARGET_SWITCH\",\"from\":\"0x%llX\",\"fromName\":%s,"
                     "\"old\":\"0x%llX\",\"new\":\"0x%llX\",\"newName\":%s,\"toIsMe\":%d}\n",
                     now, (unsigned long long)X->guid, jq(X->nm),
                     (unsigned long long)P->atkTgt, (unsigned long long)X->atkTgt,
                     jq(lc_nameOfGuid(X->atkTgt)), X->atkTgt == lc_meGuid ? 1 : 0);
                g_nEv++;
            } else if (!X->hasAtk && P->hasAtk) {
                emit("{\"t\":%u,\"ev\":\"ATTACK_END\",\"from\":\"0x%llX\",\"fromName\":%s,\"to\":\"0x%llX\"}\n",
                     now, (unsigned long long)X->guid, jq(X->nm), (unsigned long long)P->atkTgt);
                g_nEv++;
            }
            if (X->dead && !P->dead) {
                emit("{\"t\":%u,\"ev\":\"DEATH\",\"guid\":\"0x%llX\",\"name\":%s,\"cls\":\"%s\","
                     "\"cell\":[%d,%d],\"at\":[%d,%d]}\n",
                     now, (unsigned long long)X->guid, jq(X->nm), clsOf(X->vft),
                     X->cellx, X->celly, spx, spy);
                g_nEv++;
            }
        }
        for (int i = 0; i < lc_npc; i++) {
            if (!lc_findCur(lc_prev[i].guid) && lc_prev[i].vft == VFT_ITEM) {
                emit("{\"t\":%u,\"ev\":\"ITEM_PICKED\",\"guid\":\"0x%llX\",\"type\":%u,\"qty\":%u,"
                     "\"cell\":[%d,%d],\"name\":%s}\n",
                     now, (unsigned long long)lc_prev[i].guid, lc_prev[i].itemType,
                     lc_prev[i].itemQty, lc_prev[i].cellx, lc_prev[i].celly,
                     jq(lc_prev[i].nm));
                g_nEv++;
            }
        }

        /* --- frame --- */
        LC_E *selfE = me;
        if (!selfE) { lc_selfIsoFromTile(spx, spy, &lastSelfU, &lastSelfV); }
        float su = selfE ? selfE->iU : lastSelfU;
        float sv = selfE ? selfE->iV : lastSelfV;

        char *b = (char *)malloc(1 << 20);
        int  p = 0, cap = 1 << 20;
        p += snprintf(b + p, cap - p,
                      "{\"t\":%u,\"self\":\"0x%llX\",\"n\":%d,\"sweep\":%d",
                      now, (unsigned long long)lc_meGuid, lc_nc, (int)lc_sweepCount);
        if (lc_mapValid)
            p += snprintf(b + p, cap - p, ",\"mapRect\":[%d,%d,%d,%d]", lc_mx0, lc_my0, lc_mx1, lc_my1);
        if (cmap) {
            p += snprintf(b + p, cap - p, ",\"mapId\":%d,\"mapName\":\"", cmap->id);
            int kl = (int)strlen(cmap->name); if (kl > 60) kl = 60;
            memcpy(b + p, cmap->name, kl); p += kl;
            b[p++] = '"';
        }
        p += snprintf(b + p, cap - p, ",\"view\":{\"pps\":%.3f,\"vpDx\":%.1f,\"vpDy\":%.1f,\"w\":%d,\"h\":%d}",
                      LC_PPS, LC_VP_DX, LC_VP_DY, vw, vh);
        p += snprintf(b + p, cap - p, ",\"ents\":[");
        for (int i = 0; i < lc_nc; i++) {
            LC_E *X = &lc_cur[i];
            p += snprintf(b + p, cap - p,
                          "%s{\"guid\":\"0x%llX\",\"cls\":\"%s\",\"name\":%s,\"cell\":[%d,%d]",
                          i ? "," : "", (unsigned long long)X->guid, clsOf(X->vft),
                          jq(X->nm), X->cellx, X->celly);
            if (X->hasIso) {
                p += snprintf(b + p, cap - p, ",\"iso\":[%.1f,%.1f],\"iiso\":[%.1f,%.1f],\"ab\":[%.1f,%.1f,%.1f,%.1f]",
                              X->aU, X->aV, X->iU, X->iV, X->aU, X->aV, X->bU, X->bV);
                LC_E se; memset(&se, 0, sizeof(se));
                se.iU = su; se.iV = sv;
                int rx, ry;
                lc_project(X, &se, &view, &rx, &ry);
                p += snprintf(b + p, cap - p, ",\"scr\":[%d,%d]", rx, ry);
            }
            p += snprintf(b + p, cap - p, ",\"alive\":%d", X->dead ? 0 : 1);
            if (cmap) {
                int bl = lc_blockedAt(cmap, X->cellx, X->celly);
                if (bl >= 0) p += snprintf(b + p, cap - p, ",\"walkable\":%d", 1 - bl);
            }
            if (X->vft == VFT_ITEM)
                p += snprintf(b + p, cap - p, ",\"item\":{\"type\":%u,\"qty\":%u}", X->itemType, X->itemQty);
            if (X->hasAtk)
                p += snprintf(b + p, cap - p,
                              ",\"atk\":{\"owner\":\"0x%llX\",\"tgt\":\"0x%llX\",\"targetsMe\":%d}",
                              (unsigned long long)X->atkOwner, (unsigned long long)X->atkTgt,
                              X->atkTgt == lc_meGuid ? 1 : 0);
            p += snprintf(b + p, cap - p, "}");
        }
        p += snprintf(b + p, cap - p, "],\"ioctl\":%llu}\n", g_ioctl);
        fputs(b, stdout); fflush(stdout);
        if (g_out) { fputs(b, g_out); fflush(g_out); }
        free(b);

        g_nFrame++;
        if (count > 0 && g_nFrame >= (unsigned long long)count) break;

        /* IOCTL/s report every 2 s */
        if (now - ioLast >= 2000) {
            double dt = (now - ioLast) / 1000.0;
            int idle = (now - lastMoved) > (DWORD)(slowMs * 2);
            fprintf(stderr, "[io] %7llu IOCTL in %.2fs => %5.0f/sec  ents=%d  %s\n",
                    g_ioctl - ioLastCount, dt, (g_ioctl - ioLastCount) / dt, lc_nc,
                    idle ? "IDLE" : "ACTIVE");
            ioLast = now; ioLastCount = g_ioctl;
        }
        /* idle slowdown, plus jitter */
        int base = ((now - lastMoved) > (DWORD)(slowMs * 2)) ? 250 : fastMs;
        int d = base + ((rand() % 21) - 10); if (d < 10) d = 10;
        Sleep((DWORD)d);
    }

    double sec = (GetTickCount() - g_t0) / 1000.0; if (sec < 0.001) sec = 0.001;
    fprintf(stderr, "[io] TOTAL %llu IOCTL / %.2fs => %.0f/sec  frames=%llu events=%llu "
                    "attacksOnMe=%llu mapChanges=%llu\n",
            g_ioctl, sec, g_ioctl / sec, g_nFrame, g_nEv, g_nAtkMe, g_nMapCh);
    if (g_out) fclose(g_out);
    SignedClose();
    return 0;
}


