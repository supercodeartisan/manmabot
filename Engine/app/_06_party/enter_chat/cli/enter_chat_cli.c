/* ============================================================================
 * enter_chat_cli.c - command-line front end for enter_chat.dll
 *
 * Examples
 *   enter_chat_cli.exe --pid 19708 --file chat.txt --cps 8 --jitter 30
 *   enter_chat_cli_admin.exe --pid 19708 --file chat.txt --cps 8 --jitter 30 --enter
 *   enter_chat_cli.exe --pid 19708 --file chat.txt --dry-run --json
 *
 * Text sources:
 *   --text <utf8/wide>   command-line text (wmain receives UTF-16)
 *   --file <path>        UTF-8 / UTF-16LE / UTF-16BE, BOM aware
 *   --stdin              bytes from stdin (UTF-8 / UTF-16, BOM aware)
 * ========================================================================== */
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <io.h>
#include <fcntl.h>

#include "enter_chat.h"

#define EC_CLI_MAX_BYTES (64u * 1024u * 1024u)

static void usage(void)
{
    wprintf(
L"enter_chat_cli %ls - PID-targeted mixed text injector\n"
L"\n"
L"Target:\n"
L"  --pid <n>            target process id\n"
L"  --hwnd <hex|dec>     explicit target window (optional)\n"
L"\n"
L"Text:\n"
L"  --text <string>      literal text (wmain receives UTF-16)\n"
L"  --file <path>        UTF-8 / UTF-16LE / UTF-16BE file (BOM aware)\n"
L"  --stdin              read bytes from stdin (UTF-8 / UTF-16, BOM aware)\n"
L"\n"
L"Typing:\n"
L"  --cps <n>            characters per second (default 10)\n"
L"  --jitter <ms>        random +/- per-character jitter (default 0)\n"
L"  --jamo-delay <ms>    delay between jamo keys (default 8)\n"
L"  --enter              press Enter after the text\n"
L"\n"
L"Options:\n"
L"  --esc                send Esc before typing (cancel/close input line)\n"
L"  --open               send Enter before typing (open a fresh input line)\n"
L"  --no-focus           do not force the target to the foreground\n"
L"  --no-sendinput       do not fall back to SendInput when WM_CHAR fails\n"
L"  --no-start-commit    skip the initial IME composition flush\n"
L"  --dry-run            count/decompose only; send nothing\n"
L"  --json               machine-readable JSON output\n"
L"  --help, -h           this help\n"
L"\n"
L"Examples:\n"
L"  enter_chat_cli.exe --pid 19708 --file chat.txt --cps 8 --jitter 30\n"
L"  enter_chat_cli_admin.exe --pid 19708 --file chat.txt --cps 8 --jitter 30\n"
L"  enter_chat_cli.exe --pid 19708 --file chat.txt --dry-run --json\n",
        ec_version());
}

static wchar_t* bytes_to_text(const unsigned char* b, size_t n)
{
    wchar_t* w = NULL;
    size_t off = 0;
    int need;

    if (n >= 2 && b[0] == 0xFF && b[1] == 0xFE) {          /* UTF-16 LE */
        size_t len = (n - 2) / 2;
        w = (wchar_t*)calloc(len + 1, sizeof(wchar_t));
        if (!w) return NULL;
        memcpy(w, b + 2, len * 2);
        w[len] = 0;
        return w;
    }
    if (n >= 2 && b[0] == 0xFE && b[1] == 0xFF) {          /* UTF-16 BE */
        size_t len = (n - 2) / 2;
        w = (wchar_t*)calloc(len + 1, sizeof(wchar_t));
        if (!w) return NULL;
        for (size_t i = 0; i < len; ++i)
            w[i] = (wchar_t)((b[2 + i * 2] << 8) | b[3 + i * 2]);
        w[len] = 0;
        return w;
    }
    if (n >= 3 && b[0] == 0xEF && b[1] == 0xBB && b[2] == 0xBF)
        off = 3;                                            /* UTF-8 BOM */

    if (n == off) {                                         /* empty file */
        w = (wchar_t*)calloc(1, sizeof(wchar_t));
        return w;
    }

    need = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS,
                               (const char*)b + off, (int)(n - off), NULL, 0);
    if (need <= 0) {
        /* Fallback for legacy ANSI files. */
        need = MultiByteToWideChar(CP_ACP, 0,
                                   (const char*)b + off, (int)(n - off), NULL, 0);
        if (need <= 0) return NULL;
        w = (wchar_t*)calloc((size_t)need + 1, sizeof(wchar_t));
        if (!w) return NULL;
        MultiByteToWideChar(CP_ACP, 0, (const char*)b + off, (int)(n - off), w, need);
        w[need] = 0;
        return w;
    }

    w = (wchar_t*)calloc((size_t)need + 1, sizeof(wchar_t));
    if (!w) return NULL;
    MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS,
                        (const char*)b + off, (int)(n - off), w, need);
    w[need] = 0;
    return w;
}

