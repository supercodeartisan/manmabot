/* lcapi_host_test.c - minimal LCAPI host: LoadLibrary -> configure -> run -> sink.
 * usage: lcapi_host_test.exe <dll> <registry> [count]
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdio.h>
#include <stdint.h>
#include "lcapi.h"

static int sink(void *ctx, uint32_t seq, const char *text, uint32_t len)
{
    (void)ctx;
    printf("[%u] %.*s\n", seq, (int)len, text);
    return 0;
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    if (argc < 3) { printf("usage: %s <dll> <registry> [count]\n", argv[0]); return 2; }
    HMODULE h = LoadLibraryA(argv[1]);
    if (!h) { printf("LoadLibrary(%s) failed: %lu\n", argv[1], GetLastError()); return 3; }

    lcapi_abi_fn abi = (lcapi_abi_fn)GetProcAddress(h, LCAPI_FN_ABI);
    lcapi_str_fn nm = (lcapi_str_fn)GetProcAddress(h, LCAPI_FN_NAME);
    lcapi_configure_fn cfg = (lcapi_configure_fn)GetProcAddress(h, LCAPI_FN_CONFIGURE);
    lcapi_run_fn run = (lcapi_run_fn)GetProcAddress(h, LCAPI_FN_RUN);
    if (!cfg || !run) { printf("missing exports (abi=%p cfg=%p run=%p)\n", (void *)abi, (void *)cfg, (void *)run); return 4; }

    printf("dll=%s name=%s abi=%u\n", argv[1], nm ? nm() : "?", abi ? abi() : 0);
    uint32_t count = (argc > 3) ? (uint32_t)atoi(argv[3]) : 3;
    int rc = cfg(argv[2], 0, 0, count, "out");
    printf("configure=%d\n", rc);
    if (rc != 0) { FreeLibrary(h); return 5; }

    char err[256] = {0};
    int n = run(sink, NULL, err, sizeof(err));
    printf("run=%d err=%s\n", n, err);
    FreeLibrary(h);
    return (n < 0) ? 6 : 0;
}
