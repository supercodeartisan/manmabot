/* partyhud_930.c — HUD 파티 바(PartyInfo) 판독
 * ===========================================================================
 *  읽는 것
 *    - 창 사각형 : 위치(x,y) + 크기(w,h) + 표시 여부
 *    - 위젯 트리 : 바 자체의 버튼/아이콘(배경·상단버튼·리스트뷰 등)을 재귀 열거
 *    - 멤버 슬롯 : guid / HP% / MP% + 슬롯 내부 버튼/아이콘/바/텍스트의 절대 좌표
 *
 *  좌표계 = cocos 화면좌표(좌하 원점). 절대좌표는 위젯 +0xB0/+0xB4 에 캐시되어
 *  있어 부모 변환을 누적할 필요가 없다. 자식 목록은 Node+0x178 (vector<Node*>).
 *
 *  드라이버 호출 최소화
 *    - 기본 1회 호출(one-shot). 상시 폴링하지 않는다.
 *    - 모든 읽기 = lc_pgRead(4KB 페이지 캐시) → 같은 페이지는 1 IOCTL.
 *    - 위젯 1개당 0x190B 1회로 vft·좌표·크기·스케일·자식벡터를 한 번에.
 *    - RTTI 클래스명은 vft 별 1회 캐시.
 *    - 기본 활성 슬롯만(-all 로 8개).
 *
 *  usage: partyhud_930.exe [registry] [out.txt] [secs] [-all] [-win] [-json] [-no-tree]
 *  output: bin/out/partyhud_out.txt
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

static uint32_t RG_WIN_VFT, RG_CVAL, RG_VIS;
static uint32_t RG_POS_X, RG_POS_Y, RG_SIZE_W, RG_SIZE_H;
static uint32_t RG_SLOT_OFF, RG_SLOT_STRIDE, RG_SLOT_OBJ, RG_SLOT_N;
static uint32_t RG_SLOT_GUID, RG_SLOT_HP, RG_SLOT_MP, RG_INACTIVE;
static uint32_t RG_WPOS_X, RG_WPOS_Y, RG_WABS_X, RG_WABS_Y, RG_WSC_X, RG_WSC_Y;
static uint32_t RG_NODE_OFF, RG_CHILD;
static uint32_t RG_DIR_OFF, RG_GLV_IN_DIR;
static uint32_t RG_GLV_FW, RG_GLV_FH, RG_GLV_DW, RG_GLV_DH;
static uint32_t RG_GLV_VX, RG_GLV_VY, RG_GLV_SX, RG_GLV_SY;
static uint32_t RG_DESIGN_W, RG_DESIGN_H;
static uint64_t g_head[8], g_next[8];
static int g_ncont = 0, g_firstTree = 1;

/* 화면 매핑 (GLView, 매 사이클 갱신) — 디자인 좌표 -> 실제 클라이언트 픽셀 */
static struct {
    int ok;
    float fw, fh;      /* frame (client pixels) */
    float dw, dh;      /* design resolution */
    float sx, sy;      /* scale */
    float vx, vy;      /* viewport origin (pixels, 좌하) */
} g_scr;

static void screenMap(float x, float y, float w, float h,
                      int *x0, int *y0, int *x1, int *y1)
{
    float px0 = g_scr.vx + x * g_scr.sx;
    float px1 = g_scr.vx + (x + w) * g_scr.sx;
    float pb0 = g_scr.vy + y * g_scr.sy;             /* bottom (cocos) */
    float pb1 = g_scr.vy + (y + h) * g_scr.sy;
    *x0 = (int)(px0 + 0.5f);
    *x1 = (int)(px1 + 0.5f);
    *y0 = (int)(g_scr.fh - pb1 + 0.5f);              /* top edge, top-left origin */
    *y1 = (int)(g_scr.fh - pb0 + 0.5f);              /* bottom edge */
}

#define CLC_MAX 48
static struct { uint32_t vft; char name[80]; } g_clc[CLC_MAX];
static int g_nclc = 0;

