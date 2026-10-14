/* liveworld.c - live result tester for the combined dataset (liveview/etview analogue).
 *
 * Drawing + coordinates follow 9.23\live_tracking\etview.c:
 *   - the game window is BitBlt-captured into a top-down 32 bpp DIB
 *   - entity markers are drawn with pixel primitives (px / circ / cross) straight
 *     into the DIB, names via GDI TextOutW on the same memory DC
 *   - marker position = etview projection of the *interpolated* iso
 *     (PRES_B +0x50 A -> +0x78 B, commit 516 ms) relative to self:
 *         sc  = clientH / 600
 *         sx0 = clientW/2 + VP_DX*sc        sy0 = clientH/2 - VP_DY*sc
 *         rx  = sx0 + (iU_E - iU_self) * PPS*sc
 *         ry  = sy0 - (iV_E - iV_self) * PPS*sc
 *
 * Entity tracking follows 9.23\live_tracking\enttrack.c: 2-speed loop on a
 * worker thread (slow cellmap sweep + ledger cache, fast batched poll) with a
 * snapshot swapped under a critical section, so the UI never blocks on IOCTLs.
 *
 * Added on top of the reference (the four-way join):
 *   - map rect from MapSubsystem, exact dossier match, shown in the side panel
 *   - dungeon entrance list (static) with live distance from self
 *   - attack lines  owner -> target  (red = targeting me)
 *   - item entities highlighted, ITEM_DROP / ITEM_PICKED in the event log
 *   - mode M: swap the left area to the static terrain grid (1px = 1 tile) with
 *     the same markers in world-cell space
 *
 * usage: liveworld.exe [ui_ms=40] [root=.] [--selftest] [--out=FILE]
 *   1/2 VP_DY  3/4 VP_DX  5/6 PPS   L labels  A attack  M map/overlay
 *   N entrance labels  P snapshot json  Q quit
 */
#define _CRT_SECURE_NO_WARNINGS
#include <stdarg.h>
#include "lcore.h"

/* 鈹€鈹€ window / view state 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static HWND   g_hwnd, g_gwnd;
static int    g_W = 800, g_H = 600, g_PANEL = 340;
static int    g_modeOverlay = 1;          /* 1 = game capture, 0 = terrain map */
static int    g_showLabels = 1, g_showAtk = 1, g_showEntr = 1;
static HFONT  g_font, g_fontB;
static DWORD  g_t0, g_lastSlow = 0, g_seqSeen = 0;
static int    g_fastMs = 50, g_slowMs = 1000;
static unsigned long long g_ioAtT0 = 0;
static double g_fps = 0;
static unsigned g_frames = 0, g_fpsTick = 0;

/* snapshot consumed by the UI thread */
static LC_E   s_ents[LC_MAXE]; static int s_n;
static uint64_t s_me;
static int s_rectOK, s_rx0, s_ry0, s_rx1, s_ry1;
static int s_mapId = -1; static char s_mapName[64];
static uint64_t s_selfE;

/* 鈹€鈹€ terrain layer (mode M) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static HBITMAP  g_terBmp; static HDC g_terDC;
static uint32_t *g_terPx; static int g_terMid = -1, g_terTx, g_terTy;
static int g_mapCamX, g_mapCamY; static double g_mapZoom = 4.0;

/* 鈹€鈹€ event log 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
#define LOGMAX 256
typedef struct { DWORD t; char s[180]; } LOGE;
static LOGE g_log[LOGMAX]; static int g_logN = 0;
static unsigned long long g_nAtkMe = 0, g_nMapCh = 0, g_nPick = 0, g_nDrop = 0;

static void addLog(const char *fmt, ...)
{
    char b[180];
    va_list ap; va_start(ap, fmt);
    vsnprintf(b, sizeof(b), fmt, ap);
    va_end(ap);
    g_log[g_logN % LOGMAX].t = GetTickCount();
    snprintf(g_log[g_logN % LOGMAX].s, 180, "%s", b);
    g_logN++;
}

/* 鈹€鈹€ worker thread: enttrack 2-speed loop 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static volatile int g_run = 1;
static CRITICAL_SECTION g_snapCS;
static int g_snapInit = 0;

static DWORD WINAPI pollThread(LPVOID p)
{
    (void)p;
    static uint64_t ptrs[LC_MAXE];
    int nptr = lc_sweepSlow(ptrs, LC_MAXE);
    DWORD lastSlow = GetTickCount();
    int pRect[4] = { 0, 0, 0, 0 };
    lc_csInit();

    while (g_run) {
        DWORD now = GetTickCount();
        if (now - lastSlow >= (DWORD)(g_slowMs + (rand() % 400 - 200))) {
            nptr = lc_sweepSlow(ptrs, LC_MAXE);
            lastSlow = now;
        }
        memcpy(lc_prev, lc_cur, sizeof(LC_E) * lc_nc);
        lc_npc = lc_nc;
        lc_pollFast(ptrs, nptr, now);
        lc_pick_self();

        LC_E *me = lc_findMe();
        int spx = me ? me->cellx : -1, spy = me ? me->celly : -1;
        lc_readMapRect(spx, spy);
        const LC_MAP *cmap = lc_mapValid ? lc_mapByRect(lc_mx0, lc_my0, lc_mx1, lc_my1)
                                          : lc_mapAt(spx, spy);

        /* ---- events ---- */
        if (lc_mapValid) {
            if ((pRect[0] || pRect[1]) &&
                (pRect[0] != lc_mx0 || pRect[1] != lc_my0 ||
                 pRect[2] != lc_mx1 || pRect[3] != lc_my1)) {
                const LC_MAP *a = lc_mapByRect(pRect[0], pRect[1], pRect[2], pRect[3]);
                lc_pushEv("MAP_CHANGE", 0, 0, pRect[0], pRect[1], pRect[2], pRect[3],
                          a ? a->name : "?", cmap ? cmap->name : "?");
                g_nMapCh++;
            }
            pRect[0] = lc_mx0; pRect[1] = lc_my0; pRect[2] = lc_mx1; pRect[3] = lc_my1;
        }
        for (int i = 0; i < lc_nc; i++) {
            LC_E *X = &lc_cur[i], *P = lc_findPrev(X->guid);
            if (!P) {
                if (X->vft == VFT_ITEM) {
                    char ob[32];
                    snprintf(ob, sizeof(ob), "0x%llX", (unsigned long long)X->itemOwner);
                    lc_pushEv("ITEM_DROP", X->guid, X->itemOwner, (int)X->itemType, (int)X->itemQty,
                              X->cellx, X->celly, X->nm, X->itemOwner ? ob : "(free)");
                    g_nDrop++;
                }
                continue;
            }
            if (X->hasAtk && !P->hasAtk) {
                int meT = (X->atkTgt == lc_meGuid);
                lc_pushEv("ATTACK", X->guid, X->atkTgt, meT, X->cellx, X->celly, 0,
                          X->nm, lc_nameOfGuid(X->atkTgt));
                if (meT) g_nAtkMe++;
            } else if (X->hasAtk && P->hasAtk && X->atkTgt != P->atkTgt) {
                lc_pushEv("RETARGET", X->guid, X->atkTgt, 0, 0, 0, 0,
                          X->nm, lc_nameOfGuid(X->atkTgt));
            } else if (!X->hasAtk && P->hasAtk) {
                lc_pushEv("ATTACK_END", X->guid, P->atkTgt, 0, 0, 0, 0, X->nm, "");
            }
            if (X->dead && !P->dead)
                lc_pushEv("DEATH", X->guid, 0, X->cellx, X->celly, 0, 0, X->nm, clsOf(X->vft));
        }
        for (int i = 0; i < lc_npc; i++)
            if (!lc_findCur(lc_prev[i].guid) && lc_prev[i].vft == VFT_ITEM) {
                lc_pushEv("ITEM_PICKED", lc_prev[i].guid, 0, (int)lc_prev[i].itemType,
                          (int)lc_prev[i].itemQty, lc_prev[i].cellx, lc_prev[i].celly,
                          lc_prev[i].nm, "");
                g_nPick++;
            }

        /* ---- publish snapshot ---- */
        EnterCriticalSection(&g_snapCS);
        memcpy(s_ents, lc_cur, sizeof(LC_E) * lc_nc);
        s_n = lc_nc;
        s_me = lc_meGuid;
        s_selfE = lc_meE;
        s_rectOK = lc_mapValid;
        s_rx0 = lc_mx0; s_ry0 = lc_my0; s_rx1 = lc_mx1; s_ry1 = lc_my1;
        s_mapId = cmap ? cmap->id : -1;
        if (cmap) snprintf(s_mapName, sizeof(s_mapName), "%s", cmap->name);
        else      s_mapName[0] = 0;
        LeaveCriticalSection(&g_snapCS);

        Sleep((DWORD)g_fastMs);
    }
    return 0;
}