static wchar_t* load_file(const wchar_t* path)
{
    FILE* f;
    long sz;
    unsigned char* b;
    size_t got;
    wchar_t* w;

    f = _wfopen(path, L"rb");
    if (!f) return NULL;
    if (fseek(f, 0, SEEK_END) != 0) { fclose(f); return NULL; }
    sz = ftell(f);
    if (sz < 0 || (unsigned long)sz > EC_CLI_MAX_BYTES) { fclose(f); return NULL; }
    rewind(f);

    b = (unsigned char*)malloc((size_t)sz + 1);
    if (!b) { fclose(f); return NULL; }
    got = fread(b, 1, (size_t)sz, f);
    fclose(f);

    w = bytes_to_text(b, got);
    free(b);
    return w;
}

static wchar_t* read_stdin(void)
{
    size_t cap = 65536, n = 0, r;
    unsigned char* b = (unsigned char*)malloc(cap);
    wchar_t* w;

    if (!b) return NULL;
    _setmode(_fileno(stdin), _O_BINARY);
    while ((r = fread(b + n, 1, cap - n, stdin)) > 0) {
        n += r;
        if (n == cap) {
            unsigned char* nb;
            if (cap >= EC_CLI_MAX_BYTES) { free(b); return NULL; }
            cap *= 2;
            nb = (unsigned char*)realloc(b, cap);
            if (!nb) { free(b); return NULL; }
            b = nb;
        }
    }
    w = bytes_to_text(b, n);
    free(b);
    return w;
}

static void json_escape(const wchar_t* w, char* out, size_t cap)
{
    char* u = NULL;
    int need;
    size_t j = 0;

    if (!out || cap == 0) return;
    out[0] = 0;
    if (!w) return;

    need = WideCharToMultiByte(CP_UTF8, 0, w, -1, NULL, 0, NULL, NULL);
    if (need > 0) {
        u = (char*)malloc((size_t)need);
        if (u) WideCharToMultiByte(CP_UTF8, 0, w, -1, u, need, NULL, NULL);
    }
    if (!u) return;

    for (char* p = u; *p && j + 2 < cap; ++p) {
        unsigned char c = (unsigned char)*p;
        if (c == '"' || c == '\\') {
            out[j++] = '\\';
            out[j++] = (char)c;
        } else if (c == '\n') {
            out[j++] = '\\'; out[j++] = 'n';
        } else if (c == '\r') {
            out[j++] = '\\'; out[j++] = 'r';
        } else if (c == '\t') {
            out[j++] = '\\'; out[j++] = 't';
        } else if (c < 0x20) {
            out[j++] = '?';
        } else {
            out[j++] = (char)c;
        }
    }
    out[j] = 0;
    free(u);
}

