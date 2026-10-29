/* ask_930.c — "지금 이 자리에서 게임이 어떤 지역명을 쓰는지" 를 즉시 묻는다
 * ---------------------------------------------------------------------------
 *  목적이 decid 이유다
 *    NCGuard 가 실행코드를 전부 암호화해 정적 역추적이 불가능하다(실측 확정).
 *    MapSubsystem 안에도 판정 결과 캐시가 없다(실측 확정).
 *    그러면 "겹친 rect 중 무엇을 고르는가" 의 유일한 정답원은
 *    게임이 화면에 내보이는 문자열뿐이다.
 *    이 도구는 후보를 전수 제시하고 각 규칙의 예측을 나란히 출력한다.
 *
 *  근거
 *    · 지역(rect) 테이블 : msub+0x768 std::vector<Rec>, stride 0x2C
 *        +0x00 _id / +0x04 nameId / +0x08 _map / +0x0C _color
 *        +0x10..0x1C _bounds / +0x28 _isDungeon
 *        (2026-10-15 라이브 실측, region.jsonc 1:1 대조 213/226 완전일치)
 *    · 현재 mapId : msub+0x718
 *    · 현재 cell  : g_base+PLAYER_X / PLAYER_Y
 *
 *  사용  ask_930.exe [registry]
 *  출력  (stdout) + bin\ask_out.txt
 * -------------------------------------------------------------------------- */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

typedef struct { int id, nameId, mapId, color, level, isDungeon;
                 int x0, y0, x1, y1; char name[96]; } REGION;
static REGION g_reg[1024]; static int g_nreg;

static void loadRegions(const char *p)
{
    FILE *f = fopen(p, "rb"); if (!f) { fprintf(stderr, "region table 없음: %s\n", p); return; }
    char line[1024]; int first = 1;
    while (fgets(line, sizeof line, f)) {
        char *nl = strchr(line, '\n'); if (nl) *nl = 0;
        if (first) { first = 0; continue; }
        if (!line[0] || g_nreg >= 1024) continue;
        char *fld[16]; int n = 0; fld[n++] = line;
        for (char *c = line; *c && n < 16; c++) if (*c == '\t') { *c = 0; fld[n++] = c + 1; }
        if (n < 9) continue;
        REGION *r = &g_reg[g_nreg];
        memset(r, 0, sizeof *r);
        r->id = atoi(fld[0]); r->nameId = atoi(fld[1]); r->mapId = atoi(fld[2]);
        snprintf(r->name, sizeof r->name, "%s", fld[3]);
        r->x0 = atoi(fld[4]); r->y0 = atoi(fld[5]);
        r->x1 = atoi(fld[6]); r->y1 = atoi(fld[7]);
        r->isDungeon = atoi(fld[8]);
        r->color = (n > 9) ? atoi(fld[9]) : 0;
        r->level = (n > 10) ? atoi(fld[10]) : 0;
        g_nreg++;
    }
    fclose(f);
}

