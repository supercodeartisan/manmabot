/* storage_930.c — 창고 아이템 읽기 정본 모듈 (10_5 규격)
 * ---------------------------------------------------------------------------
 *  목적: 창고(개인)와 혈맹창고의 **맡기기/찾기 목록을 동시에** 읽고,
 *        슬롯별 스냅샷 diff 로 **아이템 이동 이벤트(입고/출고)** 를 출력한다.
 *
 *  대원칙:
 *    1) 고정앵커  : StorageSubsystem = lc_subsGet(VFT_STORAGE)
 *                   BMStorageSubsystem = lc_subsGet(VFT_BMSTORAGE)   (혈맹창고)
 *    2) 고정체인  : ctx = *(sub + STORAGE_CTX_DEPOSIT|LIST)
 *                   ctx + STORAGE_COUNT_OFF = 아이템 개수(u64)
 *                   ctx + STORAGE_VEC_* = vector<shared_ptr<ItemEntity>>
 *    3) 항목검증  : 원소 16B, item @ 원소 + STORAGE_ELEM_ITEM ; *(item) == g_base + ITEM_VFT
 *    4) MmCopy단일: lcore 의 rm() / lc_pgRead() 만 사용
 *    5) 상수외부   : 모든 상수/경로는 registry 단일출처. 코드 하드코딩 없음.
 *    6) 읽기최소   : 헤더 1콜 + 원소배열 1콜(청크) + 아이템헤더 n(페이지 배치).
 *
 *  슬롯(4):
 *    0 NPC.dep   = StorageSubsystem   + STORAGE_CTX_DEPOSIT   (창고 맡기기창)
 *    1 NPC.list  = StorageSubsystem   + STORAGE_CTX_LIST      (창고 목록창 = 찾기)
 *    2 BM.dep    = BMStorageSubsystem + BMSTORAGE_CTX_DEPOSIT (혈맹창고 맡기기창)
 *    3 BM.list   = BMStorageSubsystem + BMSTORAGE_CTX_LIST    (혈맹창고 목록창)
 *  ctx 는 창 열림 시 생성 / 닫힘 시 소멸 → 닫혀 있으면 n=0.
 *
 *  이벤트: STORAGE_EVENTS=1 이면 슬롯별 이전 스냅샷과 비교해
 *          [IN](신규) / [OUT](소멸) / [CHG](수량변화) 를 출력한다.
 *          슬롯이 닫히면(ctx null) 이벤트를 내지 않는다(다음 열림에서 전량 [IN]).
 *
 *  usage: storage_930.exe [registry] [secs] [out.txt] [-list] [-open] [-events]
 *    -list   : 매 주기 슬롯 전체 목록도 출력(기본은 요약+이벤트만)
 *    -events : 이동이벤트 강제 ON (기본 registry STORAGE_EVENTS)
 *  출력: <EXE>\out\storage_out.txt
 *
 *  아이템 레코드(vft=ITEM_VFT): inventory 와 동일 오프셋.
 *    +ITEM_ID | +ITEM_TEMPLATE | +ITEM_CFG | +ITEM_COUNT
 *    +ITEM_ENCHANT | +ITEM_KIND | +ITEM_FMT("$NNN")
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
static uint32_t RG_SVFT, RG_BMVFT, RG_CTXDEP, RG_CTXLIST, RG_BMDEP, RG_BMLIST;
static uint32_t RG_VEC, RG_VECEND, RG_VECCAP, RG_CNT;
static uint32_t RG_STRIDE, RG_ELEMITEM, RG_ITEMVFT;
static uint32_t RG_ID, RG_TMPL, RG_CFG, RG_COUNT, RG_ENCH, RG_KIND, RG_FMT, RG_RECHDR, RG_STRLEN, RG_STRCAP, RG_SSOMAX;
static char     RG_STRCSV[256];
static uint32_t RG_MAXITEM, RG_EVENTS, RG_LISTFULL, RG_SNAPMAX, RG_CNT64;
static uint32_t RG_RET_HEAD, RG_RET_VAL, RG_RET_NIL, RG_RET_ID, RG_RET_FMT, RG_TL, RG_TP, RG_TR;

/* ── 묶음호출(페이지 배치) helper — lcore 의 lc_pgRead 경유 ────────────── */
static int      pgrm (uint64_t a, void*b, uint32_t s){ return lc_pgRead(a,b,s); }
static uint64_t pgq64(uint64_t a){ uint64_t v=0; lc_pgRead(a,&v,8); return v; }

