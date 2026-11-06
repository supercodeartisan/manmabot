/* lcapi.h — LC module API (DLL) 공개 ABI.
 * ============================================================================
 *  LC930 모듈 한 개 = DLL 한 개. 모든 모듈 DLL 은 아래 동일 ABI 를 export 한다.
 *  호스트(임의의 프로그램)는 .dll 을 LoadLibrary/GetProcAddress 하여
 *  "메모리 읽기 간격(interval)·지터(jitter)·회수(count)" 를 정해 호출하고,
 *  표본은 sink 콜백으로 "실시간" 전달받는다.
 *
 *  ── 표준 호출 순서 ──────────────────────────────────────────────────────
 *    1) h  = LoadLibraryA("enttrack.dll")
 *    2) cfg= GetProcAddress(h, "lcapi_configure")   → registry/interval/jitter/count
 *       (선택) sp = GetProcAddress(h, "lcapi_set_params")
 *              sp("ENT_SWEEP_MS=400;ENT_READ_INTERVAL_MS=100")   ← 모듈별 추가 주기
 *    3) rn = GetProcAddress(h, "lcapi_run")         → sink 로 표본 실시간 전달
 *    4) FreeLibrary(h)
 *
 *  lcapi_run 은 대상 모듈을 구동하며, 매 읽기 주기(interval + rand(0..jitter))마다
 *  표본을 만들어 sink(ctx, seq, text, len) 로 전달한다. 파일은 사용하지 않는다.
 *
 *  이 헤더의 ABI 는 lcapi_adapter.c 가 구현하고, lcapi_engine.c(호스트 로더)가
 *  소비한다. lcapi_rt.h 는 모듈 소스가 사용하는 인프로세스 훅(별도).
 * ========================================================================== */
#ifndef LCAPI_H
#define LCAPI_H

#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ABI/버전 */
#define LCAPI_ABI_VERSION 1u

/* 표본 수신 콜백(인프로세스, 실시간).
 *   ctx : 호출자 컨텍스트
 *   seq : 표본 번호(1부터)
 *   text: UTF-8 표본 텍스트(가변, 널 미보장 → len 사용)
 *   len : text 바이트 수
 *   반환: 0=계속, 그 외=중단 요청 */
typedef int (*lcapi_sink_fn)(void *ctx, uint32_t seq, const char *text, uint32_t len);

/* 모듈 DLL 이 export 하는 심볼 이름 (GetProcAddress 용) */
#define LCAPI_FN_ABI        "lcapi_abi_version"
#define LCAPI_FN_NAME       "lcapi_module_name"
#define LCAPI_FN_VERSION    "lcapi_module_version"
#define LCAPI_FN_INFO       "lcapi_module_info"
#define LCAPI_FN_CONFIGURE  "lcapi_configure"
#define LCAPI_FN_PARAMS     "lcapi_set_params"
#define LCAPI_FN_RUN        "lcapi_run"

/* lcapi_configure(registry, interval_ms, jitter_ms, count, out_dir)
 *   registry   : LC930_REGISTRY.txt 경로(0/"" 이면 모듈 기본 탐색)
 *   interval_ms: 기본 읽기 간격(ms). 0 이면 모듈/registry 기본값.
 *   jitter_ms  : 지터(ms). 실제 간격 = interval + rand(0..jitter).
 *   count      : 만들 표본 수(>=1).
 *   out_dir    : (예약) 호환용. 현재 파일을 쓰지 않으므로 사용되지 않는다.
 *   반환: 0=성공, 그 외=오류.
 *
 * lcapi_set_params(params)  [선택]
 *   params : 모듈별 추가 설정. 세미콜론/콤마 구분 "KEY=VALUE" 목록.
 *            KEY 는 registry 키 이름이며 그 값이 우선 적용된다.
 *            예) enttrack "ENT_SWEEP_MS=400;ENT_READ_INTERVAL_MS=100"
 *                (스윕주기 / 보간주기)
 *   반환: 0=성공.
 *
 * lcapi_run(sink, ctx, err, err_cap)
 *   err/err_cap: 오류 메시지 버퍼(선택).
 *   반환: 전달한 표본 수(>=0), 음수=오류. */
typedef int  (*lcapi_configure_fn)(const char *registry, uint32_t interval_ms,
                                   uint32_t jitter_ms, uint32_t count, const char *out_dir);
typedef int  (*lcapi_params_fn)(const char *params);
typedef int  (*lcapi_run_fn)(lcapi_sink_fn sink, void *ctx, char *err, uint32_t err_cap);
typedef uint32_t (*lcapi_abi_fn)(void);
typedef const char *(*lcapi_str_fn)(void);

#ifdef __cplusplus
}
#endif

#endif /* LCAPI_H */
