/* lcreg.h — LC930 통합 registry 로더 (header-only)
 * ------------------------------------------------------------------
 * 모든 도구/실행파일은 이 헤더를 include 하고 lcreg_load() 만 호출하면
 * LC930_REGISTRY.txt 의 모든 상수를 사용할 수 있다.
 *   #define LCREG_IMPLEMENT 로 한 개 .c 에서만 구현부를 켠다.
 *   또는 모든 TU 에서 static 인라인으로 쓰려면 그냥 include 만.
 *
 * 사용 예:
 *   #include "lcreg.h"
 *   lcreg_load("10_4_test/registry/LC930_REGISTRY.txt");
 *   uint64_t mgr = q64(g_base + lcreg_u32("MGR", 0));
 */
#ifndef LCREG_H
#define LCREG_H
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
/* LCAPI 인프로세스 훅(lcapi_done/lcapi_sample). EXE 빌드에서는 no-op. */
#include "lcapi_rt.h"

#define LCREG_MAXKEYS 1024
static char  LCREG_K[LCREG_MAXKEYS][64];
static char  LCREG_V[LCREG_MAXKEYS][256];
static int   LCREG_N = 0;

static inline void lcreg_load(const char* path){
    FILE* f = fopen(path, "r");
    if(!f){ fprintf(stderr, "[lcreg] not found: %s\n", path); return; }
    char ln[512];
    LCREG_N = 0;
    while(fgets(ln, sizeof(ln), f)){
        char* s = ln; while(*s==' '||*s=='\t') s++;
        if(*s=='#' || *s=='\n' || !*s) continue;
        char* eq = strchr(s, '='); if(!eq) continue; *eq=0;
        char* k = s; char* ke = k + strlen(k);
        while(ke>k && (ke[-1]==' '||ke[-1]=='\t')) *--ke=0;
        char* v = eq+1; while(*v==' '||*v=='\t') v++;
        char* ve = v + strlen(v);
        while(ve>v && (ve[-1]=='\n'||ve[-1]=='\r'||ve[-1]==' '||ve[-1]=='\t')) *--ve=0;
        if(LCREG_N < LCREG_MAXKEYS){
            strncpy(LCREG_K[LCREG_N], k, 63);
            strncpy(LCREG_V[LCREG_N], v, 255);
            LCREG_N++;
        }
    }
    fclose(f);
}
static inline const char* lcreg_raw(const char* key){
#ifdef LCAPI_INPROC
    /* API 모드: 호출자가 준 LCAPI_CFG_<KEY> 가 registry 값보다 우선한다.
     * (예: ENT_SWEEP_MS, ENT_READ_INTERVAL_MS) */
    if(key && key[0]){
        static char ek[160];
        snprintf(ek, sizeof(ek), "LCAPI_CFG_%s", key);
        const char* ev = getenv(ek);
        if(ev && ev[0]) return ev;
    }
#endif
    for(int i=0;i<LCREG_N;i++) if(!strcmp(LCREG_K[i], key)) return LCREG_V[i];
    return 0;
}
static inline uint32_t lcreg_u32(const char* key, uint32_t def){
    const char* v = lcreg_raw(key); return v ? (uint32_t)strtoul(v,0,0) : def;
}
static inline uint64_t lcreg_u64(const char* key, uint64_t def){
    const char* v = lcreg_raw(key); return v ? (uint64_t)strtoull(v,0,0) : def;
}
static inline double lcreg_f(const char* key, double def){
    const char* v = lcreg_raw(key); return v ? atof(v) : def;
}
static inline const char* lcreg_str(const char* key, const char* def){
    const char* v = lcreg_raw(key); return v ? v : def;
}
/* 고정체인: "0x00,0x40,0x58,0x30" 파싱 */
typedef struct { int n; uint32_t off[32]; } lcreg_chain;
static inline int lcreg_chain_load(const char* key, lcreg_chain* c){
    const char* v = lcreg_raw(key); if(!v) return 0;
    char buf[256]; strncpy(buf, v, 255); buf[255]=0;
    c->n = 0;
    char* tok = strtok(buf, ",");
    while(tok && c->n < 32){ c->off[c->n++] = (uint32_t)strtoul(tok, 0, 0); tok = strtok(0, ","); }
    return c->n;
}