static void vftClass(uint32_t rva, char *out, size_t cap)
{
    out[0] = 0;
    for (int i = 0; i < g_nclc; i++)
        if (g_clc[i].vft == rva) { strncpy(out, g_clc[i].name, cap - 1); out[cap - 1] = 0; return; }
    uint8_t nm[128];
    uint64_t col = q64(g_base + rva - 8);
    if (!isMod(col)) return;
    uint32_t td = d32(col + 0xC);
    if (!td || td >= g_modSize) return;
    if (!rm(g_base + td + 0x10, nm, sizeof nm - 1)) return;
    nm[sizeof nm - 1] = 0;
    const char *s = strstr((char *)nm, "AV"); s = s ? s + 2 : (char *)nm;
    strncpy(out, s, cap - 1); out[cap - 1] = 0;
    if (g_nclc < CLC_MAX) { g_clc[g_nclc].vft = rva; strncpy(g_clc[g_nclc].name, out, 79); g_nclc++; }
}

typedef struct {
    uint64_t p, cb, ce; uint32_t vft;
    float lx, ly, ax, ay, w, h, sx, sy;
    char cls[80];
} LW;

static int readWidget(uint64_t p, LW *o)
{
    uint8_t b[0x190];
    if (!isHeap(p) || !lc_pgRead(p, b, sizeof b)) return 0;
    memset(o, 0, sizeof *o);
    o->p = p;
    uint64_t vf = *(uint64_t *)b;
    o->vft = isMod(vf) ? (uint32_t)(vf - g_base) : 0;
    o->lx = *(float *)(b + RG_WPOS_X);
    o->ly = *(float *)(b + RG_WPOS_Y);
    o->ax = *(float *)(b + RG_WABS_X);
    o->ay = *(float *)(b + RG_WABS_Y);
    o->w  = *(float *)(b + RG_SIZE_W);
    o->h  = *(float *)(b + RG_SIZE_H);
    o->sx = *(float *)(b + RG_WSC_X);
    o->sy = *(float *)(b + RG_WSC_Y);
    if (RG_CHILD + 16 <= sizeof b) {
        o->cb = *(uint64_t *)(b + RG_CHILD);
        o->ce = *(uint64_t *)(b + RG_CHILD + 8);
    }
    if (!o->vft) return 0;
    vftClass(o->vft, o->cls, sizeof o->cls);
    return 1;
}

static void jsonStr(char *dst, size_t cap, const char *s)
{
    size_t o = 0;
    for (; *s && o + 2 < cap; s++) {
        if (*s == '"' || *s == '\\') dst[o++] = '\\';
        dst[o++] = *s;
    }
    dst[o] = 0;
}

static int isPlaced(const LW *w) { return w->ax != 0.0f || w->ay != 0.0f; }

/* GLView(Director+0x100)에서 frame/design/scale/viewport 를 읽는다.
 * 실패 시 호출측이 client rect 로 폴백한다. */
static int readScreen(uint64_t node)
{
    memset(&g_scr, 0, sizeof g_scr);
    uint64_t dir = q64(node + RG_DIR_OFF);
    if (!isHeap(dir)) return 0;
    uint64_t glv = q64(dir + RG_GLV_IN_DIR);
    if (!isHeap(glv)) return 0;
    uint8_t b[0x80];
    if (!lc_pgRead(glv, b, sizeof b)) return 0;
    g_scr.fw = *(float *)(b + RG_GLV_FW);
    g_scr.fh = *(float *)(b + RG_GLV_FH);
    g_scr.dw = *(float *)(b + RG_GLV_DW);
    g_scr.dh = *(float *)(b + RG_GLV_DH);
    g_scr.vx = *(float *)(b + RG_GLV_VX);
    g_scr.vy = *(float *)(b + RG_GLV_VY);
    g_scr.sx = *(float *)(b + RG_GLV_SX);
    g_scr.sy = *(float *)(b + RG_GLV_SY);
    if (!(g_scr.fw > 0 && g_scr.fh > 0 && g_scr.sx > 0 && g_scr.sy > 0)) return 0;
    g_scr.ok = 1;
    return 1;
}

