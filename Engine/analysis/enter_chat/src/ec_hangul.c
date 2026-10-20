/* ============================================================================
 * ec_hangul.c - precomposed Hangul -> 2-beolsik jamo key sequence
 *
 * The Korean IME composes the jamo keys into syllables.  Compound vowels and
 * finals are expanded into their component keys in IME order.
 * ========================================================================== */
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <imm.h>

#include "ec_internal.h"

#ifndef IMC_GETCONVERSIONMODE
#define IMC_GETCONVERSIONMODE 0x0001
#endif
#ifndef IMC_SETCONVERSIONMODE
#define IMC_SETCONVERSIONMODE 0x0002
#endif

static const wchar_t KO_L[19] = {
    L'ㄱ',L'ㄲ',L'ㄴ',L'ㄷ',L'ㄸ',L'ㄹ',L'ㅁ',L'ㅂ',L'ㅃ',L'ㅅ',
    L'ㅆ',L'ㅇ',L'ㅈ',L'ㅉ',L'ㅊ',L'ㅋ',L'ㅌ',L'ㅍ',L'ㅎ'
};
static const wchar_t KO_V[21] = {
    L'ㅏ',L'ㅐ',L'ㅑ',L'ㅒ',L'ㅓ',L'ㅔ',L'ㅕ',L'ㅖ',L'ㅗ',L'ㅘ',L'ㅙ',
    L'ㅚ',L'ㅛ',L'ㅜ',L'ㅝ',L'ㅞ',L'ㅟ',L'ㅠ',L'ㅡ',L'ㅢ',L'ㅣ'
};
static const wchar_t KO_T[28] = {
    0,
    L'ㄱ',L'ㄲ',L'ㄳ',L'ㄴ',L'ㄵ',L'ㄶ',L'ㄷ',L'ㄹ',L'ㄺ',L'ㄻ',L'ㄼ',L'ㄽ',
    L'ㄾ',L'ㄿ',L'ㅀ',L'ㅁ',L'ㅂ',L'ㅄ',L'ㅅ',L'ㅆ',L'ㅇ',L'ㅈ',L'ㅊ',L'ㅋ',
    L'ㅌ',L'ㅍ',L'ㅎ'
};

/* compatibility jamo -> US QWERTY key; uppercase means Shift is required */
static char ko_jamo_key(wchar_t j)
{
    switch (j) {
    case L'ㄱ': return 'r'; case L'ㄲ': return 'R'; case L'ㄴ': return 's';
    case L'ㄷ': return 'e'; case L'ㄸ': return 'E'; case L'ㄹ': return 'f';
    case L'ㅁ': return 'a'; case L'ㅂ': return 'q'; case L'ㅃ': return 'Q';
    case L'ㅅ': return 't'; case L'ㅆ': return 'T'; case L'ㅇ': return 'd';
    case L'ㅈ': return 'w'; case L'ㅉ': return 'W'; case L'ㅊ': return 'c';
    case L'ㅋ': return 'z'; case L'ㅌ': return 'x'; case L'ㅍ': return 'v';
    case L'ㅎ': return 'g';
    case L'ㅏ': return 'k'; case L'ㅐ': return 'o'; case L'ㅑ': return 'i';
    case L'ㅒ': return 'O'; case L'ㅓ': return 'j'; case L'ㅔ': return 'p';
    case L'ㅕ': return 'u'; case L'ㅖ': return 'P'; case L'ㅗ': return 'h';
    case L'ㅛ': return 'y'; case L'ㅜ': return 'n'; case L'ㅠ': return 'b';
    case L'ㅡ': return 'm'; case L'ㅣ': return 'l';
    default: return 0;
    }
}

static int ko_one(wchar_t j, char* out, int max)
{
    char k = ko_jamo_key(j);
    if (!k || max < 1) return 0;
    out[0] = k;
    return 1;
}