/* ── 슬롯 스냅샷 ──────────────────────────────────────────────────────── */
#define ST_SLOTS 4
#define ST_SNAP_MAX 512

typedef struct { uint32_t id, tmpl, cfg, cnt, ench, kind; char name[96]; char fmt[48]; } StRec;
typedef struct { uint64_t ctx; int n; uint32_t total, max; StRec r[ST_SNAP_MAX]; } StSnap;

static StSnap   g_cur[ST_SLOTS], g_prev[ST_SLOTS];
static uint32_t SLOT_CTXOFF[ST_SLOTS];
static const char* ST_TAG[ST_SLOTS] = { "NPC.dep", "NPC.ret", "BM.dep", "BM.ret" };

/* ── 이름표 (string.csv: ID,EP,TYPE,KR,...) ───────────────────────────── */
static int  RG_PREFKR = 1;   /* 1=한글 사전(STRINGS) 우선, 0=메모리 이름 우선 */
static int  s_id[40000]; static char s_kr[40000][160]; static int s_n = 0;
static const char *strName(int id){
    for (int i=0;i<s_n;i++) if(s_id[i]==id){
        const char *v=s_kr[i];
        if(!v[0] || !strncmp(v,"desc",4) || !strncmp(v,"string",6)) return 0;
        return v;
    }
    return 0;
}
static void loadStrings(const char *p){
    FILE *g=fopen(p,"rb"); if(!g){ fprintf(stderr,"[storage] strings not found: %s\n",p); return; }
    char *raw=(char*)malloc(2<<20); if(!raw){ fclose(g); return; }
    int n=(int)fread(raw,1,2<<20,g); fclose(g); raw[n]=0;
    char *s=raw;
    if((unsigned char)s[0]==0xEF&&(unsigned char)s[1]==0xBB&&(unsigned char)s[2]==0xBF) s+=3;
    while(*s){ char *e=strchr(s,'\n'); if(e)*e=0;
        char *cm=strchr(s,','); if(cm){ int id=atoi(s);
            if(id>0){ char *p1=strchr(cm+1,','), *p2=p1?strchr(p1+1,','):0;
                if(p2){ char *kr=p2+1, *buf=s_kr[s_n]; int bi=0,inq=0; if(*kr=='"'){inq=1;kr++;}
                    while(*kr&&bi<159){ if(inq){ if(*kr=='"')break; } else { if(*kr==',')break; } buf[bi++]=*kr++; }
                    buf[bi]=0; s_id[s_n]=id; s_n++; if(s_n>=40000) break; } } }
        if(!e) break; s=e+1; }
    free(raw);
}
/* "$NNN" 표시문자열에서 이름ID 추출 (접두사/보정값 허용: 첫 "$NNN" 사용) */
static int fmtNameId(const char *fmt){
    if(!fmt) return 0;
    for(const char *p=fmt; *p; p++){
        if(*p!='$') continue;
        const char *q=p+1;
        if(*q<'0'||*q>'9') continue;
        int v=0; while(*q>='0'&&*q<='9'){ v=v*10+(*q-'0'); q++; }
        if(v>0) return v;
    }
    return 0;
}

/* ── 메시지 테이블 이름 해석 (FNV1a 버킷 + "1_<mid>" SSO 키) ───────────── */
static uint32_t RG_ARVA, RG_MASK, RG_STRIDE2, RG_NEXT, RG_RECNAME, RG_NAMEKR, RG_NODETEXT, RG_NODELANG;
static uint64_t RG_FNVOFF, RG_FNVPRIME;

