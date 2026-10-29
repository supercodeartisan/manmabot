/* storewin_930.c — 창고 창(State + 화면 표시목록) 읽기 독립 모듈
 * ===========================================================================
 *  목적: 창고 창이 **지금 무엇을 표시하고 있는지**를 창문에서 직접 읽는다.
 *        (맡기기/찾기 어느 쪽이든 화면에 보이는 목록 그대로)
 *
 *  대원칙 (IOCTL 최소화 · 고정앵커 · 고정체인 · 캐시)
 *    1) 고정앵커  : lc_subsGet(VFT_UISUBSYSTEM)            (lcore 내부 캐시)
 *    2) 고정체인  : UISubsystem + UIDLG_CONT 로 레이아웃 컨테이너를 직접 walk
 *                   (head:next 쌍, 노드 값 @ UIDLG_CONT_VAL)
 *    3) 창 식별    : RTTI 클래스명(RTTI_COL_TD_OFF/RTTI_TD_NAME_OFF) → 짧은이름 비교
 *                   → 창 활성 여부는 +VIS_FLAG
 *    4) 목록       : 창 + WINSLOT_VEC 벡터(stride WINSLOT_STRIDE)
 *                   슬롯 + WINSLOT_NAMEW(이름 위젯) → +WIDGET_RENDERER(렌더러)
 *                   → 렌더러 + LABEL_TEXT_OFF 의 std::string = 표시 문자열
 *    5) 캐시       : RTTI 클래스명/레이아웃 vft 캐시, lc_pgRead 페이지 캐시(사이클당)
 *
 *  ※ uidialogmon 과 **독립** 모듈이다(감시창 명단/합치기 없음).
 *
 *  usage: storewin_930.exe [secs] [-v] [registry] [out.txt]
 *  출력: <EXE>\out\storewin_out.txt
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
static uint32_t RG_UVFT, RG_VIS, RG_CVAL, RG_TDNAME, RG_COLTD;
static uint32_t RG_WSVEC, RG_WSTRIDE, RG_WNAMEW, RG_WCNTW, RG_WRENDER, RG_WTEXT;
static uint32_t RG_STRLEN, RG_STRCAP, RG_SSOMAX;
static char     RG_CLSNPC[96], RG_CLSBM[96];
static uint32_t g_chead[8], g_cnext[8]; static int g_ncont = 0;

/* ── RTTI: vft → 클래스명 ─────────────────────────────────────────────── */
static int classOf(uint64_t vft, char *out, int cap){
    out[0] = 0;
    if (!isMod(vft)) return 0;
    uint64_t col = q64(vft - 8);
    if (!isMod(col)){ if (col > 0 && col < (uint64_t)g_modSize) col = g_base + col; else return 0; }
    uint32_t td_rva = 0;
    if (!lc_pgRead(col + RG_COLTD, &td_rva, 4)) return 0;
    uint64_t td = g_base + td_rva;
    if (!isMod(td)) return 0;
    char raw[512]; memset(raw, 0, sizeof raw);
    if (!lc_pgRead(td + RG_TDNAME, raw, sizeof raw - 1)) return 0;
    const char *p = raw;
    if (!strncmp(p, ".?AV", 4)) p += 4;
    int n = 0;
    while (*p && n < cap - 1){
        if (p[0] == '@' && p[1] == '@') break;
        if (p[0] == '@'){ if (n < cap - 2){ out[n++] = ':'; out[n++] = ':'; } p++; }
        else out[n++] = *p++;
    }
    out[n] = 0;
    return n > 0;
}
static void shortCls(const char *nm, char *out, int cap){
    int i = 0;
    while (nm[i] && nm[i] != ':' && i < cap - 1){ out[i] = nm[i]; i++; }
    out[i] = 0;
}
/* vft → 클래스명 캐시 (컨테이너 walk 마다 RTTI 재해석 제거) */
#define CC_MAX 256
static uint64_t CC_vft[CC_MAX]; static char CC_nm[CC_MAX][160]; static int CC_n = 0;
static int classOfC(uint64_t vft, char *out, int cap){
    for (int i = 0; i < CC_n; i++) if (CC_vft[i] == vft){ snprintf(out, cap, "%s", CC_nm[i]); return 1; }
    if (!classOf(vft, out, cap)) return 0;
    if (CC_n < CC_MAX){ CC_vft[CC_n] = vft; snprintf(CC_nm[CC_n], 160, "%s", out); CC_n++; }
    return 1;
}
/* 레이아웃 포인터 → vft 캐시 (창 객체 vft 는 불변) */
#define LV_MAX 1024
static uint64_t LV_lay[LV_MAX], LV_vf[LV_MAX]; static int LV_n = 0;
static int lvFind(uint64_t lay, uint64_t *vf){
    for (int i = 0; i < LV_n; i++) if (LV_lay[i] == lay){ *vf = LV_vf[i]; return 1; }
    return 0;
}
static void lvSet(uint64_t lay, uint64_t vf){
    if (LV_n < LV_MAX){ LV_lay[LV_n] = lay; LV_vf[LV_n] = vf; LV_n++; }
}

