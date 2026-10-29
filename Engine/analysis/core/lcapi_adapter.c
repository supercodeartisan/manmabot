/* lcapi_adapter.c — LC 모듈 DLL 글루(공통). 모듈 .c 와 함께 한 개의 DLL 로 빌드된다.
 * ============================================================================
 *  이 파일은 "모든 모듈 DLL 이 공통으로 export 하는 API" 를 구현한다.
 *  실제 데이터 읽기 로직은 같은 DLL 에 함께 링크된 모듈 원천(.c)이 담당하고,
 *  그 진입점은 shim(src/api/<mod>_api.c)에서 `#define main lcapi_mod_main` 으로
 *  리네임되어 이 파일이 호출한다.
 *
 *  구동 방식(파일 없이 실시간 전달):
 *    1) interval/jitter 를 환경변수로 주입 → 모듈의 lcreg_poll_load 가 채택.
 *    2) 모듈별 추가 파라미터(KEY=VALUE)를 LCAPI_CFG_<KEY> 환경변수로 주입
 *       → lcreg 가 registry 값 대신 채택한다(예: enttrack 스윕/보간 주기).
 *    3) 모듈을 동기 실행한다. 모듈의 1차 출력은 "NUL"(lcapi_rt.h)이고,
 *       그 파일로 가는 fprintf 는 메모리 버퍼로 캡처된다.
 *    4) 모듈이 매 반복 끝에서 lcapi_sample() 를 호출하면, 캡처 버퍼를 곧바로
 *       sink 로 전달한다(실시간). count 도달 시 모듈에 조기종료를 요청한다.
 *    5) 표본 간 최소 간격(interval + rand(0..jitter))을 어댑터가 보장한다.
 *
 *  모듈 원천은 LCAPI_INPROC 정의 하에 컴파일되며, EXE 빌드에서는 이 파일이
 *  링크되지 않는다(동작 불변).
 * ========================================================================== */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "lcapi.h"
#include "lcapi_rt.h"

/* ── 모듈 TU(shim)가 제공하는 심볼 ─────────────────────────────────────── */
extern const char *lcapi_mod_name;
extern const char *lcapi_mod_out;
extern const char *lcapi_mod_args;     /* argv 템플릿: %R=registry %S=secs %D=outdir */
extern const char *lcapi_mod_version;
extern const char *lcapi_mod_info;
extern int lcapi_mod_main(int argc, char **argv);

/* ── 공유 런타임 전역(모듈 TU 가 lcapi_rt.h 로 참조) ───────────────────── */
volatile int  lcapi_active = 0;
volatile int  lcapi_stop   = 0;
volatile long lcapi_target = 0;
volatile long lcapi_seen   = 0;
FILE         *lcapi_out_file = NULL;

/* ── 설정 상태 ─────────────────────────────────────────────────────────── */
static char     g_reg[1024]    = {0};
static char     g_params[2048] = {0};
static uint32_t g_interval = 0;
static uint32_t g_jitter   = 0;
static uint32_t g_count    = 0;

/* ── 캡처 버퍼(모듈 1차 출력 텍스트) ──────────────────────────────────── */
static char  *g_cap     = NULL;
static size_t g_capLen  = 0;
static size_t g_capCap  = 0;

/* ── 표본 전달(sink) + 페이싱 ─────────────────────────────────────────── */
static lcapi_sink_fn g_sink = NULL;
static void         *g_ctx  = NULL;
static DWORD         g_lastEmit = 0;
static int           g_haveEmit = 0;

static void err_set(char *err, uint32_t cap, const char *msg)
{
    if (err && cap) snprintf(err, cap, "%s", msg ? msg : "");
}

void lcapi_cap_add(const char *s, int n)
{
    if (n <= 0) return;
    if (g_capLen + (size_t)n + 1 > g_capCap) {
        size_t nc = g_capCap ? g_capCap * 2 : 65536;
        while (nc < g_capLen + (size_t)n + 1) nc *= 2;
        char *np = (char *)realloc(g_cap, nc);
        if (!np) return;
        g_cap = np; g_capCap = nc;
    }
    memcpy(g_cap + g_capLen, s, (size_t)n);
    g_capLen += (size_t)n;
    g_cap[g_capLen] = 0;
}