static int readSso(uint64_t a, char* out, int outSz){
    uint8_t h[0x20];
    if(outSz<2 || !pgrm(a,h,sizeof(h))) return -1;
    uint64_t size=*(uint64_t*)(h+RG_STRLEN), cap=*(uint64_t*)(h+RG_STRCAP);
    if(size==0||size>0x300||cap>0x100000) return -1;
    if((int)size>=outSz) size=outSz-1;
    if(cap<RG_SSOMAX) memcpy(out,h,(size_t)size);
    else { uint64_t p=*(uint64_t*)h; if(!isHeap(p)||!pgrm(p,out,(uint32_t)size)) return -1; }
    out[size]=0; return (int)size;
}
static uint64_t fnv1aKey(uint32_t mid){
    char s[24]; int n=snprintf(s,sizeof(s),"1_%u",mid);
    uint64_t h=RG_FNVOFF; for(int i=0;i<n;i++){ h^=(unsigned char)s[i]; h*=RG_FNVPRIME; } return h;
}
static uint32_t recMidOf(uint64_t rec){
    uint8_t h[0x20]; if(!pgrm(rec+RG_RECHDR,h,sizeof(h))) return 0;
    if(h[0]!='1'||h[1]!='_') return 0;
    uint64_t size=*(uint64_t*)(h+RG_STRLEN); if(size<3||size>12) return 0;
    uint32_t m=0; for(uint64_t i=2;i<size;i++){ if(h[i]<'0'||h[i]>'9') return 0; m=m*10+(h[i]-'0'); }
    return m;
}
static int msgName(uint32_t mid, char* out, int outSz){
    if(!RG_ARVA) return 0;
    uint64_t anchor=pgq64(g_base+RG_ARVA); if(!isHeap(anchor)) return 0;
    uint64_t rec=pgq64(anchor+(fnv1aKey(mid)&RG_MASK)*RG_STRIDE2);
    for(int steps=0; isHeap(rec)&&steps<64; steps++){
        if(recMidOf(rec)==mid){
            uint64_t nxt=pgq64(rec+RG_RECNAME); if(!isHeap(nxt)) return 0;
            uint64_t kr=pgq64(nxt+RG_NAMEKR); if(!isHeap(kr)) return 0;
            return readSso(kr+RG_NODETEXT,out,outSz)>0;
        }
        uint64_t nx=pgq64(rec+RG_NEXT); if(nx==rec) break; rec=nx;
    }
    return 0;
}
/* mid→이름 캐시 (정적 이름 재해석 제거) */
static uint32_t NC_mid[2048]; static char NC_nm[2048][128]; static int NC_n=0;
static const char* ncFind(uint32_t mid){ for(int i=0;i<NC_n;i++) if(NC_mid[i]==mid) return NC_nm[i]; return 0; }
static void ncAdd(uint32_t mid,const char* nm){ if(NC_n>=2048) return; NC_mid[NC_n]=mid; snprintf(NC_nm[NC_n],128,"%s",nm); NC_n++; }

/* ── [RET] 찾기 목록: std::map<int, ItemInfo@LIN> (10/21 신빌드 실측) ────
 *   head=*(ctx+0x18), node: _Isnil@0x19, value(ItemInfo)@0x28
 *   ItemInfo: ID@0x70(u32), FMT(태그된 std::string*)@0x58 → "$<mid> (<수량>)"
 */
