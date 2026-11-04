/* storelist_930.c — 창고 목록 정본 모듈 (맡기기/찾기 · 개인/혈맹)
 * ---------------------------------------------------------------------------
 *  목적: 창고 UI 가 실제로 표시하는 **두 목록**을 그대로 읽는다.
 *
 *    [DEP]/[RET]  = StorageSubsystem 의 ctx
 *                   ctx = *(sub + STORAGE_CTX_DEPOSIT | STORAGE_CTX_LIST)
 *                   ctx + STORAGE_VEC_OFF/END/CAP = vector<shared_ptr<ItemEntity>>
 *                   원소 stride STORAGE_ELEM_STRIDE, item @ 원소+STORAGE_ELEM_ITEM
 *    [BDEP]/[BRET] = BMStorageSubsystem (혈맹창고) 동일 체인
 *
 *  ※ 목록은 가방/장비로 재구성하지 않는다. 창고 컨텍스트 벡터를 **직접** 읽는다.
 *     (실측: StorageSubsystem+0x28 ctx 의 벡터 = 창 맡기기 목록과 순서까지 일치)
 *
 *  아이템 레코드(vft=ITEM_VFT): ID / COUNT / FMT("$<이름ID> (<수량>)")
 *  이름 해석: 라이브 메시지 테이블(msgName, FNV1a "1_<id>") 우선.
 *
 *  대원칙: 고정앵커(서브시스템 vft) + 고정체인(registry 상수만). 오프셋 하드코딩 없음.
 *          읽기는 lc_pgRead 경유(페이지 배치).
 *
 *  usage: storelist_930.exe [secs] [-v] [registry] [out.txt]
 *  출력: <EXE>\out\storelist_930_out.txt
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

/* ── 라이브 메시지 테이블(이름 해석) ─────────────────────────────── */
static uint32_t RG_ARVA, RG_MASK, RG_STRIDE, RG_NEXT, RG_RECNAME, RG_NAMEKR, RG_NODETEXT, RG_RECHDR;
static uint32_t RG_STRLEN, RG_STRCAP;
static uint64_t RG_FNVOFF, RG_FNVPRIME;
static int  RG_PREFKR = 1;
static char RG_STRCSV[256];
static int  s_id[40000]; static char s_kr[40000][160]; static int s_n = 0;
static const char* strName(int id){
    for(int i=0;i<s_n;i++) if(s_id[i]==id){
        const char* v=s_kr[i];
        if(!v[0] || !strncmp(v,"desc",4) || !strncmp(v,"string",6)) return 0;
        return v;
    }
    return 0;
}
static void loadStrings(const char *p){
    FILE *g = fopen(p, "rb"); if (!g) return;
    char *raw = (char*)malloc(2<<20); if (!raw){ fclose(g); return; }
    int n = (int)fread(raw, 1, 2<<20, g); fclose(g); raw[n] = 0; char *s = raw;
    if ((unsigned char)s[0]==0xEF&&(unsigned char)s[1]==0xBB&&(unsigned char)s[2]==0xBF) s += 3;
    while (*s){ char *e = strchr(s, '\n'); if (e) *e = 0; char *cm = strchr(s, ',');
        if (cm){ int id = atoi(s);
            if (id > 0){ char *p1 = strchr(cm+1, ','), *p2 = p1 ? strchr(p1+1, ',') : 0;
                if (p2){ char *kr = p2+1, *buf = s_kr[s_n]; int bi = 0, inq = 0; if (*kr=='"'){ inq=1; kr++; }
                    while (*kr && bi < 159){ if (inq){ if (*kr=='"') break; } else { if (*kr==',') break; } buf[bi++] = *kr++; }
                    buf[bi] = 0; s_id[s_n] = id; s_n++; if (s_n >= 40000) break; } } }
        if (!e) break; s = e + 1; }
    free(raw);
}

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
    uint64_t rec = q64(anchor + (fnv1aKey(mid) & RG_MASK) * RG_STRIDE);
    for (int steps = 0; isHeap(rec) && steps < 64; steps++){
        if (recMidOf(rec) == mid){
            uint64_t nxt = q64(rec + RG_RECNAME); if (!isHeap(nxt)) return 0;
            uint64_t kr = q64(nxt + RG_NAMEKR); if (!isHeap(kr)) return 0;
            return readSso(kr + RG_NODETEXT, out, outSz) > 0;
        }
        uint64_t nx = q64(rec + RG_NEXT); if (nx == rec) break; rec = nx;
    }
    return 0;
}

