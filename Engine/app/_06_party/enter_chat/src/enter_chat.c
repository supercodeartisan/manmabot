/* ============================================================================
 * enter_chat.c - orchestrator of the enter_chat module
 *
 * Flow
 *   validate -> resolve PID/window -> preflight (UIPI, elevation, Interception)
 *   -> focus -> Korean layout/IME -> optional Esc/Enter -> text
 *   -> optional final Enter -> restore layout -> result.
 *
 * Text model
 *   - Hangul: 2-beolsik jamo keys through Interception + Korean IME.
 *   - Other:  PostMessage(WM_CHAR); optional SendInput fallback.
 *   - Tab:    physical Tab key.  Esc/Enter: physical keys.
 *
 * Timing
 *   - Pause after each character = 1000 / chars_per_second + jitter.
 *   - Jitter is uniform in [-jitter_ms, +jitter_ms], clamped to >= 0.
 *   - Jamo keys inside a syllable use jamo_delay_ms (default 8 ms).
 * ========================================================================== */
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <mmsystem.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>

#include "enter_chat.h"
#include "ec_internal.h"

#pragma comment(lib, "user32.lib")
#pragma comment(lib, "imm32.lib")
#pragma comment(lib, "winmm.lib")
#pragma comment(lib, "advapi32.lib")

/* ---------------------------------------------------------------- lock */
static INIT_ONCE      g_lock_once = INIT_ONCE_STATIC_INIT;
static CRITICAL_SECTION g_lock;

static BOOL CALLBACK ec_init_lock(PINIT_ONCE once, PVOID param, PVOID* ctx)
{
    (void)once; (void)param; (void)ctx;
    InitializeCriticalSection(&g_lock);
    return TRUE;
}

/* ---------------------------------------------------------------- helpers */
typedef struct EcTextPlan {
    int has_hangul;
    int needs_wmchar;
    int total_chars;
    int planned_keys;
} EcTextPlan;

static int ec_next_codepoint(const wchar_t* p, uint32_t* out)
{
    uint32_t c = (uint32_t)p[0];
    if (c >= 0xD800 && c <= 0xDBFF &&
        p[1] >= 0xDC00 && p[1] <= 0xDFFF) {
        *out = 0x10000u + ((c - 0xD800u) << 10) + ((uint32_t)p[1] - 0xDC00u);
        return 2;
    }
    *out = c;
    return 1;
}

static void ec_analyze_text(const wchar_t* text, EcTextPlan* plan)
{
    const wchar_t* p;

    memset(plan, 0, sizeof(*plan));
    for (p = text; *p; ) {
        uint32_t cp;
        int units = ec_next_codepoint(p, &cp);

        if (cp == L'\t') {
            plan->planned_keys++;
        } else if (cp < 0x20) {
            /* control character: skipped */
        } else if (ec_is_hangul((wchar_t)cp)) {
            char keys[EC_MAX_KEYS_PER_CHAR];
            int n = ec_hangul_keys((wchar_t)cp, keys, EC_MAX_KEYS_PER_CHAR);
            if (n > 0) {
                plan->has_hangul = 1;
                plan->planned_keys += n;
            } else {
                plan->needs_wmchar = 1;
                plan->planned_keys++;
            }
        } else {
            plan->needs_wmchar = 1;
            plan->planned_keys += units;
        }
        plan->total_chars++;
        p += units;
    }
}

static void ec_set_error(EcResult* res, EcStatus status, const wchar_t* msg)
{
    res->status = status;
    if (msg) ec_result_message(res, L"%ls", msg);
}

/* ---------------------------------------------------------------- public */
const wchar_t* __cdecl ec_version(void)
{
    return EC_VERSION_STRING;
}

const wchar_t* __cdecl ec_status_string(EcStatus status)
{
    switch (status) {
    case EC_OK:             return L"ok";
    case EC_E_ARGUMENT:     return L"invalid argument";
    case EC_E_PID:          return L"pid/window not found";
    case EC_E_WINDOW:       return L"invalid target window";
    case EC_E_ELEVATION:    return L"elevation required";
    case EC_E_INTERCEPTION: return L"interception unavailable";
    case EC_E_IME:          return L"korean layout/IME unavailable";
    case EC_E_FOCUS:        return L"could not focus target";
    case EC_E_TEXT:         return L"some characters failed";
    case EC_E_INTERNAL:     return L"internal error";
    default:                return L"unknown status";
    }
}