/* ── 창 탐색: 컨테이너 walk 로 클래스명 일치 창의 인스턴스를 찾는다 ────── */
#define W_MAX 8
typedef struct { char cls[96]; uint64_t inst; } WINFO;
static WINFO g_w[W_MAX]; static int g_nw = 0;

static void findWins(uint64_t ui){
    g_nw = 0;
    if (!isHeap(ui)) return;
    for (int c = 0; c < g_ncont && g_nw < W_MAX; c++){
        uint64_t node = q64(ui + g_chead[c]);
        uint32_t need = RG_CVAL + 8; if (g_cnext[c] + 8 > need) need = g_cnext[c] + 8;
        if (need > 0x48) need = 0x48;
        for (int n = 0; n < 2048 && isHeap(node); n++){
            uint8_t nb[0x48];
            if (!lc_pgRead(node, nb, need)) break;
            uint64_t lay = 0, nxt = 0;
            memcpy(&lay, nb + RG_CVAL, 8);
            memcpy(&nxt, nb + g_cnext[c], 8);
            if (isHeap(lay)){
                uint64_t vf = 0;
                if (!lvFind(lay, &vf)){ vf = q64(lay); lvSet(lay, vf); }
                if (isMod(vf)){
                    char nm[160], sh[96];
                    if (classOfC(vf, nm, sizeof nm)){
                        shortCls(nm, sh, sizeof sh);
                        if (!strcmp(sh, RG_CLSNPC) || !strcmp(sh, RG_CLSBM)){
                            int dup = 0;
                            for (int k = 0; k < g_nw; k++) if (!strcmp(g_w[k].cls, sh)) dup = 1;
                            if (!dup){ snprintf(g_w[g_nw].cls, sizeof g_w[0].cls, "%s", sh); g_w[g_nw].inst = lay; g_nw++; }
                        }
                    }
                }
            }
            if (nxt == node) break;
            node = nxt;
        }
    }
}

