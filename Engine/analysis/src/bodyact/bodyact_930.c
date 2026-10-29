/* bodyact_930.c — MyPlayer body action + command monitor (10_15)
 * ===========================================================================
 *  Manmabot action_view / action_timeline 대응:
 *    body = ActionComponent + AC_ACTION_OFF (0xC0) 객체 vft
 *    cmd  = ActorController + CTL_CMD_OFF (0x58) 객체 vft
 *  읽기: lc_pollSelfBodyFast (sticky AC/CTL, 잎만 ~4 IOCTL). 퓨전 없음.
 *
 *  usage: bodyact_930.exe [registry] [secs] [out.txt]
 *  output: <exe>\out\bodyact_out.txt
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg = lcreg_resolve("10_5/registry/LC930_REGISTRY.txt",
                                    "registry/LC930_REGISTRY.txt");
    const char *outp = lcreg_outpath("bodyact_out.txt");
    int secs = 0;
    {
        int seenReg = 0;
        for (int i = 1; i < argc; i++) {
            if (strstr(argv[i], ".txt") || strstr(argv[i], ".out")) {
                if (!seenReg && strstr(argv[i], "REGISTRY")) {
                    reg = argv[i];
                    seenReg = 1;
                } else
                    outp = argv[i];
            } else if (atoi(argv[i]) > 0 && !strstr(argv[i], ".")) {
                secs = atoi(argv[i]);
            }
        }
    }
    lcreg_load(lcreg_resolve(reg, "registry/LC930_REGISTRY.txt"));
    lc_reg_apply();
    lcreg_poll P = lcreg_poll_load("BODYACT");

    if (lc_attach()) return 1;
    if (!lc_anchor()) {
        fprintf(stderr, "anchor fail\n");
        return 2;
    }

    lcreg_mkdir_for(outp);
    FILE *f = fopen(outp, "w");
    if (!f) return 4;

    DWORD t0 = GetTickCount();
    uint32_t lastBody = ~0u, lastCmd = ~0u;
    int plen = 0;
    LARGE_INTEGER fr, q0, q1;
    QueryPerformanceFrequency(&fr);

    fprintf(f, "# bodyact_930  body=AC+0x%X  cmd=ActorCtl+0x%X  (fast leaf)\n",
            (unsigned)LC_AC_ACTION_OFF, (unsigned)LC_CTL_CMD_OFF_V);
    fprintf(f, "# t_ms body cmd body_rva cmd_rva ioctl ms\n");
    fflush(f);

    for (;;) {
        DWORD now = GetTickCount();
        QueryPerformanceCounter(&q0);
        g_ioctl = 0;
        int ok = lc_pollSelfBodyFast();
        QueryPerformanceCounter(&q1);
        double ms = (double)(q1.QuadPart - q0.QuadPart) * 1000.0 / (double)fr.QuadPart;

        uint32_t body = ok ? lc_selfBodyAct : 0;
        uint32_t cmd = ok ? lc_selfCmdVft : 0;
        const char *bn = lc_bodyOf(body);
        const char *cn = lc_cmdOf(cmd);

        char line[512];
        int len = snprintf(
            line, sizeof line,
            "[BODYACT] t=%ums ok=%d body=%s(0x%X) cmd=%s(0x%X) ioctl=%llu time=%.3fms",
            (unsigned)(now - t0), ok, bn, body, cn, cmd,
            (unsigned long long)g_ioctl, ms);

        printf("\r%s", line);
        for (int i = len; i < plen; i++) putchar(' ');
        fflush(stdout);
        plen = len;

        if (body != lastBody || cmd != lastCmd) {
            fprintf(f, "%u\t%s\t%s\t0x%X\t0x%X\t%llu\t%.3f\n",
                    (unsigned)(now - t0), bn, cn, body, cmd,
                    (unsigned long long)g_ioctl, ms);
            fflush(f);
            lastBody = body;
            lastCmd = cmd;
        }

        lcapi_sample(f);
        if (lcapi_done() || (secs && (int)(now - t0) >= secs * 1000)) break;
        Sleep(lcreg_poll_sleep_ms(&P));
    }

    putchar('\n');
    fclose(f);
    SignedClose();
    printf("done -> %s\n", outp);
    return 0;
}
