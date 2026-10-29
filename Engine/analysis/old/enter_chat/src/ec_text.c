/* ============================================================================
 * ec_text.c - UTF-8 conversion, WM_CHAR/SendInput, timing and jitter
 * ========================================================================== */
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "ec_internal.h"

/* ---------------------------------------------------------------- UTF-8 */
int ec_utf8_to_wide(const char* s, wchar_t** out)
{
    int need;
    wchar_t* w;

    if (out) *out = NULL;
    if (!s || !out) return 0;

    need = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, NULL, 0);
    if (need <= 0) return 0;
    w = (wchar_t*)calloc((size_t)need, sizeof(wchar_t));
    if (!w) return 0;
    if (MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, s, -1, w, need) <= 0) {
        free(w);
        return 0;
    }
    *out = w;
    return 1;
}

/* ---------------------------------------------------------------- timing */
void ec_sleep_ms(double ms)
{
    if (ms <= 0.0) return;
    if (ms > 60000.0) ms = 60000.0;
    Sleep((DWORD)(ms + 0.5));
}

uint32_t ec_rand_next(EcContext* ctx)
{
    uint32_t x;
    if (!ctx) return 0;
    x = ctx->rng ? ctx->rng : 0x9E3779B9u;
    x ^= x << 13;
    x ^= x >> 17;
    x ^= x << 5;
    ctx->rng = x;
    return x;
}

int ec_jitter(EcContext* ctx)
{
    uint32_t span;
    if (!ctx || ctx->jitter_ms <= 0) return 0;
    span = (uint32_t)(ctx->jitter_ms * 2 + 1);
    return (int)(ec_rand_next(ctx) % span) - ctx->jitter_ms;
}

/* ---------------------------------------------------------------- text out */
BOOL ec_send_unicode(EcContext* ctx, WCHAR c)
{
    INPUT in[2];
    (void)ctx;

    memset(in, 0, sizeof(in));
    in[0].type = INPUT_KEYBOARD;
    in[0].ki.wVk = 0;
    in[0].ki.wScan = c;
    in[0].ki.dwFlags = KEYEVENTF_UNICODE;
    in[1] = in[0];
    in[1].ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP;
    return SendInput(2, in, sizeof(INPUT)) == 2;
}

BOOL ec_post_char(EcContext* ctx, WCHAR c)
{
    HWND h;
    DWORD err;

    if (!ctx) return FALSE;
    h = ctx->focus ? ctx->focus : ctx->hwnd;
    if (!h) return FALSE;

    SetLastError(0);
    if (PostMessageW(h, WM_CHAR, (WPARAM)(unsigned short)c, 1))
        return TRUE;

    err = GetLastError();
    if (ctx->res && err) ctx->res->os_error = err;

    if (ctx->req.flags & EC_FLAG_SENDINPUT_FALLBACK)
        return ec_send_unicode(ctx, c);
    return FALSE;
}

/* ---------------------------------------------------------------- messages */
void ec_result_message(EcResult* res, const wchar_t* fmt, ...)
{
    size_t used;
    va_list ap;

    if (!res || !fmt) return;
    used = wcslen(res->message);
    if (used >= 511) return;
    if (used > 0) {
        res->message[used++] = L' ';
        res->message[used] = 0;
    }
    va_start(ap, fmt);
    _vsnwprintf_s(res->message + used, 512 - used, _TRUNCATE, fmt, ap);
    va_end(ap);
}