static const char *cname(int c)
{
    switch (c) { case 0: return "야외"; case 10: return "마을";
                 case 11: return "성";   case 13: return "특수"; default: return "?"; }
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("registry/LC930_REGISTRY.txt");
    const char *reg = (argc > 1) ? argv[1]
        : lcreg_resolve("registry/LC930_REGISTRY.txt", "registry/LC930_REGISTRY.txt");
    lcreg_load(reg); lc_reg_apply();
    if (lc_attach()) { fprintf(stderr, "attach fail (WinNotify 드라이버 필요)\n"); return 1; }
    if (!lc_anchor()) { fprintf(stderr, "anchor fail\n"); return 2; }

    /* region_table.tsv 는 registry 파일과 같은 폴더에 있다
       (lcreg_find_root 가 현재 폴더를 바꾸므로 절대 경로로 만든다) */
    {
        char dir[512];
        snprintf(dir, sizeof dir, "%s", reg);
        char *sl = strrchr(dir, '\\'); char *sl2 = strrchr(dir, '/');
        if (sl2 > sl) sl = sl2;
        if (sl) { *sl = 0; snprintf(dir, sizeof dir, "%s\\", dir); }
        else    { snprintf(dir, sizeof dir, ".\\"); }
        char tsv[600];
        snprintf(tsv, sizeof tsv, "%sregion_table.tsv", dir);
        loadRegions(tsv);
    }
    if (!g_nreg) { fprintf(stderr, "region_table.tsv 로드 실패 (cwd=%s)\n", reg); return 3; }

    uint32_t VFT  = lcreg_u32("VFT_MAPSUBS",     0x1228050);
    uint32_t AOFF = lcreg_u32("MAP_AREA_OFF",     0x768);
    uint32_t MOFF = lcreg_u32("MAP_ID_OFF",      0x718);
    uint32_t PX   = lcreg_u32("PLAYER_X",        0x1668640);
    uint32_t PY   = lcreg_u32("PLAYER_Y",        0x1668644);
    uint32_t ST   = lcreg_u32("MAP_AREA_STRIDE", 0x2C);

    uint64_t msub = lc_subsGet(VFT);
    if (!isHeap(msub)) { fprintf(stderr, "msub invalid\n"); return 4; }

    uint64_t beg = q64(msub + AOFF), end = q64(msub + AOFF + 8);
    uint32_t cnt = (uint32_t)((end - beg) / ST);
    int cx = (int)d32(g_base + PX), cy = (int)d32(g_base + PY);
    int cmap = (int)d32(msub + MOFF);

    FILE *f = NULL;
#define P(...) fprintf(stdout, __VA_ARGS__)

    P("================================================================\n");
    P(" 지금 이 자리에서 게임은 어떤 지역명을 쓰고 있는가?\n");
    P("================================================================\n");
    P("  mapId = %d    cell = (%d, %d)    지역벡터 = %u 건\n", cmap, cx, cy, cnt);
    P("  (벡터 0x%llX..0x%llX, stride 0x%X)\n\n",
      (unsigned long long)beg, (unsigned long long)end, ST);

    /* ── 런타임 테이블에서 현재 셀을 포함하는 모든 rect ───────────── */
    typedef struct { int idx, id, nameId, mapId, color, x0, y0, x1, y1; long area; } HIT;
    static HIT hit[256]; int nh = 0;
    for (uint32_t i = 0; i < cnt && nh < 256; i++) {
        uint32_t rec[11] = {0};
        if (!rm(beg + (uint64_t)i * ST, rec, ST)) continue;
        if (!(rec[6] > rec[4] && rec[7] > rec[5])) continue;
        if (!((int)rec[4] <= cx && cx <= (int)rec[6] &&
              (int)rec[5] <= cy && cy <= (int)rec[7])) continue;
        hit[nh].idx = (int)i; hit[nh].id = (int)rec[0]; hit[nh].nameId = (int)rec[1];
        hit[nh].mapId = (int)rec[2]; hit[nh].color = (int)rec[3];
        hit[nh].x0 = (int)rec[4]; hit[nh].y0 = (int)rec[5];
        hit[nh].x1 = (int)rec[6]; hit[nh].y1 = (int)rec[7];
        hit[nh].area = (long)(rec[6] - rec[4]) * (long)(rec[7] - rec[5]);
        nh++;
    }

    P("  [1] 현재 셀을 포함하는 rect : %d 개\n", nh);
    P("      %-4s %-6s %-8s %-6s %-6s %-24s %-10s %s\n",
      "idx", "_id", "nameId", "_map", "_color", "_bounds", "넓이", "이름");
    for (int i = 0; i < nh; i++) {
        const char *nm = "?";
        for (int k = 0; k < g_nreg; k++)
            if (g_reg[k].nameId == hit[i].nameId && g_reg[k].mapId == hit[i].mapId) { nm = g_reg[k].name; break; }
        P("      %-4d %-6d %-8d %-6d %-6d [%d,%d..%d,%d]%-*s %-10ld %s%s\n",
          hit[i].idx, hit[i].id, hit[i].nameId, hit[i].mapId, hit[i].color,
          hit[i].x0, hit[i].y0, hit[i].x1, hit[i].y1,
          (i == 0 ? 4 : 4), "", hit[i].area, nm,
          hit[i].mapId == cmap ? "  ★현재 mapId" : "  (다른 맵)");
    }
    if (!nh) { P("\n  → 포함 rect 없음 (맵 로딩 직후 등). 잠시 후 다시 실행.\n"); goto tail; }

    /* ── 규칙별 예측 ─────────────────────────────────────────────── */
    P("\n  [2] 규칙별 예측값\n");
    int iMinArea = -1, iFirstVec = -1, iMinMap = -1, iFirstMap = -1, iMaxColor = -1;
    for (int i = 0; i < nh; i++) {
        if (iMinArea < 0 || hit[i].area < hit[iMinArea].area) iMinArea = i;
        if (iFirstVec < 0) iFirstVec = i;
        if (hit[i].mapId == cmap) {
            if (iMinMap < 0 || hit[i].area < hit[iMinMap].area) iMinMap = i;
            if (iFirstMap < 0) iFirstMap = i;
        }
        if (iMaxColor < 0 || hit[i].color > hit[iMaxColor].color ||
            (hit[i].color == hit[iMaxColor].color && hit[i].area < hit[iMaxColor].area))
            iMaxColor = i;
    }
    const char *tag[] = { "안A 최소 넓이          ",
                          "안B 벡터 최초 일치     ",
                          "안C mapId 일치 최소넓이",
                          "안D mapId 일치 최초    ",
                          "안E _color 우선(고>0)  " };
    int idxs[5]; idxs[0] = iMinArea; idxs[1] = iFirstVec; idxs[2] = iMinMap;
    idxs[3] = iFirstMap; idxs[4] = iMaxColor;
    for (int k = 0; k < 5; k++) {
        int i = idxs[k];
        if (i < 0) { P("      %s → (해당 후보 없음)\n", tag[k]); continue; }
        const char *nm = "?";
        for (int j = 0; j < g_nreg; j++)
            if (g_reg[j].nameId == hit[i].nameId && g_reg[j].mapId == hit[i].mapId) { nm = g_reg[j].name; break; }
        P("      %s → nameId=%-7d id=%-5d _color=%-3d %s\n",
          tag[k], hit[i].nameId, hit[i].id, hit[i].color, nm);
    }

    /* ── 판정 가능 여부 ──────────────────────────────────────────── */
    int same = (hit[idxs[0]].id == hit[idxs[1]].id);
    P("\n  [3] 판정\n");
    if (same)
        P("      안A 와 안B 가 같은 값을 낸다 → 이 위치로는 규칙을 가를 수 없다.\n"
          "      최소넓이와 파일순이 갈리는 곳으로 이동해야 한다.\n");
    else
        P("      ★ 안A 와 안B 가 갈린다. 여기서 결정적이다.\n"
          "        화면(위치 이름 표시)에 떠 있는 이름을 말해 주십시오.\n");
    P("\n      → 지금 화면에 보이는 지역명이 위 5개 중 어느 것인지 알려주시면\n"
      "        그 규칙이 확정된다. 이름이 목록에 없다면 '없음' 이라고 답해 주십시오.\n");

tail:
    P("\n================================================================\n");

    SignedClose();
    return 0;
}