/* ── 이름 해석(라이브 메시지 테이블) — 가방 대조/모드 판정용 ───────────── */
static uint32_t RG_ARVA, RG_MASK, RG_BKT, RG_NEXT, RG_RECNAME, RG_NAMEKR, RG_NODETEXT, RG_RECHDR;
static uint64_t RG_FNVOFF, RG_FNVPRIME;
static uint64_t fnv1aKey(uint32_t mid){
    char s[24]; int n = snprintf(s, sizeof s, "1_%u", mid);
    uint64_t h = RG_FNVOFF;
    for (int i = 0; i < n; i++){ h ^= (unsigned char)s[i]; h *= RG_FNVPRIME; }
    return h;
}
static uint32_t recMidOf(uint64_t rec){
    uint8_t h[0x20];
    if (!lc_pgRead(rec + RG_RECHDR, h, sizeof h)) return 0;
    if (h[0] != '1' || h[1] != '_') return 0;
    uint64_t size = *(uint64_t*)(h + RG_STRLEN);
    if (size < 3 || size > 12) return 0;
    uint32_t m = 0;
    for (uint64_t i = 2; i < size; i++){ if (h[i] < '0' || h[i] > '9') return 0; m = m*10 + (h[i]-'0'); }
    return m;
}
static int readSso(uint64_t a, char *out, int outSz){
    uint8_t h[0x20];
    if (outSz < 2 || !lc_pgRead(a, h, sizeof h)) return -1;
    uint64_t size = *(uint64_t*)(h + RG_STRLEN), cap = *(uint64_t*)(h + RG_STRCAP);
    if (size == 0 || size > 0x300 || cap > 0x100000) return -1;
    if ((int)size >= outSz) size = outSz - 1;
    if (cap <= 0xF) memcpy(out, h, (size_t)size);
    else { uint64_t p = *(uint64_t*)h; if (!isHeap(p) || !lc_pgRead(p, out, (uint32_t)size)) return -1; }
    out[size] = 0;
    return (int)size;
}
static int msgName(uint32_t mid, char *out, int outSz){
    out[0] = 0;
    if (!RG_ARVA) return 0;
    uint64_t anchor = q64(g_base + RG_ARVA);
    if (!isHeap(anchor)) return 0;
    uint64_t rec = q64(anchor + (fnv1aKey(mid) & RG_MASK) * RG_BKT);
    for (int steps = 0; isHeap(rec) && steps < 64; steps++){
        if (recMidOf(rec) == mid){
            uint64_t nxt = q64(rec + RG_RECNAME); if (!isHeap(nxt)) return 0;
            uint64_t kr = q64(nxt + RG_NAMEKR);   if (!isHeap(kr))  return 0;
            return readSso(kr + RG_NODETEXT, out, outSz) > 0;
        }
        uint64_t nx = q64(rec + RG_NEXT); if (nx == rec) break; rec = nx;
    }
    return 0;
}
static uint32_t fmtMid(const char *fmt){
    for (const char *p = fmt; *p; p++){
        if (*p != '$') continue;
        const char *q = p + 1;
        if (*q < '0' || *q > '9') continue;
        uint32_t v = 0;
        while (*q >= '0' && *q <= '9'){ v = v*10 + (uint32_t)(*q - '0'); q++; }
        if (v) return v;
    }
    return 0;
}
/* 이름 정규화: 선행 "+n " 제거, 후행 " (n)" 제거 */
static void normName(const char *in, char *out, int cap){
    const char *p = in;
    if (*p == '+'){ const char *q = p + 1; while (*q >= '0' && *q <= '9') q++; if (*q == ' ') p = q + 1; }
    int n = (int)strlen(p);
    if (n > 3 && p[n-1] == ')'){
        int i = n - 2;
        while (i >= 0 && ((p[i] >= '0' && p[i] <= '9') || p[i] == ',')) i--;
        if (i >= 1 && p[i] == '(' && p[i-1] == ' ') n = i - 1;
    }
    if (n >= cap) n = cap - 1;
    memcpy(out, p, (size_t)n); out[n] = 0;
}
/* ── 가방 아이템 이름 목록 (모드 판정용) ─────────────────────────────── */
#define BAG_MAX 256
static char g_bag[BAG_MAX][96]; static int g_bagN = 0;
static uint32_t RG_INVVFT, RG_VBEG, RG_VEND, RG_ITEMVFT, RG_IFMT;
static void readBag(void){
    g_bagN = 0;
    uint64_t sub = lc_subsGet(RG_INVVFT);
    if (!isHeap(sub)) return;
    uint64_t vb = q64(sub + RG_VBEG), ve = q64(sub + RG_VEND);
    if (!(isHeap(vb) && isHeap(ve)) || ve < vb) return;
    uint64_t cnt = (ve - vb) / 8;
    if (cnt > 4096) cnt = 4096;
    for (uint64_t i = 0; i < cnt && g_bagN < BAG_MAX; i++){
        uint64_t it = q64(vb + i * 8);
        if (!isHeap(it)) continue;
        uint64_t vf = q64(it);
        if (!isMod(vf) || (uint32_t)(vf - g_base) != RG_ITEMVFT) continue;
        uint8_t ih[0x90];
        if (!lc_pgRead(it, ih, sizeof ih)) continue;
        char fmt[48] = {0};
        const uint8_t *fh = ih + RG_IFMT;
        uint64_t sz = *(uint64_t*)(fh + RG_STRLEN), cp = *(uint64_t*)(fh + RG_STRCAP);
        if (sz > 0 && sz < sizeof fmt && cp >= sz && cp <= 0x10000){
            if (cp <= RG_SSOMAX) memcpy(fmt, fh, (size_t)sz);
            else { uint64_t p = *(uint64_t*)fh; if (isHeap(p)) lc_pgRead(p, fmt, (uint32_t)sz); }
            fmt[sz] = 0;
        }
        uint32_t mid = fmtMid(fmt);
        if (!mid) continue;
        char nm[160];
        if (msgName(mid, nm, sizeof nm)){ snprintf(g_bag[g_bagN], sizeof g_bag[0], "%s", nm); g_bagN++; }
    }
}
static int bagHas(const char *name){
    char a[128]; normName(name, a, sizeof a);
    for (int i = 0; i < g_bagN; i++){
        char b[128]; normName(g_bag[i], b, sizeof b);
        if (!strcmp(a, b)) return 1;
    }
    return 0;
}

