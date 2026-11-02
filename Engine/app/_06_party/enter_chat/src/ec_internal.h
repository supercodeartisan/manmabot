/* ============================================================================
 * ec_internal.h - private contract between the enter_chat source files
 * ========================================================================== */
#ifndef EC_INTERNAL_H
#define EC_INTERNAL_H

#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <stdint.h>

#include "enter_chat.h"

#define EC_MAX_KEYS_PER_CHAR     8
#define EC_DEFAULT_CPS           10.0
#define EC_DEFAULT_JAMO_DELAY    8
#define EC_DEFAULT_FOCUS_TIMEOUT 1500
#define EC_KEY_HOLD_MS           3

typedef struct EcContext {
    EcRequest  req;
    EcResult*  res;

    HWND       hwnd;          /* top-level / caller-provided target          */
    HWND       focus;         /* focused child used for WM_CHAR              */
    DWORD      pid;

    BOOL       elevated;
    BOOL       uipi_blocked;

    /* Interception */
    BOOL       interception_ok;
    void*      ic;            /* InterceptionContext                         */
    int        ic_keyboard;   /* injection keyboard device                   */

    /* timing */
    uint32_t   rng;
    DWORD      start_tick;
    double     char_interval_ms;
    int        jitter_ms;
    int        jamo_delay_ms;

    /* Korean layout / IME */
    HKL        old_hkl;
    HKL        ko_hkl;
    BOOL       layout_switched;
    DWORD      old_conv;
    DWORD      old_sent;
    BOOL       changed_conv;
    HWND       ime_wnd;          /* default IME window used for WM_IME_CONTROL */
    DWORD      ime_old_mode;
    BOOL       ime_mode_forced;
    BOOL       hangul_started;
} EcContext;

/* ---------------------------------------------------------------- target */
HWND         ec_find_window_for_pid(DWORD pid);
HWND         ec_resolve_focus(HWND top);
BOOL         ec_is_foreground(HWND top);
BOOL         ec_force_foreground(HWND top, DWORD timeout_ms);
BOOL         ec_is_elevated(void);
BOOL         ec_uipi_blocked(HWND hwnd);
unsigned int ec_process_integrity(DWORD pid);

/* --------------------------------------------------------------- keyboard */
BOOL ec_ic_load(void);
BOOL ec_ic_open(EcContext* ctx);
void ec_ic_close(EcContext* ctx);
BOOL ec_ic_key(EcContext* ctx, int scancode, int e0, int up);
BOOL ec_ic_press(EcContext* ctx, int scancode, int e0, int hold_ms);
BOOL ec_send_vk(EcContext* ctx, WORD vk);
BOOL ec_sendinput_press(int scancode, int shift, int hold_ms);
int  ec_ascii_to_scan(WCHAR c, int* shift);

/* ----------------------------------------------------------------- hangul */
BOOL ec_is_hangul(wchar_t c);
int  ec_hangul_keys(wchar_t c, char* out, int max);

#ifndef EC_TEST
BOOL ec_hangul_prepare(EcContext* ctx, HWND hwnd);
void ec_hangul_done(EcContext* ctx);
BOOL ec_hangul_commit(EcContext* ctx);
/* ASCII-only line (invite accept Y): foreground + English IME, then restore. */
BOOL ec_english_prepare(EcContext* ctx, HWND hwnd);
void ec_english_done(EcContext* ctx);
#endif

/* ------------------------------------------------------------- text/time */
int  ec_utf8_to_wide(const char* s, wchar_t** out);
BOOL ec_post_char(EcContext* ctx, WCHAR c);
BOOL ec_send_unicode(EcContext* ctx, WCHAR c);
void ec_sleep_ms(double ms);
uint32_t ec_rand_next(EcContext* ctx);
int  ec_jitter(EcContext* ctx);
void ec_result_message(EcResult* res, const wchar_t* fmt, ...);

#endif /* EC_INTERNAL_H */