/* ── 설정 ─────────────────────────────────────────────────────────── */
static uint32_t RG_SVFT, RG_BMVFT, RG_DEP_OFF, RG_RET_OFF, RG_BDEP_OFF, RG_BRET_OFF;
static uint32_t RG_VEC, RG_VECEND, RG_VECCAP, RG_STRIDE2, RG_ELEMITEM;
static uint32_t RG_ITEMVFT, RG_ID, RG_COUNT, RG_FMT, RG_MAXITEM, RG_CNT64;
/* 찾기(RET) 체인 — ctx=*(sub+STORAGE_CTX_LIST), map=*(ctx+STORAGE_MAP_OFF) */
static uint32_t RG_CTXLIST, RG_MAPOFF, RG_NIL, RG_KEY, RG_VAL, RG_RETID, RG_RETCF, RG_RETCNT, RG_RETNAME;
static uint32_t RG_TREE_L, RG_TREE_P, RG_TREE_R;

/* ── 이름 캐시 (mid → 이름). 메시지 테이블 재순회(다수 IOCTL) 제거 ────── */
#define NMC_MAX 512
static uint32_t g_nmcMid[NMC_MAX];
static char     g_nmcNm[NMC_MAX][160];
static int      g_nmcN = 0;
static const char* nmFind(uint32_t mid){
    for (int i = 0; i < g_nmcN; i++) if (g_nmcMid[i] == mid) return g_nmcNm[i];
    return 0;
}
static void nmAdd(uint32_t mid, const char *nm){
    if (g_nmcN >= NMC_MAX || !nm || !nm[0]) return;
    g_nmcMid[g_nmcN] = mid;
    snprintf(g_nmcNm[g_nmcN], sizeof g_nmcNm[0], "%s", nm);
    g_nmcN++;
}

/* ── 목록 ─────────────────────────────────────────────────────────── */
#define SL_MAX 512
typedef struct { uint32_t id; uint32_t cnt; char fmt[64]; char nm[160]; } SLITEM;
typedef struct { uint64_t ctx; int n; uint32_t total, max; SLITEM it[SL_MAX]; } SLIST;

#define NLIST 4
enum { L_DEP = 0, L_RET = 1, L_BDEP = 2, L_BRET = 3 };
static const char *L_TAG[NLIST]  = { "DEP",  "RET",  "BDEP",  "BRET"  };
static const char *L_KIND[NLIST] = { "개인 창고", "개인 창고", "혈맹 창고", "혈맹 창고" };
static const char *L_MODE[NLIST] = { "맡기기", "찾기", "맡기기", "찾기" };

static SLIST g_cur[NLIST], g_prev[NLIST];

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

