/* shop_listen.c - ShopSubsystem Buy/Sell snapshot for LC.exe
 * Same offsets as shopwatch.c. DLL export for the bot; exe watches changes.
 * usage: shop_listen.exe [seconds]   (0 = until Ctrl+C)
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "signeddrv_client.h"

static uint64_t g_pid = 0, g_base = 0;
static uint32_t g_modSize = 0;
static int g_attached = 0;

static int rm(uint64_t a, void* b, uint32_t s) {
    uint32_t br = 0;
    return SignedReadMemory(g_pid, a, b, s, &br) && br == s;
}
static uint64_t q64(uint64_t a) {
    uint64_t v = 0;
    rm(a, &v, 8);
    return v;
}
static uint32_t d32(uint64_t a) {
    uint32_t v = 0;
    rm(a, &v, 4);
    return v;
}
static int inMod(uint64_t a) {
    return a >= g_base && a < g_base + (uint64_t)g_modSize;
}
static int isHeap(uint64_t a) {
    return a >= 0x10000000000ULL && a < 0x80000000000ULL;
}

static int getModule(uint64_t* base, uint32_t* size) {
    uint64_t peb = 0, ldr = 0, head = 0, cur = 0;
    if (!SignedGetPeb(g_pid, &peb) || !peb) return 0;
    if (!rm(peb + 0x18, &ldr, 8) || !ldr) return 0;
    if (!rm(ldr + 0x20, &head, 8) || !head) return 0;
    cur = head;
    for (int g = 0; g < 5000 && cur && cur != (ldr + 0x20); g++) {
        uint64_t e = cur - 0x10, db = 0;
        uint32_t ds = 0;
        if (rm(e + 0x30, &db, 8) && db && rm(e + 0x40, &ds, 4) && ds) {
            *base = db;
            *size = ds;
            return 1;
        }
        if (!rm(cur, &cur, 8)) break;
    }
    return 0;
}

static uint64_t FNV_OFF = 0xcbf29ce484222325ULL, FNV_PRIME = 0x100000001b3ULL;
static uint64_t fnv1a(const char* s) {
    uint64_t h = FNV_OFF;
    for (const unsigned char* p = (const unsigned char*)s; *p; p++) {
        h ^= *p;
        h *= FNV_PRIME;
    }
    return h;
}
static void readSSO(uint64_t a, char* out, int cap) {
    out[0] = 0;
    if (!a) return;
    uint64_t len = q64(a + 0x10), cp = q64(a + 0x18), data = (cp >= 16) ? q64(a) : a;
    if (len == 0 || len > (uint64_t)cap - 1) return;
    if (!rm(data, out, (uint32_t)len))
        out[0] = 0;
    else
        out[len] = 0;
}
static int resolve(uint32_t mid, char* out, int cap) {
    out[0] = 0;
    uint64_t anchor = q64(g_base + 0x1668888);
    if (!anchor) return 0;
    char key[32];
    snprintf(key, sizeof(key), "1_%u", mid);
    uint64_t idx = fnv1a(key) & 0xFFFF;
    uint64_t rec = q64(anchor + idx * 0x10);
    int guard = 0;
    while (rec && isHeap(rec) && guard++ < 64) {
        char k[64];
        readSSO(rec + 0x10, k, sizeof(k));
        if (!strcmp(k, key)) {
            uint64_t p1 = q64(rec + 0x38);
            if (!isHeap(p1)) return 0;
            uint64_t p2 = q64(p1 + 0x00);
            if (!isHeap(p2)) return 0;
            readSSO(p2 + 0x30, out, cap);
            return out[0] != 0;
        }
        rec = q64(rec + 0x00);
    }
    return 0;
}
static uint32_t midFromKey(uint64_t ptr) {
    if (!isHeap(ptr)) return 0;
    char b[64];
    if (!rm(ptr - 8, b, 60)) return 0;
    for (int i = 0; i < 52; i++) {
        if (b[i] == '$') {
            int j = i + 1;
            uint32_t v = 0, ok = 0;
            while (j < 60 && b[j] >= '0' && b[j] <= '9') {
                v = v * 10 + (uint32_t)(b[j] - '0');
                j++;
                ok = 1;
            }
            if (ok) return v;
        }
    }
    return 0;
}
static uint32_t midFromFmt(const char* fmt) {
    for (int i = 0; fmt[i]; i++)
        if (fmt[i] == '$') {
            int j = i + 1;
            uint32_t v = 0, ok = 0;
            while (fmt[j] >= '0' && fmt[j] <= '9') {
                v = v * 10 + (uint32_t)(fmt[j] - '0');
                j++;
                ok = 1;
            }
            if (ok) return v;
        }
    return 0;
}

static void jsonEscape(const char* in, char* out, int cap) {
    int o = 0;
    if (!in) {
        out[0] = 0;
        return;
    }
    for (int i = 0; in[i] && o < cap - 2; i++) {
        unsigned char c = (unsigned char)in[i];
        if (c == '"' || c == '\\') {
            if (o + 2 >= cap) break;
            out[o++] = '\\';
            out[o++] = (char)c;
        } else if (c < 0x20) {
            continue;
        } else {
            out[o++] = (char)c;
        }
    }
    out[o] = 0;
}

static DWORD findPid(const wchar_t* exe) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32W pe;
    pe.dwSize = sizeof(pe);
    DWORD pid = 0;
    if (Process32FirstW(snap, &pe))
        do {
            if (_wcsicmp(pe.szExeFile, exe) == 0) {
                pid = pe.th32ProcessID;
                break;
            }
        } while (Process32NextW(snap, &pe));
    CloseHandle(snap);
    return pid;
}

static int shopAttach(void) {
    if (g_attached && g_pid && g_base) return 1;
    if (!SignedOpen()) return 0;
    DWORD pid = findPid(L"LC.exe");
    if (!pid) {
        SignedClose();
        return 0;
    }
    SignedSetTarget(pid);
    g_pid = pid;
    if (!getModule(&g_base, &g_modSize)) {
        SignedClose();
        g_pid = 0;
        g_base = 0;
        return 0;
    }
    g_attached = 1;
    return 1;
}

static void shopDetach(void) {
    if (!g_attached) return;
    SignedClose();
    g_attached = 0;
    g_pid = 0;
    g_base = 0;
    g_modSize = 0;
}

/* Write one JSON snapshot to f. Returns 1 on success. */
static int writeShopJson(FILE* f) {
    uint64_t mgr = q64(g_base + 0x1668860);
    uint64_t holder = q64(mgr + 0xD0);
    uint64_t subs = q64(holder + 0x180);
    uint64_t shop = q64(subs + 16 * 36);
    uint64_t inv = q64(subs + 16 * 26);
    if (!isHeap(shop)) {
        fprintf(f, "{\"cmd\":\"shop\",\"error\":\"no_shop\",\"pid\":%lu,\"base\":\"0x%llX\"}",
                (unsigned long)g_pid, (unsigned long long)g_base);
        return 1;
    }
    int state = (int)d32(shop + 0x28);
    uint64_t vb = q64(shop + 0x40), ve = q64(shop + 0x48);
    uint64_t sb = q64(shop + 0x58), se = q64(shop + 0x60);
    uint64_t bn = (isHeap(vb) && isHeap(ve) && ve >= vb) ? (ve - vb) / 0x90 : 0;
    uint64_t sn = (isHeap(sb) && isHeap(se) && se >= sb) ? (se - sb) / 0x20 : 0;
    if (bn > 512) bn = 512;
    if (sn > 512) sn = 512;
    uint64_t ib = q64(inv + 0x3D8), ie = q64(inv + 0x3E0);
    int incnt = (isHeap(ib) && isHeap(ie) && ie >= ib) ? (int)((ie - ib) / 8) : 0;
    if (incnt > 0x400) incnt = 0x400;

    fprintf(f,
            "{\"cmd\":\"shop\",\"pid\":%lu,\"base\":\"0x%llX\",\"state\":%d,\"buy_n\":%llu,\"sell_n\":%llu,\"buy\":[",
            (unsigned long)g_pid, (unsigned long long)g_base, state, (unsigned long long)bn,
            (unsigned long long)sn);

    for (uint64_t k = 0; k < bn; k++) {
        uint64_t b = vb + k * 0x90;
        if (!inMod(q64(b)) || (uint32_t)(q64(b) - g_base) != 0x11DE1B8u) break;
        uint32_t order = d32(b + 0x38), itemId = d32(b + 0x3C), tmpl = d32(b + 0x40),
                 price = d32(b + 0x44);
        uint64_t kp = q64(b + 0x30);
        uint32_t mid = isHeap(kp) ? midFromKey(kp) : 0;
        char nm[256] = "", esc[512];
        if (mid) resolve(mid, nm, sizeof(nm));
        jsonEscape(nm, esc, sizeof(esc));
        if (k) fputc(',', f);
        fprintf(f,
                "{\"idx\":%llu,\"order\":%u,\"itemId\":%u,\"tmpl\":%u,\"price\":%u,\"name\":\"%s\"}",
                (unsigned long long)k, order, itemId, tmpl, price, esc);
    }
    fprintf(f, "],\"sell\":[");
    int sold = 0;
    for (uint64_t k = 0; k < sn; k++) {
        uint64_t b = sb + k * 0x20;
        if (!inMod(q64(b)) || (uint32_t)(q64(b) - g_base) != 0x11DE220u) break;
        uint32_t id = d32(b + 0x18), unit = d32(b + 0x1C);
        char fmt[64] = "", nm[256] = "", esc[512];
        uint32_t tmpl = 0, cnt = 0, mid = 0;
        for (int j = 0; j < incnt; j++) {
            uint64_t it = q64(ib + j * 8);
            if (isHeap(it) && (uint32_t)(q64(it) - g_base) == 0x11C6640u &&
                d32(it + 0x18) == id) {
                readSSO(it + 0x68, fmt, sizeof(fmt));
                tmpl = d32(it + 0x20);
                cnt = d32(it + 0x38);
                break;
            }
        }
        mid = midFromFmt(fmt);
        if (mid) resolve(mid, nm, sizeof(nm));
        jsonEscape(nm, esc, sizeof(esc));
        if (sold) fputc(',', f);
        fprintf(f,
                "{\"idx\":%llu,\"id\":%u,\"tmpl\":%u,\"count\":%u,\"unit\":%u,\"name\":\"%s\"}",
                (unsigned long long)k, id, tmpl, cnt, unit, esc);
        sold++;
    }
    fprintf(f, "]}");
    return 1;
}