/* 鈹€鈹€ render target: top-down 32 bpp DIB (etview convention) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static BYTE *g_bits = 0; static int g_stride = 0, g_bw = 0, g_bh = 0;
static HDC g_memDC = 0; static HBITMAP g_hbm = 0; static HGDIOBJ g_oldBm = 0;
static int g_viewW = 0, g_viewH = 0;        /* size of the left (game) area */

static void recreate(int w, int h)
{
    if (w < 2 || h < 2) return;
    if (g_memDC) { SelectObject(g_memDC, g_oldBm); DeleteObject(g_hbm); DeleteDC(g_memDC); g_memDC = 0; }
    if (!g_font) {
        g_font = CreateFontA(13, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET,
                             OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                             DEFAULT_PITCH, "Malgun Gothic");
        g_fontB = CreateFontA(14, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET,
                              OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                              DEFAULT_PITCH, "Malgun Gothic");
    }
    HDC s = GetDC(NULL);
    g_memDC = CreateCompatibleDC(s);
    BITMAPINFO bi; memset(&bi, 0, sizeof(bi));
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = w; bi.bmiHeader.biHeight = -h;
    bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
    void *pv = 0;
    g_hbm = CreateDIBSection(s, &bi, DIB_RGB_COLORS, &pv, 0, 0);
    g_bits = (BYTE *)pv;
    g_oldBm = SelectObject(g_memDC, g_hbm);
    SelectObject(g_memDC, g_font);
    ReleaseDC(NULL, s);
    g_stride = w * 4; g_bw = w; g_bh = h;
    g_viewW = w; g_viewH = h;
}

/* pixel primitives (etview) */
static void px(int x, int y, int r, int g, int b, int a)
{
    if (x < 0 || y < 0 || x >= g_bw || y >= g_bh) return;
    BYTE *p = g_bits + (size_t)y * g_stride + x * 4;
    p[0] = (BYTE)b; p[1] = (BYTE)g; p[2] = (BYTE)r; p[3] = (BYTE)a;
}
static void argbFill(int a, int r, int g, int b)
{
    for (int y = 0; y < g_bh; y++) {
        BYTE *row = g_bits + (size_t)y * g_stride;
        for (int x = 0; x < g_bw; x++) { row[x*4] = (BYTE)b; row[x*4+1] = (BYTE)g; row[x*4+2] = (BYTE)r; row[x*4+3] = (BYTE)a; }
    }
}
static void circ(int cx, int cy, int rad, int r, int g, int b, int filled)
{
    for (int y = -rad; y <= rad; y++) for (int x = -rad; x <= rad; x++) {
        int d = x * x + y * y;
        if (filled ? (d <= rad * rad) : (d <= rad * rad && d >= (rad - 1) * (rad - 1)))
            px(cx + x, cy + y, r, g, b, 255);
    }
}
static void cross(int cx, int cy, int len, int r, int g, int b)
{
    for (int k = 0; k <= len; k++) {
        px(cx, cy - k, r, g, b, 255); px(cx, cy + k, r, g, b, 255);
        px(cx - k, cy, r, g, b, 255); px(cx + k, cy, r, g, b, 255);
    }
}
static void line(int x0, int y0, int x1, int y1, int r, int g, int b, int dash)
{
    int dx = abs(x1 - x0), dy = abs(y1 - y0), sx = x0 < x1 ? 1 : -1, sy = y0 < y1 ? 1 : -1, e2;
    int err = dx - dy, k = 0;
    for (;;) {
        if (!dash || ((k / 6) & 1) == 0) px(x0, y0, r, g, b, 255);
        if (x0 == x1 && y0 == y1) break;
        e2 = err * 2;
        if (e2 > -dy) { err -= dy; x0 += sx; }
        if (e2 <  dx) { err += dx; y0 += sy; }
        k++;
    }
}
static void rect(int x, int y, int w, int h, int r, int g, int b)
{
    for (int i = 0; i < w; i++) { px(x + i, y, r, g, b, 255); px(x + i, y + h, r, g, b, 255); }
    for (int i = 0; i < h; i++) { px(x, y + i, r, g, b, 255); px(x + w, y + i, r, g, b, 255); }
}
static void textOut(int x, int y, const char *utf8, int r, int g, int b, int outline)
{
    if (!g_memDC || !utf8 || !utf8[0]) return;
    wchar_t wb[160];
    int n = MultiByteToWideChar(CP_UTF8, 0, utf8, -1, wb, 159);
    if (n <= 0) return;
    wb[159] = 0;
    SetBkMode(g_memDC, TRANSPARENT);
    if (outline) {
        SetTextColor(g_memDC, RGB(0, 0, 0));
        for (int dx = -1; dx <= 1; dx++) for (int dy = -1; dy <= 1; dy++)
            if (dx || dy) TextOutW(g_memDC, x + dx, y + dy, wb, n - 1);
    }
    SetTextColor(g_memDC, RGB(r, g, b));
    TextOutW(g_memDC, x, y, wb, n - 1);
}