/* ctx = *(sub + off) → vector<shared_ptr<ItemEntity>> → ItemEntity 필드 */
static int readList(SLIST *L, uint64_t sub, uint32_t off){
    L->n = 0; L->ctx = 0; L->total = 0; L->max = 0;
    if (!isHeap(sub)) return 0;
    uint64_t ctx = q64(sub + off);
    if (!isHeap(ctx)) return 0;
    L->ctx = ctx;
    /* ctx+0x8 = u32 total / u32 max  (창고 표시 "보관 29/100") — 실측 확인 */
    { uint64_t cm = 0;
      if (lc_pgRead(ctx + RG_CNT64, &cm, 8)){
          uint32_t t = (uint32_t)cm, mx = (uint32_t)(cm >> 32);
          if (t && mx && t <= mx && mx <= RG_MAXITEM){ L->total = t; L->max = mx; }
      } }

    uint8_t hb[0x38];
    uint32_t need = RG_VECCAP + 8; if (need > sizeof hb) need = sizeof hb;
    if (!lc_pgRead(ctx, hb, need)) return 0;
    uint64_t vb, ve;
    memcpy(&vb, hb + RG_VEC, 8);
    memcpy(&ve, hb + RG_VECEND, 8);
    if (!(isHeap(vb) && isHeap(ve)) || ve < vb) return 0;
    if ((ve - vb) % RG_STRIDE2) return 0;
    int m = (int)((ve - vb) / RG_STRIDE2);
    if (m < 0) return 0;
    if (m > (int)RG_MAXITEM) m = (int)RG_MAXITEM;

    static uint8_t ebuf[8192];
    int done = 0;
    for (int base = 0; base < m && L->n < SL_MAX; ){
        int c = ((m - base) > 512) ? 512 : (m - base);
        if (!lc_pgRead(vb + (uint64_t)base * RG_STRIDE2, ebuf, (uint32_t)c * RG_STRIDE2)) break;
        for (int k = 0; k < c && L->n < SL_MAX; k++){
            uint64_t it;
            memcpy(&it, ebuf + (uint64_t)k * RG_STRIDE2 + RG_ELEMITEM, 8);
            if (!isHeap(it)) continue;
            /* 아이템 헤더(vft/ID/COUNT) + FMT(std::string) 를 **1콜**로 함께 읽는다
               (같은 페이지면 페이지 캐시로 IOCTL 1회) */
            uint8_t ih[0x90];
            if (!lc_pgRead(it, ih, sizeof ih)) continue;
            uint64_t vfp; memcpy(&vfp, ih, 8);
            if (!isMod(vfp) || (uint32_t)(vfp - g_base) != RG_ITEMVFT) continue;   /* 항목 서명검증 */

            SLITEM *R = &L->it[L->n];
            memset(R, 0, sizeof *R);
            memcpy(&R->id,  ih + RG_ID,    4);
            memcpy(&R->cnt, ih + RG_COUNT, 4);

            if (RG_FMT + 0x20 <= sizeof ih){
                const uint8_t *fh = ih + RG_FMT;
                uint64_t sz = *(uint64_t*)(fh + RG_STRLEN);
                uint64_t cp = *(uint64_t*)(fh + RG_STRCAP);
                if (sz > 0 && sz < sizeof R->fmt && cp >= sz && cp <= 0x10000){
                    if (cp <= 0xF) memcpy(R->fmt, fh, (size_t)sz);
                    else { uint64_t p = *(uint64_t*)fh; if (isHeap(p)) lc_pgRead(p, R->fmt, (uint32_t)sz); }
                    R->fmt[sz] = 0;
                }
            }
            uint32_t mid = fmtMid(R->fmt);
            if (mid){
                const char *c = nmFind(mid);
                if (c) snprintf(R->nm, sizeof R->nm, "%s", c);
                else { const char *d = RG_PREFKR ? strName(mid) : 0;   /* 한글 사전 우선 */
                       if (d){ snprintf(R->nm, sizeof R->nm, "%s", d); nmAdd(mid, R->nm); }
                       else if (msgName(mid, R->nm, sizeof R->nm)) nmAdd(mid, R->nm); }
            }
            L->n++; done++;
        }
        base += c;
    }
    return done;
}

/* ── [RET] 찾기 목록: std::map<int, ItemInfo@LIN> ────────────────────────
 *   ctx = *(StorageSubsystem + STORAGE_CTX_LIST)   (StorageRetrieveInfo)
 *   head = *(ctx + STORAGE_RET_MAP_OFF)            ← 10/21 신빌드: 0x18 (head 노드 직접)
 *   size =  *(ctx + STORAGE_RET_SIZE_OFF)          ← 0x20 (29)
 *   node: _Isnil@0x19, key@0x20, value(ItemInfo)@0x28, _Left@0, _Parent@8, _Right@0x10
 *   ItemInfo: ID@0x70(u32), FMT(태그된 std::string*)@0x58 → "$<이름ID> (<수량>)"
 *   순회: begin = *head (leftmost) → 중위 후속.
 */