/* One shop scan. Returns JSON bytes written to out, or <0 on failure. */
__declspec(dllexport) int shop_listen_snapshot(const char* unusedOffsets, char* out, int outCap) {
    FILE* tf;
    long n;
    size_t got;
    (void)unusedOffsets;
    if (!out || outCap < 16) return -1;
    if (!shopAttach()) return -1;
    tf = tmpfile();
    if (!tf) return -1;
    writeShopJson(tf);
    fflush(tf);
    if (fseek(tf, 0, SEEK_END) != 0) {
        fclose(tf);
        return -1;
    }
    n = ftell(tf);
    if (n < 2 || n >= outCap) {
        fclose(tf);
        return -2;
    }
    fseek(tf, 0, SEEK_SET);
    got = fread(out, 1, (size_t)n, tf);
    fclose(tf);
    if (got < 2) return -1;
    out[got] = 0;
    return (int)got;
}

__declspec(dllexport) void shop_listen_shutdown(void) { shopDetach(); }

#ifndef SHOP_LISTEN_DLL
static const char* g_last = NULL;

static void dumpBuy(uint64_t shop) {
    uint64_t vb = q64(shop + 0x40), ve = q64(shop + 0x48);
    uint64_t n = (isHeap(vb) && isHeap(ve) && ve >= vb) ? (ve - vb) / 0x90 : 0;
    if (n > 512) n = 512;
    printf("[BUY] n=%llu\n", (unsigned long long)n);
    for (uint64_t k = 0; k < n; k++) {
        uint64_t b = vb + k * 0x90;
        if (!inMod(q64(b)) || (uint32_t)(q64(b) - g_base) != 0x11DE1B8u) break;
        uint32_t order = d32(b + 0x38), itemId = d32(b + 0x3C), tmpl = d32(b + 0x40),
                 price = d32(b + 0x44);
        uint64_t kp = q64(b + 0x30);
        uint32_t mid = isHeap(kp) ? midFromKey(kp) : 0;
        char nm[256] = "";
        if (mid) resolve(mid, nm, sizeof(nm));
        printf("  idx=%2llu order=%u itemId=%u tmpl=%u price=%u %s\n", (unsigned long long)k,
               order, itemId, tmpl, price, nm);
    }
    fflush(stdout);
}

