/* map_930.c — 맵ID·지역명·하위지역명 읽기 정본 모듈 (10_5 규격)
 * ---------------------------------------------------------------------------
 *  대원칙:
 *    1) 고정앵커  : MapSubsystem = lc_subsGet(VFT_MAPSUBS)   (vft 식별)
 *    2) 고정체인  : mapId = d32(msub + MAP_ID_OFF)
 *                   player cell = d32(g_base + PLAYER_X/Y)
 *    3) 정적접속  : 지역명/하위지역명 = registry region_table.tsv
 *                   (원천 정본 = data_region.jsonc.lcf.dec)
 *                   → 후보 = _map==mapId && cell∈[left,top,right,bottom]
 *                     하위지역 = 최소 넓이 rect,  지역 = 최대 넓이 rect
 *                     rect 없으면(던전 등) map단위(무-bounds) 이름
 *
 *  검증 상태 (2026-10-15 라이브 실측, docs\REGION_RULE_RE_2026-10-15.md)
 *    [확정] 맵 테이블은 msub+0x768 = std::vector<Rec>{begin,end,cap},
 *            stride 0x2C, 실측 232건. 각 필드가 region.jsonc 와 1:1 대응.
 *            +0x08 = _map , +0x0C = _color , +0x28 = _isDungeon.
 *    [확정] _map 필터는 필수. 서로 다른 맵의 rect 가 실제로 겹친다(8쌍 실측).
 *            필터 없으면 말하는섬에서 아덴대륙 이름이 나온다.
 *    [확정] "더 넓은데 _color 가 낮은" 모순 0건 → 최소넓이 ≡ 가장 구체적인 층.
 *    [미확정] 겹침 우선순위(최소넓이 / 파일순 / _color). NCGuard 가 실행코드를
 *            암호화해 정적 역추적이 불가. bin\ask_930.exe 실측으로 확정할 것.
 *            아래 최소/최대 넓이 규칙은 ★후보★ 임을 명시한다.
 *    4) MmCopy단일 : lcore 의 rm() 만 사용
 *    5) 상수외부   : 모든 상수/경로는 registry 단일출처. 코드 하드코딩 없음.
 *    6) 읽기최소   : lc_subsGet + mapId + cell = 소수 read. POLL_MAP_*.
 *  usage: map_930.exe [registry] [secs] [out.txt]
 *  출력: 10_5/out/map_out.txt (고정)
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

/* ── registry ─────────────────────────────────────────────────────────── */
static uint32_t RG_MVFT, RG_MID, RG_PX, RG_PY;
static char     RG_REGION[256];
static int      RG_RESCAN = 2000;

/* ── 지역 테이블 ──────────────────────────────────────────────────────── */
typedef struct { int id, nameId, mapId, x0, y0, x1, y1, isDungeon; char name[96]; } REGION;
static REGION *g_reg = 0; static int g_nreg = 0;
static void loadRegions(const char *p){
    FILE *f = fopen(p, "rb"); if (!f) { fprintf(stderr, "[map] region table not found: %s\n", p); return; }
    g_reg = (REGION *)malloc(sizeof(REGION) * 1024); if (!g_reg) { fclose(f); return; }
    char line[1024]; int first = 1;
    while (fgets(line, sizeof(line), f)) {
        if (first) { first = 0; continue; }                 /* header */
        char *nl = strchr(line, '\n'); if (nl) *nl = 0;
        if (!line[0]) continue;
        if (g_nreg >= 1024) break;
        REGION *r = &g_reg[g_nreg];
        memset(r, 0, sizeof(*r));
        /* id, nameId, mapId, name(KR, spaces ok), left, top, right, bottom, isDungeon */
        char *fld[9]; int n = 0; fld[n++] = line;
        for (char *c = line; *c && n < 9; c++) if (*c == '\t') { *c = 0; fld[n++] = c + 1; }
        if (n < 9) continue;
        r->id = atoi(fld[0]); r->nameId = atoi(fld[1]); r->mapId = atoi(fld[2]);
        snprintf(r->name, sizeof(r->name), "%s", fld[3]);
        r->x0 = atoi(fld[4]); r->y0 = atoi(fld[5]); r->x1 = atoi(fld[6]); r->y1 = atoi(fld[7]);
        r->isDungeon = atoi(fld[8]);
        g_nreg++;
    }
    fclose(f);
}
static long areaOf(const REGION *r){ return (long)(r->x1 - r->x0) * (long)(r->y1 - r->y0); }

/* mapId + cell 로 지역/하위지역 선정.
 *  ★후보 규칙 (미확정 — 실측 필요)★
 *  - rect 후보 있으면: 하위지역=최소 rect, 지역=최대 rect
 *  - rect 후보 없으면(던전 등): map 단위(무-bounds) 항목을 지역/하위지역으로 사용
 *  확정된 부분 : 아래의 mapId 필터(아래 if). 제거하면 명백히 틀린 이름이 나온다. */