static int isNilU(uint64_t n){
    uint8_t b = 1;
    if (!pgrm(n + RG_RET_NIL, &b, 1)) return 1;
    return b != 0;
}
static uint64_t treeNextU(uint64_t node){
    uint64_t r = pgq64(node + RG_TR);
    if (isHeap(r) && !isNilU(r)){
        node = r;
        for (int g = 0; g < 64; g++){
            uint64_t l = pgq64(node + RG_TL);
            if (!isHeap(l) || isNilU(l)) break;
            node = l;
        }
        return node;
    }
    uint64_t p = pgq64(node + RG_TP);
    for (int g = 0; g < 64 && isHeap(p) && !isNilU(p); g++){
        if (node != pgq64(p + RG_TR)) break;
        node = p; p = pgq64(p + RG_TP);
    }
    return p;
}
static int fmtCountOf(const char *fmt){
    for (const char *p = fmt; *p; p++){
        if (*p != '(') continue;
        int v = atoi(p + 1);
        return v > 0 ? v : 1;
    }
    return 1;
}
static int readRetMap(int s, uint64_t ctx){
    StSnap* o = &g_cur[s];
    uint64_t head = pgq64(ctx + RG_RET_HEAD);
    if (!isHeap(head)) return 0;
    uint64_t node = pgq64(head);                    /* leftmost */
    for (int guard = 0; isHeap(node) && !isNilU(node) && o->n < (int)RG_SNAPMAX && guard < 4096; guard++){
        uint64_t val = node + RG_RET_VAL;
        uint8_t b4[4];
        if (!pgrm(val + RG_RET_ID, b4, 4)) break;
        StRec* R = &o->r[o->n];
        memset(R, 0, sizeof *R);
        memcpy(&R->id, b4, 4);
        char fmt[96]; fmt[0] = 0;
        uint64_t np = pgq64(val + RG_RET_FMT) & ~(uint64_t)3;
        if (isHeap(np)){
            uint8_t sh[0x20];
            if (pgrm(np, sh, sizeof sh)){
                uint64_t sz = *(uint64_t*)(sh + RG_STRLEN), cp = *(uint64_t*)(sh + RG_STRCAP);
                if (sz > 0 && sz < sizeof fmt && cp >= sz && cp <= 0x10000){
                    if (cp <= 0xF) memcpy(fmt, sh, (size_t)sz);
                    else { uint64_t p = *(uint64_t*)sh; if (isHeap(p)) pgrm(p, fmt, (uint32_t)sz); }
                    fmt[sz] = 0;
                }
            }
        }
        R->cnt = (uint32_t)fmtCountOf(fmt);
        snprintf(R->fmt, sizeof R->fmt, "%s", fmt);
        uint32_t mid = fmtNameId(fmt);
        if (mid){
            const char* c = ncFind(mid);
            if (c) snprintf(R->name, sizeof(R->name), "%s", c);
            else { const char* q = RG_PREFKR ? strName(mid) : 0;   /* 한글 사전 우선 */
                   if (q) snprintf(R->name, sizeof(R->name), "%s", q);
                   else if (!msgName(mid, R->name, sizeof(R->name))){ q = strName(mid); if (q) snprintf(R->name, sizeof(R->name), "%s", q); }
                   if (R->name[0]) ncAdd(mid, R->name); }
        }
        o->n++;
        node = treeNextU(node);
    }
    return o->n;
}

/* ── 슬롯 1개 읽기 ────────────────────────────────────────────────────── */
static int readSlot(int s, uint64_t sub)
{
    StSnap* o=&g_cur[s]; o->n=0; o->ctx=0; o->total=0; o->max=0;
    if(!isHeap(sub)) return 0;
    uint64_t ctx=pgq64(sub+SLOT_CTXOFF[s]);
    if(!isHeap(ctx)) return 0;
    o->ctx=ctx;
    /* ctx+0x8 = u32 total / u32 max ("보관 29/100") */
    { uint64_t cm=pgq64(ctx+RG_CNT64);
      uint32_t t=(uint32_t)cm, mx=(uint32_t)(cm>>32);
      if(t && mx && t<=mx && mx<=RG_MAXITEM){ o->total=t; o->max=mx; } }
    uint8_t hb[0x38]; uint32_t need=RG_VECCAP+8; if(need>sizeof hb) need=sizeof hb;
    if(!pgrm(ctx,hb,need)) return 0;                       /* 헤더 1콜 */
    uint64_t vb,ve; memcpy(&vb,hb+RG_VEC,8); memcpy(&ve,hb+RG_VECEND,8);
    if(!(isHeap(vb)&&isHeap(ve)&&ve>=vb)) return readRetMap(s,ctx);   /* RET=map */
    uint64_t bytes=ve-vb; if(bytes > (uint64_t)0x10000*RG_STRIDE) return 0;
    int m=(int)(bytes/RG_STRIDE); if(m>(int)RG_MAXITEM) m=RG_MAXITEM; if(m>(int)RG_SNAPMAX) m=(int)RG_SNAPMAX;
    static uint8_t ebuf[8192];
    for(int base=0; base<m && o->n<(int)RG_SNAPMAX; ){
        int c=((m-base)>512)?512:(m-base);
        if(!pgrm(vb+(uint64_t)base*RG_STRIDE,ebuf,c*RG_STRIDE)) break;   /* 원소배열 1콜/청크 */
        for(int k=0;k<c;k++){
            int i=base+k;
            uint64_t it; memcpy(&it,ebuf+(uint64_t)k*RG_STRIDE+RG_ELEMITEM,8);
            if(!isHeap(it)) continue;
            uint8_t ih[0x50]; if(!pgrm(it,ih,sizeof ih)) continue;        /* 아이템헤더 1콜 */
            uint64_t vfp; memcpy(&vfp,ih,8);
            if(!isMod(vfp)||(uint32_t)(vfp-g_base)!=RG_ITEMVFT) continue; /* vft 서명검증 */
            StRec* R=&o->r[o->n];
            memcpy(&R->id  ,ih+RG_ID     ,4); memcpy(&R->cnt ,ih+RG_COUNT,4);
            memcpy(&R->ench,ih+RG_ENCH   ,4); memcpy(&R->kind,ih+RG_KIND ,4);
            memcpy(&R->tmpl,ih+RG_TMPL   ,4); memcpy(&R->cfg ,ih+RG_CFG  ,4);
            R->fmt[0]=0; R->name[0]=0;
            uint8_t fh[0x20];
            if(pgrm(it+RG_FMT,fh,sizeof fh)){
                uint64_t len; memcpy(&len,fh+RG_STRLEN,8); uint64_t cap; memcpy(&cap,fh+RG_STRCAP,8);
                if(len>0&&len<47){ if((int)len>=47)len=47;
                    if(cap<RG_SSOMAX) memcpy(R->fmt,fh,(size_t)len);
                    else { uint64_t p; memcpy(&p,fh,8); if(isHeap(p)) pgrm(p,R->fmt,(uint32_t)len); }
                    R->fmt[len]=0;
                }
            }
            int nmid=fmtNameId(R->fmt);
            if(nmid){
                const char* cch=ncFind(nmid);
                if(cch) snprintf(R->name,sizeof(R->name),"%s",cch);
                else { const char* q = RG_PREFKR ? strName(nmid) : 0;   /* 한글 사전 우선 */
                       if(q) snprintf(R->name,sizeof(R->name),"%s",q);
                       else if(!msgName(nmid,R->name,sizeof(R->name))){ q=strName(nmid); if(q) snprintf(R->name,sizeof(R->name),"%s",q); }
                       if(R->name[0]) ncAdd(nmid,R->name); }
            }
            o->n++;
            (void)i;
            if(o->n>=(int)RG_SNAPMAX) break;
        }
        base+=c;
    }
    return o->n;
}