/* ── 슬롯 텍스트 읽기: 위젯 → 렌더러 → std::string ─────────────────────── */
static int widgetText(uint64_t slot, uint32_t wOff, char *out, int cap){
    out[0] = 0;
    uint64_t w = q64(slot + wOff);
    if (!isHeap(w)) return 0;
    uint64_t ren = q64(w + RG_WRENDER);
    if (!isHeap(ren)) return 0;
    uint8_t sh[0x20];
    if (!lc_pgRead(ren + RG_WTEXT, sh, sizeof sh)) return 0;
    uint64_t sz = *(uint64_t*)(sh + RG_STRLEN), cp = *(uint64_t*)(sh + RG_STRCAP);
    if (sz == 0 || sz > 0x200 || cp < sz || cp > 0x100000) return 0;
    int n = (int)sz; if (n >= cap) n = cap - 1;
    if (cp <= RG_SSOMAX) memcpy(out, sh, (size_t)n);
    else { uint64_t p = *(uint64_t*)sh; if (!isHeap(p) || !lc_pgRead(p, out, (uint32_t)n)) return 0; }
    out[n] = 0;
    return n > 0;
}
/* "이름 (12)" 형태에서 수량 분리 */
static void splitQty(char *txt, uint32_t *qty){
    *qty = 0;
    int L = (int)strlen(txt);
    if (L < 4 || txt[L-1] != ')') return;
    int i = L - 2, d = 1, digits = 0; uint32_t v = 0;
    while (i >= 0 && ((txt[i] >= '0' && txt[i] <= '9') || txt[i] == ',')){
        if (txt[i] != ','){ v += (uint32_t)(txt[i]-'0') * (uint32_t)d; d *= 10; digits++; }
        i--;
    }
    if (!digits || i < 1 || txt[i] != '(' || txt[i-1] != ' ') return;
    txt[i-1] = 0;
    *qty = v;
}

/* ── 창 1개 상태 + 표시목록 출력 ───────────────────────────────────────── */
#define SMAX 128
typedef struct { char txt[96]; uint32_t qty; } SROW;
typedef struct { uint64_t inst; int vis, n; SROW r[SMAX]; } WSNAP;
static WSNAP g_prev[W_MAX], g_cur[W_MAX];
/* -diff: 창 객체 0x00~0x1FF 변화 필드 덤프(모드 필드 탐색용) */
static uint8_t g_wprevB[W_MAX][0x200];
static int     g_havePrevB[W_MAX];

