/* ============================================================================
 * ec_keyboard.c - Interception loading and physical key injection
 * ========================================================================== */
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <stdio.h>
#include <string.h>

#include "ec_internal.h"

/* ---------------------------------------------------------------- Interception */
typedef void* InterceptionContext;
typedef int   InterceptionDevice;

typedef InterceptionContext (__cdecl *pfn_ic_create)(void);
typedef void                 (__cdecl *pfn_ic_destroy)(InterceptionContext);
typedef int                  (__cdecl *pfn_ic_send)(InterceptionContext, InterceptionDevice,
                                                    const void*, unsigned int);
typedef int                  (__cdecl *pfn_ic_is_kb)(InterceptionDevice);

static HMODULE             g_ic_dll;
static pfn_ic_create       g_ic_create;
static pfn_ic_destroy      g_ic_destroy;
static pfn_ic_send         g_ic_send;
static pfn_ic_is_kb        g_ic_is_kb;
static INIT_ONCE           g_ic_once = INIT_ONCE_STATIC_INIT;

static BOOL CALLBACK ec_ic_load_once(PINIT_ONCE once, PVOID param, PVOID* ctx)
{
    wchar_t path[MAX_PATH];
    (void)once; (void)param; (void)ctx;

    /* Prefer interception.dll next to the host executable. */
    if (GetModuleFileNameW(NULL, path, MAX_PATH)) {
        wchar_t* slash = wcsrchr(path, L'\\');
        if (slash) {
            size_t prefix = (size_t)(slash - path) + 1;
            if (prefix + 18 < MAX_PATH) {
                wcscpy_s(slash + 1, MAX_PATH - prefix, L"interception.dll");
                g_ic_dll = LoadLibraryW(path);
            }
        }
    }
    if (!g_ic_dll)
        g_ic_dll = LoadLibraryW(L"interception.dll");
    if (!g_ic_dll)
        return TRUE;   /* initialization finished: unavailable */

    g_ic_create  = (pfn_ic_create)GetProcAddress(g_ic_dll, "interception_create_context");
    g_ic_destroy = (pfn_ic_destroy)GetProcAddress(g_ic_dll, "interception_destroy_context");
    g_ic_send    = (pfn_ic_send)GetProcAddress(g_ic_dll, "interception_send");
    g_ic_is_kb   = (pfn_ic_is_kb)GetProcAddress(g_ic_dll, "interception_is_keyboard");

    if (!g_ic_create || !g_ic_destroy || !g_ic_send) {
        FreeLibrary(g_ic_dll);
        g_ic_dll = NULL;
    }
    return TRUE;
}

BOOL ec_ic_load(void)
{
    InitOnceExecuteOnce(&g_ic_once, ec_ic_load_once, NULL, NULL);
    return g_ic_dll && g_ic_create && g_ic_destroy && g_ic_send;
}

BOOL ec_ic_open(EcContext* ctx)
{
    if (!ctx) return FALSE;
    if (ctx->ic) return TRUE;
    if (!ec_ic_load()) return FALSE;

    ctx->ic = g_ic_create();
    if (!ctx->ic) return FALSE;

    /* interception_is_keyboard is only a range check, so slot 1 is always
     * "a keyboard" even when this PC's strokes are accepted on a later slot.
     * A key-UP for scancode 0x04 is a no-op. Keep the first slot that accepts. */
    ctx->ic_keyboard = 0;
    for (int d = 1; d <= 10; ++d) {
        unsigned char buf[64];
        memset(buf, 0, sizeof(buf));
        *(unsigned short*)(buf + 0) = 0x04;
        *(unsigned short*)(buf + 2) = 0x01; /* key up */
        if (g_ic_send(ctx->ic, d, buf, 1) == 1) {
            ctx->ic_keyboard = d;
            break;
        }
    }
    if (!ctx->ic_keyboard) {
        if (g_ic_destroy) g_ic_destroy(ctx->ic);
        ctx->ic = NULL;
        ctx->interception_ok = FALSE;
        return FALSE;
    }
    ctx->interception_ok = TRUE;
    if (ctx->res)
        ec_result_message(ctx->res, L"keyboard slot %d", ctx->ic_keyboard);
    return TRUE;
}

void ec_ic_close(EcContext* ctx)
{
    if (!ctx) return;
    if (ctx->ic && g_ic_destroy) g_ic_destroy(ctx->ic);
    ctx->ic = NULL;
    ctx->interception_ok = FALSE;
}

