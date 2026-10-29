/* lcapi_engine.c — LCAPI 호스트 엔진 구현. lcapi.dll 로도, 정적 링크로도 쓰인다.
 *  모듈 DLL 을 LoadLibrary 하고 공통 ABI(configure/set_params/run)를 호출한다.
 * ========================================================================== */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <process.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include "lcapi.h"
#include "lcapi_engine.h"

static void eng_err(char *err, uint32_t cap, const char *m)
{
    if (err && cap) snprintf(err, cap, "%s", m ? m : "");
}

__declspec(dllexport) const char *LcapiEngineVersion(void) { return LCAPI_ENGINE_VERSION; }

/* <dir>\<module>.dll 경로 생성(항상 절대경로).
 *  동시 실행 시 모듈이 SetCurrentDirectoryA 로 cwd 를 바꾸므로, LoadLibrary 는
 *  반드시 절대경로로 수행해야 한다(상대경로는 스레드 간 경합으로 실패). */
static void dll_path(const char *dir, const char *module, char *out, uint32_t cap)
{
    const char *d = (dir && dir[0]) ? dir : ".";
    int has_ext = 0;
    size_t ml = strlen(module);
    if (ml > 4 && _stricmp(module + ml - 4, ".dll") == 0) has_ext = 1;
    char rel[1400];
    snprintf(rel, sizeof(rel), "%s\\%s%s", d, module, has_ext ? "" : ".dll");
    if (!GetFullPathNameA(rel, cap, out, NULL)) snprintf(out, cap, "%s", rel);
}

__declspec(dllexport) int LcapiRunModuleEx(const char *dllDir, const char *module,
                                           const char *registry,
                                           uint32_t interval_ms, uint32_t jitter_ms, uint32_t count,
                                           const char *params,
                                           lcapi_sink_fn sink, void *ctx,
                                           char *err, uint32_t errCap)
{
    if (err && errCap) err[0] = 0;
    if (!module || !module[0]) { eng_err(err, errCap, "module name required"); return -1; }

    char path[1200];
    dll_path(dllDir, module, path, sizeof(path));

    HMODULE h = LoadLibraryA(path);
    if (!h) {
        char m[1400];
        snprintf(m, sizeof(m), "LoadLibrary failed (%lu): %s", GetLastError(), path);
        eng_err(err, errCap, m);
        return -2;
    }

    lcapi_configure_fn cfg = (lcapi_configure_fn)GetProcAddress(h, LCAPI_FN_CONFIGURE);
    lcapi_params_fn    par = (lcapi_params_fn)GetProcAddress(h, LCAPI_FN_PARAMS);
    lcapi_run_fn       run = (lcapi_run_fn)GetProcAddress(h, LCAPI_FN_RUN);
    lcapi_abi_fn       abi = (lcapi_abi_fn)GetProcAddress(h, LCAPI_FN_ABI);
    if (!cfg || !run) {
        FreeLibrary(h);
        eng_err(err, errCap, "module does not export LCAPI ABI (lcapi_configure/lcapi_run)");
        return -3;
    }
    if (abi && abi() != LCAPI_ABI_VERSION) {
        char m[128]; snprintf(m, sizeof(m), "ABI mismatch: module=%u engine=%u", abi(), LCAPI_ABI_VERSION);
        FreeLibrary(h);
        eng_err(err, errCap, m);
        return -4;
    }

    cfg(registry, interval_ms, jitter_ms, count, 0);
    if (par) par(params ? params : "");
    int n = run(sink, ctx, err, errCap);
    FreeLibrary(h);
    return n;
}

__declspec(dllexport) int LcapiRunModule(const char *dllDir, const char *module,
                                         const char *registry,
                                         uint32_t interval_ms, uint32_t jitter_ms, uint32_t count,
                                         lcapi_sink_fn sink, void *ctx,
                                         char *err, uint32_t errCap)
{
    return LcapiRunModuleEx(dllDir, module, registry, interval_ms, jitter_ms, count,
                            0, sink, ctx, err, errCap);
}

