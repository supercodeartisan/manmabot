/* combatview_930.c - etview-style overlay visualizing COMBAT + ITEM OWNERSHIP
 * on top of the existing lcore.h live-read core.
 *
 * What it draws (in its own window, right of the game window):
 *   - every entity marker: MyPlayer=white, Monster=red, Player=yellow,
 *     NPC=cyan, Item=green(free) / orange(locked)
 *   - ATTACKERS ON ME: red line entity->me + red ring
 *   - other attack lines: orange
 *   - Item label: "qty=N" + "(free)"/"(LOCKED)" from +0x48 flag
 *   - side panel: list of attackers (name/guid/cell) + fresh ITEM_DROP/own events
 *
 * Reuses lcore.h lc_collect()/lc_cur[]/lc_pick_self() so the visualization is
 * exactly the same data livetrack/liveworld consume.
 *
 * Keys: Q/ESC quit, 1/2/3/4 nudge VP_DY/VP_DX, F9 save bmp.
 * ASCII only.
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "9_30_update/src/lcore.h"

/* ---- overlay window + DIB (etview convention) ---- */
static HWND g_gwnd = 0, g_wnd = 0;
static BYTE *g_bits = 0; static int g_stride = 0, g_bw = 0, g_bh = 0;
static HDC g_memDC = 0; static HBITMAP g_hbm = 0; static HGDIOBJ g_oldBm = 0;
static HFONT g_font = 0, g_fontB = 0;

static void recreate(int w, int h)
{
    if (g_memDC) { SelectObject(g_memDC, g_oldBm); DeleteObject(g_hbm); DeleteDC(g_memDC); g_memDC = 0; }
    if (!g_font) {
        g_font  = CreateFontA(13, 0, 0, 0, FW_NORMAL, 0, 0, 0, DEFAULT_CHARSET,
                              OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                              DEFAULT_PITCH, "Malgun Gothic");
        g_fontB = CreateFontA(14, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET,
                              OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                              DEFAULT_PITCH, "Malgun Gothic");
    }
    HDC s = GetDC(NULL);
    g_memDC = CreateCompatibleDC(s);
    BITMAPINFO bi; memset(&bi, 0, sizeof(bi));
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER); bi.bmiHeader.biWidth = w; bi.bmiHeader.biHeight = -h;
    bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
    void *pv = 0; g_hbm = CreateDIBSection(s, &bi, DIB_RGB_COLORS, &pv, 0, 0);
    g_bits = (BYTE *)pv;
    g_oldBm = SelectObject(g_memDC, g_hbm);
    SelectObject(g_memDC, g_font);
    ReleaseDC(NULL, s);
    g_stride = w * 4; g_bw = w; g_bh = h;
}
static void px(int x, int y, int r, int g, int b, int a)
{
    if (x < 0 || y < 0 || x >= g_bw || y >= g_bh) return;
    BYTE *p = g_bits + (size_t)y * g_stride + x * 4;
    p[0] = (BYTE)b; p[1] = (BYTE)g; p[2] = (BYTE)r; p[3] = (BYTE)a;
}
static void line2(int x0, int y0, int x1, int y1, int r, int g, int b, int w0)
{
    int dx = x1 - x0, dy = y1 - y0, steps = abs(dx) > abs(dy) ? abs(dx) : abs(dy);
    if (steps < 1) steps = 1;
    for (int k = 0; k <= steps; k++) {
        int x = x0 + (int)((long long)dx * k / steps);
        int y = y0 + (int)((long long)dy * k / steps);
        px(x, y, r, g, b, 255);
        for (int q = 1; q < w0; q++) { px(x + q, y, r, g, b, 255); px(x, y + q, r, g, b, 255); }
    }
}
static void circ(int cx, int cy, int rad, int r, int g, int b)
{
    for (int y = -rad; y <= rad; y++) for (int x = -rad; x <= rad; x++)
        if (x * x + y * y <= rad * rad && x * x + y * y >= (rad - 1) * (rad - 1))
            px(cx + x, cy + y, r, g, b, 255);
}
static void cross(int cx, int cy, int len, int r, int g, int b)
{
    for (int k = 0; k < len; k++) { px(cx, cy - k, r, g, b, 255); px(cx, cy + k, r, g, b, 255);
                                    px(cx - k, cy, r, g, b, 255); px(cx + k, cy, r, g, b, 255); }
}
static void textOut(int x, int y, const char *utf8, int r, int g, int b, int bold)
{
    if (!g_memDC || !utf8 || !utf8[0]) return;
    wchar_t wbuf[160]; int n = MultiByteToWideChar(CP_UTF8, 0, utf8, -1, wbuf, 159);
    if (n <= 0) return; wbuf[159] = 0;
    SelectObject(g_memDC, bold ? g_fontB : g_font);
    SetBkMode(g_memDC, TRANSPARENT);
    SetTextColor(g_memDC, RGB(0, 0, 0));
    for (int dx = -1; dx <= 1; dx++) for (int dy = -1; dy <= 1; dy++) if (dx || dy) TextOutW(g_memDC, x + dx, y + dy, wbuf, n - 1);
    SetTextColor(g_memDC, RGB(r, g, b));
    TextOutW(g_memDC, x, y, wbuf, n - 1);
}

