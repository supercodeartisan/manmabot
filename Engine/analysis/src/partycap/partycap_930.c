/* partycap_930.c — 게임 화면 캡처 + 파티 바 위젯 오버레이
 * ===========================================================================
 *  캡처: etview 와 동일한 방식
 *        GetClientRect(game wnd) → CreateDIBSection(32bpp, top-down)
 *        → BitBlt(wnd DC → mem DC, SRCCOPY) → GDI 로 그 위에 그린다
 *
 *  오버레이: partyhud 와 같은 경로로 읽은 파티 창/위젯 좌표를
 *            GLView 매핑으로 클라이언트 픽셀(좌상 원점)로 변환해 사각형+라벨 표시
 *
 *  usage: partycap_930.exe [registry] [out.bmp] [-show] [-all] [-no-tree]
 *    -show    : 결과를 창에 표시(Q/ESC 종료). 기본은 BMP 저장만.
 *    -all     : 비활성 슬롯까지 표시
 *    -no-tree : 바 자체 트리 오버레이 생략
 *  output: bin/out/partycap.bmp (기본)
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

/* ── 캡처(DIB) ──────────────────────────────────────────────────────── */
static HDC g_memDC = 0; static HBITMAP g_hbm = 0; static HGDIOBJ g_oldBm = 0;
static BYTE *g_bits = 0; static int g_bw = 0, g_bh = 0;
static HFONT g_font = 0;
static HWND g_gwnd = 0;

static void recreateDIB(int w, int h)
{
    if (g_memDC) { SelectObject(g_memDC, g_oldBm); DeleteObject(g_hbm); DeleteDC(g_memDC); g_memDC = 0; }
    if (!g_font) g_font = CreateFontA(13, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET,
        OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY, DEFAULT_PITCH, "Malgun Gothic");
    HDC s = GetDC(NULL);
    g_memDC = CreateCompatibleDC(s);
    BITMAPINFO bi; memset(&bi, 0, sizeof bi);
    bi.bmiHeader.biSize = sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth = w; bi.bmiHeader.biHeight = -h;
    bi.bmiHeader.biPlanes = 1; bi.bmiHeader.biBitCount = 32; bi.bmiHeader.biCompression = BI_RGB;
    void *pv = 0; g_hbm = CreateDIBSection(s, &bi, DIB_RGB_COLORS, &pv, 0, 0);
    g_bits = (BYTE *)pv; g_oldBm = SelectObject(g_memDC, g_hbm); SelectObject(g_memDC, g_font);
    ReleaseDC(NULL, s);
    g_bw = w; g_bh = h;
}

static int capture(void)
{
    if (!g_gwnd) return 0;
    RECT rc; if (!GetClientRect(g_gwnd, &rc)) return 0;
    int cw = rc.right, ch = rc.bottom;
    if (cw < 2 || ch < 2) return 0;
    if (cw != g_bw || ch != g_bh) recreateDIB(cw, ch);
    HDC wdc = GetDC(g_gwnd);
    BOOL ok = BitBlt(g_memDC, 0, 0, cw, ch, wdc, 0, 0, SRCCOPY);
    ReleaseDC(g_gwnd, wdc);
    return ok ? 1 : 0;
}

static void saveBMP(const char *path)
{
    if (!g_bits) return;
    int w = g_bw, h = g_bh, size = w * 4 * h;
    BITMAPFILEHEADER fh; memset(&fh, 0, sizeof fh);
    fh.bfType = 0x4D42; fh.bfOffBits = 54; fh.bfSize = 54 + size;
    BITMAPINFOHEADER ih; memset(&ih, 0, sizeof ih);
    ih.biSize = 40; ih.biWidth = w; ih.biHeight = -h; ih.biPlanes = 1;
    ih.biBitCount = 32; ih.biSizeImage = size;
    FILE *fp = fopen(path, "wb"); if (!fp) return;
    fwrite(&fh, sizeof fh, 1, fp); fwrite(&ih, sizeof ih, 1, fp);
    fwrite(g_bits, 1, size, fp); fclose(fp);
    printf("saved %s (%dx%d)\n", path, w, h);
}

/* ── 그리기 ─────────────────────────────────────────────────────────── */
static void box(HDC dc, int x0, int y0, int x1, int y1, COLORREF c, int w)
{
    HPEN p = CreatePen(PS_SOLID, w, c); HGDIOBJ o = SelectObject(dc, p);
    HGDIOBJ b = SelectObject(dc, GetStockObject(NULL_BRUSH));
    Rectangle(dc, x0, y0, x1, y1);
    SelectObject(dc, o); SelectObject(dc, b); DeleteObject(p);
}

