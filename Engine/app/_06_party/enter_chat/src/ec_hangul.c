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
#define COBJMACROS
#include <objbase.h>
#include <msctf.h>

/* This SDK has msctf.h and no msctf.lib. The ids are the registered coclass
 * TF_InputProcessorProfiles and the ITfInputProcessorProfileMgr interface. */
static const CLSID EC_CLSID_TF_PROFILES = {
    0x33C53A50, 0xF456, 0x4884, {0xB0, 0x49, 0x85, 0xFD, 0x64, 0x3E, 0xCF, 0xED}
};
static const IID EC_IID_PROFILE_MGR = {
    0x71C6E74C, 0x0F28, 0x11D8, {0xA8, 0x2A, 0x00, 0x06, 0x5B, 0x84, 0x43, 0x5C}
};

static BOOL ec_thread_is_korean(DWORD tid)
{
    return (((ULONG_PTR)GetKeyboardLayout(tid)) & 0xFFFF) == 0x0412;
}

static LANGID ec_thread_lang(DWORD tid)
{
    return (LANGID)((ULONG_PTR)GetKeyboardLayout(tid) & 0xFFFF);
}

/* Chinese IMEs use IME_CMODE_NATIVE for 中, not for 한. */
static BOOL ec_lang_is_chinese(LANGID lang)
{
    return PRIMARYLANGID(lang) == LANG_CHINESE;
}

static const wchar_t* ec_ime_name(LANGID lang)
{
    if (PRIMARYLANGID(lang) == LANG_KOREAN) return L"ko";
    if (PRIMARYLANGID(lang) == LANG_ENGLISH) return L"en";
    if (!ec_lang_is_chinese(lang)) return L"other";
    if (SUBLANGID(lang) == SUBLANG_CHINESE_SIMPLIFIED) return L"zh-CN";
    if (SUBLANGID(lang) == SUBLANG_CHINESE_TRADITIONAL) return L"zh-TW";
    if (SUBLANGID(lang) == SUBLANG_CHINESE_HONGKONG) return L"zh-HK";
    return L"zh";
}

/* The game thread applies a layout change only while it is foreground.
 * SendMessageTimeout waits for that thread; PostMessage covers clients that
 * handle only the queued form. */
static BOOL ec_switch_game_layout(HWND hwnd, HKL ko, DWORD tid)
{
    DWORD me;
    BOOL attached = FALSE;
    DWORD_PTR ignored = 0;
    DWORD waited = 0;

    if (!hwnd || !ko || !tid) return FALSE;
    if (ec_thread_is_korean(tid)) return TRUE;

    me = GetCurrentThreadId();
    if (tid != me)
        attached = AttachThreadInput(me, tid, TRUE);

    SendMessageTimeoutW(hwnd, WM_INPUTLANGCHANGEREQUEST,
        0, (LPARAM)ko, SMTO_ABORTIFHUNG | SMTO_BLOCK, 500, &ignored);
    PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST, 0, (LPARAM)ko);

    while (waited < 500) {
        if (ec_thread_is_korean(tid)) break;
        Sleep(20);
        waited += 20;
    }
    if (attached)
        AttachThreadInput(me, tid, FALSE);
    return ec_thread_is_korean(tid);
}

/* Ask the game window for the Korean layout even when the thread HKL is
 * already 0412. 0412 is both 한 and 영, and it can stay set while the
 * language bar on that window is still English (United States). */
static void ec_select_korean_on_window(HWND hwnd, HKL ko)
{
    DWORD_PTR ignored = 0;

    if (!hwnd || !ko) return;
    SendMessageTimeoutW(hwnd, WM_INPUTLANGCHANGEREQUEST,
        INPUTLANGCHANGE_SYSCHARSET, (LPARAM)ko,
        SMTO_ABORTIFHUNG | SMTO_BLOCK, 300, &ignored);
    PostMessageW(hwnd, WM_INPUTLANGCHANGEREQUEST,
        INPUTLANGCHANGE_SYSCHARSET, (LPARAM)ko);
}

/* Turn on the installed ko-KR keyboard profile. An input processor
 * (the language-bar IME) wins over a bare keyboard layout. */