/* ── 프로그램별 읽기 규격 (간격/지터/최대읽기) ──────────────────────────
 *   prog = 도구 식별자 (예: "BUFF","CHAR","ENTVIEW" ...)
 *   키 조회 순서: POLL_<prog>_XXX  →  DEFAULT_XXX  →  하드 기본값
 */
typedef struct { uint32_t interval_ms; uint32_t jitter_ms; uint32_t max_reads; } lcreg_poll;
static inline lcreg_poll lcreg_poll_load(const char* prog){
    char key[64];
    lcreg_poll p;
    snprintf(key, sizeof(key), "POLL_%s_INTERVAL_MS", prog);
    p.interval_ms = lcreg_u32(key, lcreg_u32("DEFAULT_INTERVAL_MS", 100));
    snprintf(key, sizeof(key), "POLL_%s_JITTER_MS", prog);
    p.jitter_ms   = lcreg_u32(key, lcreg_u32("DEFAULT_JITTER_MS", 0));
    snprintf(key, sizeof(key), "POLL_%s_MAX_READS", prog);
    p.max_reads   = lcreg_u32(key, lcreg_u32("DEFAULT_MAX_READS", 10000));
    /* LCAPI: API 모드에서는 호출자가 준 간격/지터가 registry 보다 우선한다. */
    { const char* ei = getenv("LCAPI_INTERVAL_MS");
      if(ei) p.interval_ms = (uint32_t)strtoul(ei, 0, 0);
      const char* ej = getenv("LCAPI_JITTER_MS");
      if(ej) p.jitter_ms = (uint32_t)strtoul(ej, 0, 0); }
    return p;
}
/* 실제 대기시간 = interval + rand(0..jitter).  jitter=0 이면 고정. */
static inline uint32_t lcreg_poll_sleep_ms(const lcreg_poll* p){
    uint32_t extra = 0;
    if(p->jitter_ms) extra = (uint32_t)(rand() % (p->jitter_ms + 1));
    return p->interval_ms + extra;
}

/* ── 실행환경 자동 인식: "EXE 위치 기준" ────────────────────────────────
 *  규칙(통일):
 *    - ROOT = EXE 가 있는 디렉토리 (lcreg_base()). cwd 도 ROOT 로 이동.
 *    - registry : ROOT/registry/LC930_REGISTRY.txt, 없으면 상위에서 '10_5/registry/...' 탐색
 *    - data     : ROOT/data/... , 없으면 상위 탐색
 *    - 출력      : ROOT/out/<tool>_out.txt  (항상 EXE 옆)
 *  → 개발트리(10_5\bin)든 배포판(dist\bin)이든 결과는 항상 "EXE 옆 out/" 에 저장된다.
 */
