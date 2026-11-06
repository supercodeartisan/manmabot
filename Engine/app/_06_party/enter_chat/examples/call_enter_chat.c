/* ============================================================================
 * call_enter_chat.c - minimal C API example
 *
 * Build (from enter_chat\examples):
 *   build_example.bat
 *
 * Run (from enter_chat\bin):
 *   example_call.exe 19708 "#안녕하세요 简体team@#"
 * ========================================================================== */
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

#include "enter_chat.h"

int wmain(int argc, wchar_t** argv)
{
    EcRequest req;
    EcResult  res;
    DWORD     pid;
    int       rc;

    if (argc < 3) {
        wprintf(L"usage: %ls <pid> <text>\n", argv[0]);
        wprintf(L"example: %ls 19708 \"#안녕하세요 简体team@#\"\n", argv[0]);
        return 1;
    }

    pid = (DWORD)wcstoul(argv[1], NULL, 10);
    if (!pid) {
        wprintf(L"error: invalid pid\n");
        return 1;
    }

    ZeroMemory(&req, sizeof(req));
    req.text             = argv[2];
    req.pid              = pid;
    req.chars_per_second = 10.0;
    req.jitter_ms        = 25;
    req.jamo_delay_ms    = 8;
    req.press_enter      = FALSE;   /* set TRUE only when you want to send */
    req.flags            = EC_FLAG_SENDINPUT_FALLBACK;

    ZeroMemory(&res, sizeof(res));
    rc = ec_run(&req, &res);

    wprintf(L"rc=%d status=%d (%ls)\n",
            rc, (int)res.status, ec_status_string(res.status));
    wprintf(L"target pid=%lu hwnd=0x%p\n",
            (unsigned long)res.pid, (void*)res.hwnd);
    wprintf(L"chars=%d keys=%d failed=%d skipped=%d enter=%ls elapsed=%lu ms\n",
            res.chars, res.keys, res.failed, res.skipped,
            res.enter_pressed ? L"yes" : L"no",
            (unsigned long)res.elapsed_ms);
    if (res.message[0])
        wprintf(L"message: %ls\n", res.message);

    return rc;
}