static void textOut(HDC dc, int x, int y, const char *u8, COLORREF c)
{
    if (!u8 || !u8[0]) return;
    wchar_t wb[256]; int n = MultiByteToWideChar(CP_UTF8, 0, u8, -1, wb, 255); if (n <= 0) return;
    wb[255] = 0; SetBkMode(dc, TRANSPARENT);
    SetTextColor(dc, RGB(0, 0, 0));
    for (int dx = -1; dx <= 1; dx++) for (int dy = -1; dy <= 1; dy++)
        if (dx || dy) TextOutW(dc, x + dx, y + dy, wb, n - 1);
    SetTextColor(dc, c); TextOutW(dc, x, y, wb, n - 1);
}

/* ── 파티 읽기 (partyhud 와 동일 경로) ─────────────────────────────── */
static uint32_t RG_WIN_VFT, RG_CVAL, RG_VIS;
static uint32_t RG_POS_X, RG_POS_Y, RG_SIZE_W, RG_SIZE_H;
static uint32_t RG_SLOT_OFF, RG_SLOT_STRIDE, RG_SLOT_OBJ, RG_SLOT_N;
static uint32_t RG_SLOT_GUID, RG_SLOT_HP, RG_SLOT_MP, RG_INACTIVE;
static uint32_t RG_WABS_X, RG_WABS_Y, RG_WSC_X, RG_WSC_Y;
static uint32_t RG_NODE_OFF, RG_CHILD;
static uint32_t RG_DIR_OFF, RG_GLV_IN_DIR;
static uint32_t RG_GLV_FW, RG_GLV_FH, RG_GLV_DW, RG_GLV_DH;
static uint32_t RG_GLV_VX, RG_GLV_VY, RG_GLV_SX, RG_GLV_SY;
static uint64_t g_hd[8], g_nx[8]; static int g_nc = 0;

static struct { int ok; float fw, fh, dw, dh, sx, sy, vx, vy; } S;

#define CLC_MAX 48
static struct { uint32_t vft; char name[80]; } g_clc[CLC_MAX];
static int g_nclc = 0;

static void vftClass(uint32_t rva, char *out, size_t cap)
{
    out[0] = 0;
    for (int i = 0; i < g_nclc; i++)
        if (g_clc[i].vft == rva) { strncpy(out, g_clc[i].name, cap - 1); out[cap - 1] = 0; return; }
    uint8_t nm[128];
    uint64_t col = q64(g_base + rva - 8);
    if (!isMod(col)) return;
    uint32_t td = d32(col + 0xC);
    if (!td || td >= g_modSize) return;
    if (!rm(g_base + td + 0x10, nm, sizeof nm - 1)) return;
    nm[sizeof nm - 1] = 0;
    const char *s = strstr((char *)nm, "AV"); s = s ? s + 2 : (char *)nm;
    strncpy(out, s, cap - 1); out[cap - 1] = 0;
    if (g_nclc < CLC_MAX) { g_clc[g_nclc].vft = rva; strncpy(g_clc[g_nclc].name, out, 79); g_nclc++; }
}

typedef struct { uint64_t p, cb, ce; uint32_t vft; float ax, ay, w, h, sx, sy; char cls[80]; } LW;

static int readWidget(uint64_t p, LW *o)
{
    uint8_t b[0x190];
    if (!isHeap(p) || !lc_pgRead(p, b, sizeof b)) return 0;
    memset(o, 0, sizeof *o);
    o->p = p;
    uint64_t vf = *(uint64_t *)b;
    o->vft = isMod(vf) ? (uint32_t)(vf - g_base) : 0;
    o->ax = *(float *)(b + RG_WABS_X);
    o->ay = *(float *)(b + RG_WABS_Y);
    o->w = *(float *)(b + RG_SIZE_W);
    o->h = *(float *)(b + RG_SIZE_H);
    o->sx = *(float *)(b + RG_WSC_X);
    o->sy = *(float *)(b + RG_WSC_Y);
    if (RG_CHILD + 16 <= sizeof b) {
        o->cb = *(uint64_t *)(b + RG_CHILD);
        o->ce = *(uint64_t *)(b + RG_CHILD + 8);
    }
    if (!o->vft) return 0;
    vftClass(o->vft, o->cls, sizeof o->cls);
    return 1;
}