static int readWin(FILE *f, int wi, int verbose){
    WSNAP *S = &g_cur[wi];
    S->inst = g_w[wi].inst; S->n = 0;
    S->vis = (int)(q64(S->inst + RG_VIS) & 0xFF);
    if (S->vis != 1) return 0;                 /* 창 닫힘: 목록 읽지 않음(해제 메모리 방지) */
    uint64_t beg = q64(S->inst + RG_WSVEC), end = q64(S->inst + RG_WSVEC + 8);
    if (!(isHeap(beg) && isHeap(end)) || end < beg || ((end - beg) % RG_WSTRIDE)) return 0;
    int cnt = (int)((end - beg) / RG_WSTRIDE);
    if (cnt > SMAX) cnt = SMAX;
    for (int i = 0; i < cnt; i++){
        uint64_t slot = q64(beg + (uint64_t)i * RG_WSTRIDE);
        if (!isHeap(slot)) continue;
        SROW *R = &S->r[S->n];
        memset(R, 0, sizeof *R);
        if (!widgetText(slot, RG_WNAMEW, R->txt, sizeof R->txt)) continue;
        splitQty(R->txt, &R->qty);
        S->n++;
    }
    (void)f; (void)verbose;
    return S->n;
}

static int sameWin(const WSNAP *a, const WSNAP *b){
    if (a->inst != b->inst || a->vis != b->vis || a->n != b->n) return 0;
    for (int i = 0; i < a->n; i++)
        if (strcmp(a->r[i].txt, b->r[i].txt) || a->r[i].qty != b->r[i].qty) return 0;
    return 1;
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg  = lcreg_resolve("10_5/registry/LC930_REGISTRY.txt", "registry/LC930_REGISTRY.txt");
    const char *outp = lcreg_outpath("storewin_out.txt");
    int secs = 0, verbose = 0, diffMode = 0;
    for (int i = 1; i < argc; i++){
        if (!strcmp(argv[i], "-v")){ verbose = 1; continue; }
        if (!strcmp(argv[i], "-diff")){ verbose = 1; diffMode = 1; continue; }
        if (strstr(argv[i], ".txt") || strstr(argv[i], ".out")){
            if (strstr(argv[i], "REGISTRY")) reg = argv[i]; else outp = argv[i];
        } else if (atoi(argv[i]) > 0 && !strchr(argv[i], '.')) secs = atoi(argv[i]);
    }
    lcreg_load(reg); lc_reg_apply();

    RG_UVFT    = lcreg_u32("VFT_UISUBSYSTEM", 0x11E2710);
    RG_VIS     = lcreg_u32("VIS_FLAG", 0x70);
    RG_CVAL    = lcreg_u32("UIDLG_CONT_VAL", 0x38);
    RG_TDNAME  = lcreg_u32("RTTI_TD_NAME_OFF", 0x10);
    RG_COLTD   = lcreg_u32("RTTI_COL_TD_OFF", 0xC);
    RG_WSVEC   = lcreg_u32("WINSLOT_VEC", 0x100);
    RG_WSTRIDE = lcreg_u32("WINSLOT_STRIDE", 0x10);
    RG_WNAMEW  = lcreg_u32("WINSLOT_NAMEW", 0x18);
    RG_WCNTW   = lcreg_u32("WINSLOT_CNTW", 0x28);
    RG_WRENDER = lcreg_u32("WIDGET_RENDERER", 0x740);
    RG_WTEXT   = lcreg_u32("LABEL_TEXT_OFF", 0x378);
    RG_STRLEN  = lcreg_u32("OFF_STR_LEN", 0x10);
    RG_STRCAP  = lcreg_u32("OFF_STR_CAP", 0x18);
    RG_SSOMAX  = lcreg_u32("STR_SSO_MAX", 0x10);
    snprintf(RG_CLSNPC, sizeof RG_CLSNPC, "%s", lcreg_str("WINSLOT_WINCLS", "NPCStorageLayoutPCImpl"));
    snprintf(RG_CLSBM,  sizeof RG_CLSBM,  "%s", lcreg_str("UIDLG_WIN_BMStorage", "BMStorageLayoutPCImpl"));
    (void)RG_WCNTW;

    /* 모드 판정용: 가방(인벤토리) + 메시지 테이블 */
    RG_INVVFT   = lcreg_u32("VFT_INVENTORY", 0x1226BB0);
    RG_VBEG     = lcreg_u32("INV_VEC_BEG", 0x3D8);
    RG_VEND     = lcreg_u32("INV_VEC_END", 0x3E0);
    RG_ITEMVFT  = lcreg_u32("ITEM_VFT", 0x12265C8);
    RG_IFMT     = lcreg_u32("ITEM_FMT", 0x68);
    RG_ARVA     = lcreg_u32("MSG_ANCHOR_RVA", 0x16687B8);
    RG_MASK     = lcreg_u32("MSG_BUCKET_MASK", 0xFFFF);
    RG_BKT      = lcreg_u32("MSG_BUCKET_STRIDE", 0x10);
    RG_NEXT     = lcreg_u32("MSG_REC_NEXT", 0x00);
    RG_RECNAME  = lcreg_u32("MSG_REC_NAME", 0x38);
    RG_NAMEKR   = lcreg_u32("MSG_NAME_KR", 0x00);
    RG_NODETEXT = lcreg_u32("MSG_NODE_TEXT", 0x30);
    RG_RECHDR   = lcreg_u32("OFF_REC_HDR", 0x10);
    RG_FNVOFF   = lcreg_u64("MSG_FNV_OFFSET", 0xcbf29ce484222325ULL);
    RG_FNVPRIME = lcreg_u64("MSG_FNV_PRIME", 0x100000001b3ULL);

    /* 컨테이너 head/next 쌍 파싱: "0x38:0x18,0x28:0x28" */
    { const char *v = lcreg_str("UIDLG_CONT", "0x38:0x18,0x28:0x28");
      char buf[128]; snprintf(buf, sizeof buf, "%s", v);
      char *tok = strtok(buf, ",");
      while (tok && g_ncont < 8){
          char *colon = strchr(tok, ':');
          if (colon){
              *colon = 0;
              g_chead[g_ncont] = (uint32_t)strtoul(tok, 0, 0);
              g_cnext[g_ncont] = (uint32_t)strtoul(colon + 1, 0, 0);
              g_ncont++;
          }
          tok = strtok(0, ",");
      }
    }

    if (lc_attach()) return 1;
    if (!lc_anchor()) return 2;
    lcreg_mkdir_for(outp);
    FILE *f = fopen(outp, "w");
    if (!f) return 4;
    fprintf(f, "# storewin_930 (독립 모듈) registry=%s\n", reg);
    fprintf(f, "# anchor=UISubsystem(vft %X)  cont=%d  창 클래스: %s / %s\n",
            RG_UVFT, g_ncont, RG_CLSNPC, RG_CLSBM);
    fprintf(f, "# chain: 창+0x%X(벡터 stride 0x%X) → 슬롯+0x%X(위젯) → +0x%X(렌더러) → +0x%X(std::string)\n",
            RG_WSVEC, RG_WSTRIDE, RG_WNAMEW, RG_WRENDER, RG_WTEXT);

    DWORD t0 = GetTickCount();
    int first = 1;
    do {
        g_ioctl = 0;               /* 사이클당 IOCTL 계수 리셋 */
        lc_pgc_reset();
        uint64_t ui = lc_subsGet(RG_UVFT);
        findWins(ui);

        static WSNAP prevStore[W_MAX];
        for (int wi = 0; wi < g_nw; wi++){
            readWin(f, wi, verbose);
            g_prev[wi] = prevStore[wi];
            prevStore[wi] = g_cur[wi];
        }

        fprintf(f, "\n## cycle t=%ums ui=0x%llX windows=%d ioctl=%llu\n",
                (unsigned)(GetTickCount()-t0), (unsigned long long)ui, g_nw, g_ioctl);

        for (int wi = 0; wi < g_nw; wi++){
            WSNAP *C = &g_cur[wi];
            int changed = first || !sameWin(&g_prev[wi], C);
            /* 목록이 바뀐 순간에만 창 객체 필드 diff (모드 필드 탐색) */
            if (diffMode && C->vis == 1 && !first && changed && g_havePrevB[wi]){
                uint8_t nb[0x200];
                if (lc_pgRead(C->inst, nb, sizeof nb)){
                    fprintf(f, "# DIFF(win=0x%llX)\n", (unsigned long long)C->inst);
                    for (int o = 0; o + 8 <= 0x200; o += 8){
                        uint64_t a, b;
                        memcpy(&a, g_wprevB[wi] + o, 8);
                        memcpy(&b, nb + o, 8);
                        if (a != b) fprintf(f, "    +0x%03X: 0x%llX -> 0x%llX\n",
                                            o, (unsigned long long)a, (unsigned long long)b);
                    }
                }
            }
            if (C->vis == 1 && lc_pgRead(C->inst, g_wprevB[wi], sizeof g_wprevB[wi])) g_havePrevB[wi] = 1;
            /* 모드 판정: 표시 목록이 가방(인벤토리)에 전부 있으면 맡기기, 아니면 찾기 */
            if (changed) readBag();
            int match = 0;
            for (int i = 0; i < C->n; i++) if (bagHas(C->r[i].txt)) match++;
            const char *mode = "미상";
            if (C->vis == 1 && C->n > 0)
                mode = (match == C->n) ? "맡기기(DP)" : "찾기(RT)";
            fprintf(f, "# [%s] inst=0x%llX %s rows=%d mode=%s bagMatch=%d/%d(bag=%d)%s\n",
                    g_w[wi].cls, (unsigned long long)C->inst,
                    C->vis == 1 ? "OPEN" : "closed", C->n, mode, match, C->n, g_bagN,
                    changed ? "" : " (unchanged)");
            if (verbose || changed){
                for (int i = 0; i < C->n; i++){
                    if (C->r[i].qty) fprintf(f, "  %2d  \"%s\"  x%u\n", i+1, C->r[i].txt, C->r[i].qty);
                    else             fprintf(f, "  %2d  \"%s\"\n", i+1, C->r[i].txt);
                }
            }
            if (!first && !sameWin(&g_prev[wi], C)){
                /* 이동/변화 요약 */
                for (int i = 0; i < C->n; i++){
                    const char *o = 0; uint32_t oq = 0;
                    for (int j = 0; j < g_prev[wi].n; j++)
                        if (!strcmp(g_prev[wi].r[j].txt, C->r[i].txt)){ o = g_prev[wi].r[j].txt; oq = g_prev[wi].r[j].qty; break; }
                    if (!o) fprintf(f, "  [+] \"%s\" x%u\n", C->r[i].txt, C->r[i].qty);
                    else if (oq != C->r[i].qty) fprintf(f, "  [~] \"%s\" %u -> %u\n", C->r[i].txt, oq, C->r[i].qty);
                }
                for (int j = 0; j < g_prev[wi].n; j++){
                    int found = 0;
                    for (int i = 0; i < C->n; i++) if (!strcmp(C->r[i].txt, g_prev[wi].r[j].txt)){ found = 1; break; }
                    if (!found) fprintf(f, "  [-] \"%s\"\n", g_prev[wi].r[j].txt);
                }
            }
        }
        first = 0;
        fflush(f);
        lcapi_sample(f);
        if (secs) Sleep(lcreg_u32("POLL_STORAGE_INTERVAL_MS", 500));
    } while (!lcapi_done() && secs && (int)(GetTickCount()-t0) < secs * 1000);

    fclose(f); SignedClose();
    printf("done -> %s\n", outp);
    return 0;
}