static void ec_activate_korean_profile(HKL ko)
{
    ITfInputProcessorProfileMgr* mgr = NULL;
    IEnumTfInputProcessorProfiles* en = NULL;
    TF_INPUTPROCESSORPROFILE best;
    HRESULT co;
    HRESULT hr;
    BOOL com_owned = FALSE;
    BOOL have = FALSE;
    int rank_best = 99;

    co = CoInitializeEx(NULL, COINIT_APARTMENTTHREADED);
    if (FAILED(co) && co != RPC_E_CHANGED_MODE) return;
    com_owned = (co == S_OK);

    hr = CoCreateInstance(&EC_CLSID_TF_PROFILES, NULL,
                          CLSCTX_INPROC_SERVER, &EC_IID_PROFILE_MGR,
                          (void**)&mgr);
    if (FAILED(hr) || !mgr) goto done;
    hr = ITfInputProcessorProfileMgr_EnumProfiles(mgr, 0x0412, &en);
    if (SUCCEEDED(hr) && en) {
        for (;;) {
            TF_INPUTPROCESSORPROFILE p;
            ULONG got = 0;
            int rank;
            hr = IEnumTfInputProcessorProfiles_Next(en, 1, &p, &got);
            if (hr != S_OK || got != 1) break;
            if (p.langid != 0x0412) continue;
            if (!(p.dwFlags & TF_IPP_FLAG_ENABLED)) continue;
            if (p.dwProfileType == TF_PROFILETYPE_INPUTPROCESSOR) rank = 0;
            else if (p.dwProfileType == TF_PROFILETYPE_KEYBOARDLAYOUT) rank = 1;
            else continue;
            if (rank < rank_best) {
                best = p;
                rank_best = rank;
                have = TRUE;
            }
        }
    }
    if (have) {
        HKL hkl = best.hkl ? best.hkl : (best.hklSubstitute ? best.hklSubstitute : ko);
        ITfInputProcessorProfileMgr_ActivateProfile(
            mgr, best.dwProfileType, best.langid, &best.clsid, &best.guidProfile,
            hkl, TF_IPPMF_DONTCARECURRENTINPUTLANGUAGE | TF_IPPMF_ENABLEPROFILE);
    }
done:
    if (en) IEnumTfInputProcessorProfiles_Release(en);
    if (mgr) ITfInputProcessorProfileMgr_Release(mgr);
    if (com_owned) CoUninitialize();
}

/* TRUE when a conversion mode was actually read into *mode. */
static BOOL ec_read_conv(HWND ime_wnd, DWORD* mode)
{
    HIMC himc;
    DWORD conv = 0;
    DWORD sent = 0;
    HWND def;
    DWORD_PTR got_mode = 0;

    if (!ime_wnd || !mode) return FALSE;
    himc = ImmGetContext(ime_wnd);
    if (himc) {
        BOOL ok = ImmGetConversionStatus(himc, &conv, &sent);
        ImmReleaseContext(ime_wnd, himc);
        if (ok) {
            *mode = conv;
            return TRUE;
        }
    }
    def = ImmGetDefaultIMEWnd(ime_wnd);
    if (!def) return FALSE;
    if (!SendMessageTimeoutW(def, WM_IME_CONTROL, IMC_GETCONVERSIONMODE, 0,
            SMTO_ABORTIFHUNG | SMTO_BLOCK, 400, &got_mode))
        return FALSE;
    *mode = (DWORD)got_mode;
    return TRUE;
}

static void ec_write_conv(EcContext* ctx, HWND ime_wnd)
{
    HIMC himc;
    DWORD conv = 0;
    DWORD sent = 0;
    HWND def;
    DWORD_PTR cur = 0;
    DWORD_PTR setres = 0;

    if (!ctx || !ime_wnd) return;
    himc = ImmGetContext(ime_wnd);
    if (himc) {
        if (ImmGetConversionStatus(himc, &conv, &sent) && !(conv & IME_CMODE_NATIVE)) {
            ctx->old_conv = conv;
            ctx->old_sent = sent;
            if (ImmSetConversionStatus(himc, conv | IME_CMODE_NATIVE, sent))
                ctx->changed_conv = TRUE;
        }
        ImmReleaseContext(ime_wnd, himc);
    }
    def = ImmGetDefaultIMEWnd(ime_wnd);
    if (!def) return;
    if (!SendMessageTimeoutW(def, WM_IME_CONTROL, IMC_GETCONVERSIONMODE, 0,
            SMTO_ABORTIFHUNG | SMTO_BLOCK, 400, &cur))
        return;
    if (cur & IME_CMODE_NATIVE) return;
    ctx->ime_wnd = def;
    ctx->ime_old_mode = (DWORD)cur;
    ctx->ime_mode_forced = TRUE;
    SendMessageTimeoutW(def, WM_IME_CONTROL, IMC_SETCONVERSIONMODE,
        cur | IME_CMODE_NATIVE, SMTO_ABORTIFHUNG | SMTO_BLOCK, 400, &setres);
}