static int capture(void)
{
    RECT rc; GetClientRect(g_gwnd, &rc); int cw = rc.right, ch = rc.bottom;
    if (cw < 2 || ch < 2) return 0;
    if (cw != g_bw || ch != g_bh) recreate(cw, ch);
    HDC wdc = GetDC(g_gwnd); BOOL ok = BitBlt(g_memDC, 0, 0, cw, ch, wdc, 0, 0, SRCCOPY);
    ReleaseDC(g_gwnd, wdc);
    return ok ? 1 : 0;
}

struct CV_FIND { DWORD pid; HWND best; long long area; };
static BOOL CALLBACK cvFindWnd(HWND h, LPARAM lp)
{
    struct CV_FIND *e = (struct CV_FIND *)lp;
    DWORD p = 0; GetWindowThreadProcessId(h, &p);
    if (p != e->pid || !IsWindowVisible(h)) return TRUE;
    RECT r; if (!GetClientRect(h, &r)) return TRUE;
    long long a = (long long)(r.right - r.left) * (r.bottom - r.top);
    if (a > e->area) { e->area = a; e->best = h; }
    return TRUE;
}
static HWND findGameWnd(void)
{
    struct CV_FIND f; memset(&f, 0, sizeof(f));
    f.pid = (DWORD)g_pid; f.area = -1;
    EnumWindows(cvFindWnd, (LPARAM)&f);
    return f.best;
}

static int g_quit = 0, g_bmp = 0, g_capture = 0;
static LRESULT CALLBACK wp(HWND h, UINT m, WPARAM w, LPARAM l)
{
    if (m == WM_DESTROY) { PostQuitMessage(0); g_quit = 1; return 0; }
    if (m == WM_KEYDOWN) {
        switch ((int)w) {
        case 'Q': case VK_ESCAPE: PostQuitMessage(0); g_quit = 1; break;
        case '1': LC_VP_DY -= 1.f; break;
        case '2': LC_VP_DY += 1.f; break;
        case '3': LC_VP_DX -= 1.f; break;
        case '4': LC_VP_DX += 1.f; break;
        case VK_F9: g_bmp = 1; break;
        case VK_F5: g_capture = 1; break;
        }
    }
    return DefWindowProcA(h, m, w, l);
}