static void dumpSell(uint64_t shop, uint64_t ib, int incnt) {
    uint64_t sb = q64(shop + 0x58), se = q64(shop + 0x60);
    uint64_t n = (isHeap(sb) && isHeap(se) && se >= sb) ? (se - sb) / 0x20 : 0;
    if (n > 512) n = 512;
    printf("[SELL] n=%llu  (idx 0 = top; scroll must NOT reorder)\n", (unsigned long long)n);
    char order_line[2048];
    int op = 0;
    order_line[0] = 0;
    for (uint64_t k = 0; k < n; k++) {
        uint64_t b = sb + k * 0x20;
        if (!inMod(q64(b)) || (uint32_t)(q64(b) - g_base) != 0x11DE220u) break;
        uint32_t id = d32(b + 0x18), unit = d32(b + 0x1C);
        char fmt[64] = "", nm[256] = "";
        uint32_t tmpl = 0, cnt = 0, mid = 0;
        for (int j = 0; j < incnt; j++) {
            uint64_t it = q64(ib + j * 8);
            if (isHeap(it) && (uint32_t)(q64(it) - g_base) == 0x11C6640u &&
                d32(it + 0x18) == id) {
                readSSO(it + 0x68, fmt, sizeof(fmt));
                tmpl = d32(it + 0x20);
                cnt = d32(it + 0x38);
                break;
            }
        }
        mid = midFromFmt(fmt);
        if (mid) resolve(mid, nm, sizeof(nm));
        printf("  idx=%2llu id=%u tmpl=%u invCnt=%u unit=%u %s\n", (unsigned long long)k, id,
               tmpl, cnt, unit, nm);
        if (op < (int)sizeof(order_line) - 64) {
            const char* label = nm[0] ? nm : "?";
            int wr = snprintf(order_line + op, (int)sizeof(order_line) - op, "%s%llu:%s",
                              op ? ", " : "", (unsigned long long)k, label);
            if (wr > 0) op += wr;
        }
    }
    if (order_line[0]) printf("[SELL-ORDER] %s\n", order_line);
    fflush(stdout);
}