/* 鈹€鈹€ game capture (etview: BitBlt of the game client area) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static int captureGame(void)
{
    if (!g_gwnd) return 0;
    RECT rc; GetClientRect(g_gwnd, &rc);
    int cw = rc.right - rc.left, ch = rc.bottom - rc.top;
    if (cw < 2 || ch < 2) return 0;
    if (cw != g_viewW || ch != g_viewH) recreate(cw, ch);
    HDC wdc = GetDC(g_gwnd);
    BOOL ok = BitBlt(g_memDC, 0, 0, g_viewW, g_viewH, wdc, 0, 0, SRCCOPY);
    ReleaseDC(g_gwnd, wdc);
    return ok ? 1 : 0;
}

/* 鈹€鈹€ terrain build (mode M) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static int terrainBuild(const LC_MAP *m)
{
    if (!m) return 0;
    if (g_terBmp && g_terMid == m->id) return 1;
    const unsigned char *g = lc_grid(m);
    if (!g) { g_terMid = -1; return 0; }
    int w = m->tx, h = m->ty;
    if (w <= 0 || h <= 0 || w > 4096 || h > 4096) { g_terMid = -1; return 0; }
    /* DeleteObject on a DIB section releases its bits too - never free() g_terPx */
    if (g_terDC)  { DeleteDC(g_terDC); g_terDC = NULL; }
    if (g_terBmp) { DeleteObject(g_terBmp); g_terBmp = NULL; }
    g_terPx = NULL;

    BITMAPINFO bi; memset(&bi, 0, sizeof(bi));
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = w; bi.bmiHeader.biHeight = -h;   /* top-down */
    bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
    g_terBmp = CreateDIBSection(NULL, &bi, DIB_RGB_COLORS, (void **)&g_terPx, NULL, 0);
    if (!g_terBmp || !g_terPx) { g_terBmp = NULL; g_terPx = NULL; g_terMid = -1; return 0; }
    g_terDC = CreateCompatibleDC(NULL);
    SelectObject(g_terDC, g_terBmp);
    for (int y = 0; y < h; y++) {
        uint32_t *row = g_terPx + (size_t)y * w;
        const unsigned char *src = g + (size_t)y * w;
        for (int x = 0; x < w; x++) {
            int blocked = src[x] != 0;
            int chk = ((x + y) & 1) ? 5 : 0;
            row[x] = blocked
                ? (0xFF000000u | ((uint32_t)(18 + chk) << 16) | ((uint32_t)(20 + chk) << 8) | (uint32_t)(26 + chk))
                : (0xFF000000u | ((uint32_t)(40 + chk) << 16) | ((uint32_t)(58 + chk) << 8) | (uint32_t)(44 + chk));
        }
    }
    g_terMid = m->id; g_terTx = w; g_terTy = h;
    return 1;
}

static int mw2sx(int wx) { return (int)((wx - g_mapCamX) * g_mapZoom + g_viewW / 2.0); }
static int mw2sy(int wy) { return (int)((wy - g_mapCamY) * g_mapZoom + g_viewH / 2.0); }

static int drawMapMode(void)
{
    const LC_MAP *m = s_mapId >= 0 ? lc_mapById(s_mapId) : NULL;
    if (!m) return 0;
    if (!terrainBuild(m)) {
        argbFill(255, 12, 14, 18);
        textOut(20, 20, "terrain grid not available for this map", 255, 120, 120, 0);
        return 1;
    }
    /* clear */
    argbFill(255, 6, 7, 10);

    double z = g_mapZoom;
    int t0x = (int)floor(g_mapCamX - g_viewW  / (2.0 * z));
    int t1x = (int)ceil (g_mapCamX + g_viewW  / (2.0 * z));
    int t0y = (int)floor(g_mapCamY - g_viewH / (2.0 * z));
    int t1y = (int)ceil (g_mapCamY + g_viewH / (2.0 * z));
    int sx0 = t0x < m->x0 ? m->x0 : t0x, sx1 = t1x > m->x1 ? m->x1 : t1x;
    int sy0 = t0y < m->y0 ? m->y0 : t0y, sy1 = t1y > m->y1 ? m->y1 : t1y;

    if (sx1 > sx0 && sy1 > sy0) {
        int dX = mw2sx(sx0), dY = mw2sy(sy0);
        int dW = (int)((sx1 - sx0 + 1) * z + 0.5), dH = (int)((sy1 - sy0 + 1) * z + 0.5);
        int sX = sx0 - m->x0, sY = sy0 - m->y0;
        int sW = sx1 - sx0 + 1,        sH = sy1 - sy0 + 1;
        /* StretchDIBits refuses negative destinations -> clip dest, move source */
        if (dX < 0) { int c = (int)ceil(-dX / z); if (c > sW - 1) c = sW - 1; sX += c; sW -= c; dW -= (int)(c * z); dX = 0; }
        if (dY < 0) { int c = (int)ceil(-dY / z); if (c > sH - 1) c = sH - 1; sY += c; sH -= c; dH -= (int)(c * z); dY = 0; }
        if (dX + dW > g_viewW) { int c = (int)ceil((dX + dW - g_viewW) / z); if (c > sW - 1) c = sW - 1; sW -= c; dW -= (int)(c * z); }
        if (dY + dH > g_viewH) { int c = (int)ceil((dY + dH - g_viewH) / z); if (c > sH - 1) c = sH - 1; sH -= c; dH -= (int)(c * z); }
        if (sW > 0 && sH > 0 && dW > 0 && dH > 0) {
            HDC dst = g_memDC;
            SetStretchBltMode(dst, z >= 2.0 ? COLORONCOLOR : HALFTONE);
            BITMAPINFO bi; memset(&bi, 0, sizeof(bi));
            bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
            bi.bmiHeader.biWidth = g_terTx; bi.bmiHeader.biHeight = -g_terTy;
            bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
            StretchDIBits(dst, dX, dY, dW, dH, sX, sY, sW, sH, g_terPx, &bi, DIB_RGB_COLORS, SRCCOPY);
        }
    }
    /* map border */
    int bx = mw2sx(m->x0), by = mw2sy(m->y0);
    rect(bx, by, (int)((m->x1 - m->x0) * z), (int)((m->y1 - m->y0) * z), 90, 110, 140);
    /* exits */
    for (int i = 0; i < gA.nexit; i++) {
        if (gA.exit_[i].map != m->id) continue;
        int x = mw2sx(gA.exit_[i].x), y = mw2sy(gA.exit_[i].y);
        if (x < -4 || y < -4 || x > g_viewW + 4 || y > g_viewH + 4) continue;
        rect(x - 1, y - 1, 3, 3, 255, 210, 40);
    }
    return 1;
}