/* VK_HANGUL is 0x15. MapVirtualKey on a US layout can hand back scancode
 * 0x15, which is the Y key. The Korean toggle key is scancode 0x72. */
static BOOL ec_press_hangul_toggle(EcContext* ctx)
{
    UINT scan;

    if (!ctx) return FALSE;
    scan = MapVirtualKeyW(VK_HANGUL, MAPVK_VK_TO_VSC);
    if (scan == 0 || scan == 0x15) scan = 0x72;
    if (ctx->ic) return ec_ic_press(ctx, (int)scan, 0, 30);
    return ec_sendinput_press((int)scan, 0, 30);
}

/* Leave the game IME in 한. A mode we can read as 한 is left alone.
 * A mode we can read as 영 is switched, then the 한/영 key is pressed
 * once if it is still 영. A mode we cannot read is not toggled. */
static BOOL ec_ensure_hangul_mode(EcContext* ctx, HWND hwnd, DWORD tid)
{
    HWND ime_wnd;
    DWORD mode = 0;
    DWORD focus_ms;
    LANGID lang = 0;
    BOOL known = FALSE;

    if (!ctx) return FALSE;
    ime_wnd = ctx->focus ? ctx->focus : hwnd;
    focus_ms = ctx->req.focus_timeout_ms
             ? ctx->req.focus_timeout_ms : EC_DEFAULT_FOCUS_TIMEOUT;

    ec_activate_korean_profile(ctx->ko_hkl);
    ec_select_korean_on_window(hwnd, ctx->ko_hkl);
    Sleep(80);
    if (ctx->hwnd) ec_force_foreground(ctx->hwnd, focus_ms);

    /* A Chinese IME also reports IME_CMODE_NATIVE. That bit is 중, so it
     * must not count as 한. Ask for Korean once more, then stop if the
     * game thread is still on a Chinese layout. */
    if (ec_lang_is_chinese(ec_thread_lang(tid))) {
        ec_activate_korean_profile(ctx->ko_hkl);
        ec_select_korean_on_window(hwnd, ctx->ko_hkl);
        Sleep(80);
        if (ctx->hwnd) ec_force_foreground(ctx->hwnd, focus_ms);
    }

    lang = ec_thread_lang(tid);
    if (PRIMARYLANGID(lang) == LANG_KOREAN) {
        known = ec_read_conv(ime_wnd, &mode);
        if (!known || !(mode & IME_CMODE_NATIVE)) {
            ec_write_conv(ctx, ime_wnd);
            Sleep(50);
            known = ec_read_conv(ime_wnd, &mode);
        }
        if (known && !(mode & IME_CMODE_NATIVE)) {
            if (ctx->hwnd && !ec_is_foreground(ctx->hwnd))
                ec_force_foreground(ctx->hwnd, focus_ms);
            ec_press_hangul_toggle(ctx);
            Sleep(60);
            known = ec_read_conv(ime_wnd, &mode);
        }
        lang = ec_thread_lang(tid);
    }

    ec_result_message(ctx->res, L"hkl=%04X ime=%ls hangul=%ls",
        (unsigned)lang, ec_ime_name(lang),
        (PRIMARYLANGID(lang) == LANG_KOREAN && known && (mode & IME_CMODE_NATIVE))
            ? L"on" : (known ? L"off" : L"?"));
    if (ec_lang_is_chinese(lang)) {
        ec_result_message(ctx->res,
            L"Chinese IME is the game input; Hangul was not sent");
        return FALSE;
    }
    if (PRIMARYLANGID(lang) == LANG_KOREAN && known && !(mode & IME_CMODE_NATIVE)) {
        ec_result_message(ctx->res,
            L"could not switch the Korean IME to Hangul (한) mode");
        return FALSE;
    }
    return TRUE;
}

