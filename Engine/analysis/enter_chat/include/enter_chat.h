/* ============================================================================
 * enter_chat.h - public API of the enter_chat module
 *
 * Purpose
 *   Inject an arbitrary mixed text (Hangul / Chinese / ASCII / symbols) into a
 *   window that belongs to a given process id (PID), at a requested typing
 *   speed, with per-character random jitter, and optionally press Enter at the
 *   end.
 *
 * Design
 *   - Hangul is sent as physical 2-beolsik jamo keystrokes through Interception
 *     and composed by the installed Korean IME.  This bypasses clients that
 *     drop Hangul from WM_CHAR after an ANSI codepage conversion.
 *   - Other characters are sent with PostMessage(WM_CHAR) (SendInput fallback
 *     optional).
 *   - Enter / Esc / Tab are sent as physical keys through Interception.
 *
 * Build
 *   Build with ENTER_CHAT_EXPORTS for the DLL.  Consumers include this header
 *   and link enter_chat.lib (or define ENTER_CHAT_STATIC for a static build).
 * ========================================================================== */
#ifndef ENTER_CHAT_H
#define ENTER_CHAT_H

#include <windows.h>

#ifdef __cplusplus
extern "C" {
#endif

#if defined(ENTER_CHAT_STATIC)
#  define EC_API
#elif defined(ENTER_CHAT_EXPORTS)
#  define EC_API __declspec(dllexport)
#else
#  define EC_API __declspec(dllimport)
#endif

#define EC_VERSION_MAJOR 1
#define EC_VERSION_MINOR 1
#define EC_VERSION_PATCH 0
#define EC_VERSION_STRING L"1.1.0"

/* ------------------------------------------------------------------------- */
/* Status codes                                                              */
/* ------------------------------------------------------------------------- */
typedef enum EcStatus {
    EC_OK             = 0,   /* text (and optional Enter) sent             */
    EC_E_ARGUMENT     = 1,   /* invalid request / missing text             */
    EC_E_PID          = 2,   /* PID has no usable window / PID mismatch    */
    EC_E_WINDOW       = 3,   /* target HWND is not valid                   */
    EC_E_ELEVATION    = 4,   /* target is higher integrity; run elevated   */
    EC_E_INTERCEPTION = 5,   /* Interception DLL/driver unavailable        */
    EC_E_IME          = 6,   /* Korean layout/IME could not be prepared    */
    EC_E_FOCUS        = 7,   /* target could not be brought to foreground  */
    EC_E_TEXT         = 8,   /* one or more characters could not be sent   */
    EC_E_INTERNAL     = 9    /* allocation / internal failure              */
} EcStatus;

/* ------------------------------------------------------------------------- */
/* Optional flags                                                            */
/* ------------------------------------------------------------------------- */
#define EC_FLAG_CLEAR_FIRST         0x00000001u  /* send Esc before typing     */
#define EC_FLAG_OPEN_CHAT           0x00000002u  /* send Enter before typing   */
#define EC_FLAG_NO_FOCUS            0x00000004u  /* caller guarantees focus    */
#define EC_FLAG_SENDINPUT_FALLBACK  0x00000008u  /* SendInput if WM_CHAR fails */
#define EC_FLAG_DRY_RUN             0x00000010u  /* plan/count only, no input  */
#define EC_FLAG_NO_START_COMMIT     0x00000020u  /* skip initial IME commit    */

/* ------------------------------------------------------------------------- */
/* Request                                                                   */
/* ------------------------------------------------------------------------- */
typedef struct EcRequest {
    /* UTF-16, NUL-terminated text. Required. */
    const wchar_t* text;

    /* Target selection.  Use pid (normal) and/or an explicit hwnd.
     * If both are set, the window's process id must match pid. */
    DWORD pid;
    HWND  hwnd;

    /* Typing speed in characters per second. <= 0 selects 10.0.
     * The pause after each character is 1000 / chars_per_second ms. */
    double chars_per_second;

    /* Random offset in [-jitter_ms, +jitter_ms] added to each character
     * pause.  0 disables jitter.  The resulting pause is clamped to >= 0. */
    int jitter_ms;

    /* Delay between jamo keys inside one Hangul syllable (default 8 ms).
     * This is not affected by chars_per_second; it only lets the IME
     * consume each jamo before the next one arrives. */
    int jamo_delay_ms;

    /* Press Enter after the text (also sends the chat message in games). */
    BOOL press_enter;

    /* EC_FLAG_* bit mask. */
    DWORD flags;

    /* How long to wait for the target to become foreground (default 1500 ms). */
    DWORD focus_timeout_ms;
} EcRequest;

/* ------------------------------------------------------------------------- */
/* Result                                                                    */
/* ------------------------------------------------------------------------- */
typedef struct EcResult {
    EcStatus status;          /* EC_OK or the first fatal error              */
    DWORD    os_error;        /* last Win32 error, if relevant               */
    DWORD    pid;             /* resolved target PID                         */
    HWND     hwnd;            /* resolved target window                      */

    int      chars;           /* code points sent (or planned in dry-run)    */
    int      keys;            /* text key events (jamo keys + WM_CHAR)       */
    int      failed;          /* code points that could not be sent          */
    int      skipped;         /* control code points skipped                 */

    BOOL     enter_pressed;   /* Enter key event was sent                    */
    DWORD    elapsed_ms;      /* wall time of this call                      */

    /* Human-readable warnings / error detail. UTF-16. */
    wchar_t  message[512];
} EcResult;

/* ------------------------------------------------------------------------- */
/* API                                                                       */
/* ------------------------------------------------------------------------- */

/* Run one injection request.  Returns (int)result->status (0 == success).
 * The call is synchronous and internally serialized. */
EC_API int __cdecl ec_run(const EcRequest* request, EcResult* result);

/* Convenience wrapper: text is UTF-8.  Defaults: jamo_delay=8, flags=0. */
EC_API int __cdecl ec_run_utf8(const char* text_utf8, DWORD pid,
                               double chars_per_second, int jitter_ms,
                               BOOL press_enter, EcResult* result);

/* Press one physical key (set-1 scancode, e0 for extended) in the target
 * window: focus -> Interception down/up -> done.  Interception only (no
 * message / SendInput fallback).  hwnd may be NULL when pid is set.
 * hold_ms <= 0 selects 30.  Returns (int)result->status. */
EC_API int __cdecl ec_press_key(DWORD pid, HWND hwnd, int scancode, int e0,
                                int hold_ms, DWORD focus_timeout_ms,
                                EcResult* result);

/* Decompose one Hangul character into 2-beolsik QWERTY keys.
 * Uppercase letters mean "with Shift".  Returns key count, 0 if unsupported.
 * Example: L'\uC548' ("안") -> "dks" (3). */
EC_API int __cdecl ec_decompose_hangul(wchar_t ch, char* keys, int max_keys);

/* Diagnostics. */
EC_API const wchar_t* __cdecl ec_status_string(EcStatus status);
EC_API const wchar_t* __cdecl ec_version(void);
EC_API BOOL __cdecl ec_is_elevated(void);

#ifdef __cplusplus
}
#endif
#endif /* ENTER_CHAT_H */