/* 鈹€鈹€ entity marker colours (etview palette) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static void clsRGB(uint32_t v, int self, int dead, int *R, int *G, int *B)
{
    *R = 160; *G = 160; *B = 160;
    if (v == VFT_MONSTER)   { *R = 255; *G = 40;  *B = 40; }
    else if (v == VFT_PLAYER)   { *R = 255; *G = 220; *B = 0; }
    else if (v == VFT_SELF)     { *R = 255; *G = 255; *B = 255; }
    else if (v == VFT_ITEM)     { *R = 40;  *G = 255; *B = 40; }
    else if (v == VFT_NPC)      { *R = 0;   *G = 220; *B = 220; }
    else if (v == VFT_SEGPROP)  { *R = 170; *G = 80;  *B = 255; }
    else if (v == VFT_SUMMON)   { *R = 255; *G = 170; *B = 60; }
    if (dead) { *R = 90; *G = 30; *B = 30; }
    if (self) { *R = 255; *G = 255; *B = 255; }
}

static LC_E s_self; static int s_haveSelf = 0;
static int s_scr[LC_MAXE][2]; static int s_hasScr[LC_MAXE];
static float s_selfScrX, s_selfScrY;

static void computeScreen(void)
{
    LC_VIEW v; lc_viewCalc(&v, g_viewW ? g_viewW : 800, g_viewH ? g_viewH : 600);
    s_haveSelf = 0; s_self.iU = 0; s_self.iV = 0;
    for (int i = 0; i < s_n; i++) {
        if (s_ents[i].guid == s_me && s_ents[i].hasIso) {
            s_self = s_ents[i]; s_haveSelf = 1; break;
        }
    }
    if (!s_haveSelf) {
        int cx = -1, cy = -1;
        for (int i = 0; i < s_n; i++) if (s_ents[i].guid == s_me) { cx = s_ents[i].cellx; cy = s_ents[i].celly; break; }
        if (cx < 0) { cx = (int)d32(g_base + LC_PLAYER_X); cy = (int)d32(g_base + LC_PLAYER_Y); }
        lc_selfIsoFromTile(cx, cy, &s_self.iU, &s_self.iV);
    }
    for (int i = 0; i < s_n; i++) {
        s_hasScr[i] = 0;
        if (!s_ents[i].hasIso) continue;
        int rx, ry;
        lc_project(&s_ents[i], &s_self, &v, &rx, &ry);
        s_scr[i][0] = rx; s_scr[i][1] = ry; s_hasScr[i] = 1;
    }
    if (s_haveSelf) {
        s_scr[0][0] = s_scr[0][0];  /* no-op, keeps the self entry in range */
    }
    /* self anchor */
    s_selfScrX = v.sx; s_selfScrY = v.sy;
}

static int idxByGuid(uint64_t g)
{
    for (int i = 0; i < s_n; i++) if (s_ents[i].guid == g) return i;
    return -1;
}

static void drawOverlayMode(void)
{
    if (!captureGame()) {
        argbFill(255, 10, 12, 16);
        textOut(20, 20, "game window capture failed", 255, 120, 120, 0);
        return;
    }
    /* attack lines first (under the markers) */
    if (g_showAtk) {
        for (int i = 0; i < s_n; i++) {
            if (!s_ents[i].hasAtk) continue;
            int j = idxByGuid(s_ents[i].atkTgt);
            if (j < 0 || !s_hasScr[i] || !s_hasScr[j]) continue;
            int meT = (s_ents[i].atkTgt == s_me);
            if (meT) line(s_scr[i][0], s_scr[i][1], s_scr[j][0], s_scr[j][1], 255, 40, 40, 1);
            else     line(s_scr[i][0], s_scr[i][1], s_scr[j][0], s_scr[j][1], 255, 150, 30, 1);
        }
    }
    /* dungeon entrances that are near self (projected through the same iso math) */
    if (g_showEntr) {
        int meX = s_self.iU, meY = s_self.iV;
        (void)meX; (void)meY;
        for (int i = 0; i < gA.nentr; i++) {
            float u = 48.0f * ((float)gA.entr[i].x + (float)gA.entr[i].y) - 3145680.0f;
            float v = 24.0f * ((float)gA.entr[i].x - (float)gA.entr[i].y);
            float du = u - s_self.iU, dv = v - s_self.iV;
            LC_VIEW vv; lc_viewCalc(&vv, g_viewW, g_viewH);
            int rx = (int)(vv.sx + du * vv.pxp), ry = (int)(vv.sy - dv * vv.pyp);
            if (rx < 0 || ry < 0 || rx >= g_viewW || ry >= g_viewH) continue;
            /* draw a magenta diamond (etview-style pixel primitive) */
            for (int k = 0; k < 7; k++) { px(rx, ry - k, 255, 60, 255, 255); px(rx, ry + k, 255, 60, 255, 255); }
            for (int k = 1; k < 6; k++) { px(rx - k, ry, 255, 60, 255, 255); px(rx + k, ry, 255, 60, 255, 255); }
            if (g_showLabels) textOut(rx + 9, ry - 14, gA.entr[i].key, 255, 160, 255, 1);
        }
    }
    /* entity markers */
    for (int i = 0; i < s_n; i++) {
        if (!s_hasScr[i]) continue;
        int rx = s_scr[i][0], ry = s_scr[i][1];
        if (rx < -60 || ry < -20 || rx > g_viewW + 60 || ry > g_viewH + 20) continue;
        int R, G, B; int isSelf = (s_ents[i].guid == s_me);
        clsRGB(s_ents[i].vft, isSelf, s_ents[i].dead, &R, &G, &B);
        int rad = (s_ents[i].vft == VFT_ITEM) ? 5 : 7;
        circ(rx, ry, rad, R, G, B, 0);
        cross(rx, ry, 4, R, G, B);
        if (s_ents[i].hasAtk && s_ents[i].atkTgt == s_me)
            circ(rx, ry, 10, 255, 40, 40, 0);       /* attacking me */
        if (g_showLabels) {
            if (s_ents[i].nm[0]) textOut(rx + 10, ry - 14, s_ents[i].nm, R, G, B, 1);
            char cb[32];
            snprintf(cb, sizeof(cb), "%s 0x%llX", clsOf(s_ents[i].vft), (unsigned long long)s_ents[i].guid);
            textOut(rx + 10, ry - 1, cb, R, G, B, 1);
            if (s_ents[i].vft == VFT_ITEM) {
                char ib[64];
                if (s_ents[i].itemOwner)
                    snprintf(ib, sizeof(ib), "item qty=%u own=0x%llX", s_ents[i].itemQty,
                             (unsigned long long)s_ents[i].itemOwner);
                else
                    snprintf(ib, sizeof(ib), "item qty=%u free", s_ents[i].itemQty);
                textOut(rx + 10, ry + 12, ib, 40, 255, 40, 1);
            }
        }
    }
    /* self anchor: white cross at the battlefield centre */
    circ((int)s_selfScrX, (int)s_selfScrY, 10, 255, 255, 255, 0);
    cross((int)s_selfScrX, (int)s_selfScrY, 7, 255, 255, 255);
}