/* compound vowel/final -> its component jamo keys, in IME order */
static int ko_emit(wchar_t j, char* out, int max)
{
    int n;
    switch (j) {
    case L'ㅘ': n=ko_one(L'ㅗ',out,max); return n+ko_one(L'ㅏ',out+n,max-n);
    case L'ㅙ': n=ko_one(L'ㅗ',out,max); return n+ko_one(L'ㅐ',out+n,max-n);
    case L'ㅚ': n=ko_one(L'ㅗ',out,max); return n+ko_one(L'ㅣ',out+n,max-n);
    case L'ㅝ': n=ko_one(L'ㅜ',out,max); return n+ko_one(L'ㅓ',out+n,max-n);
    case L'ㅞ': n=ko_one(L'ㅜ',out,max); return n+ko_one(L'ㅔ',out+n,max-n);
    case L'ㅟ': n=ko_one(L'ㅜ',out,max); return n+ko_one(L'ㅣ',out+n,max-n);
    case L'ㅢ': n=ko_one(L'ㅡ',out,max); return n+ko_one(L'ㅣ',out+n,max-n);
    case L'ㄳ': n=ko_one(L'ㄱ',out,max); return n+ko_one(L'ㅅ',out+n,max-n);
    case L'ㄵ': n=ko_one(L'ㄴ',out,max); return n+ko_one(L'ㅈ',out+n,max-n);
    case L'ㄶ': n=ko_one(L'ㄴ',out,max); return n+ko_one(L'ㅎ',out+n,max-n);
    case L'ㄺ': n=ko_one(L'ㄹ',out,max); return n+ko_one(L'ㄱ',out+n,max-n);
    case L'ㄻ': n=ko_one(L'ㄹ',out,max); return n+ko_one(L'ㅁ',out+n,max-n);
    case L'ㄼ': n=ko_one(L'ㄹ',out,max); return n+ko_one(L'ㅂ',out+n,max-n);
    case L'ㄽ': n=ko_one(L'ㄹ',out,max); return n+ko_one(L'ㅅ',out+n,max-n);
    case L'ㄾ': n=ko_one(L'ㄹ',out,max); return n+ko_one(L'ㅌ',out+n,max-n);
    case L'ㄿ': n=ko_one(L'ㄹ',out,max); return n+ko_one(L'ㅍ',out+n,max-n);
    case L'ㅀ': n=ko_one(L'ㄹ',out,max); return n+ko_one(L'ㅎ',out+n,max-n);
    case L'ㅄ': n=ko_one(L'ㅂ',out,max); return n+ko_one(L'ㅅ',out+n,max-n);
    default:   return ko_one(j,out,max);
    }
}

BOOL ec_is_hangul(wchar_t c)
{
    return ((c >= 0xAC00 && c <= 0xD7A3) ||   /* precomposed syllables */
            (c >= 0x3131 && c <= 0x318E) ||   /* compatibility jamo  */
            (c >= 0x1100 && c <= 0x11FF))     /* conjoining jamo    */
           ? TRUE : FALSE;
}

static wchar_t ko_conjoining(wchar_t c)
{
    if (c >= 0x1100 && c <= 0x1112) return KO_L[c - 0x1100];
    if (c >= 0x1161 && c <= 0x1175) return KO_V[c - 0x1161];
    if (c >= 0x11A8 && c <= 0x11C2) return KO_T[c - 0x11A8 + 1];
    return 0;
}

/* one Hangul char -> QWERTY key sequence (max 6 for L + compound V + compound T) */
int ec_hangul_keys(wchar_t c, char* out, int max)
{
    if (!out || max <= 0) return 0;

    if (c >= 0xAC00 && c <= 0xD7A3) {
        int s = c - 0xAC00;
        int L = s / 588;
        int V = (s % 588) / 28;
        int T = s % 28;
        int n = ko_emit(KO_L[L], out, max);
        n += ko_emit(KO_V[V], out + n, max - n);
        if (T) n += ko_emit(KO_T[T], out + n, max - n);
        return n;
    }
    if (c >= 0x3131 && c <= 0x318E) return ko_emit(c, out, max);
    if (c >= 0x1100 && c <= 0x11FF) {
        wchar_t j = ko_conjoining(c);
        return j ? ko_emit(j, out, max) : 0;
    }
    return 0;
}