/* One stroke per call.  A raw 64-byte buffer avoids depending on the exact
 * size of the InterceptionStroke union exported by different DLL versions. */
BOOL ec_ic_key(EcContext* ctx, int scancode, int e0, int up)
{
    unsigned char buf[64];

    if (!ctx || !ctx->ic || !g_ic_send) return FALSE;
    memset(buf, 0, sizeof(buf));
    *(unsigned short*)(buf + 0) = (unsigned short)scancode;
    *(unsigned short*)(buf + 2) = (unsigned short)((up ? 0x01 : 0x00) | (e0 ? 0x02 : 0x00));
    return g_ic_send(ctx->ic, ctx->ic_keyboard, buf, 1) == 1;
}

BOOL ec_ic_press(EcContext* ctx, int scancode, int e0, int hold_ms)
{
    if (!ec_ic_key(ctx, scancode, e0, 0)) return FALSE;
    Sleep((DWORD)(hold_ms > 0 ? hold_ms : EC_KEY_HOLD_MS));
    return ec_ic_key(ctx, scancode, e0, 1);
}

/* ---------------------------------------------------------------- VK keys */
static int ec_vk_extended(WORD vk)
{
    switch (vk) {
    case VK_LEFT: case VK_RIGHT: case VK_UP: case VK_DOWN:
    case VK_HOME: case VK_END: case VK_PRIOR: case VK_NEXT:
    case VK_INSERT: case VK_DELETE:
        return 1;
    default:
        return 0;
    }
}

BOOL ec_send_vk(EcContext* ctx, WORD vk)
{
    int scan;
    int e0;
    HWND h;

    if (!ctx) return FALSE;
    scan = (int)MapVirtualKeyW(vk, MAPVK_VK_TO_VSC);
    e0 = ec_vk_extended(vk);

    /* Preferred path: a real hardware-style key through Interception. */
    if (ctx->ic && ec_ic_press(ctx, scan, e0, 10))
        return TRUE;

    /* Fallback 1: message to the focused control. */
    h = ctx->focus ? ctx->focus : ctx->hwnd;
    if (h) {
        LPARAM down = 1 | ((LPARAM)(scan & 0xFF) << 16) | (e0 ? ((LPARAM)1 << 24) : 0);
        LPARAM up   = down | 0xC0000000;
        if (PostMessageW(h, WM_KEYDOWN, vk, down)) {
            Sleep(10);
            PostMessageW(h, WM_KEYUP, vk, up);
            return TRUE;
        }
        if (GetLastError() == ERROR_ACCESS_DENIED && ctx->res)
            ctx->res->os_error = ERROR_ACCESS_DENIED;
    }

    /* Fallback 2: SendInput (goes to the foreground window). */
    {
        INPUT in[2];
        memset(in, 0, sizeof(in));
        in[0].type = INPUT_KEYBOARD;
        if (vk == VK_RETURN || vk == VK_TAB || vk == VK_ESCAPE) {
            in[0].ki.wVk = vk;
            in[0].ki.wScan = 0;
            in[0].ki.dwFlags = 0;
        } else {
            in[0].ki.wVk = 0;
            in[0].ki.wScan = (WORD)(scan & 0xFF);
            in[0].ki.dwFlags = KEYEVENTF_SCANCODE | (e0 ? KEYEVENTF_EXTENDEDKEY : 0);
        }
        in[1] = in[0];
        in[1].ki.dwFlags |= KEYEVENTF_KEYUP;
        return SendInput(2, in, sizeof(INPUT)) == 2;
    }
}

/* US layout scancode for one ASCII key used by the 2-beolsik mapping.
 * Uppercase letters return shift=1. */
int ec_ascii_to_scan(WCHAR c, int* shift)
{
    HKL us;
    SHORT v;
    BYTE vk;

    if (shift) *shift = 0;
    us = LoadKeyboardLayoutW(L"00000409", 0);
    if (!us) return -1;
    v = VkKeyScanExW(c, us);
    if (v == -1) return -1;
    vk = LOBYTE(v);
    if (shift) *shift = (HIBYTE(v) & 1) ? 1 : 0;
    return (int)MapVirtualKeyExW(vk, MAPVK_VK_TO_VSC, us);
}