/* map-mode markers (world cell space) */
static void drawMapMarkers(void)
{
    /* attack lines */
    if (g_showAtk) {
        for (int i = 0; i < s_n; i++) {
            if (!s_ents[i].hasAtk) continue;
            int j = idxByGuid(s_ents[i].atkTgt);
            if (j < 0) continue;
            int x1 = mw2sx(s_ents[i].cellx), y1 = mw2sy(s_ents[i].celly);
            int x2 = mw2sx(s_ents[j].cellx), y2 = mw2sy(s_ents[j].celly);
            int meT = (s_ents[i].atkTgt == s_me);
            line(x1, y1, x2, y2, meT ? 255 : 255, meT ? 40 : 150, meT ? 40 : 30, 1);
        }
    }
    /* entrances */
    if (g_showEntr) {
        for (int i = 0; i < gA.nentr; i++) {
            int x = mw2sx(gA.entr[i].x), y = mw2sy(gA.entr[i].y);
            if (x < 0 || y < 0 || x >= g_viewW || y >= g_viewH) continue;
            for (int k = 0; k < 7; k++) { px(x, y - k, 255, 60, 255, 255); px(x, y + k, 255, 60, 255, 255); }
            for (int k = 1; k < 6; k++) { px(x - k, y, 255, 60, 255, 255); px(x + k, y, 255, 60, 255, 255); }
            if (g_showLabels) textOut(x + 9, y - 14, gA.entr[i].key, 255, 160, 255, 1);
        }
    }
    /* entities */
    for (int i = 0; i < s_n; i++) {
        int x = mw2sx(s_ents[i].cellx), y = mw2sy(s_ents[i].celly);
        if (x < -40 || y < -40 || x > g_viewW + 40 || y > g_viewH + 40) continue;
        int R, G, B; int isSelf = (s_ents[i].guid == s_me);
        clsRGB(s_ents[i].vft, isSelf, s_ents[i].dead, &R, &G, &B);
        int sz = (int)(g_mapZoom < 3 ? 3 : g_mapZoom);
        for (int yy = 0; yy < sz; yy++) for (int xx = 0; xx < sz; xx++) px(x + xx, y + yy, R, G, B, 255);
        if (isSelf) circ(x + sz / 2, y + sz / 2, 8, 255, 255, 255, 0);
        if (s_ents[i].hasAtk && s_ents[i].atkTgt == s_me)
            circ(x + sz / 2, y + sz / 2, 6, 255, 40, 40, 0);
        if (g_showLabels && g_mapZoom >= 2.0) textOut(x + sz + 3, y - 12, s_ents[i].nm, R, G, B, 1);
    }
}

/* 鈹€鈹€ side panel: HUD + entrances + event log 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static void panelFill(int x, int y, int w, int h)
{
    for (int yy = y; yy < y + h; yy++) for (int xx = x; xx < x + w; xx++) {
        if (xx < 0 || yy < 0 || xx >= g_bw || yy >= g_bh) continue;
        BYTE *p = g_bits + (size_t)yy * g_stride + xx * 4;
        p[0] = 10; p[1] = 12; p[2] = 16; p[3] = 255;
    }
}
static void panelLine(int y) { for (int x = g_viewW; x < g_bw; x++) px(x, y, 70, 80, 95, 255); }

static void drawPanel(void)
{
    int X = g_viewW;
    panelFill(X, 0, g_PANEL, g_bh);
    SelectObject(g_memDC, g_fontB);
    int y = 8;
    char buf[340];

    int nply = 0, nmon = 0, nnpc = 0, nitem = 0, natk = 0, nme = 0, ndead = 0;
    for (int i = 0; i < s_n; i++) {
        LC_E *X2 = &s_ents[i];
        if (X2->hasAtk) { natk++; if (X2->atkTgt == s_me) nme++; }
        if (X2->vft == VFT_PLAYER || X2->vft == VFT_SELF) nply++;
        else if (X2->vft == VFT_MONSTER) nmon++;
        else if (X2->vft == VFT_NPC) nnpc++;
        else if (X2->vft == VFT_ITEM) nitem++;
        if (X2->dead) ndead++;
    }
    int meIdx = s_me ? idxByGuid(s_me) : -1;

    snprintf(buf, sizeof(buf), "LiveWorld  [%s]", g_modeOverlay ? "overlay (etview)" : "map (terrain)");
    textOut(X + 8, y, buf, 230, 235, 245, 0); y += 20;
    SelectObject(g_memDC, g_font);

    snprintf(buf, sizeof(buf), "map %d %s", s_mapId, s_mapName[0] ? s_mapName : "?");
    textOut(X + 8, y, buf, 230, 235, 245, 0); y += 16;
    snprintf(buf, sizeof(buf), "rect %s %d,%d - %d,%d", s_rectOK ? "live" : "?",
             s_rx0, s_ry0, s_rx1, s_ry1);
    textOut(X + 8, y, buf, 170, 180, 195, 0); y += 16;
    if (meIdx >= 0)
        snprintf(buf, sizeof(buf), "me %s", s_ents[meIdx].nm[0] ? s_ents[meIdx].nm : "-");
    else
        snprintf(buf, sizeof(buf), "me (not found)");
    textOut(X + 8, y, buf, 170, 180, 195, 0); y += 16;
    if (meIdx >= 0)
        snprintf(buf, sizeof(buf), "cell %d,%d  iso %.0f,%.0f  iiso %.0f,%.0f",
                 s_ents[meIdx].cellx, s_ents[meIdx].celly,
                 s_ents[meIdx].aU, s_ents[meIdx].aV, s_ents[meIdx].iU, s_ents[meIdx].iV);
    textOut(X + 8, y, buf, 170, 180, 195, 0); y += 16;
    snprintf(buf, sizeof(buf), "anchor %.0f,%.0f  pps %.3f  sc %.2f",
             s_selfScrX, s_selfScrY, LC_PPS, LC_REF_H);
    textOut(X + 8, y, buf, 150, 160, 175, 0); y += 18;

    snprintf(buf, sizeof(buf), "ents %d  ply %d  mon %d  npc %d  item %d  dead %d",
             s_n, nply, nmon, nnpc, nitem, ndead);
    textOut(X + 8, y, buf, 200, 205, 215, 0); y += 16;
    snprintf(buf, sizeof(buf), "atk %d  (on me %d)", natk, nme);
    textOut(X + 8, y, buf, nme ? 255 : 200, nme ? 90 : 205, nme ? 90 : 215, 0); y += 16;
    snprintf(buf, sizeof(buf), "ATK-ON-ME %llu   pick %llu  drop %llu  mapchg %llu",
             g_nAtkMe, g_nPick, g_nDrop, g_nMapCh);
    textOut(X + 8, y, buf, 200, 205, 215, 0); y += 16;
    {
        double dt = (GetTickCount() - g_t0) / 1000.0; if (dt < 0.5) dt = 0.5;
        snprintf(buf, sizeof(buf), "%.0f fps   ioctl %.0f/s   ledger %d   ui %dms",
                 g_fps, (g_ioctl - g_ioAtT0) / dt, lc_ledN, g_fastMs);
        textOut(X + 8, y, buf, 150, 160, 175, 0); y += 20;
    }
    panelLine(y); y += 6;

    /* dungeon entrances */
    SelectObject(g_memDC, g_fontB);
    snprintf(buf, sizeof(buf), "dungeon entrances (%d total)", gA.nentr);
    textOut(X + 8, y, buf, 230, 235, 245, 0); y += 18;
    SelectObject(g_memDC, g_font);
    {
        int shown = 0;
        for (int i = 0; i < gA.nentr && y < g_bh - 260; i++) {
            int ex = gA.entr[i].x, ey = gA.entr[i].y;
            int d = 0;
            if (meIdx >= 0) d = abs(ex - s_ents[meIdx].cellx) + abs(ey - s_ents[meIdx].celly);
            snprintf(buf, sizeof(buf), "%-26s (%d,%d) d=%d%s",
                     gA.entr[i].key, ex, ey, d,
                     (s_rectOK && s_rx0 <= ex && ex <= s_rx1 && s_ry0 <= ey && ey <= s_ry1) ? " *IN*" : "");
            textOut(X + 8, y, buf, d <= 32 ? 255 : 150, d <= 32 ? 160 : 150, d <= 32 ? 255 : 160, 0);
            y += 15; shown++;
            if (shown >= 19) break;
        }
    }
    y += 4;
    panelLine(y); y += 6;

    /* event log */
    SelectObject(g_memDC, g_fontB);
    textOut(X + 8, y, "events (newest at bottom)", 230, 235, 245, 0); y += 18;
    SelectObject(g_memDC, g_font);
    DWORD now = GetTickCount();
    for (int i = g_logN - 1, n = 0; i >= 0 && n < 14; i--, n++) {
        int idx = i % LOGMAX;
        DWORD age = now - g_log[idx].t;
        snprintf(buf, sizeof(buf), "%5.1fs %s", age / 1000.0, g_log[idx].s);
        textOut(X + 8, y, buf, age < 3000 ? 255 : 135, age < 3000 ? 240 : 145, age < 3000 ? 160 : 155, 0);
        y += 14;
    }
    /* key help at the very bottom */
    textOut(X + 8, g_bh - 44, "1/2 VP_DY  3/4 VP_DX  5/6 PPS", 120, 130, 145, 0);
    textOut(X + 8, g_bh - 30, "L labels  A atk  M mode  N entr  P snap  Q quit", 120, 130, 145, 0);
    textOut(X + 8, g_bh - 16, "map mode: WASD/arrows pan  +/- zoom  0 fit  C center", 120, 130, 145, 0);
}