/* ── 이벤트(diff) ─────────────────────────────────────────────────────── */
static int stFind(const StSnap* S, uint32_t id){ for(int i=0;i<S->n;i++) if(S->r[i].id==id) return i; return -1; }
static void emitRec(FILE*f,const char*verb,const char*tag,const StRec*R){
    fprintf(f,"  [%s] %-8s id=%-10u tmpl=%-6u cfg=%-6u cnt=%-6u ench=%-3u kind=%-4u fmt=\"%s\" name=%s\n",
        verb,tag,R->id,R->tmpl,R->cfg,R->cnt,R->ench,R->kind,R->fmt,R->name[0]?R->name:"(?)");
}
static int diffSlot(FILE*f,int s){
    const StSnap* A=&g_prev[s]; const StSnap* B=&g_cur[s]; int ev=0;
    if(!B->ctx){ g_prev[s].n=0; g_prev[s].ctx=0; return 0; }   /* 창 닫힘: 이벤트 없음 */
    for(int i=0;i<B->n;i++){
        int j=stFind(A,B->r[i].id);
        if(j<0){ emitRec(f,"IN ",ST_TAG[s],&B->r[i]); ev++; }
        else if(A->r[j].cnt!=B->r[i].cnt){ emitRec(f,"CHG",ST_TAG[s],&B->r[i]); ev++; }
    }
    for(int j=0;j<A->n;j++) if(stFind(B,A->r[j].id)<0){ emitRec(f,"OUT",ST_TAG[s],&A->r[j]); ev++; }
    g_prev[s]=B[0];
    return ev;
}
static void dumpSlot(FILE*f,int s){
    const StSnap* B=&g_cur[s];
    fprintf(f,"  * %s (n=%d ctx=0x%llX)\n",ST_TAG[s],B->n,(unsigned long long)B->ctx);
    for(int i=0;i<B->n;i++) emitRec(f,"..",ST_TAG[s],&B->r[i]);
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char* reg=lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    const char* outp=lcreg_outpath("storage_out.txt");
    int secs=0, cliList=0, cliEvents=0;
    { int seenReg=0;
      for(int i=1;i<argc;i++){
        if(!strcmp(argv[i],"-list")){ cliList=1; continue; }
        if(!strcmp(argv[i],"-events")){ cliEvents=1; continue; }
        if(!strcmp(argv[i],"-open")){ continue; }
        if(strstr(argv[i],".txt")||strstr(argv[i],".out")){
          if(!seenReg && strstr(argv[i],"REGISTRY")){ reg=argv[i]; seenReg=1; } else { outp=argv[i]; }
        } else if(atoi(argv[i])>0 && !strstr(argv[i],".")){ secs=atoi(argv[i]); }
      }
    }
    lcreg_load(reg); lc_reg_apply();
    RG_SVFT   = lcreg_u32("VFT_STORAGE", 0x122B648);
    RG_BMVFT  = lcreg_u32("VFT_BMSTORAGE", 0x122B328);
    RG_CTXDEP = lcreg_u32("STORAGE_CTX_DEPOSIT", 0x28);
    RG_CTXLIST= lcreg_u32("STORAGE_CTX_LIST", 0x38);
    RG_BMDEP  = lcreg_u32("BMSTORAGE_CTX_DEPOSIT", 0x28);
    RG_BMLIST = lcreg_u32("BMSTORAGE_CTX_LIST", 0x38);
    RG_VEC    = lcreg_u32("STORAGE_VEC_OFF", 0x20);
    RG_VECEND = lcreg_u32("STORAGE_VEC_END", 0x28);
    RG_VECCAP = lcreg_u32("STORAGE_VEC_CAP", 0x30);
    RG_CNT    = lcreg_u32("STORAGE_COUNT_OFF", 0x18);
    RG_CNT64  = lcreg_u32("STORAGE_CTX_COUNT64", 0x8);
    RG_RET_HEAD=lcreg_u32("STORAGE_RET_MAP_OFF", 0x18);
    RG_RET_VAL =lcreg_u32("RET_MAP_VALUE", 0x28);
    RG_RET_NIL =lcreg_u32("RET_MAP_NIL", 0x19);
    RG_RET_ID  =lcreg_u32("RET_ID_OFF", 0x70);
    RG_RET_FMT =lcreg_u32("RET_NAME_PTR", 0x58);
    RG_TL      =lcreg_u32("RET_TREE_LEFT", 0x00);
    RG_TP      =lcreg_u32("RET_TREE_PARENT", 0x08);
    RG_TR      =lcreg_u32("RET_TREE_RIGHT", 0x10);
    RG_STRIDE = lcreg_u32("STORAGE_ELEM_STRIDE", 0x10);
    RG_ELEMITEM=lcreg_u32("STORAGE_ELEM_ITEM", 0x8);
    RG_MAXITEM= lcreg_u32("STORAGE_MAX_ITEM", 4096);
    RG_EVENTS = lcreg_u32("STORAGE_EVENTS", 1);
    RG_LISTFULL=lcreg_u32("STORAGE_LIST_FULL", 0);
    RG_SNAPMAX= lcreg_u32("STORAGE_SNAP_MAX", 512);
    RG_ITEMVFT= lcreg_u32("ITEM_VFT", 0x12265C8);
    RG_ID     = lcreg_u32("ITEM_ID", 0x18);
    RG_TMPL   = lcreg_u32("ITEM_TEMPLATE", 0x20);
    RG_CFG    = lcreg_u32("ITEM_CFG", 0x30);
    RG_COUNT  = lcreg_u32("ITEM_COUNT", 0x38);
    RG_ENCH   = lcreg_u32("ITEM_ENCHANT", 0x3C);
    RG_KIND   = lcreg_u32("ITEM_KIND", 0x44);
    RG_FMT    = lcreg_u32("ITEM_FMT", 0x68);
    RG_RECHDR = lcreg_u32("OFF_REC_HDR", 0x10);
    RG_STRLEN = lcreg_u32("OFF_STR_LEN", 0x10);
    RG_STRCAP = lcreg_u32("OFF_STR_CAP", 0x18);
    RG_SSOMAX = lcreg_u32("STR_SSO_MAX", 0x10);
    RG_PREFKR = (int)lcreg_u32("NAME_PREFER_KR", 1);
    snprintf(RG_STRCSV, sizeof(RG_STRCSV), "%s",
        lcreg_resolve(lcreg_str("ITEM_NAME_CSV","data/item_name_kr.csv"),
                      lcreg_str("ITEM_NAME_DIST","data/item_name_kr.csv")));
    RG_ARVA   = lcreg_u32("MSG_ANCHOR_RVA", 0x16687B8);
    RG_MASK   = lcreg_u32("MSG_BUCKET_MASK", 0xFFFF);
    RG_STRIDE2= lcreg_u32("MSG_BUCKET_STRIDE", 0x10);
    RG_NEXT   = lcreg_u32("MSG_REC_NEXT", 0x00);
    RG_RECNAME= lcreg_u32("MSG_REC_NAME", 0x38);
    RG_NAMEKR = lcreg_u32("MSG_NAME_KR", 0x00);
    RG_NODETEXT=lcreg_u32("MSG_NODE_TEXT", 0x30);
    RG_NODELANG=lcreg_u32("MSG_NODE_LANG", 0x10);
    RG_FNVOFF = lcreg_u64("MSG_FNV_OFFSET", 0xcbf29ce484222325ULL);
    RG_FNVPRIME=lcreg_u64("MSG_FNV_PRIME", 0x100000001b3ULL);
    lcreg_poll P = lcreg_poll_load("STORAGE");

    SLOT_CTXOFF[0]=RG_CTXDEP;  SLOT_CTXOFF[1]=RG_CTXLIST;
    SLOT_CTXOFF[2]=RG_BMDEP;   SLOT_CTXOFF[3]=RG_BMLIST;
    if(cliList) RG_LISTFULL=1;
    if(cliEvents) RG_EVENTS=1;

    if(lc_attach())return 1;
    loadStrings(RG_STRCSV);
    if(!lc_anchor()){ fprintf(stderr,"anchor fail\n"); return 2; }

    lcreg_mkdir_for(outp);
    FILE *f=fopen(outp,"w"); if(!f){ fprintf(stderr,"cannot open %s\n",outp); return 4; }
    fprintf(f,"# registry=%s strings=%d VFT_STORAGE=%X VFT_BMSTORAGE=%X ITEM_VFT=%X events=%u list=%u\n",
        reg, s_n, RG_SVFT, RG_BMVFT, RG_ITEMVFT, RG_EVENTS, RG_LISTFULL);
    fprintf(f,"# slots: 0=NPC.dep(+0x%X) 1=NPC.ret(+0x%X) 2=BM.dep(+0x%X) 3=BM.ret(+0x%X)\n",
        RG_CTXDEP,RG_CTXLIST,RG_BMDEP,RG_BMLIST);

    DWORD t0=GetTickCount();
    do{
        LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr); QueryPerformanceCounter(&q0);
        g_ioctl=0;
        lc_pgc_reset();                       /* 묶음호출: 페이지 캐시 사이클 초기화 */
        uint64_t subNPC = lc_subsGet(RG_SVFT);
        uint64_t subBM  = lc_subsGet(RG_BMVFT);
        /* 4 슬롯 읽기 */
        readSlot(0,subNPC); readSlot(1,subNPC); readSlot(2,subBM); readSlot(3,subBM);
        fprintf(f,"t=%ums NPC=0x%llX dep(ctx=0x%llX n=%d/%u) list(ctx=0x%llX n=%d/%u) | BM=0x%llX dep(ctx=0x%llX n=%d/%u) list(ctx=0x%llX n=%d/%u)\n",
            (unsigned)(GetTickCount()-t0),
            (unsigned long long)subNPC,
            (unsigned long long)g_cur[0].ctx, g_cur[0].n, g_cur[0].total,
            (unsigned long long)g_cur[1].ctx, g_cur[1].n, g_cur[1].total,
            (unsigned long long)subBM,
            (unsigned long long)g_cur[2].ctx, g_cur[2].n, g_cur[2].total,
            (unsigned long long)g_cur[3].ctx, g_cur[3].n, g_cur[3].total);
        if(RG_LISTFULL){ for(int s=0;s<ST_SLOTS;s++) if(g_cur[s].n) dumpSlot(f,s); }
        if(RG_EVENTS){ int ev=0; for(int s=0;s<ST_SLOTS;s++) ev+=diffSlot(f,s);
            if(ev) fprintf(f,"  -- %d event(s)\n",ev); }
        QueryPerformanceCounter(&q1);
        fprintf(f,"# ioctl=%llu time=%.4fms\n",g_ioctl,(q1.QuadPart-q0.QuadPart)*1000.0/fr.QuadPart);
        fflush(f);
        lcapi_sample(f);
        if(secs) Sleep(lcreg_poll_sleep_ms(&P));
    } while(!lcapi_done() && secs && (int)(GetTickCount()-t0)<secs*1000);

    fclose(f); SignedClose(); printf("done -> %s\n",outp); return 0;
}