int __cdecl ec_decompose_hangul(wchar_t ch, char* keys, int max_keys)
{
    return ec_hangul_keys(ch, keys, max_keys);
}

int __cdecl ec_run(const EcRequest* request, EcResult* result)
{
    EcResult local_result;
    EcResult* res;
    EcContext ctx;
    EcTextPlan plan;
    HWND target;
    HWND top;
    DWORD target_pid = 0;
    DWORD focus_timeout;
    DWORD t0;
    double cps;
    unsigned int target_integrity;
    unsigned int self_integrity;
    BOOL need_ic;
    BOOL timer_started = FALSE;
    int in_hangul = 0;
    int sent_chars = 0;
    int sent_keys = 0;
    int failed = 0;
    int skipped = 0;

    InitOnceExecuteOnce(&g_lock_once, ec_init_lock, NULL, NULL);
    EnterCriticalSection(&g_lock);

    if (!result) result = &local_result;
    res = result;
    memset(res, 0, sizeof(*res));
    res->status = EC_OK;
    t0 = GetTickCount();

    if (!request || !request->text) {
        ec_set_error(res, EC_E_ARGUMENT, L"request or text is NULL");
        goto cleanup_no_ctx;
    }

    memset(&ctx, 0, sizeof(ctx));
    ctx.req = *request;
    ctx.res = res;
    ctx.rng = (uint32_t)GetTickCount()
            ^ (uint32_t)GetCurrentProcessId()
            ^ (uint32_t)(uintptr_t)request;
    if (!ctx.rng) ctx.rng = 0x9E3779B9u;

    cps = request->chars_per_second;
    if (!(cps > 0.0)) cps = EC_DEFAULT_CPS;
    if (cps > 1000.0) cps = 1000.0;
    ctx.char_interval_ms = 1000.0 / cps;

    ctx.jitter_ms = request->jitter_ms;
    if (ctx.jitter_ms < 0) ctx.jitter_ms = 0;
    if (ctx.jitter_ms > 10000) ctx.jitter_ms = 10000;

    ctx.jamo_delay_ms = request->jamo_delay_ms > 0
                      ? request->jamo_delay_ms : EC_DEFAULT_JAMO_DELAY;
    if (ctx.jamo_delay_ms > 1000) ctx.jamo_delay_ms = 1000;

    focus_timeout = request->focus_timeout_ms
                  ? request->focus_timeout_ms : EC_DEFAULT_FOCUS_TIMEOUT;

    /* ------------------------------------------------------------ target */
    target = request->hwnd;
    if (target) {
        if (!IsWindow(target)) {
            ec_set_error(res, EC_E_WINDOW, L"target hwnd is not a valid window");
            goto cleanup_no_ctx;
        }
        GetWindowThreadProcessId(target, &target_pid);
        if (request->pid && target_pid != request->pid) {
            ec_set_error(res, EC_E_PID, L"target hwnd belongs to a different pid");
            goto cleanup_no_ctx;
        }
    } else if (request->pid) {
        target = ec_find_window_for_pid(request->pid);
        if (!target) {
            ec_set_error(res, EC_E_PID, L"no usable window found for the pid");
            goto cleanup_no_ctx;
        }
        target_pid = request->pid;
    } else {
        ec_set_error(res, EC_E_ARGUMENT, L"set pid or hwnd");
        goto cleanup_no_ctx;
    }

    top = GetAncestor(target, GA_ROOT);
    if (!top) top = target;
    ctx.hwnd = top;
    ctx.pid = target_pid;

    /* If the caller passed a specific child control, keep it as the text sink. */
    if (request->hwnd && target != top)
        ctx.focus = target;

    res->pid = target_pid;
    res->hwnd = target;

    ec_analyze_text(request->text, &plan);

    /* ------------------------------------------------------------ dry run */
    if (request->flags & EC_FLAG_DRY_RUN) {
        res->chars = plan.total_chars;
        res->keys = plan.planned_keys;
        res->status = EC_OK;
        ec_result_message(res, L"dry-run: %d chars, %d key events",
                          plan.total_chars, plan.planned_keys);
        goto cleanup_no_ctx;
    }

    /* ------------------------------------------------------------ UIPI */
    ctx.elevated = ec_is_elevated();
    target_integrity = ec_process_integrity(target_pid);
    self_integrity = ec_process_integrity(GetCurrentProcessId());
    ctx.uipi_blocked = ec_uipi_blocked(ctx.hwnd) ||
                       (target_integrity != 0xFFFFFFFF &&
                        self_integrity != 0xFFFFFFFF &&
                        target_integrity > self_integrity);

    if (ctx.uipi_blocked && !ctx.elevated && plan.needs_wmchar) {
        ec_set_error(res, EC_E_ELEVATION,
            L"target is at a higher integrity level; run the caller elevated "
            L"(WM_CHAR requires it)");
        goto cleanup_no_ctx;
    }
    if (ctx.uipi_blocked)
        ec_result_message(res, L"warning: target is at a higher integrity level");

    /* ------------------------------------------------------------ focus */
    if (!(request->flags & EC_FLAG_NO_FOCUS)) {
        if (!ec_force_foreground(ctx.hwnd, focus_timeout)) {
            ec_set_error(res, EC_E_FOCUS,
                L"could not bring the target to the foreground");
            goto cleanup_no_ctx;
        }
    }
    if (!ctx.focus)
        ctx.focus = ec_resolve_focus(ctx.hwnd);

    /* ------------------------------------------------------------ Interception */
    need_ic = plan.has_hangul || request->press_enter ||
              (request->flags & (EC_FLAG_CLEAR_FIRST | EC_FLAG_OPEN_CHAT)) != 0;

    if (plan.has_hangul) {
        if (!ec_ic_open(&ctx)) {
            ec_set_error(res, EC_E_INTERCEPTION,
                L"Interception unavailable (interception.dll / driver not installed)");
            goto cleanup;
        }
    } else if (need_ic) {
        if (!ec_ic_open(&ctx))
            ec_result_message(res,
                L"warning: Interception unavailable; using message/SendInput fallback");
    }

    /* ------------------------------------------------------------ Korean IME */
    timeBeginPeriod(1);
    timer_started = TRUE;

    /* ------------------------------------------------------------ optional reset */
    if (request->flags & EC_FLAG_CLEAR_FIRST) {
        ec_send_vk(&ctx, VK_ESCAPE);
        Sleep(180);
    }
    if (request->flags & EC_FLAG_OPEN_CHAT) {
        ec_send_vk(&ctx, VK_RETURN);
        Sleep(280);
    }

    /* Opening/closing an input line can move focus to another child control.
     * Re-resolve it unless the caller pinned an explicit HWND. */
    if (!request->hwnd)
        ctx.focus = ec_resolve_focus(ctx.hwnd);

    /* Prepare the Korean layout/IME on the final focus target. */
    if (plan.has_hangul) {
        if (!ec_hangul_prepare(&ctx, ctx.hwnd)) {
            ec_set_error(res, EC_E_IME,
                L"could not prepare the Korean layout/IME");
            goto cleanup;
        }
    }

    /* Flush a composition that a previous/manual IME run may have left. */
    if (plan.has_hangul && !(request->flags & EC_FLAG_NO_START_COMMIT))
        ec_hangul_commit(&ctx);

    /* ------------------------------------------------------------ text */
    {
        const wchar_t* p;
        for (p = request->text; *p; ) {
            uint32_t cp;
            int units = ec_next_codepoint(p, &cp);
            const wchar_t* start = p;
            p += units;

            if (cp == L'\t') {
                if (in_hangul) { ec_hangul_commit(&ctx); in_hangul = 0; }
                if (ec_send_vk(&ctx, VK_TAB)) {
                    sent_chars++;
                    sent_keys++;
                } else {
                    failed++;
                }
                ec_sleep_ms(ctx.char_interval_ms + ec_jitter(&ctx));
                continue;
            }
            if (cp < 0x20) {
                skipped++;
                continue;
            }

            if (ec_is_hangul((wchar_t)cp)) {
                char keys[EC_MAX_KEYS_PER_CHAR];
                int n = ec_hangul_keys((wchar_t)cp, keys, EC_MAX_KEYS_PER_CHAR);

                if (n > 0) {
                    BOOL ok = TRUE;
                    if (!in_hangul) in_hangul = 1;

                    for (int i = 0; i < n; ++i) {
                        int shift = 0;
                        int sc = ec_ascii_to_scan((WCHAR)(unsigned char)keys[i], &shift);
                        if (sc < 0) { ok = FALSE; break; }

                        if (shift) {
                            if (!ec_ic_key(&ctx, 0x2A, 0, 0)) ok = FALSE;
                            Sleep(3);
                        }
                        if (ec_ic_press(&ctx, sc, 0, EC_KEY_HOLD_MS)) sent_keys++;
                        else ok = FALSE;
                        if (shift) {
                            Sleep(3);
                            if (!ec_ic_key(&ctx, 0x2A, 0, 1)) ok = FALSE;
                        }
                        Sleep((DWORD)ctx.jamo_delay_ms);
                    }
                    if (ok) sent_chars++; else failed++;
                } else {
                    /* halfwidth or otherwise unsupported Hangul: WM_CHAR fallback */
                    if (in_hangul) { ec_hangul_commit(&ctx); in_hangul = 0; }
                    if (ec_post_char(&ctx, (WCHAR)cp)) {
                        sent_chars++;
                        sent_keys++;
                    } else {
                        failed++;
                    }
                }
                ec_sleep_ms(ctx.char_interval_ms + ec_jitter(&ctx));
                continue;
            }

            /* non-Hangul: WM_CHAR, one unit at a time (surrogate pairs included) */
            if (in_hangul) { ec_hangul_commit(&ctx); in_hangul = 0; }
            {
                BOOL ok = TRUE;
                int units_sent = 0;
                for (int u = 0; u < units; ++u) {
                    if (ec_post_char(&ctx, start[u])) {
                        units_sent++;
                    } else {
                        ok = FALSE;
                        break;
                    }
                }
                if (ok) {
                    sent_chars++;
                    sent_keys += units_sent;
                } else {
                    failed++;
                }
            }
            ec_sleep_ms(ctx.char_interval_ms + ec_jitter(&ctx));
        }
    }

    if (in_hangul) { ec_hangul_commit(&ctx); in_hangul = 0; }

    /* ------------------------------------------------------------ final Enter */
    if (request->press_enter) {
        BOOL ok = ec_send_vk(&ctx, VK_RETURN);
        Sleep(30);
        if (ok) {
            res->enter_pressed = TRUE;
        } else {
            failed++;
            ec_result_message(res, L"final Enter could not be sent");
        }
    }

    res->chars = sent_chars;
    res->keys = sent_keys;
    res->failed = failed;
    res->skipped = skipped;
    res->status = failed > 0 ? EC_E_TEXT : EC_OK;

cleanup:
    if (ctx.hangul_started) ec_hangul_done(&ctx);
    if (ctx.ic) ec_ic_close(&ctx);
    if (timer_started) timeEndPeriod(1);
    res->elapsed_ms = GetTickCount() - t0;
    LeaveCriticalSection(&g_lock);
    return (int)res->status;

cleanup_no_ctx:
    res->elapsed_ms = GetTickCount() - t0;
    LeaveCriticalSection(&g_lock);
    return (int)res->status;
}

int __cdecl ec_run_utf8(const char* text_utf8, DWORD pid,
                        double chars_per_second, int jitter_ms,
                        BOOL press_enter, EcResult* result)
{
    wchar_t* wide = NULL;
    EcRequest req;
    int rc;

    if (!text_utf8) {
        if (result) {
            memset(result, 0, sizeof(*result));
            result->status = EC_E_ARGUMENT;
            ec_result_message(result, L"text is NULL");
        }
        return EC_E_ARGUMENT;
    }
    if (!ec_utf8_to_wide(text_utf8, &wide)) {
        if (result) {
            memset(result, 0, sizeof(*result));
            result->status = EC_E_TEXT;
            ec_result_message(result, L"text is not valid UTF-8");
        }
        return EC_E_TEXT;
    }

    memset(&req, 0, sizeof(req));
    req.text = wide;
    req.pid = pid;
    req.chars_per_second = chars_per_second;
    req.jitter_ms = jitter_ms;
    req.press_enter = press_enter;

    rc = ec_run(&req, result);
    free(wide);
    return rc;
}