/* 鈹€鈹€ selftest (no human eye needed) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static int g_selfTest = 0, g_stFrames = 0;
static const char *g_stOut = "liveworld_selftest.txt";
static void selftestRun(void)
{
    HDC dc = GetDC(g_hwnd);
    HDC mem = CreateCompatibleDC(dc);
    HBITMAP bmp = CreateCompatibleBitmap(dc, g_bw, g_bh);
    HGDIOBJ ob = SelectObject(mem, bmp);
    BOOL ok = BitBlt(mem, 0, 0, g_bw, g_bh, g_memDC, 0, 0, SRCCOPY);
    BITMAPINFO bi; memset(&bi, 0, sizeof(bi));
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = g_bw; bi.bmiHeader.biHeight = -g_bh;
    bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
    uint32_t *buf = (uint32_t *)malloc((size_t)g_bw * g_bh * 4);
    GetDIBits(mem, bmp, 0, g_bh, buf, &bi, DIB_RGB_COLORS);
    long white = 0, red = 0, green = 0, yellow = 0, cyan = 0, magenta = 0, n = 0;
    long terAll = 0, terOpen = 0, terBlocked = 0;
    for (long i = 0; i < (long)g_bw * g_bh; i++) {
        uint32_t c = buf[i] & 0xFFFFFF;
        int r = (c >> 16) & 255, g = (c >> 8) & 255, b = c & 255;
        if (r == 255 && g == 255 && b == 255) white++;
        if (r > 200 && g < 90  && b < 90)  red++;
        if (g > 200 && r < 90  && b < 90)  green++;
        if (r > 200 && g > 180 && b < 90)  yellow++;
        if (g > 180 && b > 180 && r < 90)  cyan++;
        if (r > 200 && b > 200 && g < 120) magenta++;
        /* terrain: dark, blue/green dominant. open=(40,58,44)+chk, blocked=(18,20,26)+chk */
        if (r <= 55 && g <= 70 && b <= 60 && g >= r && b > r) {
            terAll++;
            if (g >= 45) terOpen++; else terBlocked++;
        }
        n++;
    }
    FILE *f = fopen(g_stOut, "w");
    if (f) {
        fprintf(f, "blt_ok          %d\n", ok);
        fprintf(f, "view            %dx%d   panel %d   total %dx%d\n", g_viewW, g_viewH, g_PANEL, g_bw, g_bh);
        fprintf(f, "mode            %s\n", g_modeOverlay ? "overlay" : "map");
        fprintf(f, "game_hwnd        %p  capture=%d\n", (void *)g_gwnd, g_gwnd ? 1 : 0);
        fprintf(f, "map             %d %s  rect %d,%d - %d,%d (live=%d)\n",
                s_mapId, s_mapName, s_rx0, s_ry0, s_rx1, s_ry1, s_rectOK);
        fprintf(f, "terrain_dib     id=%d %dx%d %s\n", g_terMid, g_terTx, g_terTy,
                g_terBmp ? "built" : "MISSING");
        fprintf(f, "ents            %d   me=0x%llX  haveSelf=%d\n", s_n, (unsigned long long)s_me, s_haveSelf);
        fprintf(f, "self_anchor     %.0f,%.0f   selfScr px %d,%d\n",
                s_selfScrX, s_selfScrY, (int)s_selfScrX, (int)s_selfScrY);
        fprintf(f, "pixels          %ld\n", n);
        fprintf(f, "terrain_px      %ld  (open %ld / blocked %ld)\n", terAll, terOpen, terBlocked);
        fprintf(f, "white_px        %ld   (self marker / self anchor)\n", white);
        fprintf(f, "red_px          %ld   (monster + attack-on-me ring)\n", red);
        fprintf(f, "green_px        %ld   (item)\n", green);
        fprintf(f, "yellow_px       %ld   (player)\n", yellow);
        fprintf(f, "cyan_px         %ld   (npc)\n", cyan);
        fprintf(f, "magenta_px      %ld   (dungeon entrance)\n", magenta);
        fprintf(f, "events          log=%d atkOnMe=%llu pick=%llu drop=%llu mapchg=%llu\n",
                g_logN, g_nAtkMe, g_nPick, g_nDrop, g_nMapCh);
        fclose(f);
    }
    free(buf);
    SelectObject(mem, ob); DeleteObject(bmp); DeleteDC(mem); ReleaseDC(g_hwnd, dc);
    PostQuitMessage(0);
}

