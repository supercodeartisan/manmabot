/* doorwatch_930.c — Door(문) 개폐 상태 실시간 감시 (독립 모듈)
 * ===========================================================================
 *  목적: 화면에 보이는 모든 Door(InteractiveNPC)의 **열림/닫힘**을 실시간 판독.
 *
 *  판정 근거(registry 단일 진실 공급처, DOOR_*):
 *    - Door 식별 : vft == VFT_NPC(InteractiveNPC) 이고 (species == DOOR_SP=8 또는 name == "Door")
 *    - 개폐 상태 : ActionComponent + DOOR_STATE_OFF(0xD8) dword
 *                  DOOR_STATE_OPEN(0x1C)=열림 / DOOR_STATE_CLOSED(0x1D)=닫힘
 *    - 문 종류   : Presentation + DOOR_GFX_OFF(0x38) dword
 *                  DOOR_GFX_NORMAL(0x800A)=여닫이 / DOOR_GFX_LOCKED(0x8009)=열 수 없는(고정) 문
 *    - 근거: 같은 문 C6C 가 60초 라이브에서 1D(닫힘)→1C(열림)→1D(닫힘) 로 양방향 전이 확정.
 *            그 동안 PRES+0x38 은 0x800A 로 불변 → 그래픽은 '상태'가 아니라 '종류'.
 *    - 무효 후보: AC+0x108(플래그), AC+0xD4(진행도), PRES+0x1F8(실행마다 뒤바뀜).
 *    - 현시 토큰: lcore `lc_doorToken()` = open / close / not_permitted (etview·JSON 공통).
 *
 *  IOCTL 최소화: 스냅샷(lc_fillDoor) 캐시 사용 → 추가 IOCTL 0(실측).
 *
 *  usage: doorwatch_930.exe [secs] [-clear] [-v] [-all] [registry] [out.txt]
 *    -clear : 매 사이클 콘솔 지우고 다시 그림(라이브 뷰)
 *    -v     : AC 프레임/플래그, 문 종류(PRES+0x40) 등 부가 필드 표기
 *   출력: <EXE>\out\doorwatch_out.txt
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

#define DWMAX 64
#define FRAME_OPEN      0x1Cu   /* AC+0xD8 == 0x1C : 열림 */
#define FRAME_CLOSED    0x1Du   /* AC+0xD8 == 0x1D : 닫힘 */

typedef struct {
    uint64_t guid;
    int      cx, cy;
    uint32_t gfx, kind, frame, flag, f198;
    int      locked;
    int      state;        /* 0=닫힘 1=열림 2=미상 */
    float    dist;
} DW;

static DW g_cur[DWMAX], g_prev[DWMAX];
static int g_n = 0, g_prevN = 0;
static int g_clear = 0, g_verbose = 0;
static uint32_t RG_KIND = 0x40;