BOOL ec_hangul_prepare(EcContext* ctx, HWND hwnd)
{
    DWORD tid;
    HKL old;
    DWORD focus_ms;

    if (!ctx || !hwnd) return FALSE;
    if (ctx->hangul_started) return TRUE;

    focus_ms = ctx->req.focus_timeout_ms
             ? ctx->req.focus_timeout_ms : EC_DEFAULT_FOCUS_TIMEOUT;
    if (ctx->hwnd)
        ec_force_foreground(ctx->hwnd, focus_ms);

    tid = GetWindowThreadProcessId(hwnd, NULL);
    old = GetKeyboardLayout(tid);
    ctx->old_hkl = old;
    ctx->ko_hkl = LoadKeyboardLayoutW(L"00000412", KLF_NOTELLSHELL);
    if (!ctx->ko_hkl) {
        ec_result_message(ctx->res, L"Korean keyboard layout 0412 is not installed.");
        return FALSE;
    }

    if (!ec_thread_is_korean(tid)) {
        ctx->layout_switched = TRUE;
        if (!ec_switch_game_layout(hwnd, ctx->ko_hkl, tid)) {
            ec_result_message(ctx->res, L"Could not switch the target thread to Korean layout 0412.");
            /* allow cleanup to restore the layout if the request was posted */
            ctx->hangul_started = TRUE;
            return FALSE;
        }
    }

    if (!ec_ensure_hangul_mode(ctx, hwnd, tid)) {
        ctx->hangul_started = TRUE;
        return FALSE;
    }

    ctx->hangul_started = TRUE;
    return TRUE;
}

/* Invite-accept Y is one ASCII key. In 한글 mode that key is the jamo ㅛ,
 * so the popup never sees Y. Switch the game thread to English only after
 * the game is in front — the same window the physical key will hit. */
BOOL ec_english_prepare(EcContext* ctx, HWND hwnd)
{
    HWND ime_wnd;
    HWND def;
    DWORD focus_ms;
    DWORD_PTR mode = 0;
    DWORD_PTR setres = 0;
    DWORD_PTR verify = 0;
    LRESULT got;
    LRESULT vgot;

    if (!ctx || !hwnd) return FALSE;
    focus_ms = ctx->req.focus_timeout_ms
             ? ctx->req.focus_timeout_ms : EC_DEFAULT_FOCUS_TIMEOUT;
    if (ctx->hwnd)
        ec_force_foreground(ctx->hwnd, focus_ms);

    ime_wnd = ctx->focus ? ctx->focus : hwnd;
    def = ImmGetDefaultIMEWnd(ime_wnd);
    if (!def) {
        ec_result_message(ctx->res,
            L"IME context unavailable; keep the Korean IME in English (영) mode.");
        return TRUE;
    }
    got = SendMessageTimeoutW(def, WM_IME_CONTROL, IMC_GETCONVERSIONMODE, 0,
        SMTO_ABORTIFHUNG | SMTO_BLOCK, 400, &mode);
    if (!got) {
        ec_result_message(ctx->res,
            L"IME context unavailable; keep the Korean IME in English (영) mode.");
        return TRUE;
    }
    if (!(mode & IME_CMODE_NATIVE))
        return TRUE;

    ctx->ime_wnd = def;
    ctx->ime_old_mode = (DWORD)mode;
    ctx->ime_mode_forced = TRUE;
    SendMessageTimeoutW(def, WM_IME_CONTROL, IMC_SETCONVERSIONMODE,
        mode & ~IME_CMODE_NATIVE, SMTO_ABORTIFHUNG | SMTO_BLOCK, 400, &setres);
    Sleep(50);
    vgot = SendMessageTimeoutW(def, WM_IME_CONTROL, IMC_GETCONVERSIONMODE, 0,
        SMTO_ABORTIFHUNG | SMTO_BLOCK, 400, &verify);
    if (!vgot || (verify & IME_CMODE_NATIVE)) {
        if (ctx->hwnd)
            ec_force_foreground(ctx->hwnd, focus_ms);
        SendMessageTimeoutW(def, WM_IME_CONTROL, IMC_SETCONVERSIONMODE,
            mode & ~IME_CMODE_NATIVE, SMTO_ABORTIFHUNG | SMTO_BLOCK, 400, &setres);
        Sleep(50);
        verify = 0;
        vgot = SendMessageTimeoutW(def, WM_IME_CONTROL, IMC_GETCONVERSIONMODE, 0,
            SMTO_ABORTIFHUNG | SMTO_BLOCK, 400, &verify);
    }
    if (!vgot || (verify & IME_CMODE_NATIVE))
        ec_result_message(ctx->res,
            L"could not switch the Korean IME to English (영) mode");
    return TRUE;
}

void ec_english_done(EcContext* ctx)
{
    DWORD_PTR setres = 0;

    if (!ctx || !ctx->ime_mode_forced || !ctx->ime_wnd) return;
    /* The game reads the key after the stroke. Hold English until then. */
    Sleep(150);
    SendMessageTimeoutW(ctx->ime_wnd, WM_IME_CONTROL,
        IMC_SETCONVERSIONMODE, ctx->ime_old_mode,
        SMTO_ABORTIFHUNG | SMTO_BLOCK, 400, &setres);
    ctx->ime_mode_forced = FALSE;
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