int wmain(int argc, wchar_t** argv)
{
    DWORD pid = 0;
    HWND hwnd = NULL;
    const wchar_t* text = NULL;
    wchar_t* owned = NULL;
    double cps = 0.0;
    int jitter = 0;
    int jamo = 0;
    BOOL press_enter = FALSE;
    BOOL json = FALSE;
    DWORD flags = EC_FLAG_SENDINPUT_FALLBACK;
    EcRequest req;
    EcResult res;
    int rc;

    for (int i = 1; i < argc; ++i) {
        const wchar_t* a = argv[i];

        if (!wcscmp(a, L"--pid") && i + 1 < argc) {
            pid = (DWORD)wcstoul(argv[++i], NULL, 10);
        } else if (!wcscmp(a, L"--hwnd") && i + 1 < argc) {
            hwnd = (HWND)(ULONG_PTR)wcstoull(argv[++i], NULL, 0);
        } else if (!wcscmp(a, L"--text") && i + 1 < argc) {
            free(owned);
            owned = _wcsdup(argv[++i]);
            text = owned;
        } else if (!wcscmp(a, L"--file") && i + 1 < argc) {
            free(owned);
            owned = load_file(argv[++i]);
            text = owned;
            if (!owned) {
                wprintf(L"error: cannot read or decode file: %ls\n", argv[i]);
                return EC_E_TEXT;
            }
        } else if (!wcscmp(a, L"--stdin")) {
            free(owned);
            owned = read_stdin();
            text = owned;
            if (!owned) {
                wprintf(L"error: cannot read or decode stdin\n");
                return EC_E_TEXT;
            }
        } else if (!wcscmp(a, L"--cps") && i + 1 < argc) {
            cps = _wtof(argv[++i]);
        } else if (!wcscmp(a, L"--jitter") && i + 1 < argc) {
            jitter = _wtoi(argv[++i]);
        } else if (!wcscmp(a, L"--jamo-delay") && i + 1 < argc) {
            jamo = _wtoi(argv[++i]);
        } else if (!wcscmp(a, L"--enter")) {
            press_enter = TRUE;
        } else if (!wcscmp(a, L"--esc")) {
            flags |= EC_FLAG_CLEAR_FIRST;
        } else if (!wcscmp(a, L"--open")) {
            flags |= EC_FLAG_OPEN_CHAT;
        } else if (!wcscmp(a, L"--no-focus")) {
            flags |= EC_FLAG_NO_FOCUS;
        } else if (!wcscmp(a, L"--no-sendinput")) {
            flags &= ~EC_FLAG_SENDINPUT_FALLBACK;
        } else if (!wcscmp(a, L"--no-start-commit")) {
            flags |= EC_FLAG_NO_START_COMMIT;
        } else if (!wcscmp(a, L"--dry-run")) {
            flags |= EC_FLAG_DRY_RUN;
        } else if (!wcscmp(a, L"--json")) {
            json = TRUE;
        } else if (!wcscmp(a, L"--help") || !wcscmp(a, L"-h")) {
            usage();
            free(owned);
            return 0;
        } else {
            wprintf(L"unknown option: %ls\n", a);
            usage();
            free(owned);
            return EC_E_ARGUMENT;
        }
    }

    if (!text) {
        wprintf(L"error: specify --text, --file or --stdin\n");
        usage();
        return EC_E_ARGUMENT;
    }
    if (!pid && !hwnd) {
        wprintf(L"error: specify --pid or --hwnd\n");
        usage();
        free(owned);
        return EC_E_ARGUMENT;
    }

    memset(&req, 0, sizeof(req));
    req.text = text;
    req.pid = pid;
    req.hwnd = hwnd;
    req.chars_per_second = cps;
    req.jitter_ms = jitter;
    req.jamo_delay_ms = jamo;
    req.press_enter = press_enter;
    req.flags = flags;
    req.focus_timeout_ms = 1500;

    memset(&res, 0, sizeof(res));
    rc = ec_run(&req, &res);

    if (json) {
        char msg[2048];
        json_escape(res.message, msg, sizeof(msg));
        printf("{\"ok\":%s,\"status\":%d,\"pid\":%lu,\"hwnd\":\"0x%llX\","
               "\"chars\":%d,\"keys\":%d,\"failed\":%d,\"skipped\":%d,"
               "\"enter\":%s,\"elapsed_ms\":%lu,\"message\":\"%s\"}\n",
               rc == EC_OK ? "true" : "false",
               (int)res.status,
               (unsigned long)res.pid,
               (unsigned long long)(ULONG_PTR)res.hwnd,
               res.chars, res.keys, res.failed, res.skipped,
               res.enter_pressed ? "true" : "false",
               (unsigned long)res.elapsed_ms,
               msg);
    } else {
        wprintf(L"enter_chat %ls (elevated=%d)\n", ec_version(), ec_is_elevated());
        wprintf(L"target: pid=%lu hwnd=0x%p\n",
                (unsigned long)res.pid, (void*)res.hwnd);
        wprintf(L"text: chars=%d keys=%d failed=%d skipped=%d enter=%ls\n",
                res.chars, res.keys, res.failed, res.skipped,
                res.enter_pressed ? L"yes" : L"no");
        wprintf(L"status: %d (%ls)\n", (int)res.status, ec_status_string(res.status));
        if (res.message[0])
            wprintf(L"message: %ls\n", res.message);
        wprintf(L"elapsed: %lu ms\n", (unsigned long)res.elapsed_ms);

        if (res.status == EC_E_ELEVATION && !ec_is_elevated())
            wprintf(L"hint: run enter_chat_cli_admin.exe for high-integrity targets.\n");
    }

    free(owned);
    return rc;
}