static void pxRect(float x, float y, float w, float h, int *x0, int *y0, int *x1, int *y1)
{
    *x0 = (int)(S.vx + x * S.sx + 0.5f);
    *x1 = (int)(S.vx + (x + w) * S.sx + 0.5f);
    *y0 = (int)(S.fh - (S.vy + (y + h) * S.sy) + 0.5f);
    *y1 = (int)(S.fh - (S.vy + y * S.sy) + 0.5f);
}

static int readScreen(uint64_t node)
{
    memset(&S, 0, sizeof S);
    uint64_t dir = q64(node + RG_DIR_OFF);
    if (!isHeap(dir)) return 0;
    uint64_t glv = q64(dir + RG_GLV_IN_DIR);
    if (!isHeap(glv)) return 0;
    uint8_t b[0x80];
    if (!lc_pgRead(glv, b, sizeof b)) return 0;
    S.fw = *(float *)(b + RG_GLV_FW); S.fh = *(float *)(b + RG_GLV_FH);
    S.dw = *(float *)(b + RG_GLV_DW); S.dh = *(float *)(b + RG_GLV_DH);
    S.vx = *(float *)(b + RG_GLV_VX); S.vy = *(float *)(b + RG_GLV_VY);
    S.sx = *(float *)(b + RG_GLV_SX); S.sy = *(float *)(b + RG_GLV_SY);
    if (!(S.fw > 0 && S.fh > 0 && S.sx > 0 && S.sy > 0)) return 0;
    S.ok = 1; return 1;
}

static uint64_t findLayout(uint64_t ui)
{
    for (int c = 0; c < g_nc; c++) {
        uint64_t node = q64(ui + g_hd[c]);
        for (int n = 0; n < 2048 && isHeap(node); n++) {
            uint8_t nb[0x48];
            if (!rm(node, nb, sizeof nb)) break;
            uint64_t lay = *(uint64_t *)(nb + RG_CVAL);
            uint64_t nxt = *(uint64_t *)(nb + g_nx[c]);
            if (isHeap(lay) && vrva(lay) == RG_WIN_VFT) return lay;
            if (nxt == node) break;
            node = nxt;
        }
    }
    return 0;
}

static int g_all = 0, g_noTree = 0, g_nBox = 0, g_nTreeBox = 0;

static COLORREF colorOf(const char *cls)
{
    if (strstr(cls, "Button"))     return RGB(0, 255, 0);
    if (strstr(cls, "LoadingBar")) return RGB(0, 200, 255);
    if (strstr(cls, "ImageView"))  return RGB(0, 200, 255);
    if (strstr(cls, "Text"))       return RGB(80, 160, 255);
    if (strstr(cls, "ListView"))   return RGB(255, 0, 255);
    return RGB(160, 160, 160);
}