/* 바 자체 위젯 트리(멤버 슬롯 제외) 열거 */
static void walkTree(FILE *f, uint64_t node, int depth, int maxd, int json, int *nOut)
{
    if (depth > maxd) return;
    LW w;
    if (!readWidget(node, &w)) return;
    int placed = isPlaced(&w);
    (*nOut)++;
    int px0, py0, px1, py1;
    screenMap(w.ax, w.ay, w.w, w.h, &px0, &py0, &px1, &py1);
    if (json) {
        char cls[200]; jsonStr(cls, sizeof cls, w.cls);
        fprintf(f, "%s{\"d\":%d,\"cls\":\"%s\",\"x\":%.1f,\"y\":%.1f,\"w\":%.1f,\"h\":%.1f,"
                   "\"px\":[%d,%d,%d,%d],\"placed\":%d}",
                g_firstTree ? "" : ",", depth, cls, w.ax, w.ay, w.w, w.h, px0, py0, px1, py1, placed);
        g_firstTree = 0;
    } else {
        fprintf(f, "  %*s%-26s abs=(%.1f, %.1f) size=(%.1f x %.1f) px=[%d,%d,%d,%d]%s\n",
                depth * 2, "", w.cls[0] ? w.cls : "?", w.ax, w.ay, w.w, w.h,
                px0, py0, px1, py1, placed ? "" : "   [미배치]");
    }
    if (depth >= maxd) return;
    if (!isHeap(w.cb) || !isHeap(w.ce) || w.ce <= w.cb) return;
    uint64_t n = (w.ce - w.cb) / 8;
    if ((w.ce - w.cb) % 8 || n > 256) return;
    for (uint64_t i = 0; i < n; i++) {
        uint64_t ch = q64(w.cb + i * 8);
        if (!isHeap(ch) || !isMod(q64(ch))) continue;
        walkTree(f, ch, depth + 1, maxd, json, nOut);
    }
}