static int isNilNode(uint64_t n){
    uint8_t b = 1;
    if (!lc_pgRead(n + RG_NIL, &b, 1)) return 1;
    return b != 0;
}
static uint64_t treeNext(uint64_t node){
    uint64_t r = q64(node + RG_TREE_R);
    if (isHeap(r) && !isNilNode(r)){
        node = r;
        for (int g = 0; g < 64; g++){
            uint64_t l = q64(node + RG_TREE_L);
            if (!isHeap(l) || isNilNode(l)) break;
            node = l;
        }
        return node;
    }
    uint64_t p = q64(node + RG_TREE_P);
    for (int g = 0; g < 64 && isHeap(p) && !isNilNode(p); g++){
        if (node != q64(p + RG_TREE_R)) break;
        node = p; p = q64(p + RG_TREE_P);
    }
    return p;
}
static uint64_t g_retMap = 0, g_retRoot = 0;
static int readRet(SLIST *L, uint64_t sub){
    L->n = 0; L->ctx = 0; g_retMap = 0; g_retRoot = 0;
    if (!isHeap(sub)) return 0;
    uint64_t ctx = q64(sub + RG_CTXLIST);
    if (!isHeap(ctx)) return 0;
    L->ctx = ctx;
    { uint64_t cm = 0;
      if (lc_pgRead(ctx + RG_CNT64, &cm, 8)){
          uint32_t t = (uint32_t)cm, mx = (uint32_t)(cm >> 32);
          if (t && mx && t <= mx && mx <= RG_MAXITEM){ L->total = t; L->max = mx; }
      } }
    uint64_t head = q64(ctx + RG_MAPOFF);        /* head 노드 (0x18) */
    if (!isHeap(head)) return 0;
    g_retMap = head;
    uint64_t node = q64(head);                   /* leftmost */
    g_retRoot = node;
    for (int guard = 0; isHeap(node) && !isNilNode(node) && L->n < SL_MAX && guard < 4096; guard++){
        SLITEM *R = &L->it[L->n];
        memset(R, 0, sizeof *R);
        uint64_t val = node + RG_VAL;
        uint8_t b4[4];
        if (lc_pgRead(val + RG_RETID, b4, 4)) memcpy(&R->id, b4, 4);
        /* FMT: val+RG_RETNAME = 태그된 포인터 → std::string (data@0,size@0x10,cap@0x18) */
        char fmt[96]; fmt[0] = 0;
        uint64_t np = q64(val + RG_RETNAME) & ~(uint64_t)3;
        if (isHeap(np)){
            uint8_t sh[0x20];
            if (lc_pgRead(np, sh, sizeof sh)){
                uint64_t sz = *(uint64_t*)(sh + RG_STRLEN), cp = *(uint64_t*)(sh + RG_STRCAP);
                if (sz > 0 && sz < sizeof fmt && cp >= sz && cp <= 0x10000){
                    if (cp <= 0xF) memcpy(fmt, sh, (size_t)sz);
                    else { uint64_t p = *(uint64_t*)sh; if (isHeap(p)) lc_pgRead(p, fmt, (uint32_t)sz); }
                    fmt[sz] = 0;
                }
            }
        }
        /* 수량: FMT 의 "(N)" — 없으면 1 */
        R->cnt = 1;
        snprintf(R->fmt, sizeof R->fmt, "%s", fmt);
        for (char *p = fmt; *p; p++){
            if (*p == '('){ int v = atoi(p + 1); if (v > 0) R->cnt = (uint32_t)v; break; }
        }
        /* 이름: "$<mid>" → 라이브 메시지 테이블 */
        uint32_t mid = fmtMid(fmt);
        if (mid){
            const char *c = nmFind(mid);
            if (c) snprintf(R->nm, sizeof R->nm, "%s", c);
            else { const char *d = RG_PREFKR ? strName(mid) : 0;   /* 한글 사전 우선 */
                   if (d){ snprintf(R->nm, sizeof R->nm, "%s", d); nmAdd(mid, R->nm); }
                   else if (msgName(mid, R->nm, sizeof R->nm)) nmAdd(mid, R->nm); }
        }
        L->n++;
        node = treeNext(node);
    }
    return L->n;
}