int main(int argc, char** argv) {
    SetConsoleOutputCP(CP_UTF8);
    int seconds = argc > 1 ? atoi(argv[1]) : 0;
    if (!shopAttach()) {
        printf("attach fail (LC.exe / driver)\n");
        return 1;
    }
    printf("watch start (BASE=0x%llX). open the NPC shop; lists auto-capture.\n",
           (unsigned long long)g_base);
    DWORD t0 = GetTickCount();
    for (;;) {
        uint64_t mgr = q64(g_base + 0x1668860), holder = q64(mgr + 0xD0),
                 subs = q64(holder + 0x180);
        uint64_t shop = q64(subs + 16 * 36), inv = q64(subs + 16 * 26);
        int state = (int)d32(shop + 0x28);
        uint64_t vb = q64(shop + 0x40), ve = q64(shop + 0x48), sb = q64(shop + 0x58),
                 se = q64(shop + 0x60);
        uint64_t bn = (isHeap(vb) && isHeap(ve) && ve >= vb) ? (ve - vb) / 0x90 : 0;
        uint64_t sn = (isHeap(sb) && isHeap(se) && se >= sb) ? (se - sb) / 0x20 : 0;
        uint64_t ib = q64(inv + 0x3D8), ie = q64(inv + 0x3E0);
        int incnt = (isHeap(ib) && isHeap(ie) && ie >= ib) ? (int)((ie - ib) / 8) : 0;
        if (incnt > 0x400) incnt = 0x400;
        char sig[128];
        snprintf(sig, sizeof(sig), "s%d_b%llu_%u_s%llu_%u", state, (unsigned long long)bn,
                 bn ? d32(vb + 0x38) : 0, (unsigned long long)sn, sn ? d32(sb + 0x18) : 0);
        if (!g_last || strcmp(g_last, sig) != 0) {
            printf("\n=== change t=%ums state=%d buy=%llu sell=%llu ===\n",
                   (unsigned)(GetTickCount() - t0), state, (unsigned long long)bn,
                   (unsigned long long)sn);
            if (bn) dumpBuy(shop);
            if (sn) dumpSell(shop, ib, incnt);
            free((void*)g_last);
            g_last = strdup(sig);
        }
        if (seconds > 0 && (int)(GetTickCount() - t0) >= seconds * 1000) break;
        Sleep(150);
    }
    shopDetach();
    return 0;
}
#endif