/* ---- render current lc_cur snapshot into the overlay ---- */
static int s_scrX[LC_MAXE], s_scrY[LC_MAXE]; static int s_hasScr[LC_MAXE];
static void renderFrame(int vw, int vh)
{
    LC_E *me = lc_findMe();
    float su, sv;
    if (me) { su = me->iU; sv = me->iV; }
    else if (lc_meGuid) { LC_E *p = lc_findCur(lc_meGuid); if (p) { su = p->iU; sv = p->iV; } else { lc_selfIsoFromTile(0,0,&su,&sv); su=sv=0; } }
    else { su = sv = 0; }

    LC_VIEW view; lc_viewCalc(&view, vw, vh);
    for (int i = 0; i < lc_nc; i++) {
        LC_E *X = &lc_cur[i];
        s_hasScr[i] = 0;
        if (!X->hasIso) continue;
        float du = X->iU - su, dv = X->iV - sv;
        int rx = (int)(view.sx + du * view.pxp), ry = (int)(view.sy - dv * view.pyp);
        s_scrX[i] = rx; s_scrY[i] = ry; s_hasScr[i] = 1;
    }

    /* attack lines (under markers) */
    for (int i = 0; i < lc_nc; i++) {
        LC_E *X = &lc_cur[i];
        if (!X->hasAtk || !s_hasScr[i]) continue;
        int j = -1; for (int k = 0; k < lc_nc; k++) if (lc_cur[k].guid == X->atkTgt) { j = k; break; }
        if (j < 0 || !s_hasScr[j]) continue;
        int meT = (X->atkTgt == lc_meGuid);
        line2(s_scrX[i], s_scrY[i], s_scrX[j], s_scrY[j], meT ? 255 : 255, meT ? 40 : 150, meT ? 40 : 30, 1);
    }

    /* entity markers */
    for (int i = 0; i < lc_nc; i++) {
        LC_E *X = &lc_cur[i];
        if (!s_hasScr[i]) continue;
        int rx = s_scrX[i], ry = s_scrY[i];
        if (rx < -80 || ry < -30 || rx > vw + 80 || ry > vh + 30) continue;
        int R, G, B;
        switch (X->vft) {
        case VFT_SELF:    R = 255; G = 255; B = 255; break;
        case VFT_MONSTER: R = 255; G = 40;  B = 40;  break;
        case VFT_PLAYER:  R = 255; G = 220; B = 0;   break;
        case VFT_SUMMON:  R = 255; G = 120; B = 220; break;
        case VFT_NPC:     R = 0;   G = 220; B = 220; break;
        case VFT_SHIP:    R = 170; G = 80;  B = 255; break;
        case VFT_ITEM:    R = (X->itemFlag) ? 255 : 40; G = (X->itemFlag) ? 140 : 255; B = 0; break;
        default:          R = 150; G = 150; B = 150; break;
        }
        int rad = (X->vft == VFT_ITEM) ? 5 : 7;
        if (X->dead) {
            /* dead monster/actor: dim gray, hollow ring + X (no cross) */
            R = 90; G = 90; B = 90;
            circ(rx, ry, rad + 1, 90, 90, 90);
            for (int k = 0; k <= rad; k++) { px(rx - k, ry - k, 90, 90, 90, 255); px(rx + k, ry - k, 90, 90, 90, 255);
                                             px(rx - k, ry + k, 90, 90, 90, 255); px(rx + k, ry + k, 90, 90, 90, 255); }
            if (X->nm[0]) textOut(rx + 10, ry - 14, X->nm, 140, 140, 140, 0);
            textOut(rx + 10, ry - 1, "(dead)", 200, 120, 120, 0);
            continue;
        }
        circ(rx, ry, rad, R, G, B);
        cross(rx, ry, 4, R, G, B);
        if (X->hasAtk && X->atkTgt == lc_meGuid) circ(rx, ry, 11, 255, 40, 40); /* attacking me */
        if (X->nm[0]) textOut(rx + 10, ry - 14, X->nm, R, G, B, 0);
        char cb[96];
        if (X->vft == VFT_ITEM) {
            snprintf(cb, sizeof(cb), "qty=%u %s", X->itemQty, X->itemFlag ? "LOCKED" : "free");
            textOut(rx + 10, ry - 1, cb, R, G, B, 0);
        } else {
            snprintf(cb, sizeof(cb), "%s", clsOf(X->vft));
            textOut(rx + 10, ry - 1, cb, R, G, B, 0);
        }
    }
    /* self anchor */
    circ((int)view.sx, (int)view.sy, 10, 255, 255, 255);
    cross((int)view.sx, (int)view.sy, 7, 255, 255, 255);
}