static int pickRegion(int mapId, int cx, int cy,
                      const REGION **sub, const REGION **reg)
{
    const REGION *best = 0, *big = 0, *mapLevel = 0; long bestA = 0, bigA = 0;
    for (int i = 0; i < g_nreg; i++) {
        const REGION *r = &g_reg[i];
        if (r->mapId != mapId) continue;
        if (r->x1 <= r->x0 || r->y1 <= r->y0) {           /* no bounds */
            if (!mapLevel) mapLevel = r;                   /* map 단위 이름 */
            continue;
        }
        if (!(r->x0 <= cx && cx <= r->x1 && r->y0 <= cy && cy <= r->y1)) continue;
        long a = areaOf(r);
        if (!best || a < bestA) { best = r; bestA = a; }
        if (!big  || a > bigA)  { big  = r; bigA  = a; }
    }
    if (!best && mapLevel) { *sub = mapLevel; *reg = mapLevel; return 1; }  /* 던전 등 */
    if (sub) *sub = best;
    if (reg) *reg = big;
    return best ? 1 : 0;
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg = lcreg_resolve("10_5/registry/LC930_REGISTRY.txt", "registry/LC930_REGISTRY.txt");
    const char *outp = lcreg_outpath("map_out.txt");
    int secs=0;
    { int seenReg=0;
      for (int i=1;i<argc;i++){
        if(strstr(argv[i],".txt")||strstr(argv[i],".out")){
          if(!seenReg && strstr(argv[i],"REGISTRY")){ reg=argv[i]; seenReg=1; } else { outp=argv[i]; }
        } else if(atoi(argv[i])>0 && !strstr(argv[i],".")){ secs=atoi(argv[i]); }
      }
    }
    lcreg_load(reg); lc_reg_apply();
    RG_MVFT = lcreg_u32("VFT_MAPSUBS", 0x1208F70);
    RG_MID  = lcreg_u32("MAP_ID_OFF", 0x718);
    RG_PX   = lcreg_u32("PLAYER_X", 0x16BB990);
    RG_PY   = lcreg_u32("PLAYER_Y", 0x16BB994);
    RG_RESCAN = (int)lcreg_u32("MAP_RESCAN_MS", 2000);
    snprintf(RG_REGION, sizeof(RG_REGION), "%s",
        lcreg_resolve(lcreg_str("REGIONS_CSV", "10_5/registry/region_table.tsv"),
                      lcreg_str("REGIONS_DIST", "registry/region_table.tsv")));
    lcreg_poll P = lcreg_poll_load("MAP");
    loadRegions(RG_REGION);

    if (lc_attach()) return 1;
    if (!lc_anchor()) { fprintf(stderr, "anchor fail\n"); return 2; }

    lcreg_mkdir_for(outp);
    FILE *f = fopen(outp, "w"); if (!f) { fprintf(stderr, "cannot open %s\n", outp); return 4; }
    fprintf(f, "# registry=%s regions=%d MAP interval=%ums jitter=%ums\n",
        reg, g_nreg, P.interval_ms, P.jitter_ms);

    DWORD t0 = GetTickCount();
    do {
        LARGE_INTEGER fr, q0, q1; QueryPerformanceFrequency(&fr); QueryPerformanceCounter(&q0);
        g_ioctl = 0;
        uint64_t msub = lc_subsGet(RG_MVFT);
        uint32_t pc[2]={0,0}; rm(g_base + RG_PX, pc, 8);   /* 플레이어 셀 1콜 배치 */
        int cx = (int)pc[0], cy = (int)pc[1];
        int mapId = isHeap(msub) ? (int)d32(msub + RG_MID) : -1;
        const REGION *sub = 0, *reg2 = 0;
        int hit = (mapId >= 0) ? pickRegion(mapId, cx, cy, &sub, &reg2) : 0;

        fprintf(f, "t=%ums mapId=%d cell=(%d,%d) region=%-24s subregion=%-24s%s\n",
            (unsigned)(GetTickCount() - t0), mapId, cx, cy,
            hit && reg2 ? reg2->name : "(?)",
            hit && sub  ? sub->name  : "(?)",
            (hit && sub && reg2 && strcmp(sub->name, reg2->name) == 0) ? "  (동일)" : "");
        QueryPerformanceCounter(&q1);
        fprintf(f, "# ioctl=%llu mapId_off=0x%X time=%.4fms\n",
            g_ioctl, RG_MID, (q1.QuadPart - q0.QuadPart) * 1000.0 / fr.QuadPart);
        fflush(f);
        lcapi_sample(f);
        if (secs) Sleep(lcreg_poll_sleep_ms(&P));
    } while (!lcapi_done() && secs && (int)(GetTickCount() - t0) < secs * 1000);

    fclose(f); SignedClose();
    printf("done -> %s\n", outp); return 0;
}