int lcapi_emit(void)
{
    /* 표본 간 최소 간격 보장: interval + rand(0..jitter).
     * 모듈이 자체적으로 Sleep 을 하면 실측 간격이 이 값보다 크므로 추가 지연이 없다. */
    if (g_interval) {
        DWORD now = GetTickCount();
        uint32_t extra = g_jitter ? (uint32_t)(rand() % (g_jitter + 1)) : 0;
        uint32_t want = g_interval + extra;
        if (g_haveEmit) {
            uint32_t el = (uint32_t)(now - g_lastEmit);
            if (el < want) { Sleep(want - el); now = GetTickCount(); }
        }
        g_lastEmit = now; g_haveEmit = 1;
    }
    if (g_sink) {
        int r = g_sink(g_ctx, (uint32_t)lcapi_seen, g_cap ? g_cap : "", (uint32_t)g_capLen);
        if (r) lcapi_stop = 1;      /* 호출자가 중단 요청 */
    }
    g_capLen = 0;
    if (g_cap) g_cap[0] = 0;
    return 0;
}

__declspec(dllexport) uint32_t lcapi_abi_version(void) { return LCAPI_ABI_VERSION; }
__declspec(dllexport) const char *lcapi_module_name(void)    { return lcapi_mod_name; }
__declspec(dllexport) const char *lcapi_module_version(void) { return lcapi_mod_version; }
__declspec(dllexport) const char *lcapi_module_info(void)    { return lcapi_mod_info; }

__declspec(dllexport) int lcapi_configure(const char *registry, uint32_t interval_ms,
                                          uint32_t jitter_ms, uint32_t count,
                                          const char *out_dir)
{
    (void)out_dir;   /* 파일 미사용(호환용 인자) */
    g_reg[0] = 0; if (registry) { strncpy(g_reg, registry, sizeof(g_reg) - 1); }
    g_interval = interval_ms;
    g_jitter   = jitter_ms;
    g_count    = count;
    return 0;
}

/* 모듈별 추가 파라미터(KEY=VALUE;...). 0/"" 이면 해제. */
__declspec(dllexport) int lcapi_set_params(const char *params)
{
    g_params[0] = 0;
    if (params) { strncpy(g_params, params, sizeof(g_params) - 1); }
    return 0;
}

/* argv 템플릿을 실제 인자열로. 토큰: %R=registry, %S=secs, %D=outdir */
static int build_args(const char *tmpl, const char *reg, const char *secs, const char *outdir,
                      char *argbuf, uint32_t cap)
{
    const char *t = (tmpl && tmpl[0]) ? tmpl : "%R %S";
    uint32_t n = 0;
    for (const char *p = t; *p && n + 1 < cap; p++) {
        if (*p == '%' && (p[1] == 'R' || p[1] == 'S' || p[1] == 'D')) {
            const char *sub = (p[1] == 'R') ? reg : (p[1] == 'S') ? secs : outdir;
            if (!sub) sub = "";
            for (const char *q = sub; *q && n + 1 < cap; q++) argbuf[n++] = *q;
            p++;
        } else {
            argbuf[n++] = *p;
        }
    }
    argbuf[n] = 0;
    return 0;
}

#define LCAPI_MAXENV 64
static char g_envNames[LCAPI_MAXENV][160];
static int  g_envN = 0;

static void env_set(const char *name, const char *val)
{
    _putenv_s(name, val ? val : "");
    if (g_envN < LCAPI_MAXENV) { strncpy(g_envNames[g_envN], name, 159); g_envNames[g_envN][159] = 0; g_envN++; }
}
static void env_clear_all(void)
{
    for (int i = 0; i < g_envN; i++) _putenv_s(g_envNames[i], "");
    g_envN = 0;
}

