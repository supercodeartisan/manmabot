/* inventory_930.c — 인벤토리 읽기 정본 모듈 (10_5 규격)
 * ---------------------------------------------------------------------------
 *  대원칙:
 *    1) 고정앵커  : InventorySubsystem = lc_subsGet(VFT_INVENTORY)   (vft 식별)
 *    2) 고정체인  : items = vector<ItemEntity*> @ sub + INV_VEC_BEG(begin/end/cap)
 *    3) 항목검증  : *(item) == g_base + ITEM_VFT   (vft 서명검증)
 *    4) MmCopy단일: lcore 의 rm() 만 사용
 *    5) 상수외부   : 모든 상수/경로는 registry 단일출처. 코드 하드코딩 없음.
 *    6) 읽기최소   : 벡터 1회 + 아이템당 소수 reads. POLL_INVENTORY_*.
 *  usage: inventory_930.exe [registry] [secs] [out.txt]
 *  출력: 10_5/out/inventory_out.txt (고정)
 *
 *  아이템 레코드(vft=ITEM_VFT):
 *    +ITEM_ID  아이템ID | +ITEM_TEMPLATE | +ITEM_CFG | +ITEM_COUNT 수량
 *    +ITEM_ENCHANT 인챈트 | +ITEM_KIND 종류 | +ITEM_FMT 표시문자열("$NNN")
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
static uint32_t RG_INVVFT, RG_BEG, RG_END, RG_CAP, RG_ITEMVFT;
static uint32_t RG_ID, RG_TMPL, RG_CFG, RG_COUNT, RG_ENCH, RG_KIND, RG_FMT, RG_RECHDR, RG_STRLEN, RG_STRCAP, RG_SSOMAX;
static char     RG_STRCSV[256];

/* ── 이름표 (string.csv: ID,EP,TYPE,KR,...) ───────────────────────────── */
static int  s_id[40000]; static char s_kr[40000][160]; static int s_n = 0;
static const char *strName(int id){ for (int i=0;i<s_n;i++) if(s_id[i]==id) return s_kr[i]; return 0; }
static void loadStrings(const char *p){
    FILE *g=fopen(p,"rb"); if(!g){ fprintf(stderr,"[inv] strings not found: %s\n",p); return; }
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
/* "$NNN" 표시문자열에서 이름ID 추출 → string.csv 이름
 *   접두사/보정값이 붙어도("+4 $168 ($117)", "+0 $93 (1,435)") 첫 "$NNN" 을 사용한다. */
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

/* ── 메시지 테이블 이름 해석 (FNV1a 버킷 + "1_<mid>" SSO 키) ─────────────
 *   anchor = *(BASE + MSG_ANCHOR_RVA); idx=FNV1a("1_<mid>")&MASK;
 *   rec=*(anchor+idx*STRIDE); while recMid!=mid: rec=*(rec+NEXT);
 *   name = readSSO(*(*(rec+REC_NAME)+NAME_KR)+NODE_TEXT) */
static uint32_t RG_ARVA, RG_MASK, RG_STRIDE, RG_NEXT, RG_RECNAME, RG_NAMEKR, RG_NODETEXT, RG_NODELANG;
static uint64_t RG_FNVOFF, RG_FNVPRIME;

/* ── 묶음호출(페이지 배치) helper — lcore 의 lc_pgRead 경유 ──────────────
 * 같은 4KB 페이지 안의 read 를 1콜로 합치고, 같은 페이지 재방문은 캐시로
 * 0콜 처리한다. 사이클 시작에 lc_pgc_reset() 으로 초기화한다. */
static int      pgrm (uint64_t a, void*b, uint32_t s){ return lc_pgRead(a,b,s); }
static uint64_t pgq64(uint64_t a){ uint64_t v=0; lc_pgRead(a,&v,8); return v; }

/* ── mid→이름 캐시 (10_8 배치화의 누락분 보완: 이름 재해석 제거) ─────────
 * 아이템/스킬 이름은 정적이므로 최초 1회만 해석하면 이후 0콜. */
static uint32_t NC_mid[2048]; static char NC_nm[2048][128]; static int NC_n=0;
static const char* ncFind(uint32_t mid){ for(int i=0;i<NC_n;i++) if(NC_mid[i]==mid) return NC_nm[i]; return 0; }
static void ncAdd(uint32_t mid,const char* nm){ if(NC_n>=2048) return; NC_mid[NC_n]=mid; snprintf(NC_nm[NC_n],128,"%s",nm); NC_n++; }

static int readSso(uint64_t a, char* out, int outSz){
    uint8_t h[0x20];
    if(outSz<2 || !pgrm(a,h,sizeof(h))) return -1;
    uint64_t size=*(uint64_t*)(h+RG_STRLEN), cap=*(uint64_t*)(h+RG_STRCAP);
    if(size==0||size>0x300||cap>0x100000) return -1;
    if((int)size>=outSz) size=outSz-1;
    if(cap<=0xF) memcpy(out,h,(size_t)size);
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
    uint64_t rec=pgq64(anchor+(fnv1aKey(mid)&RG_MASK)*RG_STRIDE);
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

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char* reg=lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    const char* outp=lcreg_outpath("inventory_out.txt");
    int secs=0;
    { int seenReg=0;
      for(int i=1;i<argc;i++){
        if(strstr(argv[i],".txt")||strstr(argv[i],".out")){
          if(!seenReg && strstr(argv[i],"REGISTRY")){ reg=argv[i]; seenReg=1; } else { outp=argv[i]; }
        } else if(atoi(argv[i])>0 && !strstr(argv[i],".")){ secs=atoi(argv[i]); }
      }
    }
    lcreg_load(reg); lc_reg_apply();
    RG_INVVFT = lcreg_u32("INV_VFT", 0x12079A0);
    RG_BEG    = lcreg_u32("INV_VEC_BEG", 0x3D8);
    RG_END    = lcreg_u32("INV_VEC_END", 0x3E0);
    RG_CAP    = lcreg_u32("INV_VEC_CAP", 0x3E8);
    RG_ITEMVFT= lcreg_u32("ITEM_VFT", 0x1207430);
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
    snprintf(RG_STRCSV, sizeof(RG_STRCSV), "%s",
        lcreg_resolve(lcreg_str("STRINGS_CSV","T3_maps/dec/data_string.csv.lcf.out.plain"),
                      lcreg_str("STRINGS_DIST","data/data_string.csv.lcf.out.plain")));
    /* 메시지 테이블(FNV 앵커) */
    RG_ARVA   = lcreg_u32("MSG_ANCHOR_RVA", 0x16687B8);
    RG_MASK   = lcreg_u32("MSG_BUCKET_MASK", 0xFFFF);
    RG_STRIDE = lcreg_u32("MSG_BUCKET_STRIDE", 0x10);
    RG_NEXT   = lcreg_u32("MSG_REC_NEXT", 0x00);
    RG_RECNAME= lcreg_u32("MSG_REC_NAME", 0x38);
    RG_NAMEKR = lcreg_u32("MSG_NAME_KR", 0x00);
    RG_NODETEXT=lcreg_u32("MSG_NODE_TEXT", 0x30);
    RG_NODELANG=lcreg_u32("MSG_NODE_LANG", 0x10);
    RG_FNVOFF = lcreg_u64("MSG_FNV_OFFSET", 0xcbf29ce484222325ULL);
    RG_FNVPRIME=lcreg_u64("MSG_FNV_PRIME", 0x100000001b3ULL);
    lcreg_poll P = lcreg_poll_load("INVENTORY");

    if(lc_attach())return 1;
    loadStrings(RG_STRCSV);
    if(!lc_anchor()){ fprintf(stderr,"anchor fail\n"); return 2; }
    uint64_t itemVftAbs = g_base + RG_ITEMVFT;

    lcreg_mkdir_for(outp);
    FILE *f=fopen(outp,"w"); if(!f){ fprintf(stderr,"cannot open %s\n",outp); return 4; }
    fprintf(f,"# registry=%s strings=%d INV_VFT=%X ITEM_VFT=%X\n",
        reg, s_n, RG_INVVFT, RG_ITEMVFT);

    DWORD t0=GetTickCount();
    do{
        LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr); QueryPerformanceCounter(&q0);
        g_ioctl=0;
        lc_pgc_reset();                       /* 묶음호출: 페이지 캐시 사이클 초기화 */
        uint64_t sub = lc_subsGet(RG_INVVFT);
        int n=0;
        if(isHeap(sub)){
            uint64_t sv[3]={0,0,0}; pgrm(sub+RG_BEG,sv,sizeof sv);   /* begin/end/cap 1콜 묶음 */
            uint64_t vb=sv[0], ve=sv[1], vc=sv[2];
            fprintf(f,"t=%ums inv=0x%llX vec=[0x%llX..0x%llX cap 0x%llX]\n",
                (unsigned)(GetTickCount()-t0),(unsigned long long)sub,
                (unsigned long long)vb,(unsigned long long)ve,(unsigned long long)vc);
            if(isHeap(vb)&&isHeap(ve)&&ve>=vb && (ve-vb)<=0x40000){
                int cnt=(int)((ve-vb)/8);
                static uint8_t vbuf[4096];
                for(int base=0; base<cnt; ){
                    int c=((cnt-base)>512)?512:(cnt-base);
                    if(!pgrm(vb+(uint64_t)base*8,vbuf,c*8)) break;   /* 벡터 포인터 1콜/청크 */
                    for(int k=0;k<c;k++){
                        int i=base+k;
                        uint64_t it; memcpy(&it,vbuf+(uint64_t)k*8,8); if(!isHeap(it)) continue;
                        uint8_t ih[0x50]; if(!pgrm(it,ih,sizeof ih)) continue;   /* 아이템헤더 1콜 */
                        uint64_t vfp; memcpy(&vfp,ih,8);
                        if(!isMod(vfp)||(uint32_t)(vfp-g_base)!=RG_ITEMVFT) continue;   /* vft 서명검증 */
                        uint32_t id,qty,en,kd;
                        memcpy(&id,ih+RG_ID,4); memcpy(&qty,ih+RG_COUNT,4);
                        memcpy(&en,ih+RG_ENCH,4); memcpy(&kd,ih+RG_KIND,4);
                        char fmt[64]={0};
                        uint8_t fh[0x20];
                        if(pgrm(it+RG_FMT,fh,sizeof fh)){
                            uint64_t len; memcpy(&len,fh+RG_STRLEN,8); uint64_t cap; memcpy(&cap,fh+RG_STRCAP,8);
                            if(len>0&&len<40){ if((int)len>=63)len=63;
                                if(cap<=0xF) memcpy(fmt,fh,(size_t)len);
                                else { uint64_t p; memcpy(&p,fh,8); if(isHeap(p)) pgrm(p,fmt,(uint32_t)len); }
                                fmt[len]=0;
                            }
                        }
                        int nmid=fmtNameId(fmt); char nm[128]={0};
                        if(nmid){
                            const char* cch=ncFind(nmid);
                            if(cch) snprintf(nm,sizeof(nm),"%s",cch);      /* 캐시 hit → 0콜 */
                            else { if(!msgName(nmid,nm,sizeof(nm))){ const char* s=strName(nmid); if(s) snprintf(nm,sizeof(nm),"%s",s); }
                                   if(nm[0]) ncAdd(nmid,nm); }
                        }
                        fprintf(f,"  [%2d] id=%-6u cnt=%-6u ench=%-3u kind=%-3u fmt=\"%s\" name=%s\n",
                            i,id,qty,en,kd,fmt,nm[0]?nm:"(?)");
                        n++;
                    }
                    base+=c;
                }
            }
        } else fprintf(f,"t=%ums InventorySubsystem not found\n",(unsigned)(GetTickCount()-t0));
        QueryPerformanceCounter(&q1);
        fprintf(f,"# n=%d ioctl=%llu time=%.4fms\n",n,g_ioctl,(q1.QuadPart-q0.QuadPart)*1000.0/fr.QuadPart);
        fflush(f);
        lcapi_sample(f);
        if(secs) Sleep(lcreg_poll_sleep_ms(&P));
    } while(!lcapi_done() && secs && (int)(GetTickCount()-t0)<secs*1000);

    fclose(f); SignedClose(); printf("done -> %s\n",outp); return 0;
}