static int sameList(const SLIST *a, const SLIST *b){
    if (a->ctx != b->ctx || a->n != b->n) return 0;
    for (int i = 0; i < a->n; i++)
        if (a->it[i].id != b->it[i].id || a->it[i].cnt != b->it[i].cnt) return 0;
    return 1;
}

static void printList(FILE *f, int li){
    const SLIST *B = &g_cur[li];
    fprintf(f, "-- [%s] %s · %s n=%d ctx=0x%llX",
            L_TAG[li], L_KIND[li], L_MODE[li], B->n, (unsigned long long)B->ctx);
    if (B->total) fprintf(f, " 보관=%u/%u", B->total, B->max);
    fprintf(f, " --\n");
    for (int i = 0; i < B->n; i++)
        fprintf(f, "  %2d  id=%-10u cnt=%-6u fmt=\"%s\" name=\"%s\"\n",
                i + 1, B->it[i].id, B->it[i].cnt, B->it[i].fmt,
                B->it[i].nm[0] ? B->it[i].nm : "?");
}

static void printDiff(FILE *f, int li){
    const SLIST *A = &g_prev[li], *B = &g_cur[li];
    for (int i = 0; i < B->n; i++){
        int k = -1;
        for (int j = 0; j < A->n; j++) if (A->it[j].id == B->it[i].id) { k = j; break; }
        if (k < 0)
            fprintf(f, "  [%s+] id=%-10u cnt=%-6u name=\"%s\"\n", L_TAG[li], B->it[i].id, B->it[i].cnt, B->it[i].nm);
        else if (A->it[k].cnt != B->it[i].cnt)
            fprintf(f, "  [%s~] id=%-10u cnt %u -> %u name=\"%s\"\n", L_TAG[li], B->it[i].id, A->it[k].cnt, B->it[i].cnt, B->it[i].nm);
    }
    for (int j = 0; j < A->n; j++){
        int k = -1;
        for (int i = 0; i < B->n; i++) if (B->it[i].id == A->it[j].id) { k = i; break; }
        if (k < 0)
            fprintf(f, "  [%s-] id=%-10u cnt=%-6u name=\"%s\"\n", L_TAG[li], A->it[j].id, A->it[j].cnt, A->it[j].nm);
    }
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg  = lcreg_resolve("10_5/registry/LC930_REGISTRY.txt", "registry/LC930_REGISTRY.txt");
    const char *outp = lcreg_outpath("storelist_930_out.txt");
    int secs = 0, verbose = 0;
    for (int i = 1; i < argc; i++){
        if (!strcmp(argv[i], "-v")){ verbose = 1; continue; }
        if (strstr(argv[i], ".txt") || strstr(argv[i], ".out")){
            if (strstr(argv[i], "REGISTRY")) reg = argv[i]; else outp = argv[i];
        } else if (atoi(argv[i]) > 0 && !strchr(argv[i], '.')) secs = atoi(argv[i]);
    }
    lcreg_load(reg); lc_reg_apply();

    RG_ARVA     = lcreg_u32("MSG_ANCHOR_RVA", 0x16687B8);
    RG_MASK     = lcreg_u32("MSG_BUCKET_MASK", 0xFFFF);
    RG_STRIDE   = lcreg_u32("MSG_BUCKET_STRIDE", 0x10);
    RG_NEXT     = lcreg_u32("MSG_REC_NEXT", 0x00);
    RG_RECNAME  = lcreg_u32("MSG_REC_NAME", 0x38);
    RG_NAMEKR   = lcreg_u32("MSG_NAME_KR", 0x00);
    RG_NODETEXT = lcreg_u32("MSG_NODE_TEXT", 0x30);
    RG_RECHDR   = lcreg_u32("OFF_REC_HDR", 0x10);
    RG_STRLEN   = lcreg_u32("OFF_STR_LEN", 0x10);
    RG_STRCAP   = lcreg_u32("OFF_STR_CAP", 0x18);
    RG_FNVOFF   = lcreg_u64("MSG_FNV_OFFSET", 0xcbf29ce484222325ULL);
    RG_FNVPRIME = lcreg_u64("MSG_FNV_PRIME", 0x100000001b3ULL);

    RG_SVFT     = lcreg_u32("VFT_STORAGE", 0x122B648);
    RG_BMVFT    = lcreg_u32("VFT_BMSTORAGE", 0x122B328);
    RG_DEP_OFF  = lcreg_u32("STORAGE_CTX_DEPOSIT", 0x28);
    RG_RET_OFF  = lcreg_u32("STORAGE_CTX_LIST", 0x38);
    RG_BDEP_OFF = lcreg_u32("BMSTORAGE_CTX_DEPOSIT", 0x28);
    RG_BRET_OFF = lcreg_u32("BMSTORAGE_CTX_LIST", 0x38);
    RG_VEC      = lcreg_u32("STORAGE_VEC_OFF", 0x20);
    RG_VECEND   = lcreg_u32("STORAGE_VEC_END", 0x28);
    RG_VECCAP   = lcreg_u32("STORAGE_VEC_CAP", 0x30);
    RG_STRIDE2  = lcreg_u32("STORAGE_ELEM_STRIDE", 0x10);
    RG_ELEMITEM = lcreg_u32("STORAGE_ELEM_ITEM", 0x8);
    RG_ITEMVFT  = lcreg_u32("ITEM_VFT", 0x12265C8);
    RG_ID       = lcreg_u32("ITEM_ID", 0x18);
    RG_COUNT    = lcreg_u32("ITEM_COUNT", 0x38);
    RG_FMT      = lcreg_u32("ITEM_FMT", 0x68);
    RG_MAXITEM  = lcreg_u32("STORAGE_MAX_ITEM", 4096);
    RG_CNT64    = lcreg_u32("STORAGE_CTX_COUNT64", 0x8);
    /* 찾기(RET) 체인 */
    RG_CTXLIST  = lcreg_u32("STORAGE_CTX_LIST", 0x38);
    RG_MAPOFF   = lcreg_u32("STORAGE_RET_MAP_OFF", 0x18);
    RG_NIL      = lcreg_u32("RET_MAP_NIL", 0x19);
    RG_KEY      = lcreg_u32("RET_MAP_KEY", 0x20);
    RG_VAL      = lcreg_u32("RET_MAP_VALUE", 0x28);
    RG_RETID    = lcreg_u32("RET_ID_OFF", 0x70);
    RG_RETCF    = lcreg_u32("RET_CNT_FLAG", 0xCA);
    RG_RETCNT   = lcreg_u32("RET_CNT_OFF", 0xCC);
    RG_RETNAME  = lcreg_u32("RET_NAME_PTR", 0x58);
    RG_TREE_L   = lcreg_u32("RET_TREE_LEFT", 0x00);
    RG_TREE_P   = lcreg_u32("RET_TREE_PARENT", 0x08);
    RG_TREE_R   = lcreg_u32("RET_TREE_RIGHT", 0x10);
    RG_PREFKR   = (int)lcreg_u32("NAME_PREFER_KR", 1);
    snprintf(RG_STRCSV, sizeof RG_STRCSV, "%s",
        lcreg_resolve(lcreg_str("ITEM_NAME_CSV", "data/item_name_kr.csv"),
                      lcreg_str("ITEM_NAME_DIST", "data/item_name_kr.csv")));
    loadStrings(RG_STRCSV);

    if (lc_attach()) return 1;
    if (!lc_anchor()) return 2;
    lcreg_mkdir_for(outp);
    FILE *f = fopen(outp, "w");
    if (!f) return 4;
    fprintf(f, "# storelist_930 registry=%s\n", reg);
    fprintf(f, "# [DEP]=개인 창고 맡기기  [RET]=개인 창고 찾기  [BDEP]/[BRET]=혈맹 창고\n");
    fprintf(f, "# chain DEP: sub(vft)=lc_subsGet → ctx=*(sub+0x%X) → vector @ ctx+0x%X/0x%X stride 0x%X item@0x%X\n",
            RG_DEP_OFF, RG_VEC, RG_VECEND, RG_STRIDE2, RG_ELEMITEM);
    fprintf(f, "# chain RET: ctx=*(sub+0x%X) → map=*(ctx+0x%X) → node(_Isnil@0x%X,key@0x%X,val@0x%X)\n",
            RG_CTXLIST, RG_MAPOFF, RG_NIL, RG_KEY, RG_VAL);
    fprintf(f, "#            value: ID@0x%X 수량@0x%X 이름std::string@0x%X\n",
            RG_RETID, RG_RETCNT, RG_RETNAME);

    DWORD t0 = GetTickCount();
    int first = 1;
    do {
        lc_pgc_reset();
        uint64_t subP = lc_subsGet(RG_SVFT);
        uint64_t subB = lc_subsGet(RG_BMVFT);

        readList(&g_cur[L_DEP],  subP, RG_DEP_OFF);
        readRet (&g_cur[L_RET],  subP);
        readList(&g_cur[L_BDEP], subB, RG_BDEP_OFF);
        readList(&g_cur[L_BRET], subB, RG_BRET_OFF);

        fprintf(f, "\n## cycle t=%ums personal=0x%llX pledge=0x%llX ioctl=%llu\n",
                (unsigned)(GetTickCount() - t0),
                (unsigned long long)subP, (unsigned long long)subB, g_ioctl);

        /* active = 실제 항목이 있는 검증 슬롯(DEP/BDEP)만. RET/BRET(ctx +0x38)은 미확정. */
        const char *active = "none";
        for (int li = 0; li < NLIST; li++){
            if (li != L_DEP && li != L_BDEP) continue;
            if (g_cur[li].n > 0) { active = L_TAG[li]; break; }
        }
        fprintf(f, "# active=%s  ctx: dep=%d ret=%d bdep=%d bret=%d  n: DEP=%d RET=%d BDEP=%d BRET=%d\n",
                active,
                g_cur[L_DEP].ctx != 0, g_cur[L_RET].ctx != 0,
                g_cur[L_BDEP].ctx != 0, g_cur[L_BRET].ctx != 0,
                g_cur[L_DEP].n, g_cur[L_RET].n, g_cur[L_BDEP].n, g_cur[L_BRET].n);
        if (verbose)
            fprintf(f, "# RET state: ctx=0x%llX map=0x%llX leftmost=0x%llX (empty=%d)\n",
                    (unsigned long long)g_cur[L_RET].ctx, (unsigned long long)g_retMap,
                    (unsigned long long)g_retRoot,
                    (g_retMap && isNilNode(g_retRoot)) ? 1 : 0);

        int changed = first;
        if (!first) for (int li = 0; li < NLIST; li++) if (!sameList(&g_prev[li], &g_cur[li])) changed = 1;

        for (int li = 0; li < NLIST; li++){
            if (!g_cur[li].n) continue;
            if (changed || verbose) printList(f, li);
            else if (!first) printDiff(f, li);
        }

        for (int li = 0; li < NLIST; li++) g_prev[li] = g_cur[li];
        first = 0;
        fflush(f);
        lcapi_sample(f);
        if (secs) Sleep(lcreg_u32("POLL_STORAGE_INTERVAL_MS", 500));
    } while (!lcapi_done() && secs && (int)(GetTickCount() - t0) < secs * 1000);

    fclose(f); SignedClose();
    printf("done -> %s\n", outp);
    return 0;
}