/* 鈹€鈹€ snapshot json (P) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static void snapshot(const char *path)
{
    FILE *f = fopen(path, "w");
    if (!f) { addLog("snapshot failed: %s", path); return; }
    fprintf(f, "{\"t\":%u,\"mode\":\"%s\",\"mapId\":%d,\"mapName\":\"%s\",\"mapRectLive\":%d,"
               "\"rect\":[%d,%d,%d,%d],\"self\":\"0x%llX\",\"n\":%d,\"view\":{\"pps\":%.3f,"
               "\"vpDx\":%.1f,\"vpDy\":%.1f,\"anchor\":[%.0f,%.0f]},"
               "\"totals\":{\"atkOnMe\":%llu,\"itemPicked\":%llu,\"itemDrop\":%llu,\"mapChange\":%llu},\"ents\":[",
            GetTickCount(), g_modeOverlay ? "overlay" : "map", s_mapId, s_mapName, s_rectOK,
            s_rx0, s_ry0, s_rx1, s_ry1, (unsigned long long)s_me, s_n,
            LC_PPS, LC_VP_DX, LC_VP_DY, s_selfScrX, s_selfScrY,
            g_nAtkMe, g_nPick, g_nDrop, g_nMapCh);
    for (int i = 0; i < s_n; i++) {
        LC_E *X = &s_ents[i];
        fprintf(f, "%s{\"guid\":\"0x%llX\",\"cls\":\"%s\",\"name\":\"%s\",\"cell\":[%d,%d],"
                   "\"iso\":[%.1f,%.1f],\"iiso\":[%.1f,%.1f],\"ab\":[%.1f,%.1f,%.1f,%.1f],"
                   "\"scr\":[%d,%d],\"alive\":%d",
                i ? "," : "", (unsigned long long)X->guid, clsOf(X->vft), X->nm,
                X->cellx, X->celly, X->aU, X->aV, X->iU, X->iV, X->aU, X->aV, X->bU, X->bV,
                s_hasScr[i] ? s_scr[i][0] : -1, s_hasScr[i] ? s_scr[i][1] : -1, X->dead ? 0 : 1);
        if (s_mapId >= 0) {
            int bl = lc_blockedAt(lc_mapById(s_mapId), X->cellx, X->celly);
            if (bl >= 0) fprintf(f, ",\"walkable\":%d", 1 - bl);
        }
        if (X->vft == VFT_ITEM)
                fprintf(f, ",\"item\":{\"type\":%u,\"qty\":%u,\"owner\":\"0x%llX\"}",
                        X->itemType, X->itemQty, (unsigned long long)X->itemOwner);
        if (X->hasAtk) fprintf(f, ",\"atk\":{\"owner\":\"0x%llX\",\"tgt\":\"0x%llX\",\"targetsMe\":%d}",
                               (unsigned long long)X->atkOwner, (unsigned long long)X->atkTgt,
                               X->atkTgt == s_me ? 1 : 0);
        fprintf(f, "}");
    }
    fprintf(f, "]}\n");
    fclose(f);
    addLog("snapshot -> %s", path);
}

/* 鈹€鈹€ window proc 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static int g_camInit = 0;
static LRESULT CALLBACK WndProc(HWND h, UINT m, WPARAM w, LPARAM l)
{
    switch (m) {
    case WM_CREATE:
        g_t0 = GetTickCount(); g_fpsTick = g_t0; g_ioAtT0 = g_ioctl;
        SetTimer(h, 1, (UINT)g_fastMs / 2 + 10, NULL);
        return 0;
    case WM_TIMER: {
        DWORD now = GetTickCount();
        g_frames++;
        if (now - g_fpsTick >= 1000) {
            g_fps = g_frames * 1000.0 / (now - g_fpsTick);
            g_frames = 0; g_fpsTick = now; g_ioAtT0 = g_ioctl;
        }
        /* drain worker events into the log */
        LC_EV ev;
        while (lc_popEv(&ev)) {
            if (!strcmp(ev.kind, "ATTACK")) {
                char b[180];
                snprintf(b, sizeof(b), "ATTACK %s -> %s%s", ev.a, ev.b, ev.i1 ? "   <<< ME" : "");
                addLog("%s", b);
            } else if (!strcmp(ev.kind, "RETARGET")) {
                addLog("RETARGET %s -> %s", ev.a, ev.b);
            } else if (!strcmp(ev.kind, "ATTACK_END")) {
                addLog("ATTACK_END %s", ev.a);
            } else if (!strcmp(ev.kind, "DEATH")) {
                addLog("DEATH %s (%s) @%d,%d", ev.a, ev.b, ev.i1, ev.i2);
            } else if (!strcmp(ev.kind, "ITEM_DROP")) {
                addLog("ITEM_DROP %s type=%d qty=%d @%d,%d", ev.a, ev.i1, ev.i2, ev.i3, ev.i4);
            } else if (!strcmp(ev.kind, "ITEM_PICKED")) {
                addLog("ITEM_PICKED %s type=%d qty=%d @%d,%d", ev.a, ev.i1, ev.i2, ev.i3, ev.i4);
            } else if (!strcmp(ev.kind, "MAP_CHANGE")) {
                addLog("MAP_CHANGE %s -> %s", ev.a, ev.b);
            }
        }
        /* take a snapshot of the worker state */
        EnterCriticalSection(&g_snapCS);
        LC_E tmp[LC_MAXE]; int n = s_n;
        memcpy(tmp, s_ents, sizeof(LC_E) * n);
        int meIdx = -1;
        for (int i = 0; i < n; i++) if (tmp[i].guid == s_me) { meIdx = i; break; }
        LC_E meSave; memset(&meSave, 0, sizeof(meSave));
        if (meIdx >= 0) meSave = tmp[meIdx];
        memcpy(s_ents, tmp, sizeof(LC_E) * n);
        if (meIdx >= 0) s_ents[meIdx] = meSave;
        LeaveCriticalSection(&g_snapCS);
        computeScreen();
        /* map-mode camera follows self */
        if (!g_modeOverlay) {
            if (meIdx >= 0) { g_mapCamX = s_ents[meIdx].cellx; g_mapCamY = s_ents[meIdx].celly; g_camInit = 1; }
            if (!g_camInit && s_rectOK) {
                g_mapCamX = (s_rx0 + s_rx1) / 2; g_mapCamY = (s_ry0 + s_ry1) / 2;
                const LC_MAP *m = s_mapId >= 0 ? lc_mapById(s_mapId) : NULL;
                if (m) {
                    double zx = (g_viewW - 20.0) / (m->x1 - m->x0 + 1);
                    double zy = (g_viewH - 20.0) / (m->y1 - m->y0 + 1);
                    g_mapZoom = zx < zy ? zx : zy;
                    if (g_mapZoom < 0.25) g_mapZoom = 0.25;
                }
                g_camInit = 1;
            }
        }
        InvalidateRect(h, NULL, FALSE);
        if (g_selfTest && ++g_stFrames >= 12) selftestRun();
        return 0; }
    case WM_PAINT: {
        PAINTSTRUCT ps;
        HDC dc = BeginPaint(h, &ps);
        if (g_modeOverlay) drawOverlayMode();
        else { if (!drawMapMode()) { argbFill(255, 8, 9, 12); textOut(20, 20, "no map for current rect", 255, 120, 120, 0); } drawMapMarkers(); }
        drawPanel();
        BitBlt(dc, 0, 0, g_bw, g_bh, g_memDC, 0, 0, SRCCOPY);
        EndPaint(h, &ps);
        return 0; }
    case WM_ERASEBKGND: return 1;
    case WM_SIZE: {
        RECT r; GetClientRect(h, &r);
        int nw = r.right - g_PANEL, nh = r.bottom;
        if (nw < 200) nw = 200;
        if (nh < 200) nh = 200;
        if (nw != g_viewW || nh != g_viewH) { recreate(nw, nh); g_W = nw; g_H = nh; }
        return 0; }
    case WM_KEYDOWN: {
        if (w == 'Q' || w == VK_ESCAPE) { g_run = 0; PostQuitMessage(0); return 0; }
        if (w == '1') LC_VP_DY -= 1.f;
        else if (w == '2') LC_VP_DY += 1.f;
        else if (w == '3') LC_VP_DX -= 1.f;
        else if (w == '4') LC_VP_DX += 1.f;
        else if (w == '5') LC_PPS -= 0.005f;
        else if (w == '6') LC_PPS += 0.005f;
        else if (w == 'L') g_showLabels = !g_showLabels;
        else if (w == 'A') g_showAtk = !g_showAtk;
        else if (w == 'N') g_showEntr = !g_showEntr;
        else if (w == 'M') { g_modeOverlay = !g_modeOverlay; g_camInit = 0; addLog("mode -> %s", g_modeOverlay ? "overlay" : "map"); }
        else if (w == 'P') snapshot("liveworld_snapshot.json");
        else if (!g_modeOverlay) {
            int step = (int)(g_mapZoom * 12); if (step < 8) step = 8;
            if (w == VK_LEFT || w == 'A' + 0x100) g_mapCamX -= step;
            else if (w == 'C') { for (int i = 0; i < s_n; i++) if (s_ents[i].guid == s_me) { g_mapCamX = s_ents[i].cellx; g_mapCamY = s_ents[i].celly; } }
        }
        InvalidateRect(h, NULL, FALSE);
        return 0; }
    case WM_DESTROY: g_run = 0; PostQuitMessage(0); return 0;
    }
    return DefWindowProcW(h, m, w, l);
}

