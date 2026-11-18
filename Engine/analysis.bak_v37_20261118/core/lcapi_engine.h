/* lcapi_engine.h — LCAPI 호스트 엔진. 임의의 프로그램이 모듈 DLL 을 구동하는 공개 API.
 * ----------------------------------------------------------------------------
 *  lcapi.dll (또는 정적 링크) 로 제공된다. 모듈 DLL 의 경로/이름만 알면
 *  interval/jitter/count(+ 모듈별 추가 파라미터)를 지정해 표본을 sink 로 받는다.
 *  표본은 실행 중 실시간으로 전달되며 파일은 사용하지 않는다.
 * ========================================================================== */
#ifndef LCAPI_ENGINE_H
#define LCAPI_ENGINE_H

#include <stdint.h>
#include "lcapi.h"

#ifdef __cplusplus
extern "C" {
#endif

#define LCAPI_ENGINE_VERSION "1.2.0"

/* 엔진 버전 문자열. */
__declspec(dllexport) const char *LcapiEngineVersion(void);

/* 모듈 1개 실행.
 *   dllDir : 모듈 DLL 들이 있는 폴더(0/"" 이면 현재 폴더).
 *   module : 모듈 이름(확장자 없이. 예: "enttrack").
 *   registry: LC930_REGISTRY.txt 경로(0/"" 이면 DLL 이 자체 탐색).
 *   interval_ms, jitter_ms, count : 읽기 간격/지터/표본 수.
 *   sink/ctx : 표본 수신 콜백(실시간).
 *   err/errCap: 오류 메시지(선택).
 *   반환: 전달 표본 수(>=0), 음수=오류. */
__declspec(dllexport) int LcapiRunModule(const char *dllDir, const char *module,
                                         const char *registry,
                                         uint32_t interval_ms, uint32_t jitter_ms, uint32_t count,
                                         lcapi_sink_fn sink, void *ctx,
                                         char *err, uint32_t errCap);

/* 모듈 1개 실행(+ 모듈별 추가 파라미터).
 *   params : "KEY=VALUE;KEY=VALUE" (모듈별 추가 주기). 예(enttrack):
 *            "ENT_SWEEP_MS=400;ENT_READ_INTERVAL_MS=100". 0/"" 이면 없음. */
__declspec(dllexport) int LcapiRunModuleEx(const char *dllDir, const char *module,
                                           const char *registry,
                                           uint32_t interval_ms, uint32_t jitter_ms, uint32_t count,
                                           const char *params,
                                           lcapi_sink_fn sink, void *ctx,
                                           char *err, uint32_t errCap);

/* dllDir 하위의 모듈 DLL 이름들을 개행 구분으로 buf 에 채운다. 반환=개수. */
__declspec(dllexport) int LcapiListModules(const char *dllDir, char *buf, uint32_t cap);

/* 단일 모듈 DLL 에서 메타(이름/버전/설명) 읽기. 반환 0=성공. */
__declspec(dllexport) int LcapiModuleMeta(const char *dllDir, const char *module,
                                          char *name, uint32_t nameCap,
                                          char *ver,  uint32_t verCap,
                                          char *info, uint32_t infoCap);

/* ── 동시 다중 모듈 실행(모듈별 다른 주기) ─────────────────────────────────
 *  각 job 을 전용 스레드에서 동시에 구동한다. 표본은 공유 sink 로 전달되며,
 *  sink 는 스레드 안전해야 한다(여러 모듈의 표본이 인터리브되어 도착할 수 있음).
 *  ctx 가 job 별로 다르므로 호출자는 ctx 로 모듈을 식별해 출력을 분리할 수 있다
 *  → 서로 다른 주기로 동시 호출해도 출력이 섞이지 않는다. */
typedef struct {
    const char *module;        /* 모듈 이름(필수) */
    uint32_t    interval_ms;   /* 읽기 간격(ms) */
    uint32_t    jitter_ms;     /* 지터(ms) */
    uint32_t    count;         /* 표본 수 */
    const char *params;        /* 모듈별 추가 파라미터(0 가능) */
    void       *ctx;           /* 이 모듈의 sink 컨텍스트(호출자 정의) */
    int         result;        /* out: 표본 수(>=0) 또는 음수 오류 */
    char        err[256];      /* out: 오류 메시지 */
} LcapiJob;

/* 반환: 전달된 총 표본 수(>=0). 개별 결과/오류는 각 job 에 기록된다. */
__declspec(dllexport) int LcapiRunMany(const char *dllDir, const char *registry,
                                       LcapiJob *jobs, int njobs,
                                       lcapi_sink_fn sink,
                                       char *err, uint32_t errCap);

#ifdef __cplusplus
}
#endif

#endif /* LCAPI_ENGINE_H */