#ifndef EC_TEST
/* ---------------------------------------------------------------- layout/IME */
BOOL ec_hangul_prepare(EcContext* ctx, HWND hwnd)
{
    DWORD tid;
    HKL old;
    HIMC himc;
    DWORD conv = 0, sent = 0;

    if (!ctx || !hwnd) return FALSE;
    if (ctx->hangul_started) return TRUE;

    tid = GetWindowThreadProcessId(hwnd, NULL);
    old = GetKeyboardLayout(tid);
    ctx->old_hkl = old;
    ctx->ko_hkl = LoadKeyboardLayoutW(L"00000412", KLF_ACTIVATE);
    if (!ctx->ko_hkl) {
        ec_result_message(ctx->res, L"Korean keyboard layout 0412 is not installed.");
        return FALSE;
    }

    if ((((ULONG_PTR)old) & 0xFFFF) != 0x0412) {
        if (PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, (LPARAM)ctx->ko_hkl)) {
            ctx->layout_switched = TRUE;
            Sleep(120);
        }
        /* verify: the target thread must actually be on the Korean layout */
        if ((((ULONG_PTR)GetKeyboardLayout(tid)) & 0xFFFF) != 0x0412) {
            ec_result_message(ctx->res, L"Could not switch the target thread to Korean layout 0412.");
            /* allow cleanup to restore the layout if the request was posted */
            ctx->hangul_started = TRUE;
            return FALSE;
        }
    }

    {
        HWND ime_wnd = ctx->focus ? ctx->focus : hwnd;
        BOOL ime_ok = FALSE;

        himc = ImmGetContext(ime_wnd);
        if (himc) {
            if (ImmGetConversionStatus(himc, &conv, &sent)) {
                ctx->old_conv = conv;
                ctx->old_sent = sent;
                if (!(conv & IME_CMODE_NATIVE)) {
                    if (ImmSetConversionStatus(himc, conv | IME_CMODE_NATIVE, sent))
                        ctx->changed_conv = TRUE;
                }
                ime_ok = TRUE;
            }
            ImmReleaseContext(ime_wnd, himc);
        }

        if (!ime_ok) {
            /* Cross-process ImmGetContext often returns NULL.  The default IME
             * window still accepts WM_IME_CONTROL / IMC_* in many cases. */
            HWND def = ImmGetDefaultIMEWnd(ime_wnd);
            if (def) {
                DWORD_PTR mode = 0;
                LRESULT got = SendMessageTimeoutW(def, WM_IME_CONTROL,
                    IMC_GETCONVERSIONMODE, 0,
                    SMTO_ABORTIFHUNG | SMTO_BLOCK, 400, &mode);
                if (got) {
                    if (!(mode & IME_CMODE_NATIVE)) {
                        DWORD_PTR setres = 0;
                        ctx->ime_wnd = def;
                        ctx->ime_old_mode = (DWORD)mode;
                        ctx->ime_mode_forced = TRUE;
                        SendMessageTimeoutW(def, WM_IME_CONTROL,
                            IMC_SETCONVERSIONMODE, mode | IME_CMODE_NATIVE,
                            SMTO_ABORTIFHUNG | SMTO_BLOCK, 400, &setres);
                        Sleep(50);
                        {
                            DWORD_PTR verify = 0;
                            LRESULT vgot = SendMessageTimeoutW(def, WM_IME_CONTROL,
                                IMC_GETCONVERSIONMODE, 0,
                                SMTO_ABORTIFHUNG | SMTO_BLOCK, 400, &verify);
                            if (!vgot || !(verify & IME_CMODE_NATIVE))
                                ec_result_message(ctx->res,
                                    L"could not switch the Korean IME to Hangul (한) mode");
                        }
                    }
                    ime_ok = TRUE;
                }
            }
        }

        if (!ime_ok) {
            /* Normal for some elevated cross-process targets.  The user must
             * keep the IME in Hangul ("한") mode before running us. */
            ec_result_message(ctx->res,
                L"IME context unavailable; keep the Korean IME in Hangul (한) mode.");
        }
    }

    ctx->hangul_started = TRUE;
    return TRUE;
}

void ec_hangul_done(EcContext* ctx)
{
    if (!ctx || !ctx->hangul_started) return;

    if (ctx->changed_conv) {
        HWND ime_wnd = ctx->focus ? ctx->focus : ctx->hwnd;
        HIMC himc = ImmGetContext(ime_wnd);
        if (himc) {
            ImmSetConversionStatus(himc, ctx->old_conv, ctx->old_sent);
            ImmReleaseContext(ime_wnd, himc);
        }
    }
    if (ctx->ime_mode_forced && ctx->ime_wnd) {
        DWORD_PTR setres = 0;
        SendMessageTimeoutW(ctx->ime_wnd, WM_IME_CONTROL,
            IMC_SETCONVERSIONMODE, ctx->ime_old_mode,
            SMTO_ABORTIFHUNG | SMTO_BLOCK, 400, &setres);
    }
    if (ctx->layout_switched && ctx->old_hkl) {
        PostMessageW(ctx->hwnd, WM_INPUTLANGCHANGEREQUEST, 0, (LPARAM)ctx->old_hkl);
        Sleep(50);
    }
    ctx->hangul_started = FALSE;
}

/* Right arrow (E0 4D) commits the IME composition without inserting text. */
BOOL ec_hangul_commit(EcContext* ctx)
{
    if (!ctx || !ctx->ic) return FALSE;
    if (!ec_ic_press(ctx, 0x4D, 1, 6)) return FALSE;
    Sleep(24);
    return TRUE;
}
#endif /* EC_TEST */