static uint64_t findLayout(uint64_t ui)
{
    for (int c = 0; c < g_ncont; c++) {
        uint64_t node = q64(ui + g_head[c]);
        for (int n = 0; n < 2048 && isHeap(node); n++) {
            uint8_t nb[0x48];
            if (!rm(node, nb, sizeof nb)) break;
            uint64_t lay = *(uint64_t *)(nb + RG_CVAL);
            uint64_t nxt = *(uint64_t *)(nb + g_next[c]);
            if (isHeap(lay) && vrva(lay) == RG_WIN_VFT) return lay;
            if (nxt == node) break;
            node = nxt;
        }
    }
    return 0;
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("registry/LC930_REGISTRY.txt");
    const char *reg  = lcreg_resolve("registry/LC930_REGISTRY.txt", "registry/LC930_REGISTRY.txt");
    const char *outp = lcreg_outpath("partyhud_out.txt");
    int secs = 0, all = 0, winOnly = 0, json = 0, noTree = 0, maxd = 6;

    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "-all"))     { all = 1; continue; }
        if (!strcmp(argv[i], "-win"))     { winOnly = 1; continue; }
        if (!strcmp(argv[i], "-json"))    { json = 1; continue; }
        if (!strcmp(argv[i], "-no-tree")) { noTree = 1; continue; }
        if (strstr(argv[i], ".txt") || strstr(argv[i], ".out")) {
            if (strstr(argv[i], "REGISTRY")) reg = argv[i]; else outp = argv[i];
        } else if (atoi(argv[i]) > 0 && !strchr(argv[i], '.')) secs = atoi(argv[i]);
    }
    reg = lcreg_resolve(reg, "registry/LC930_REGISTRY.txt");
    lcreg_load_first(reg, "registry/LC930_REGISTRY.txt"); lc_reg_apply();
    /* Bot module: slot rows only. The exe still prints the bar tree. */
    if (lcapi_on()) noTree = 1;

    RG_WIN_VFT   = lcreg_u32("UILAY_HudPartyInfoLayoutPCImpl", 0x1294C80);
    RG_CVAL      = lcreg_u32("UIDLG_CONT_VAL", 0x38);
    RG_VIS       = lcreg_u32("VIS_FLAG", 0x70);
    RG_POS_X     = lcreg_u32("LAYOUT_POS_X", 0x60);
    RG_POS_Y     = lcreg_u32("LAYOUT_POS_Y", 0x64);
    RG_SIZE_W    = lcreg_u32("LAYOUT_SIZE_W", 0x6C);
    RG_SIZE_H    = lcreg_u32("LAYOUT_SIZE_H", 0x70);
    RG_NODE_OFF  = lcreg_u32("LAYOUT_WIDGET_NODE", 0x30);
    RG_SLOT_OFF  = lcreg_u32("PARTY_HUD_SLOT_OFF", 0xC0);
    RG_SLOT_STRIDE = lcreg_u32("PARTY_HUD_SLOT_STRIDE", 0x10);
    RG_SLOT_OBJ  = lcreg_u32("PARTY_HUD_SLOT_OBJ", 0x08);
    RG_SLOT_N    = lcreg_u32("PARTY_HUD_SLOT_COUNT", 8);
    RG_SLOT_GUID = lcreg_u32("PARTY_HUD_SLOT_GUID_OFF", 0x10);
    RG_SLOT_HP   = lcreg_u32("PARTY_HUD_SLOT_HP_OFF", 0x1C);
    RG_SLOT_MP   = lcreg_u32("PARTY_HUD_SLOT_MP_OFF", 0x20);
    RG_INACTIVE  = lcreg_u32("PARTY_HUD_SLOT_INACTIVE_GUID", 0xFFFFFFFF);
    RG_WPOS_X    = lcreg_u32("WIDGET_POS_X", 0x3C);
    RG_WPOS_Y    = lcreg_u32("WIDGET_POS_Y", 0x40);
    RG_WABS_X    = lcreg_u32("WIDGET_ABS_X", 0xB0);
    RG_WABS_Y    = lcreg_u32("WIDGET_ABS_Y", 0xB4);
    RG_WSC_X     = lcreg_u32("WIDGET_SCALE_X", 0x2C);
    RG_WSC_Y     = lcreg_u32("WIDGET_SCALE_Y", 0x30);
    RG_CHILD     = lcreg_u32("WIDGET_CHILDREN", 0x178);
    RG_DIR_OFF   = lcreg_u32("DIRECTOR_OFF", 0x198);
    RG_GLV_IN_DIR= lcreg_u32("GLVIEW_IN_DIR", 0x100);
    RG_GLV_FW    = lcreg_u32("GLV_FRAME_W", 0x10);
    RG_GLV_FH    = lcreg_u32("GLV_FRAME_H", 0x14);
    RG_GLV_DW    = lcreg_u32("GLV_DESIGN_W", 0x18);
    RG_GLV_DH    = lcreg_u32("GLV_DESIGN_H", 0x1C);
    RG_GLV_VX    = lcreg_u32("GLV_VIEW_X", 0x20);
    RG_GLV_VY    = lcreg_u32("GLV_VIEW_Y", 0x24);
    RG_GLV_SX    = lcreg_u32("GLV_SCALE_X", 0x50);
    RG_GLV_SY    = lcreg_u32("GLV_SCALE_Y", 0x54);
    RG_DESIGN_W  = lcreg_u32("UI_DESIGN_W", 1280);
    RG_DESIGN_H  = lcreg_u32("UI_DESIGN_H", 960);

    { const char *v = lcreg_str("UIDLG_CONT", "0x38:0x18,0x28:0x28"); char buf[128];
      strncpy(buf, v, 127); buf[127] = 0;
      for (char *t = strtok(buf, ","); t && g_ncont < 8; t = strtok(0, ",")) {
          char *c = strchr(t, ':'); if (!c) continue; *c = 0;
          g_head[g_ncont] = strtoull(t, 0, 0);
          g_next[g_ncont] = strtoull(c + 1, 0, 0);
          g_ncont++; } }

    if (lc_attach()) return 1;
    if (!lc_anchor()) { fprintf(stderr, "anchor fail\n"); return 2; }
    uint64_t ui = lc_subsGet(lcreg_u32("VFT_UISUBSYSTEM", 0x11F6A38));
    if (!isHeap(ui)) { fprintf(stderr, "UI subsystem not found\n"); return 2; }

    lcreg_mkdir_for(outp);
    FILE *f = fopen(outp, "w");
    if (!f) { fprintf(stderr, "cannot open %s\n", outp); return 4; }

    DWORD t0 = GetTickCount();
    LARGE_INTEGER fr, q0, q1; QueryPerformanceFrequency(&fr);
    int cycles = 0;

    do {
        lc_pgc_reset();
        g_nclc = 0; g_firstTree = 1;
        unsigned long long io0 = g_ioctl;
        QueryPerformanceCounter(&q0);
        uint64_t lay = findLayout(ui);

        if (!lay) {
            fprintf(f, "# partyhud t=%ums  창 없음 ioctl=%llu\n",
                    (unsigned)(GetTickCount() - t0), g_ioctl - io0);
            fflush(f);
            lcapi_sample(f);
            if (!secs) break;
            if (!lcapi_on()) Sleep(lcreg_u32("PARTYHUD_POLL_MS", 200));
            continue;
        }
        uint64_t node = q64(lay + RG_NODE_OFF);
        float wx = f32(lay + RG_POS_X), wy = f32(lay + RG_POS_Y);
        float ww = isHeap(node) ? f32(node + RG_SIZE_W) : 0.0f;
        float wh = isHeap(node) ? f32(node + RG_SIZE_H) : 0.0f;
        uint32_t vis = d32(lay + RG_VIS) & 0xFF;

        /* 화면 매핑: GLView 우선, 실패 시 현재 client rect 로 폴백 */
        const char *src = "glview";
        int okScreen = isHeap(node) ? readScreen(node) : 0;
        if (!okScreen) {
            HWND hw = lc_findGameWnd((DWORD)g_pid);
            RECT r;
            if (hw && GetClientRect(hw, &r) && r.right > 0 && r.bottom > 0) {
                g_scr.ok = 1;
                g_scr.fw = (float)r.right; g_scr.fh = (float)r.bottom;
                g_scr.dw = (float)RG_DESIGN_W; g_scr.dh = (float)RG_DESIGN_H;
                g_scr.sx = g_scr.fw / g_scr.dw;
                g_scr.sy = g_scr.fh / g_scr.dh;
                g_scr.vx = g_scr.vy = 0;
                src = "client";
            }
        }
        if (!g_scr.ok) {
            g_scr.ok = 1;
            g_scr.fw = (float)RG_DESIGN_W; g_scr.fh = (float)RG_DESIGN_H;
            g_scr.dw = (float)RG_DESIGN_W; g_scr.dh = (float)RG_DESIGN_H;
            g_scr.sx = g_scr.sy = 1.0f; g_scr.vx = g_scr.vy = 0;
            src = "design";
        }
        int wx0, wy0, wx1, wy1; screenMap(wx, wy, ww, wh, &wx0, &wy0, &wx1, &wy1);

        int nTree = 0;
        if (!winOnly && !noTree && isHeap(node))
            ; /* walk 은 아래에서 */

        int nAct = 0;
        if (!winOnly) {
            for (uint32_t i = 0; i < RG_SLOT_N; i++) {
                uint64_t so = q64(lay + RG_SLOT_OFF + i * RG_SLOT_STRIDE + RG_SLOT_OBJ);
                if (!isHeap(so)) continue;
                uint32_t guid = d32(so + RG_SLOT_GUID);
                if (guid != RG_INACTIVE) nAct++;
            }
        }

        QueryPerformanceCounter(&q1);
        double ms = (double)(q1.QuadPart - q0.QuadPart) * 1000.0 / (double)fr.QuadPart;
        unsigned long long io = g_ioctl - io0;

        if (json) {
            fprintf(f, "{\"t\":%u,\"screen\":{\"src\":\"%s\",\"frame\":[%.0f,%.0f],"
                       "\"design\":[%.0f,%.0f],\"scale\":[%.5f,%.5f],\"vp\":[%.0f,%.0f]},"
                       "\"win\":{\"x\":%.1f,\"y\":%.1f,\"w\":%.1f,\"h\":%.1f,\"vis\":%u,"
                       "\"px\":[%d,%d,%d,%d]},"
                       "\"ioctl\":%llu,\"ms\":%.3f,\"tree\":[",
                    (unsigned)(GetTickCount() - t0), src,
                    g_scr.fw, g_scr.fh, g_scr.dw, g_scr.dh, g_scr.sx, g_scr.sy, g_scr.vx, g_scr.vy,
                    wx, wy, ww, wh, vis, wx0, wy0, wx1, wy1, io, ms);
        } else {
            fprintf(f, "# partyhud t=%ums registry=%s ioctl=%llu time=%.3fms\n",
                    (unsigned)(GetTickCount() - t0), reg, io, ms);
            fprintf(f, "# screen src=%s frame=%.0fx%.0f design=%.0fx%.0f scale=%.5f vp=(%.0f,%.0f)\n",
                    src, g_scr.fw, g_scr.fh, g_scr.dw, g_scr.dh, g_scr.sx, g_scr.sy, g_scr.vx, g_scr.vy);
            fprintf(f, "WIN x=%.1f y=%.1f w=%.1f h=%.1f vis=%u  px=[%d,%d,%d,%d]   "
                       "(design=cocos 좌하 원점 / px=클라이언트 픽셀 좌상 원점)\n",
                    wx, wy, ww, wh, vis, wx0, wy0, wx1, wy1);
            if (!winOnly && !noTree) fprintf(f, "TREE (바 자체 버튼/아이콘):\n");
        }
        g_firstTree = 1;
        if (!winOnly && !noTree && isHeap(node)) walkTree(f, node, 0, maxd, json, &nTree);

        if (json) fprintf(f, "],\"slots\":[");
        int nSlotOut = 0;
        if (!winOnly) {
            for (uint32_t i = 0; i < RG_SLOT_N; i++) {
                uint64_t so = q64(lay + RG_SLOT_OFF + i * RG_SLOT_STRIDE + RG_SLOT_OBJ);
                if (!isHeap(so)) continue;
                uint8_t sb[0x30];
                if (!lc_pgRead(so, sb, sizeof sb)) continue;
                uint32_t guid = *(uint32_t *)(sb + RG_SLOT_GUID);
                float hp = *(float *)(sb + RG_SLOT_HP);
                float mp = *(float *)(sb + RG_SLOT_MP);
                int active = (guid != RG_INACTIVE);
                if (!active && !all) continue;

                if (json) {
                    fprintf(f, "%s{\"i\":%u,\"guid\":\"0x%X\",\"hp\":%.1f,\"mp\":%.1f,\"active\":%d,\"w\":[",
                            nSlotOut ? "," : "", i, guid, hp, mp, active);
                } else {
                    fprintf(f, "SLOT %u guid=0x%X hp=%.1f mp=%.1f active=%d\n", i, guid, hp, mp, active);
                }
                int firstw = 1;
                for (uint32_t off = 0x60; off <= 0xF0; off += 8) {
                    uint64_t wp = q64(so + off);
                    LW w;
                    if (!readWidget(wp, &w)) continue;
                    int placed = isPlaced(&w);
                    int qx0, qy0, qx1, qy1;
                    screenMap(w.ax, w.ay, w.w, w.h, &qx0, &qy0, &qx1, &qy1);
                    if (json) {
                        char cls[200]; jsonStr(cls, sizeof cls, w.cls);
                        fprintf(f, "%s{\"off\":\"0x%X\",\"cls\":\"%s\",\"x\":%.1f,\"y\":%.1f,"
                                   "\"w\":%.1f,\"h\":%.1f,\"px\":[%d,%d,%d,%d],"
                                   "\"sx\":%.2f,\"sy\":%.2f,\"placed\":%d}",
                                firstw ? "" : ",", off, cls, w.ax, w.ay, w.w, w.h,
                                qx0, qy0, qx1, qy1, w.sx, w.sy, placed);
                        firstw = 0;
                    } else {
                        fprintf(f, "  W +0x%03X %-14s abs=(%.1f, %.1f) size=(%.1f x %.1f) "
                                   "px=[%d,%d,%d,%d] scale=%.2f,%.2f%s\n",
                                off, w.cls[0] ? w.cls : "?", w.ax, w.ay, w.w, w.h,
                                qx0, qy0, qx1, qy1, w.sx, w.sy,
                                placed ? "" : "   [미배치]");
                    }
                }
                if (json) fprintf(f, "]}");
                nSlotOut++;
            }
        }
        if (json) fprintf(f, "]}\n");
        else if (!winOnly) fprintf(f, "SLOTS active=%d/%u\n", nAct, RG_SLOT_N);
        fflush(f);
        lcapi_sample(f);

        printf("WIN x=%.0f y=%.0f w=%.0f h=%.0f vis=%u  px=[%d,%d,%d,%d]  screen=%.0fx%.0f@%.4f(%s)  tree=%d slots=%d/%u  ioctl=%llu  %.2fms\n",
               wx, wy, ww, wh, vis, wx0, wy0, wx1, wy1,
               g_scr.fw, g_scr.fh, g_scr.sx, src, nTree, nAct, RG_SLOT_N, io, ms);

        cycles++;
        if (secs && !lcapi_on()) Sleep(lcreg_u32("PARTYHUD_POLL_MS", 200));
    } while (!lcapi_done() && secs && (int)(GetTickCount() - t0) < secs * 1000);

    fclose(f);
    SignedClose();
    if (cycles != 1) printf("done -> %s (%d cycles)\n", outp, cycles);
    else printf("done -> %s\n", outp);
    return 0;
}