/* ---- side panel: attackers + items ---- */
static void drawPanel(int vw, int vh, int PANEL, DWORD now)
{
    SelectObject(g_memDC, g_fontB);
    int y = 8;
    char buf[300];
    snprintf(buf, sizeof(buf), "COMBAT VIEW  ents=%d", lc_nc);
    textOut(vw + 4, y, buf, 255, 255, 255, 1); y += 20;
    snprintf(buf, sizeof(buf), "me=0x%llX", (unsigned long long)lc_meGuid);
    textOut(vw + 4, y, buf, 200, 200, 255, 0); y += 20;
    int ndead = 0; for (int i = 0; i < lc_nc; i++) if (lc_cur[i].dead) ndead++;
    snprintf(buf, sizeof(buf), "dead=%d  (gray X)", ndead);
    textOut(vw + 4, y, buf, 160, 160, 160, 0); y += 20;

    /* attackers on me */
    textOut(vw + 4, y, "--- attackers on me ---", 255, 60, 60, 1); y += 18;
    int natk = 0;
    for (int i = 0; i < lc_nc; i++) {
        LC_E *X = &lc_cur[i];
        if (X->hasAtk && X->atkTgt == lc_meGuid) {
            snprintf(buf, sizeof(buf), "%s 0x%llX %d,%d", clsOf(X->vft),
                     (unsigned long long)X->guid, X->cellx, X->celly);
            if (X->nm[0]) snprintf(buf + strlen(buf), sizeof(buf) - strlen(buf), " %s", X->nm);
            textOut(vw + 6, y, buf, 255, 80, 80, 0); y += 16;
            natk++;
        }
    }
    textOut(vw + 4, y, natk ? "" : "(none)", 120, 120, 120, 0); y += 20;

    /* items */
    textOut(vw + 4, y, "--- ground items ---", 60, 255, 60, 1); y += 18;
    int nItem = 0;
    for (int i = 0; i < lc_nc; i++) {
        LC_E *X = &lc_cur[i];
        if (X->vft != VFT_ITEM) continue;
        snprintf(buf, sizeof(buf), "%s qty=%u %s 0x%08X", X->nm, X->itemQty,
                 X->itemFlag ? "LOCK" : "free", X->itemFlag);
        textOut(vw + 6, y, buf, X->itemFlag ? 255 : 120, 255, X->itemFlag ? 80 : 120, 0);
        y += 16;
        nItem++;
        if (y > vh - 40) break;
    }
    if (!nItem) textOut(vw + 6, y, "(none)", 120, 120, 120, 0);
}

static void saveBmp(void)
{
    /* save the overlay window content to combatview_shot.png (via BMP then
     * it's fine to leave as BMP).  Used to verify the game screen shows. */
    int w = g_bw, h = g_bh;
    BITMAPFILEHEADER fh; BITMAPINFOHEADER ih;
    memset(&fh, 0, sizeof(fh)); memset(&ih, 0, sizeof(ih));
    ih.biSize = sizeof(ih); ih.biWidth = w; ih.biHeight = h;
    ih.biPlanes = 1; ih.biBitCount = 32; ih.biCompression = BI_RGB;
    int rowsz = w * 4;
    fh.bfType = 0x4D42; fh.bfOffBits = sizeof(fh) + sizeof(ih);
    fh.bfSize = fh.bfOffBits + rowsz * h;
    FILE *f = fopen("combatview_shot.bmp", "wb");
    if (!f) return;
    fwrite(&fh, sizeof(fh), 1, f);
    fwrite(&ih, sizeof(ih), 1, f);
    /* bottom-up rows */
    for (int y = h - 1; y >= 0; y--) fwrite(g_bits + (size_t)y * g_stride, 1, rowsz, f);
    fclose(f);
    fprintf(stderr, "[combatview] saved combatview_shot.bmp (%dx%d)\n", w, h);
}

/* F5: dump every ground item's full fingerprint (0x00..0x1C0 as u64) plus
 * ownership candidates, so the user can correlate "I could pick it" vs
 * "I could not" with the raw fields.  Appends to combatview_capture.txt. */
static void captureItems(void)
{
    FILE *f = fopen("combatview_capture.txt", "a");
    if (!f) return;
    DWORD now = GetTickCount();
    fprintf(f, "\n[%u] capture n=%d me=0x%llX\n", now, lc_nc,
            (unsigned long long)lc_meGuid);
    for (int i = 0; i < lc_nc; i++) {
        LC_E *X = &lc_cur[i];
        if (X->vft != VFT_ITEM) continue;
        fprintf(f, "ITEM %016llX cell=(%d,%d) \"%s\"\n",
                (unsigned long long)X->e, X->cellx, X->celly, X->nm);
        /* raw u64 fields 0x00..0x1C0 */
        for (int o = 0; o < 0x1C0; o += 8) {
            uint64_t v = q64(X->e + o);
            const char *tag = "";
            if (v == lc_meGuid) tag = "  <== meGuid";
            else if (v && !isHeap(v) && !isMod(v) && v < 0x100000000ULL) {
                /* small non-heap value: could be an owner id / seq */
                for (int k = 0; k < lc_nc; k++)
                    if (lc_cur[k].guid == v) { tag = "  <== actorGuid"; break; }
            }
            fprintf(f, "  +%03X %016llX%s\n", o, (unsigned long long)v, tag);
        }
        fprintf(f, "  flag48=%08X seq54=%08X qty38=%08X\n",
                X->itemFlag, d32(X->e + 0x54), X->itemQty);
        /* ownership candidates: small non-heap qwords in the record */
        fprintf(f, "  ownerCand:");
        for (int o = 0; o < 0x1C0; o += 8) {
            uint64_t v = q64(X->e + o);
            if (v && !isHeap(v) && !isMod(v) && v < 0x100000000ULL)
                fprintf(f, " +%03X=%lX", o, (unsigned long)v);
        }
        fprintf(f, "\n");
    }
    fclose(f);
    fprintf(stderr, "[combatview] F5 capture -> combatview_capture.txt\n");
}