int main(int argc, char **argv)
{
    SetProcessDPIAware();
    SetConsoleOutputCP(CP_UTF8);
    g_fastMs = argc > 1 ? atoi(argv[1]) : 40; if (g_fastMs < 20) g_fastMs = 40;
    const char *root = argc > 2 ? argv[2] : ".";
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--selftest")) g_selfTest = 1;
        else if (!strncmp(argv[i], "--out=", 6)) g_stOut = argv[i] + 6;
        else if (!strncmp(argv[i], "--fast=", 7)) g_fastMs = atoi(argv[i] + 7);
        else if (!strncmp(argv[i], "--slow=", 7)) g_slowMs = atoi(argv[i] + 7);
        else if (!strcmp(argv[i], "--map")) g_modeOverlay = 0;
    }

    HANDLE mu = CreateMutexW(NULL, TRUE, L"Global\\LiveWorldLC");
    if (GetLastError() == ERROR_ALREADY_EXISTS) { printf("another liveworld is running\n"); return 6; }

    if (lc_attach()) return 1;
    if (!lc_anchor()) { fprintf(stderr, "anchor fail (ActorSubsystem not found by vft 0x117EAD8)\n"); return 2; }
    lc_loadAssets(root);
    InitializeCriticalSection(&g_snapCS);
    lc_csInit();

    g_gwnd = lc_findGameWnd((DWORD)g_pid);
    int vw = 800, vh = 600;
    if (g_gwnd) { RECT r; GetClientRect(g_gwnd, &r); vw = r.right; vh = r.bottom; }
    if (!g_gwnd) fprintf(stderr, "[warn] game window not found (overlay mode will show a message)\n");
    fprintf(stderr, "[liveworld] pid=%llu BASE=0x%llX actor=0x%llX game=%p %dx%d\n",
            (unsigned long long)g_pid, (unsigned long long)g_base,
            (unsigned long long)lc_actor, (void *)g_gwnd, vw, vh);
    fprintf(stderr, "[liveworld] assets %d maps / %d entrances / %d exits / %d gates\n",
            gA.nmap, gA.nentr, gA.nexit, gA.ngate);

    /* prime the first frame before the window opens */
    {
        static uint64_t ptrs[LC_MAXE];
        int n = lc_sweepSlow(ptrs, LC_MAXE);
        lc_pollFast(ptrs, n, GetTickCount());
        lc_pick_self();
        LC_E *me = lc_findMe();
        lc_readMapRect(me ? me->cellx : -1, me ? me->celly : -1);
        const LC_MAP *cmap = lc_mapValid ? lc_mapByRect(lc_mx0, lc_my0, lc_mx1, lc_my1) : NULL;
        if (cmap) { s_mapId = cmap->id; snprintf(s_mapName, sizeof(s_mapName), "%s", cmap->name); }
        s_rectOK = lc_mapValid; s_rx0 = lc_mx0; s_ry0 = lc_my0; s_rx1 = lc_mx1; s_ry1 = lc_my1;
        if (!lc_meGuid) { fprintf(stderr, "no player found (log in first)\n"); return 4; }
        fprintf(stderr, "[liveworld] me=0x%llX  map %d %s\n",
                (unsigned long long)lc_meGuid, s_mapId, s_mapName);
    }
    lc_nc = 0;   /* the worker owns the live state from here on */

    recreate(vw, vh);

    WNDCLASSEXW wc; memset(&wc, 0, sizeof(wc));
    wc.cbSize = sizeof(wc);
    wc.style = CS_HREDRAW | CS_VREDRAW;
    wc.lpfnWndProc = WndProc;
    wc.hInstance = GetModuleHandleW(NULL);
    wc.hCursor = LoadCursor(NULL, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)GetStockObject(BLACK_BRUSH);
    wc.lpszClassName = L"LiveWorldLC";
    if (!RegisterClassExW(&wc)) { fprintf(stderr, "RegisterClass fail\n"); return 5; }

    HWND hwnd = CreateWindowExW(0, L"LiveWorldLC",
        L"LiveWorld  [overlay] entity+attack+dungeon+item   Q quit",
        WS_OVERLAPPEDWINDOW | WS_VISIBLE, CW_USEDEFAULT, CW_USEDEFAULT,
        vw + g_PANEL + 24, vh + 60, NULL, NULL, wc.hInstance, NULL);
    if (!hwnd) { fprintf(stderr, "CreateWindow fail %lu\n", GetLastError()); return 5; }
    g_hwnd = hwnd;
    {
        RECT rc; GetClientRect(hwnd, &rc);
        int nw = rc.right - g_PANEL, nh = rc.bottom;
        if (nw < 200) nw = 200;
        if (nh < 200) nh = 200;
        if (nw != g_viewW || nh != g_viewH) recreate(nw, nh);
    }
    ShowWindow(hwnd, SW_SHOW);
    UpdateWindow(hwnd);

    HANDLE th = CreateThread(NULL, 0, pollThread, NULL, 0, NULL);

    MSG msg;
    while (GetMessageW(&msg, NULL, 0, 0) > 0) {
        if (msg.message == WM_QUIT) break;
        TranslateMessage(&msg); DispatchMessageW(&msg);
    }
    g_run = 0;
    if (th) { WaitForSingleObject(th, 2000); CloseHandle(th); }

    fprintf(stderr, "[liveworld] events log=%d atkOnMe=%llu pick=%llu drop=%llu mapchg=%llu ioctl=%llu\n",
            g_logN, g_nAtkMe, g_nPick, g_nDrop, g_nMapCh, g_ioctl);
    if (g_terDC)  DeleteDC(g_terDC);
    if (g_terBmp) DeleteObject(g_terBmp);   /* DIB section bits are freed with it */
    g_terPx = NULL;
    if (g_memDC) { SelectObject(g_memDC, g_oldBm); DeleteObject(g_hbm); DeleteDC(g_memDC); }
    CloseHandle(mu);
    SignedClose();
    return 0;
}


