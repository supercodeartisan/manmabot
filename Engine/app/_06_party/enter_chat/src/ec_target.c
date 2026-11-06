/* ============================================================================
 * ec_target.c - PID -> window resolution, focus and elevation helpers
 * ========================================================================== */
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <stdlib.h>

#include "ec_internal.h"

/* ---------------------------------------------------------------- elevation */
BOOL ec_is_elevated(void)
{
    HANDLE tok = NULL;
    TOKEN_ELEVATION el = {0};
    DWORD n = 0;
    BOOL r = FALSE;

    if (OpenProcessToken(GetCurrentProcess(), TOKEN_QUERY, &tok)) {
        if (GetTokenInformation(tok, TokenElevation, &el, sizeof(el), &n))
            r = el.TokenIsElevated ? TRUE : FALSE;
        CloseHandle(tok);
    }
    return r;
}

unsigned int ec_process_integrity(DWORD pid)
{
    HANDLE p = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, pid);
    HANDLE tok = NULL;
    DWORD n = 0;
    unsigned int rid = 0xFFFFFFFF;

    if (!p) return 0xFFFFFFFF;
    if (OpenProcessToken(p, TOKEN_QUERY, &tok) &&
        !GetTokenInformation(tok, TokenIntegrityLevel, NULL, 0, &n) &&
        GetLastError() == ERROR_INSUFFICIENT_BUFFER) {
        TOKEN_MANDATORY_LABEL* tml = (TOKEN_MANDATORY_LABEL*)malloc(n);
        if (tml) {
            if (GetTokenInformation(tok, TokenIntegrityLevel, tml, n, &n)) {
                DWORD cnt = *GetSidSubAuthorityCount(tml->Label.Sid);
                rid = *GetSidSubAuthority(tml->Label.Sid, cnt - 1);
            }
            free(tml);
        }
    }
    if (tok) CloseHandle(tok);
    CloseHandle(p);
    return rid;   /* 0x2000 medium, 0x3000 high, 0x4000 system */
}

/* ---------------------------------------------------------------- windows */
typedef struct EcFindCtx {
    DWORD pid;
    HWND  best;
    LONG  best_score;
    BOOL  require_title;
} EcFindCtx;

static BOOL CALLBACK ec_find_cb(HWND h, LPARAM lp)
{
    EcFindCtx* c = (EcFindCtx*)lp;
    DWORD p = 0;
    int title_len;
    RECT r;
    LONG area;
    LONG score = 0;

    GetWindowThreadProcessId(h, &p);
    if (p != c->pid) return TRUE;
    if (!IsWindowVisible(h)) return TRUE;
    if (GetWindow(h, GW_OWNER) != NULL) return TRUE;   /* top-level only */

    title_len = GetWindowTextLengthW(h);
    if (c->require_title && title_len == 0) return TRUE;

    GetWindowRect(h, &r);
    area = (r.right - r.left) * (r.bottom - r.top);
    if (area < 0) area = 0;

    if (title_len > 0) score += 1000000;
    score += area / 1000;
    if (h == GetForegroundWindow()) score += 100000000;

    if (!c->best || score > c->best_score) {
        c->best = h;
        c->best_score = score;
    }
    return TRUE;
}

HWND ec_find_window_for_pid(DWORD pid)
{
    EcFindCtx c;

    if (!pid) return NULL;

    /* First pass: visible top-level windows that have a title. */
    c.pid = pid; c.best = NULL; c.best_score = 0; c.require_title = TRUE;
    EnumWindows(ec_find_cb, (LPARAM)&c);
    if (c.best) return c.best;

    /* Second pass: any visible top-level window of the process. */
    c.pid = pid; c.best = NULL; c.best_score = 0; c.require_title = FALSE;
    EnumWindows(ec_find_cb, (LPARAM)&c);
    return c.best;
}

HWND ec_resolve_focus(HWND top)
{
    DWORD tid;
    GUITHREADINFO gi;

    if (!top) return NULL;
    tid = GetWindowThreadProcessId(top, NULL);
    memset(&gi, 0, sizeof(gi));
    gi.cbSize = sizeof(gi);
    if (tid && GetGUIThreadInfo(tid, &gi) && gi.hwndFocus) {
        if (gi.hwndFocus == top || IsChild(top, gi.hwndFocus))
            return gi.hwndFocus;
    }
    return top;
}

BOOL ec_is_foreground(HWND top)
{
    HWND fg;

    if (!top) return FALSE;
    fg = GetForegroundWindow();
    if (!fg) return FALSE;
    if (fg == top) return TRUE;
    if (IsChild(top, fg)) return TRUE;
    return GetAncestor(fg, GA_ROOT) == GetAncestor(top, GA_ROOT);
}

#ifndef ASFW_ANY
#define ASFW_ANY ((DWORD)-1)
#endif
#ifndef LSFW_UNLOCK
#define LSFW_UNLOCK 2
#endif

/* Interception scancodes go to the foreground window.  Attach to the current
 * foreground thread so the shell does not refuse SetForegroundWindow.
 * A freshly started admin exe is granted foreground rights by the shell.
 * The long-running bot is not, so unlock that restriction before the call. */
BOOL ec_force_foreground(HWND top, DWORD timeout_ms)
{
    HWND fg;
    DWORD fg_tid;
    DWORD my_tid;
    DWORD waited = 0;

    if (!top || !IsWindow(top)) return FALSE;
    if (ec_is_foreground(top)) return TRUE;

    AllowSetForegroundWindow(ASFW_ANY);
    LockSetForegroundWindow(LSFW_UNLOCK);

    fg = GetForegroundWindow();
    fg_tid = fg ? GetWindowThreadProcessId(fg, NULL) : 0;
    my_tid = GetCurrentThreadId();

    if (fg_tid && fg_tid != my_tid)
        AttachThreadInput(my_tid, fg_tid, TRUE);

    if (IsIconic(top)) ShowWindow(top, SW_RESTORE);  /* do not unmaximize */
    BringWindowToTop(top);
    SetForegroundWindow(top);

    if (fg_tid && fg_tid != my_tid)
        AttachThreadInput(my_tid, fg_tid, FALSE);

    if (timeout_ms == 0) timeout_ms = EC_DEFAULT_FOCUS_TIMEOUT;
    while (waited < timeout_ms) {
        if (ec_is_foreground(top)) return TRUE;
        Sleep(20);
        waited += 20;
    }
    return ec_is_foreground(top);
}

/* A cheap UIPI probe.  WM_NULL can pass while WM_CHAR is still blocked, so the
 * caller also compares process integrity levels. */
BOOL ec_uipi_blocked(HWND hwnd)
{
    if (!hwnd) return TRUE;
    SetLastError(0);
    if (PostMessageW(hwnd, WM_NULL, 0, 0)) return FALSE;
    return GetLastError() == ERROR_ACCESS_DENIED;
}