int main(void)
{
    SetConsoleOutputCP(CP_UTF8);
    if (lc_attach()) return 1;
    if (!lc_anchor()) { fprintf(stderr, "anchor fail\n"); return 2; }
    lc_loadAssets(".");
    lc_collect();
    lc_pick_self();
    if (!lc_meGuid) { fprintf(stderr, "no player (log in)\n"); return 3; }

    g_gwnd = findGameWnd();
    RECT rc = { 0, 0, 800, 600 };
    if (g_gwnd) GetClientRect(g_gwnd, &rc);
    fprintf(stderr, "[combatview] BASE=0x%llX me=0x%llX game %dx%d\n",
            (unsigned long long)g_base, (unsigned long long)lc_meGuid, rc.right, rc.bottom);

    WNDCLASSA wc = { 0 };
    wc.lpfnWndProc = wp; wc.hInstance = GetModuleHandleA(NULL); wc.lpszClassName = "CombatView";
    wc.hCursor = LoadCursorA(NULL, IDC_ARROW); wc.hbrBackground = (HBRUSH)GetStockObject(BLACK_BRUSH);
    RegisterClassA(&wc);

    RECT gr = { 0, 0, 0, 0 };
    if (g_gwnd) GetWindowRect(g_gwnd, &gr);
    int PANEL = 320;
    int w = rc.right + PANEL, h = rc.bottom;
    DWORD style = WS_OVERLAPPEDWINDOW | WS_VISIBLE;
    RECT adj = { 0, 0, w, h }; AdjustWindowRectEx(&adj, style, FALSE, 0);
    g_wnd = CreateWindowExA(0, "CombatView",
        "CombatView (game+markers) Q=quit 1/2=VP_DY 3/4=VP_DX F5=capture F9=shot(bmp)",
        style, gr.right + 4, gr.top, adj.right - adj.left, adj.bottom - adj.top,
        NULL, NULL, wc.hInstance, NULL);
    recreate(w, h);

    MSG msg; DWORD last = 0, lastBmp = 0;
    int autoShot = 3;   /* auto-save a verification shot on startup */
    while (!g_quit) {
        while (PeekMessageA(&msg, NULL, 0, 0, PM_REMOVE)) {
            if (msg.message == WM_QUIT) goto done;
            TranslateMessage(&msg); DispatchMessageA(&msg);
        }
        DWORD now = GetTickCount();
        if (now - last < 80) { Sleep(4); continue; }
        last = now;

        lc_collect();
        lc_pick_self();
        if (!capture()) continue;

        /* game screen stays as captured (BitBlt already copied it into the
         * left vw x h region); only the side panel area is painted. */
        int vw = rc.right;
        renderFrame(vw, h);
        /* side panel fill */
        for (int y = 0; y < h; y++) for (int x = vw; x < w; x++) px(x, y, 10, 12, 16, 255);
        drawPanel(vw, h, PANEL, now);

        HDC dc = GetDC(g_wnd);
        BitBlt(dc, 0, 0, w, h, g_memDC, 0, 0, SRCCOPY);
        ReleaseDC(g_wnd, dc);

        if (g_capture) { captureItems(); g_capture = 0; }
        if (g_bmp) { saveBmp(); g_bmp = 0; }
        if (autoShot > 0 && --autoShot == 0) saveBmp();
    }
done:
    SignedClose();
    return 0;
}