static void drawTree(HDC dc, uint64_t node, int depth, int maxd)
{
    if (depth > maxd) return;
    LW w; if (!readWidget(node, &w)) return;
    int placed = (w.ax != 0.0f || w.ay != 0.0f);
    if (placed) {
        int x0, y0, x1, y1; pxRect(w.ax, w.ay, w.w, w.h, &x0, &y0, &x1, &y1);
        COLORREF c = colorOf(w.cls);
        box(dc, x0, y0, x1, y1, c, 1);
        if (w.cls[0]) {
            char lb[128];
            snprintf(lb, sizeof lb, "%s d%d", w.cls, depth);
            textOut(dc, x0 + 1, y0 - 13, lb, c);
        }
        g_nTreeBox++;
    }
    if (depth >= maxd) return;
    if (!isHeap(w.cb) || !isHeap(w.ce) || w.ce <= w.cb) return;
    uint64_t n = (w.ce - w.cb) / 8;
    if ((w.ce - w.cb) % 8 || n > 256) return;
    for (uint64_t i = 0; i < n; i++) {
        uint64_t ch = q64(w.cb + i * 8);
        if (!isHeap(ch) || !isMod(q64(ch))) continue;
        drawTree(dc, ch, depth + 1, maxd);
    }
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("registry/LC930_REGISTRY.txt");
    const char *reg = lcreg_resolve("registry/LC930_REGISTRY.txt", "registry/LC930_REGISTRY.txt");
    char outp[MAX_PATH * 2]; snprintf(outp, sizeof outp, "%s", lcreg_outpath("partycap.bmp"));
    int show = 0, maxd = 6;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-show"))   { show = 1; continue; }
        if (!strcmp(argv[i], "-all"))    { g_all = 1; continue; }
        if (!strcmp(argv[i], "-no-tree")){ g_noTree = 1; continue; }
        if (strstr(argv[i], ".bmp") || strstr(argv[i], ".png")) {
            snprintf(outp, sizeof outp, "%s", argv[i]);
        } else if (strstr(argv[i], "REGISTRY")) reg = argv[i];
    }
    reg = lcreg_resolve(reg, "registry/LC930_REGISTRY.txt");
    lcreg_load(reg); lc_reg_apply();

    RG_WIN_VFT = lcreg_u32("UILAY_HudPartyInfoLayoutPCImpl", 0x1294C80);
    RG_CVAL = lcreg_u32("UIDLG_CONT_VAL", 0x38);
    RG_VIS = lcreg_u32("VIS_FLAG", 0x70);
    RG_POS_X = lcreg_u32("LAYOUT_POS_X", 0x60);
    RG_POS_Y = lcreg_u32("LAYOUT_POS_Y", 0x64);
    RG_SIZE_W = lcreg_u32("LAYOUT_SIZE_W", 0x6C);
    RG_SIZE_H = lcreg_u32("LAYOUT_SIZE_H", 0x70);
    RG_NODE_OFF = lcreg_u32("LAYOUT_WIDGET_NODE", 0x30);
    RG_SLOT_OFF = lcreg_u32("PARTY_HUD_SLOT_OFF", 0xC0);
    RG_SLOT_STRIDE = lcreg_u32("PARTY_HUD_SLOT_STRIDE", 0x10);
    RG_SLOT_OBJ = lcreg_u32("PARTY_HUD_SLOT_OBJ", 0x08);
    RG_SLOT_N = lcreg_u32("PARTY_HUD_SLOT_COUNT", 8);
    RG_SLOT_GUID = lcreg_u32("PARTY_HUD_SLOT_GUID_OFF", 0x10);
    RG_SLOT_HP = lcreg_u32("PARTY_HUD_SLOT_HP_OFF", 0x1C);
    RG_SLOT_MP = lcreg_u32("PARTY_HUD_SLOT_MP_OFF", 0x20);
    RG_INACTIVE = lcreg_u32("PARTY_HUD_SLOT_INACTIVE_GUID", 0xFFFFFFFF);
    RG_WABS_X = lcreg_u32("WIDGET_ABS_X", 0xB0);
    RG_WABS_Y = lcreg_u32("WIDGET_ABS_Y", 0xB4);
    RG_WSC_X = lcreg_u32("WIDGET_SCALE_X", 0x2C);
    RG_WSC_Y = lcreg_u32("WIDGET_SCALE_Y", 0x30);
    RG_CHILD = lcreg_u32("WIDGET_CHILDREN", 0x178);
    RG_DIR_OFF = lcreg_u32("DIRECTOR_OFF", 0x198);
    RG_GLV_IN_DIR = lcreg_u32("GLVIEW_IN_DIR", 0x100);
    RG_GLV_FW = lcreg_u32("GLV_FRAME_W", 0x10);
    RG_GLV_FH = lcreg_u32("GLV_FRAME_H", 0x14);
    RG_GLV_DW = lcreg_u32("GLV_DESIGN_W", 0x18);
    RG_GLV_DH = lcreg_u32("GLV_DESIGN_H", 0x1C);
    RG_GLV_VX = lcreg_u32("GLV_VIEW_X", 0x20);
    RG_GLV_VY = lcreg_u32("GLV_VIEW_Y", 0x24);
    RG_GLV_SX = lcreg_u32("GLV_SCALE_X", 0x50);
    RG_GLV_SY = lcreg_u32("GLV_SCALE_Y", 0x54);

    { const char *v = lcreg_str("UIDLG_CONT", "0x38:0x18,0x28:0x28"); char buf[128];
      strncpy(buf, v, 127); buf[127] = 0;
      for (char *t = strtok(buf, ","); t && g_nc < 8; t = strtok(0, ",")) {
          char *c = strchr(t, ':'); if (!c) continue; *c = 0;
          g_hd[g_nc] = strtoull(t, 0, 0); g_nx[g_nc] = strtoull(c + 1, 0, 0); g_nc++; } }

    if (lc_attach()) { fprintf(stderr, "attach failed\n"); return 1; }
    if (!lc_anchor()) { fprintf(stderr, "anchor failed\n"); return 2; }

    g_gwnd = lc_findGameWnd((DWORD)g_pid);
    if (!g_gwnd) { fprintf(stderr, "game window not found\n"); return 3; }
    if (!capture()) { fprintf(stderr, "capture failed\n"); return 4; }
    printf("captured %dx%d\n", g_bw, g_bh);

    uint64_t ui = lc_subsGet(lcreg_u32("VFT_UISUBSYSTEM", 0x11F6A38));
    uint64_t lay = isHeap(ui) ? findLayout(ui) : 0;
    if (!lay) { fprintf(stderr, "party HUD not found\n"); saveBMP(outp); return 5; }

    uint64_t node = q64(lay + RG_NODE_OFF);
    float wx = f32(lay + RG_POS_X), wy = f32(lay + RG_POS_Y);
    float ww = isHeap(node) ? f32(node + RG_SIZE_W) : 0.0f;
    float wh = isHeap(node) ? f32(node + RG_SIZE_H) : 0.0f;
    uint32_t vis = d32(lay + RG_VIS) & 0xFF;

    const char *src = "glview";
    if (!readScreen(node)) {
        RECT rc;
        if (GetClientRect(g_gwnd, &rc) && rc.right > 0) {
            S.ok = 1; S.fw = (float)rc.right; S.fh = (float)rc.bottom;
            S.dw = (float)lcreg_u32("UI_DESIGN_W", 1280);
            S.dh = (float)lcreg_u32("UI_DESIGN_H", 960);
            S.sx = S.fw / S.dw; S.sy = S.fh / S.dh; S.vx = S.vy = 0; src = "client";
        }
    }
    if (!S.ok) { S.ok = 1; S.fw = 1280; S.fh = 960; S.dw = 1280; S.dh = 960;
                 S.sx = S.sy = 1.0f; S.vx = S.vy = 0; src = "design"; }

    HDC dc = g_memDC;

    /* 바 창 */
    int x0, y0, x1, y1; pxRect(wx, wy, ww, wh, &x0, &y0, &x1, &y1);
    box(dc, x0, y0, x1, y1, RGB(255, 255, 0), 2);
    { char lb[160];
      snprintf(lb, sizeof lb, "PARTY HUD  win(%.0f,%.0f %.0fx%.0f) vis=%u  px[%d,%d,%d,%d]",
               wx, wy, ww, wh, vis, x0, y0, x1, y1);
      textOut(dc, x0 + 2, y0 - 16, lb, RGB(255, 255, 0)); }

    /* 바 자체 위젯 트리 */
    if (!g_noTree && isHeap(node)) drawTree(dc, node, 0, maxd);

    /* 슬롯 */
    int nAct = 0, nDraw = 0;
    for (uint32_t i = 0; i < RG_SLOT_N; i++) {
        uint64_t so = q64(lay + RG_SLOT_OFF + i * RG_SLOT_STRIDE + RG_SLOT_OBJ);
        if (!isHeap(so)) continue;
        uint32_t guid = d32(so + RG_SLOT_GUID);
        float hp = f32(so + RG_SLOT_HP), mp = f32(so + RG_SLOT_MP);
        int active = (guid != RG_INACTIVE);
        if (active) nAct++;
        if (!active && !g_all) continue;
        nDraw++;

        /* 행 대표: +0x60 Layout */
        LW row; int rx0, ry0, rx1, ry1;
        if (readWidget(q64(so + 0x60), &row))
            pxRect(row.ax, row.ay, row.w, row.h, &rx0, &ry0, &rx1, &ry1);
        else { rx0 = ry0 = rx1 = ry1 = 0; }

        for (uint32_t off = 0x60; off <= 0xF0; off += 8) {
            LW w; if (!readWidget(q64(so + off), &w)) continue;
            if (!(w.ax != 0.0f || w.ay != 0.0f)) continue;
            int qx0, qy0, qx1, qy1; pxRect(w.ax, w.ay, w.w, w.h, &qx0, &qy0, &qx1, &qy1);
            COLORREF c;
            const char *tag = "";
            if (off == 0x78)      { c = RGB(255, 60, 60);  tag = "HP"; }
            else if (off == 0x88) { c = RGB(60, 120, 255); tag = "MP"; }
            else if (off == 0xA8) { c = RGB(255, 200, 0);  tag = "LEAD"; }
            else if (off == 0xB0) { c = RGB(255, 140, 0);  tag = "ICON"; }
            else if (off == 0xC0) { c = RGB(120, 200, 255);tag = "TEXT"; }
            else if (off == 0xD0) { c = RGB(0, 255, 0);    tag = "ROW"; }
            else                  { c = RGB(120, 120, 120); }
            box(dc, qx0, qy0, qx1, qy1, c, 1);
            if (tag[0] && off != 0xD0) {
                char lb[96];
                if (off == 0x78)      snprintf(lb, sizeof lb, "HP %.0f%%", hp);
                else if (off == 0x88) snprintf(lb, sizeof lb, "MP %.0f%%", mp);
                else                  snprintf(lb, sizeof lb, "%s", tag);
                textOut(dc, qx0 + 1, qy0 - 13, lb, c);
            }
            g_nBox++;
        }
        { char lb[128];
          snprintf(lb, sizeof lb, "slot%u guid=0x%X  hp=%.0f%% mp=%.0f%%%s",
                   i, guid, hp, mp, active ? "" : " (inactive)");
          textOut(dc, rx0 + 2, ry1 + 2, lb, RGB(255, 0, 255)); }
        box(dc, rx0, ry0, rx1, ry1, RGB(255, 0, 255), 1);
    }

    /* 범례 */
    { char lb[256];
      snprintf(lb, sizeof lb,
               "yellow=window  green=Button  cyan=ImageView/LoadingBar  magenta=ListView/row  "
               "red=HP  blue=MP  orange=icon  gold=leader");
      textOut(dc, 4, g_bh - 18, lb, RGB(255, 255, 255));
      snprintf(lb, sizeof lb, "screen src=%s frame=%.0fx%.0f design=%.0fx%.0f scale=%.4f  "
               "treeBox=%d widgetBox=%d slots=%d/%u",
               src, S.fw, S.fh, S.dw, S.dh, S.sx, g_nTreeBox, g_nBox, nAct, RG_SLOT_N);
      textOut(dc, 4, 4, lb, RGB(255, 255, 255)); }

    saveBMP(outp);
    printf("WIN px=[%d,%d,%d,%d] scale=%.4f(%s) tree=%d slots=%d/%u -> %s\n",
           x0, y0, x1, y1, S.sx, src, g_nTreeBox, nAct, RG_SLOT_N, outp);

    if (show) {
        printf("show: Q/ESC to quit\n");
        /* 정적 표시 창 */
        WNDCLASSA wc; memset(&wc, 0, sizeof wc);
        wc.lpfnWndProc = DefWindowProcA;
        wc.hInstance = GetModuleHandle(0);
        wc.lpszClassName = "PartyCapView";
        wc.hCursor = LoadCursor(0, IDC_ARROW);
        RegisterClassA(&wc);
        RECT r = { 0, 0, g_bw, g_bh };
        AdjustWindowRect(&r, WS_OVERLAPPEDWINDOW, FALSE);
        HWND vw = CreateWindowA("PartyCapView", "partycap - party HUD overlay",
                                WS_OVERLAPPEDWINDOW, 80, 40,
                                r.right - r.left, r.bottom - r.top, 0, 0, wc.hInstance, 0);
        ShowWindow(vw, SW_SHOW);
        MSG m; DWORD t0 = GetTickCount();
        while (GetTickCount() - t0 < 60000) {
            while (PeekMessage(&m, 0, 0, 0, PM_REMOVE)) {
                if (m.message == WM_QUIT) goto done;
                if (m.message == WM_KEYDOWN && (m.wParam == 'Q' || m.wParam == VK_ESCAPE)) goto done;
                TranslateMessage(&m); DispatchMessage(&m);
            }
            HDC vdc = GetDC(vw); HDC cdc = CreateCompatibleDC(vdc);
            HBITMAP bmp = CreateCompatibleBitmap(vdc, g_bw, g_bh);
            HGDIOBJ ob = SelectObject(cdc, bmp);
            BitBlt(cdc, 0, 0, g_bw, g_bh, g_memDC, 0, 0, SRCCOPY);
            BitBlt(vdc, 0, 0, g_bw, g_bh, cdc, 0, 0, SRCCOPY);
            SelectObject(cdc, ob); DeleteObject(bmp); DeleteDC(cdc); ReleaseDC(vw, vdc);
            Sleep(16);
        }
done:   ;
    }

    SignedClose();
    return 0;
}
