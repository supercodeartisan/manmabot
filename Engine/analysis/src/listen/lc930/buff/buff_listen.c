/* buff_listen.c — in-process buff reader (E:\Lineage\extra lbuff.h)
 * ---------------------------------------------------------------------------
 *  Engine: core/lbuff.h
 *    BuffSubsystem = lc_subsGet(VFT_BUFF)
 *    unordered_map node walk (no BFS / no HudSlot chain)
 *  Export: buff_listen_snapshot / buff_listen_shutdown (JSON for Python)
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"
#include "lbuff.h"

static int g_ready = 0;
static char g_regPath[MAX_PATH * 2] = {0};

static void jsonEsc(const char* in, char* out, int cap) {
    int o = 0;
    if (!in) { out[0] = 0; return; }
    for (int i = 0; in[i] && o < cap - 2; i++) {
        unsigned char c = (unsigned char)in[i];
        if (c == '"' || c == '\\') { if (o + 2 >= cap) break; out[o++] = '\\'; out[o++] = (char)c; }
        else if (c < 0x20) continue;
        else out[o++] = (char)c;
    }
    out[o] = 0;
}

static void setRootFromRegistry(const char* reg) {
    char dir[MAX_PATH * 2];
    char* slash;
    snprintf(dir, sizeof(dir), "%s", reg ? reg : "");
    slash = strrchr(dir, '\\'); if (!slash) slash = strrchr(dir, '/');
    if (slash) *slash = 0; /* .../registry */
    slash = strrchr(dir, '\\'); if (!slash) slash = strrchr(dir, '/');
    if (slash) *slash = 0; /* .../lc930 */
    snprintf(LCREG_UP, sizeof(LCREG_UP), "%s", dir);
    snprintf(LCREG_BASE, sizeof(LCREG_BASE), "%s", dir);
    if (dir[0]) SetCurrentDirectoryA(dir);
}

static int buffEnsure(const char* registryPath) {
    const char* reg = registryPath && registryPath[0] ? registryPath : g_regPath;
    if (!reg || !reg[0]) reg = "registry/LC930_REGISTRY.txt";
    if (!g_ready || (registryPath && registryPath[0] && strcmp(g_regPath, registryPath) != 0)) {
        if (registryPath && registryPath[0]) {
            strncpy(g_regPath, registryPath, sizeof(g_regPath) - 1);
            g_regPath[sizeof(g_regPath) - 1] = 0;
            reg = g_regPath;
        }
        setRootFromRegistry(reg);
        lcreg_load(reg);
        lc_reg_apply();
        lbuff_load(reg);
        g_ready = 1;
    }
    if (lc_attach()) return 0;
    if (!lc_anchor()) return 0;
    lbuff_start();
    return 1;
}

static int writeBuffJson(FILE* f) {
    LBuff out[128];
    int n, first = 1;
    DWORD now = GetTickCount();

    n = lbuff_poll(out, 128, now);
    fprintf(f,
            "{\"cmd\":\"buff\",\"pid\":%llu,\"base\":\"0x%llX\",\"cache\":%d,"
            "\"rescanned\":true,\"reason\":\"map\",\"reads\":%ld,\"buffs\":[",
            (unsigned long long)g_pid, (unsigned long long)g_base, B_ncache, B_reads);

    for (int i = 0; i < n; i++) {
        char esc[320];
        jsonEsc(out[i].name, esc, (int)sizeof(esc));
        if (!first) fputc(',', f);
        first = 0;
        fprintf(f,
                "{\"name\":\"%s\",\"skill\":%u,\"strId\":%u,\"remain\":%.3f,"
                "\"duration\":%u,\"perpetual\":%s}",
                esc, out[i].skill, out[i].strid, out[i].remain, out[i].dur,
                out[i].perpet ? "true" : "false");
    }
    fprintf(f, "],\"n\":%d}", n);
    return 1;
}

__declspec(dllexport) int buff_listen_snapshot(const char* registryPath, char* out, int outCap) {
    FILE* tf;
    long n;
    size_t got;
    if (!out || outCap < 16) return -1;
    pg_reset();
    if (!buffEnsure(registryPath)) return -1;
    tf = tmpfile();
    if (!tf) return -1;
    writeBuffJson(tf);
    fflush(tf);
    if (fseek(tf, 0, SEEK_END) != 0) { fclose(tf); return -1; }
    n = ftell(tf);
    if (n < 2 || n >= outCap) { fclose(tf); return -2; }
    fseek(tf, 0, SEEK_SET);
    got = fread(out, 1, (size_t)n, tf);
    fclose(tf);
    if (got < 2) return -1;
    out[got] = 0;
    return (int)got;
}

__declspec(dllexport) void buff_listen_shutdown(void) {
    SignedClose();
    g_ready = 0;
    g_pid = 0;
    g_base = 0;
    B_ncache = 0;
    B_sn = 0;
}

#ifndef BUFF_LISTEN_DLL
int main(int argc, char** argv) {
    char buf[1 << 20];
    const char* reg = argc > 1 ? argv[1] : "registry/LC930_REGISTRY.txt";
    int n;
    SetConsoleOutputCP(CP_UTF8);
    n = buff_listen_snapshot(reg, buf, (int)sizeof(buf));
    if (n < 0) { fprintf(stderr, "buff snapshot fail %d\n", n); return 1; }
    fwrite(buf, 1, (size_t)n, stdout);
    fputc('\n', stdout);
    buff_listen_shutdown();
    return 0;
}
#endif
