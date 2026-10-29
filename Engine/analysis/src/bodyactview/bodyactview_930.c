/* bodyactview_930.c — MyPlayer body/cmd stick-figure viewer (10_15)
 * ===========================================================================
 *  Manmabot action_view.py 대응:
 *    자세 = ActionComponent + AC_ACTION_OFF (0xC0) vft
 *    하단 마크 = ActorController + CTL_CMD_OFF (0x58) vft
 *  읽기: lc_pollSelfBodyFast (sticky AC/CTL 잎 IOCTL, 퓨전 없음)
 *
 *  usage: bodyactview_930.exe [registry]
 *  keys: Q / ESC 종료
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <mmsystem.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <math.h>
#include "lcreg.h"
#include "lcore.h"
#pragma comment(lib, "gdi32.lib")
#pragma comment(lib, "user32.lib")
#pragma comment(lib, "winmm.lib")

#define W 300
#define H 300
#define TIMER_ID 1
#define TICK_MS 50

static HWND g_wnd;
static int g_quit;
static double g_phase;
static uint32_t g_body, g_cmd;
static int g_ok;
static HFONT g_font;

static COLORREF bodyColor(const char *n)
{
    if (!strcmp(n, "stand")) return RGB(0xD5, 0xDB, 0xE6);
    if (!strcmp(n, "walk") || !strcmp(n, "walkback")) return RGB(0x7D, 0xFF, 0xB0);
    if (!strcmp(n, "attack")) return RGB(0xFF, 0x5B, 0x49);
    if (!strcmp(n, "pickup")) return RGB(0xFF, 0xCC, 0x66);
    if (!strcmp(n, "turn")) return RGB(0x7E, 0xC8, 0xFF);
    if (!strcmp(n, "damaged")) return RGB(0xFF, 0x4D, 0x6D);
    if (!strcmp(n, "spell")) return RGB(0xC7, 0x9B, 0xFF);
    if (!strcmp(n, "death")) return RGB(0x8E, 0x96, 0xA3);
    if (!strcmp(n, "effect")) return RGB(0xD7, 0xB3, 0xFF);
    if (!strcmp(n, "none")) return RGB(0x3C, 0x42, 0x50);
    return RGB(0xFF, 0xFF, 0xFF);
}

static void penLine(HDC dc, int x0, int y0, int x1, int y1, COLORREF c, int w)
{
    HPEN p = CreatePen(PS_SOLID, w, c);
    HGDIOBJ o = SelectObject(dc, p);
    MoveToEx(dc, x0, y0, 0);
    LineTo(dc, x1, y1);
    SelectObject(dc, o);
    DeleteObject(p);
}

static void penCircle(HDC dc, int cx, int cy, int r, COLORREF c, int w, int fill)
{
    HPEN p = CreatePen(PS_SOLID, w, c);
    HGDIOBJ op = SelectObject(dc, p);
    HBRUSH br = fill ? CreateSolidBrush(c) : (HBRUSH)GetStockObject(NULL_BRUSH);
    HGDIOBJ ob = SelectObject(dc, br);
    Ellipse(dc, cx - r, cy - r, cx + r, cy + r);
    SelectObject(dc, op);
    SelectObject(dc, ob);
    DeleteObject(p);
    if (fill) DeleteObject(br);
}

static void drawHead(HDC dc, int x, int y, int r, COLORREF c)
{
    penCircle(dc, x, y, r, c, 8, 0);
}

static void drawStand(HDC dc, COLORREF c)
{
    drawHead(dc, 150, 78, 18, c);
    penLine(dc, 150, 96, 150, 168, c, 8);
    penLine(dc, 150, 118, 112, 150, c, 8);
    penLine(dc, 150, 118, 188, 150, c, 8);
    penLine(dc, 150, 168, 124, 228, c, 8);
    penLine(dc, 150, 168, 176, 228, c, 8);
}

static void drawWalk(HDC dc, COLORREF c)
{
    double s = sin(g_phase);
    drawHead(dc, 150 + (int)(s * 4), 78, 18, c);
    penLine(dc, 150, 96, 150 + (int)(s * 6), 168, c, 8);
    penLine(dc, 150, 118, 116 - (int)(s * 18), 148, c, 8);
    penLine(dc, 150, 118, 184 + (int)(s * 18), 148, c, 8);
    penLine(dc, 150, 168, 122 - (int)(s * 26), 230, c, 8);
    penLine(dc, 150, 168, 178 + (int)(s * 26), 230, c, 8);
}

static void drawAttack(HDC dc, COLORREF c)
{
    double swing = sin(g_phase * 1.6);
    drawHead(dc, 138, 80, 18, c);
    penLine(dc, 142, 98, 150, 170, c, 8);
    penLine(dc, 146, 122, 108, 156, c, 8);
    int x2 = 168 + (int)(62 * cos(swing * 0.9));
    int y2 = 118 + (int)(62 * sin(swing * 0.9));
    penLine(dc, 146, 120, x2, y2, c, 8);
    penLine(dc, 150, 170, 128, 228, c, 8);
    penLine(dc, 150, 170, 176, 228, c, 8);
}

static void drawPickup(HDC dc, COLORREF c)
{
    int bob = (int)(sin(g_phase) * 3);
    drawHead(dc, 168, 118 + bob, 16, c);
    penLine(dc, 156, 132, 132, 176, c, 8);
    penLine(dc, 148, 150, 196, 188, c, 8);
    penLine(dc, 140, 168, 118, 214, c, 8);
    penLine(dc, 138, 174, 168, 226, c, 8);
    penCircle(dc, 208, 214, 8, c, 1, 1);
}

static void drawTurn(HDC dc, COLORREF c)
{
    drawHead(dc, 156, 78, 16, c);
    penLine(dc, 156, 94, 150, 170, c, 8);
    penLine(dc, 154, 120, 188, 146, c, 8);
    penLine(dc, 150, 170, 142, 228, c, 8);
    penLine(dc, 150, 170, 164, 228, c, 8);
    HPEN p = CreatePen(PS_SOLID, 8, c);
    HGDIOBJ o = SelectObject(dc, p);
    Arc(dc, 108, 96, 178, 166, 178, 120, 120, 96);
    SelectObject(dc, o);
    DeleteObject(p);
}

static void drawDamaged(HDC dc, COLORREF c)
{
    drawHead(dc, 168, 86, 18, c);
    penLine(dc, 160, 104, 176, 168, c, 8);
    penLine(dc, 164, 122, 128, 100, c, 8);
    penLine(dc, 164, 128, 196, 108, c, 8);
    penLine(dc, 176, 168, 150, 226, c, 8);
    penLine(dc, 176, 168, 198, 220, c, 8);
}

static void drawSpell(HDC dc, COLORREF c)
{
    drawStand(dc, c);
    int xs[3] = {118, 150, 182};
    for (int i = 0; i < 3; i++) {
        int r = 5 + ((int)g_phase + i) % 3;
        penCircle(dc, xs[i], 42, r, c, 1, 1);
    }
}

static void drawDeath(HDC dc, COLORREF c)
{
    drawHead(dc, 78, 168, 16, c);
    penLine(dc, 96, 168, 210, 168, c, 8);
    penLine(dc, 150, 168, 132, 140, c, 8);
    penLine(dc, 150, 168, 168, 196, c, 8);
}

static void drawEmpty(HDC dc)
{
    COLORREF c = RGB(0x3C, 0x42, 0x50);
    penCircle(dc, 150, 150, 36, c, 8, 0);
}

static void drawCommand(HDC dc, const char *n)
{
    if (!n || !strcmp(n, "none")) return;
    COLORREF c = RGB(0xF4, 0xF7, 0xFB);
    if (!strcmp(n, "move")) {
        penLine(dc, 126, 262, 146, 248, c, 6);
        penLine(dc, 146, 248, 166, 262, c, 6);
        penLine(dc, 156, 262, 176, 248, c, 6);
        penLine(dc, 176, 248, 196, 262, c, 6);
    } else if (!strcmp(n, "attack")) {
        penLine(dc, 132, 268, 168, 244, c, 6);
        penLine(dc, 150, 270, 186, 246, c, 6);
    } else if (!strcmp(n, "interact")) {
        penLine(dc, 150, 242, 168, 258, c, 6);
        penLine(dc, 168, 258, 150, 274, c, 6);
        penLine(dc, 150, 274, 132, 258, c, 6);
        penLine(dc, 132, 258, 150, 242, c, 6);
    }
}

static void paint(HWND hwnd)
{
    PAINTSTRUCT ps;
    HDC hdc = BeginPaint(hwnd, &ps);
    HDC mem = CreateCompatibleDC(hdc);
    HBITMAP bm = CreateCompatibleBitmap(hdc, W, H);
    HGDIOBJ old = SelectObject(mem, bm);

    RECT rc = {0, 0, W, H};
    HBRUSH bg = CreateSolidBrush(RGB(0x16, 0x18, 0x1E));
    FillRect(mem, &rc, bg);
    DeleteObject(bg);

    const char *bn = g_ok ? lc_bodyOf(g_body) : "none";
    const char *cn = g_ok ? lc_cmdOf(g_cmd) : "none";
    COLORREF col = bodyColor(bn);

    if (!g_ok)
        drawEmpty(mem);
    else if (!strcmp(bn, "walk") || !strcmp(bn, "walkback"))
        drawWalk(mem, col);
    else if (!strcmp(bn, "attack"))
        drawAttack(mem, col);
    else if (!strcmp(bn, "pickup"))
        drawPickup(mem, col);
    else if (!strcmp(bn, "turn"))
        drawTurn(mem, col);
    else if (!strcmp(bn, "damaged"))
        drawDamaged(mem, col);
    else if (!strcmp(bn, "spell"))
        drawSpell(mem, col);
    else if (!strcmp(bn, "death"))
        drawDeath(mem, col);
    else
        drawStand(mem, col);

    drawCommand(mem, cn);

    if (g_font) SelectObject(mem, g_font);
    SetBkMode(mem, TRANSPARENT);
    SetTextColor(mem, RGB(0xA8, 0xB0, 0xBC));
    char lab[96];
    snprintf(lab, sizeof lab, "%s | %s", bn, cn);
    TextOutA(mem, 10, 8, lab, (int)strlen(lab));
    if (g_ok) {
        snprintf(lab, sizeof lab, "0x%X  0x%X  io %u",
                 g_body, g_cmd, (unsigned)g_ioctl);
        TextOutA(mem, 10, 26, lab, (int)strlen(lab));
    }

    BitBlt(hdc, 0, 0, W, H, mem, 0, 0, SRCCOPY);
    SelectObject(mem, old);
    DeleteObject(bm);
    DeleteDC(mem);
    EndPaint(hwnd, &ps);
}

static void tickPoll(void)
{
    g_phase += 0.55;
    g_ioctl = 0;
    g_ok = lc_pollSelfBodyFast();
    if (g_ok) {
        g_body = lc_selfBodyAct;
        g_cmd = lc_selfCmdVft;
    }
    InvalidateRect(g_wnd, NULL, FALSE);
    UpdateWindow(g_wnd);
}

static LRESULT CALLBACK wp(HWND h, UINT m, WPARAM w, LPARAM l)
{
    if (m == WM_PAINT) {
        paint(h);
        return 0;
    }
    if (m == WM_TIMER && w == TIMER_ID) {
        tickPoll();
        return 0;
    }
    if (m == WM_KEYDOWN) {
        int vk = (int)w;
        if (vk == 'Q' || vk == VK_ESCAPE) {
            g_quit = 1;
            PostQuitMessage(0);
        }
        return 0;
    }
    if (m == WM_DESTROY) {
        KillTimer(h, TIMER_ID);
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcA(h, m, w, l);
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg = lcreg_resolve("10_5/registry/LC930_REGISTRY.txt",
                                    "registry/LC930_REGISTRY.txt");
    for (int i = 1; i < argc; i++) {
        if (strstr(argv[i], "REGISTRY") || strstr(argv[i], ".txt"))
            reg = argv[i];
    }
    lcreg_load(lcreg_resolve(reg, "registry/LC930_REGISTRY.txt"));
    lc_reg_apply();

    if (lc_attach()) {
        MessageBoxA(0, "attach fail (LC.exe / WinNotify)", "bodyactview", MB_ICONERROR);
        return 1;
    }
    if (!lc_anchor()) {
        MessageBoxA(0, "anchor fail", "bodyactview", MB_ICONERROR);
        SignedClose();
        return 2;
    }

    HINSTANCE hi = GetModuleHandleA(0);
    g_font = CreateFontA(14, 0, 0, 0, FW_BOLD, 0, 0, 0, DEFAULT_CHARSET,
                         OUT_DEFAULT_PRECIS, CLIP_DEFAULT_PRECIS, CLEARTYPE_QUALITY,
                         DEFAULT_PITCH, "Consolas");

    WNDCLASSA wc;
    memset(&wc, 0, sizeof wc);
    wc.lpfnWndProc = wp;
    wc.hInstance = hi;
    wc.lpszClassName = "bodyactview_930";
    wc.hCursor = LoadCursor(0, IDC_ARROW);
    wc.hbrBackground = (HBRUSH)(COLOR_WINDOW + 1);
    RegisterClassA(&wc);

    g_wnd = CreateWindowExA(
        WS_EX_TOPMOST | WS_EX_APPWINDOW, wc.lpszClassName, "bodyactview",
        WS_OVERLAPPED | WS_CAPTION | WS_SYSMENU | WS_MINIMIZEBOX,
        CW_USEDEFAULT, CW_USEDEFAULT, W + 16, H + 39, 0, 0, hi, 0);
    if (!g_wnd) {
        SignedClose();
        return 3;
    }
    ShowWindow(g_wnd, SW_SHOW);
    timeBeginPeriod(1);
    SetTimer(g_wnd, TIMER_ID, TICK_MS, 0);
    tickPoll();

    MSG msg;
    while (!g_quit && GetMessageA(&msg, 0, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageA(&msg);
    }

    KillTimer(g_wnd, TIMER_ID);
    timeEndPeriod(1);
    if (g_font) DeleteObject(g_font);
    SignedClose();
    return 0;
}