__declspec(dllexport) int LcapiModuleMeta(const char *dllDir, const char *module,
                                          char *name, uint32_t nameCap,
                                          char *ver,  uint32_t verCap,
                                          char *info, uint32_t infoCap)
{
    if (name && nameCap) name[0] = 0;
    if (ver && verCap) ver[0] = 0;
    if (info && infoCap) info[0] = 0;
    char path[1200]; dll_path(dllDir, module, path, sizeof(path));
    HMODULE h = LoadLibraryA(path);
    if (!h) return -1;
    lcapi_str_fn fname = (lcapi_str_fn)GetProcAddress(h, LCAPI_FN_NAME);
    lcapi_str_fn fver  = (lcapi_str_fn)GetProcAddress(h, LCAPI_FN_VERSION);
    lcapi_str_fn finfo = (lcapi_str_fn)GetProcAddress(h, LCAPI_FN_INFO);
    if (name && nameCap && fname) snprintf(name, nameCap, "%s", fname());
    if (ver && verCap && fver)   snprintf(ver, verCap, "%s", fver());
    if (info && infoCap && finfo) snprintf(info, infoCap, "%s", finfo());
    FreeLibrary(h);
    return 0;
}

__declspec(dllexport) int LcapiListModules(const char *dllDir, char *buf, uint32_t cap)
{
    if (buf && cap) buf[0] = 0;
    char pat[1500];
    const char *d = (dllDir && dllDir[0]) ? dllDir : ".";
    char dabs[1400];
    if (!GetFullPathNameA(d, sizeof(dabs), dabs, NULL)) snprintf(dabs, sizeof(dabs), "%s", d);
    snprintf(pat, sizeof(pat), "%s\\*.dll", dabs);
    WIN32_FIND_DATAA fd;
    HANDLE fh = FindFirstFileA(pat, &fd);
    if (fh == INVALID_HANDLE_VALUE) return 0;
    int n = 0; uint32_t used = 0;
    do {
        if (fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY) continue;
        const char *nm = fd.cFileName;
        if (_stricmp(nm, "lcapi.dll") == 0) continue;
        char base[260]; snprintf(base, sizeof(base), "%s", nm);
        char *dot = strrchr(base, '.'); if (dot) *dot = 0;
        int w = snprintf(buf + used, (used < cap) ? cap - used : 0, "%s\n", base);
        if (used + (uint32_t)w < cap) used += (uint32_t)w; else { used = cap; break; }
        n++;
    } while (FindNextFileA(fh, &fd));
    FindClose(fh);
    return n;
}

/* ── 동시 다중 모듈 실행 ─────────────────────────────────────────────────── */
typedef struct {
    const char  *dllDir;
    const char  *registry;
    LcapiJob    *job;
    lcapi_sink_fn sink;
} ManyArg;

static unsigned __stdcall many_proc(void *p)
{
    ManyArg *a = (ManyArg *)p;
    a->job->result = LcapiRunModuleEx(a->dllDir, a->job->module, a->registry,
                                      a->job->interval_ms, a->job->jitter_ms, a->job->count,
                                      a->job->params, a->sink, a->job->ctx,
                                      a->job->err, (uint32_t)sizeof(a->job->err));
    return 0;
}

__declspec(dllexport) int LcapiRunMany(const char *dllDir, const char *registry,
                                       LcapiJob *jobs, int njobs,
                                       lcapi_sink_fn sink,
                                       char *err, uint32_t errCap)
{
    if (err && errCap) err[0] = 0;
    if (!jobs || njobs <= 0) { eng_err(err, errCap, "no jobs"); return -1; }

    ManyArg  *args = (ManyArg *)calloc((size_t)njobs, sizeof(ManyArg));
    HANDLE   *thr  = (HANDLE *)calloc((size_t)njobs, sizeof(HANDLE));
    unsigned *ids  = (unsigned *)calloc((size_t)njobs, sizeof(unsigned));
    if (!args || !thr || !ids) { free(args); free(thr); free(ids); eng_err(err, errCap, "oom"); return -1; }

    int started = 0;
    for (int i = 0; i < njobs; i++) {
        jobs[i].result = -100;
        jobs[i].err[0] = 0;
        args[i].dllDir = dllDir; args[i].registry = registry;
        args[i].job = &jobs[i]; args[i].sink = sink;
        HANDLE h = (HANDLE)_beginthreadex(NULL, 0, many_proc, &args[i], 0, &ids[i]);
        if (h) thr[started++] = h;      /* 유효 핸들만 앞으로 압축 */
        else   jobs[i].result = -101;
    }
    if (started) WaitForMultipleObjects((DWORD)started, thr, TRUE, INFINITE);
    for (int i = 0; i < started; i++) CloseHandle(thr[i]);
    free(args); free(thr); free(ids);

    int total = 0;
    for (int i = 0; i < njobs; i++) if (jobs[i].result > 0) total += jobs[i].result;
    return total;
}