static const char *stKor(int s){ return s == 1 ? "열림" : s == 0 ? "닫힘" : "미상"; }
static const char *stAscii(int s){ return s == 1 ? "OPEN" : s == 0 ? "CLOSED" : "UNKNOWN"; }

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg  = lcreg_resolve("10_5/registry/LC930_REGISTRY.txt", "registry/LC930_REGISTRY.txt");
    const char *outp = lcreg_outpath("doorwatch_out.txt");
    int secs = 0;
    for (int i = 1; i < argc; i++){
        if (!strcmp(argv[i], "-clear")){ g_clear = 1; continue; }
        if (!strcmp(argv[i], "-v")){ g_verbose = 1; continue; }
        if (!strcmp(argv[i], "-all")){ continue; }
        if (strstr(argv[i], ".txt") || strstr(argv[i], ".out")){
            if (strstr(argv[i], "REGISTRY")) reg = argv[i]; else outp = argv[i];
        } else if (atoi(argv[i]) > 0 && !strchr(argv[i], '.')) secs = atoi(argv[i]);
    }
    lcreg_load(reg); lc_reg_apply();
    RG_KIND = lcreg_u32("DOOR_KIND_OFF", 0x40);   /* 문 종류(모델) 그래픽 — 상태 아님 */

    if (lc_attach()) return 1;
    if (!lc_anchor()) return 2;
    lcreg_mkdir_for(outp);
    FILE *f = fopen(outp, "w"); if (!f) return 4;
    fprintf(f, "# doorwatch — Door 개폐 실시간 감시\n");
    fprintf(f, "#   식별: VFT_NPC + (sp=%u | name=\"%s\")\n", LC_DOOR_SP_V, LC_DOOR_NAME);
    fprintf(f, "#   상태: AC+0x%X == 0x%X(열림)/0x%X(닫힘)   종류: PRES+0x%X (0x%X=고정/0x%X=여닫이)\n",
            LC_DOOR_STATE_OFF_V, LC_DOOR_STATE_OPEN, LC_DOOR_STATE_CLOSED,
            LC_DOOR_GFX_OFF_V, LC_DOOR_GFX_LOCKED, LC_DOOR_GFX_NORMAL);

    DWORD t0 = GetTickCount();
    do {
        lc_pgc_reset();
        lc_collect();
        lc_pick_self();
        LC_E *me = lc_findMe();
        int sx = me ? me->cellx : 0, sy = me ? me->celly : 0;

        g_prevN = g_n;
        memcpy(g_prev, g_cur, sizeof(DW) * (size_t)g_n);
        g_n = 0;
        for (int i = 0; i < lc_nc && g_n < DWMAX; i++){
            LC_E *X = &lc_cur[i];
            if (!lc_isDoor(X)) continue;
            DW *D = &g_cur[g_n++];
            memset(D, 0, sizeof *D);
            D->guid = X->guid; D->cx = X->cellx; D->cy = X->celly;
            D->state = lc_doorState(X);                 /* lcore 단일 진실 공급처 */
            D->locked = lc_doorLocked(X);
            lc_doorGfx(X, &D->gfx);
            lc_doorFrame(X, &D->frame);
            if (isHeap(X->presB)) lc_pgRead(X->presB + RG_KIND, &D->kind, 4);
            if (isHeap(X->ac))    lc_pgRead(X->ac + LC_DOOR_AC_FLAG_V, &D->flag, 4);
            int dx = D->cx - sx, dy = D->cy - sy;
            D->dist = (dx < 0 ? -dx : dx) + (dy < 0 ? -dy : dy);
        }

        unsigned el = (unsigned)(GetTickCount() - t0);
        /* ── 상태 전이 집계 ── */
        int nOpen = 0, nClosed = 0, nUnk = 0, changed = 0;
        for (int i = 0; i < g_n; i++){
            if (g_cur[i].state == 1) nOpen++; else if (g_cur[i].state == 0) nClosed++; else nUnk++;
            for (int j = 0; j < g_prevN; j++)
                if (g_prev[j].guid == g_cur[i].guid && g_prev[j].state != g_cur[i].state) changed++;
        }

        if (g_clear) fputs("\x1b[2J\x1b[1;1H", stdout);
        printf("=== doorwatch  t=%ums  문 %d개  (열림 %d / 닫힘 %d / 미상 %d)  ioctl=%llu ===\n",
               el, g_n, nOpen, nClosed, nUnk, g_ioctl);
        for (int i = 0; i < g_n; i++){
            DW *D = &g_cur[i];
            char mark[40] = "";
            for (int j = 0; j < g_prevN; j++)
                if (g_prev[j].guid == D->guid &&
                    (g_prev[j].state != D->state || g_prev[j].gfx != D->gfx || g_prev[j].frame != D->frame))
                    snprintf(mark, sizeof mark, "   <== 전이: %s(gfx %04X/f%02X) → %s(gfx %04X/f%02X)",
                             stKor(g_prev[j].state), g_prev[j].gfx, g_prev[j].frame,
                             stKor(D->state), D->gfx, D->frame);
            printf("  Door %-8llX tile=%d,%d  gfx=%04X  state=%02X  => %s%s%s\n",
                   (unsigned long long)D->guid, D->cx, D->cy, D->gfx, D->frame, stKor(D->state),
                   D->locked ? "(열 수 없음) " : "", mark);
            if (g_verbose)
                printf("        종류=%04X(고정=%d)  AC.flag=%08X  dist=%d\n",
                       D->kind, D->locked, D->flag, (int)D->dist);
        }
        fflush(stdout);

        fprintf(f, "\n## t=%ums n=%d (%s) ioctl=%llu\n", el, g_n,
                nClosed == 0 ? "전부 열림" : (nOpen == 0 ? "전부 닫힘" : "혼재"), g_ioctl);
        for (int i = 0; i < g_n; i++){
            DW *D = &g_cur[i];
            int ch = 0;
            for (int j = 0; j < g_prevN; j++) if (g_prev[j].guid == D->guid && g_prev[j].state != D->state) ch = 1;
            fprintf(f, "  %llX tile=%d,%d gfx=%04X kind=%04X frame=%02X flag=%08X dist=%d => %s%s\n",
                    (unsigned long long)D->guid, D->cx, D->cy, D->gfx, D->kind, D->frame, D->flag,
                    (int)D->dist, stAscii(D->state), ch ? "  CHANGED" : "");
        }
        fflush(f);
        lcapi_sample(f);
        (void)changed;
        if (secs) Sleep(lcreg_u32("DOORWATCH_POLL_MS", 300));
    } while (!lcapi_done() && secs && (int)(GetTickCount() - t0) < secs * 1000);

    fclose(f); SignedClose();
    printf("done -> %s\n", outp);
    return 0;
}
