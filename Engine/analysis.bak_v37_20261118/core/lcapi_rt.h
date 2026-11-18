/* lcapi_rt.h — LCAPI in-process runtime hooks (header-only).
 * ============================================================================
 *  이 헤더는 모든 모듈이 공통으로 include 하는 lcreg.h 에서 자동 포함된다.
 *
 *  · EXE 빌드        : LCAPI_INPROC 미정의 → 아래 훅은 전부 no-op.
 *                      (기존 실행파일 동작/출력이 100% 불변)
 *  · DLL(API) 빌드    : LCAPI_INPROC 정의 →
 *      - 모듈의 1차 출력(파일)은 "NUL" 로 열린다 → 디스크 파일 없음.
 *      - 그 FILE 로 가는 fprintf 는 파일 대신 메모리 버퍼로 캡처된다.
 *      - 모듈이 매 폴링 반복 끝에서 lcapi_sample(f) 를 호출하면 캡처된
 *        표본을 곧바로 sink 로 전달한다(=실시간, 파일 미사용).
 *
 *  어댑터(core/lcapi_adapter.c)가 캡처 버퍼/전달/페이싱을 구현한다.
 * ========================================================================== */
#ifndef LCAPI_RT_H
#define LCAPI_RT_H

#include <stdio.h>
#include <stdarg.h>
#include <string.h>

#ifdef LCAPI_INPROC

/* ── 콘솔 출력 억제(모듈은 API 로만 결과를 배출한다) ─────────────────── */
#define printf(...)  ((void)0)
#define puts(...)    ((void)0)
#define putchar(...) ((void)0)

/* ── 어댑터(core/lcapi_adapter.c)가 정의하는 심볼 ───────────────────── */
extern volatile int  lcapi_active;    /* 1 = 어댑터가 구동 중 */
extern volatile int  lcapi_stop;      /* 1 = 조기 종료 요청(count 도달/중단) */
extern volatile long lcapi_target;    /* 요청 표본 수(0=무한) */
extern volatile long lcapi_seen;      /* 지금까지 배출한 표본 수 */
extern FILE         *lcapi_out_file;  /* 모듈 1차 출력(NUL) 핸들 */
extern void          lcapi_cap_add(const char *s, int n);
extern int           lcapi_emit(void);          /* 캡처 버퍼를 sink 로 즉시 전달 */

/* 목표 회수 도달/중단 여부(모듈 루프 조기종료용; EXE 에선 항상 0). */
static int lcapi_done(void)
{
    return lcapi_stop || (lcapi_active && lcapi_target > 0 && lcapi_seen >= lcapi_target);
}
/* API 구동 중 여부(EXE 에선 항상 0). 모듈이 API 전용 분기를 할 때 사용. */
static int lcapi_on(void) { return lcapi_active; }

/* 한 폴링 반복의 표본이 메모리에 완결된 직후 호출 → 즉시 전달(실시간). */
static void lcapi_sample(FILE *f)
{
    (void)f;
    if (!lcapi_active) return;
    lcapi_seen++;
    if (lcapi_target > 0 && lcapi_seen >= lcapi_target) lcapi_stop = 1;
    lcapi_emit();
}

/* ── 출력 캡처: 1차 출력(NUL)으로 가는 fprintf 만 메모리로 보낸다. ───── */
static int lcapi_cap_fprintf(FILE *f, const char *fmt, ...)
{
    va_list ap;
    if (lcapi_active && f && f == lcapi_out_file) {
        char tmp[8192];
        va_start(ap, fmt);
        int n = vsnprintf(tmp, sizeof(tmp), fmt, ap);
        va_end(ap);
        if (n < 0) return n;
        if (n >= (int)sizeof(tmp)) n = (int)sizeof(tmp) - 1;
        lcapi_cap_add(tmp, n);
        return n;
    }
    va_start(ap, fmt);
    int r = vfprintf(f, fmt, ap);
    va_end(ap);
    return r;
}
static int lcapi_cap_fflush(FILE *f)
{
    if (f && f == lcapi_out_file) return 0;   /* 메모리 캡처 → flush 불필요 */
    return fflush(f);
}
static FILE *lcapi_cap_fopen(const char *path, const char *mode)
{
    FILE *f = fopen(path, mode);
    if (f && path && _stricmp(path, "NUL") == 0) lcapi_out_file = f;
    return f;
}

#define fprintf lcapi_cap_fprintf
#define fflush  lcapi_cap_fflush
#define fopen   lcapi_cap_fopen

#else  /* ── EXE 빌드: 전부 no-op (동작 불변) ───────────────────────────── */
static int  lcapi_done(void)            { return 0; }
static int  lcapi_on(void)              { return 0; }
static void lcapi_sample(FILE *f)       { (void)f; }
#endif

#endif /* LCAPI_RT_H */