#include <windows.h>
static char LCREG_BASE[MAX_PATH] = {0};
static char LCREG_UP[MAX_PATH]   = {0};   /* registry 를 찾은 루트(보통 ROOT 또는 상위) */
static inline const char* lcreg_base(void){
    if(!LCREG_BASE[0]){
        /* Host (the bot) sets LCAPI_ROOT to the analysis folder so registry/
         * and data/ resolve without moving the process cwd off python.exe. */
        const char* root = getenv("LCAPI_ROOT");
        if(root && root[0]){
            snprintf(LCREG_BASE, sizeof(LCREG_BASE), "%s", root);
        } else {
            GetModuleFileNameA(NULL, LCREG_BASE, MAX_PATH);
            char* s = strrchr(LCREG_BASE, '\\'); if(s) *s = 0;
        }
    }
    return LCREG_BASE;
}
static inline int lcreg_exists_p(const char* full){ FILE* f=fopen(full,"r"); if(f){ fclose(f); return 1; } return 0; }
static inline int lcreg_exists_at(const char* dir, const char* relKey){
    char tmp[MAX_PATH*2]; snprintf(tmp,sizeof(tmp),"%s\\%s", dir, relKey); return lcreg_exists_p(tmp);
}
/* EXE 디렉토리를 ROOT 로 고정하고 cwd 를 그곳으로. registry 위치(루트)를 LCREG_UP 에 기억. */
static inline int lcreg_find_root(const char* relKey){
    const char* base = lcreg_base();
    /* 1) EXE 옆 registry/ */
    if(lcreg_exists_at(base,"registry/LC930_REGISTRY.txt")){
        snprintf(LCREG_UP,sizeof(LCREG_UP),"%s",base);
#ifndef LCAPI_INPROC
        SetCurrentDirectoryA(base);   /* EXE 빌드: cwd=EXE 위치(출력 기준) */
#endif
        return 1;
    }
    /* 2) EXE 상위로 올라가며 registry/ 또는 10_5/registry/ 탐색 */
    char up[MAX_PATH]; snprintf(up,sizeof(up),"%s",base);
    for(int i=0;i<4;i++){
        char* p=strrchr(up,'\\'); if(!p) break; *p=0;
        if(lcreg_exists_at(up,"registry/LC930_REGISTRY.txt")){
            snprintf(LCREG_UP,sizeof(LCREG_UP),"%s",up); break;
        }
        if(relKey && lcreg_exists_at(up,relKey)){
            char up10[MAX_PATH]; snprintf(up10,sizeof(up10),"%s\\10_5",up);
            snprintf(LCREG_UP,sizeof(LCREG_UP),"%s",up10); break;
        }
    }
    /* API(동시 실행) 모드: cwd 는 프로세스 전역이라 함부로 바꾸지 않는다.
     * (모듈은 NUL 로만 출력하고, 경로는 LCREG_UP/EXE 기준으로 절대 해석된다.)
     * EXE 빌드는 기존과 동일하게 cwd=EXE 위치. */
#ifndef LCAPI_INPROC
    SetCurrentDirectoryA(base);
#endif
    return LCREG_UP[0] ? 1 : 0;
}
/* registry/데이터 경로 해석: ROOT(EXE옆) 우선, 없으면 LCREG_UP(상위 루트).
 *  rel : "registry/LC930_REGISTRY.txt", "data/..." 등 (루트 기준 상대) */
static inline const char* lcreg_resolve(const char* devRel, const char* distRel){
    static char buf[MAX_PATH*2];
    const char* cands[2]; int nc=0;
    if(distRel) cands[nc++]=distRel;
    if(devRel)  cands[nc++]=devRel;
    /* 탐색 루트: cwd(EXE옆) → LCREG_UP → LCREG_UP상위 → EXE상위(dist) → EXE상위상위 */
    char roots[4][MAX_PATH*2]; int nr=0;
    if(LCREG_UP[0]) snprintf(roots[nr++],MAX_PATH*2,"%s",LCREG_UP);
    { char t[MAX_PATH*2]; snprintf(t,sizeof(t),"%s",lcreg_base());
      char* s=strrchr(t,'\\'); if(s){ *s=0; snprintf(roots[nr++],MAX_PATH*2,"%s",t); /* EXE parent */
        char* s2=strrchr(t,'\\'); if(s2){ *s2=0; snprintf(roots[nr++],MAX_PATH*2,"%s",t); } } }
    for(int i=0;i<nc;i++){
        if(lcreg_exists_at(".", cands[i])) return cands[i];
        for(int r=0;r<nr;r++) if(lcreg_exists_at(roots[r], cands[i])){
            snprintf(buf,sizeof(buf),"%s\\%s",roots[r],cands[i]); return buf; }
    }
    return distRel ? distRel : devRel;
}
/* 출력경로: 항상 EXE 옆 out/ 아래 파일명. 인자로 준 경우 호출부에서 대체. */
static inline const char* lcreg_outpath(const char* name){
    static char buf[MAX_PATH*2];
#ifdef LCAPI_INPROC
    /* API 모드: 파일을 쓰지 않는다. 모듈의 1차 출력은 NUL 로 열리고,
     * lcapi_rt.h 가 그 fprintf 를 메모리로 캡처해 sink 로 실시간 전달한다. */
    (void)name;
    snprintf(buf,sizeof(buf),"NUL");
    return buf;
#else
    snprintf(buf,sizeof(buf),"%s\\out\\%s", lcreg_base(), name);
    return buf;
#endif
}
/* 출력 파일의 디렉토리를 생성(존재하면 무시). */
static inline void lcreg_mkdir_for(const char* path){
    char d[MAX_PATH*2]; snprintf(d,sizeof(d),"%s",path);
    char* s = d; for(char* p=d; *p; p++) if(*p=='\\'||*p=='/') s=p;
    if(s==d) return; *s=0; if(d[0]) CreateDirectoryA(d,NULL);
}
#endif /* LCREG_H */