/* g_params("KEY=VAL;KEY=VAL")를 환경변수로 주입. INTERVAL/JITTER/COUNT 는 특별 처리. */
static void inject_params(void)
{
    char buf[sizeof(g_params)];
    strncpy(buf, g_params, sizeof(buf) - 1); buf[sizeof(buf) - 1] = 0;
    for (char *p = buf; *p; ) {
        while (*p == ';' || *p == ',' || *p == ' ' || *p == '\t') p++;
        if (!*p) break;
        char *tok = p;
        while (*p && *p != ';' && *p != ',') p++;
        if (*p) *p++ = 0;
        char *eq = strchr(tok, '=');
        if (!eq) continue;
        *eq = 0;
        char *key = tok, *val = eq + 1;
        while (*key == ' ' || *key == '\t') key++;
        char *ke = key + strlen(key);
        while (ke > key && (ke[-1] == ' ' || ke[-1] == '\t')) *--ke = 0;
        while (*val == ' ' || *val == '\t') val++;
        char *ve = val + strlen(val);
        while (ve > val && (ve[-1] == ' ' || ve[-1] == '\t')) *--ve = 0;
        if (!key[0]) continue;
        if      (!_stricmp(key, "INTERVAL_MS")) g_interval = (uint32_t)strtoul(val, 0, 0);
        else if (!_stricmp(key, "JITTER_MS"))   g_jitter   = (uint32_t)strtoul(val, 0, 0);
        else if (!_stricmp(key, "COUNT"))       g_count    = (uint32_t)strtoul(val, 0, 0);
        else {
            char name[160];
            snprintf(name, sizeof(name), "LCAPI_CFG_%s", key);
            env_set(name, val);
        }
    }
}

__declspec(dllexport) int lcapi_run(lcapi_sink_fn sink, void *ctx, char *err, uint32_t err_cap)
{
    if (err && err_cap) err[0] = 0;
    if (!lcapi_mod_main) { err_set(err, err_cap, "no module entry"); return -1; }

    uint32_t iv = g_interval ? g_interval : 100;
    uint32_t jt = g_jitter;
    uint32_t count = g_count;
    if (count == 0) count = 1;

    /* 모듈 실행 구간(안전 상한): count 표본을 넉넉히 뽑을 시간. */
    uint32_t eff = iv + jt / 2; if (eff < 1) eff = 1;
    uint32_t secs = (uint32_t)(((uint64_t)count * eff + 999) / 1000) + 3;
    if (secs > 7200) secs = 7200;

    /* 환경 주입 (CRT getenv 가 보도록 _putenv_s 사용) */
    char vb[32];
    snprintf(vb, sizeof(vb), "%u", iv); env_set("LCAPI_INTERVAL_MS", vb);
    snprintf(vb, sizeof(vb), "%u", jt); env_set("LCAPI_JITTER_MS", vb);
    inject_params();

    /* argv 구성 */
    char secsarg[32]; snprintf(secsarg, sizeof(secsarg), "%u", secs);
    char regarg[1024]; snprintf(regarg, sizeof(regarg), "%s", g_reg[0] ? g_reg : "");
    char argbuf[2048]; build_args(lcapi_mod_args, regarg, secsarg, "", argbuf, sizeof(argbuf));

    char *argv[64]; int argc = 0;
    argv[argc++] = (char *)lcapi_mod_name;
    { char *tok = strtok(argbuf, " \t");
      while (tok && argc < 63) { argv[argc++] = tok; tok = strtok(0, " \t"); } }
    argv[argc] = 0;

    /* 상태 초기화 후 모듈 동기 실행(표본은 실행 중 실시간으로 sink 로 전달).
     *  주의: cwd 는 건드리지 않는다. 모듈이 lcreg_find_root 에서 cwd 를 자기
     *  EXE 위치로 설정하며, 동시 실행 시 프로세스 전역 cwd 를 어댑터가 저장/복원
     *  하면 다른 스레드의 상대경로 해석과 경합한다. */
    srand(GetTickCount());
    g_capLen = 0; if (g_cap) g_cap[0] = 0;
    lcapi_out_file = NULL;
    g_sink = sink; g_ctx = ctx;
    g_haveEmit = 0;
    lcapi_seen = 0; lcapi_target = (long)count; lcapi_stop = 0; lcapi_active = 1;

    int rc = lcapi_mod_main(argc, argv);

    lcapi_active = 0;
    g_sink = NULL; g_ctx = NULL;
    env_clear_all();

    if (rc != 0) {
        char m[160];
        snprintf(m, sizeof(m), "module rc=%d", rc);
        err_set(err, err_cap, m);
        return -3;
    }
    return (int)lcapi_seen;
}
