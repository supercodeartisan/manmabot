/* lbuff.h - 공용 버프(스킬) 읽기 엔진 (header-only)  ·  (2026-10-06 재작성)
 * ===========================================================================
 *  정적/라이브 규명 결과: 활성 버프는 BuffSubsystem 의 **unordered_map** 에 있다.
 *
 *    BuffSubsystem = lc_subsGet(VFT_BUFF=0x11FC5E8)      (고정앵커, vft식별)
 *    map   = *( BuffSubsystem + BUFF_MAP_OFF(0x260) )     (std::unordered_map<u32,shared_ptr<BuffInstance>>)
 *    vec   = *( map + BUFF_VEC_OFF(0x18) )   (버킷 배열)
 *    mask  = *( map + BUFF_MASK_OFF(0x30) )
 *    end   = *( map + BUFF_END_OFF(0x08) )
 *    버킷 i: node = *( vec + 16*i + 8 ) ; node != end ; node = *( node + NODE_NEXT(0x08) )
 *    노드: key u32@+NODE_KEY(0x10), shared_ptr{_Ptr@+0x18,_Rep@+0x20}
 *          record = _Rep (vft = base+RECORD_VFT_RVA=0x11FC550) = _Ref_count_obj2<BuffInstance> 제어블록
 *    레코드/BuffInstance 필드: 캐스터 +0x10, 스킬ID +0x14, 지속 +0x18, 이름strID +0x2C, 남은초 +0x84(float)
 *
 *  ⇒ **BFS/힙그래프 순회 없음.** 앵커+고정오프셋+노드 walk(=레코드 수 비례)만.
 *  MmCopy 단일. 상수는 registry 단일출처.
 */
#ifndef LBUFF_H
#define LBUFF_H
#ifndef _CRT_SECURE_NO_WARNINGS
#define _CRT_SECURE_NO_WARNINGS
#endif
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

typedef struct { char name[160]; float remain; uint32_t skill, strid, dur; int perpet; uint64_t addr; } LBuff;

/* config (registry) */
static uint32_t B_VFT_BUFF, B_MAPOFF, B_VECOFF, B_MASKOFF, B_ENDOFF;
static uint32_t B_NODE_KEY, B_NODE_NEXT, B_NODE_REP, B_NODE_PTR;
static uint32_t B_CASTER, B_SKILL, B_DUR, B_STRID, B_REMAIN, B_REFCOUNT;
static char B_STRCSV[256];

/* name table */
static int  B_sid[40000]; static char B_skr[40000][160]; static int B_sn=0;
static char B_nmclean[192];
static const char* bname(int id){
    for(int i=0;i<B_sn;i++) if(B_sid[i]==id){
        const char* s=B_skr[i];
        /* 툴팁 문자열("이름: 설명")이면 이름 부분만 사용 */
        int k=0; while(s[k] && s[k]!=':' && s[k]!='\n' && s[k]!='\r' && k<190){
            if(s[k]=='\\' && s[k+1]=='n') break;   /* CSV의 리터럴 \\n */
            B_nmclean[k]=s[k]; k++; }
        while(k>0 && (B_nmclean[k-1]==' '||B_nmclean[k-1]=='\t')) k--;
        B_nmclean[k]=0;
        return B_nmclean;
    }
    return 0;
}
static void B_loadStrings(const char*p){
    FILE*g=fopen(p,"rb"); if(!g) return;
    char*raw=(char*)malloc(2<<20); if(!raw){fclose(g);return;}
    int n=(int)fread(raw,1,2<<20,g); fclose(g); if(n<0)n=0; raw[n]=0;
    char*s=raw; if((unsigned char)s[0]==0xEF&&(unsigned char)s[1]==0xBB&&(unsigned char)s[2]==0xBF) s+=3;
    while(*s){ char*e=strchr(s,'\n'); if(e)*e=0; char*cm=strchr(s,',');
        if(cm){ int id=atoi(s); if(id>0){ char*p1=strchr(cm+1,','); char*p2=p1?strchr(p1+1,','):0;
            if(p2){ char*kr=p2+1; char*buf=B_skr[B_sn]; int bi=0,inq=0; if(*kr=='"'){inq=1;kr++;}
                while(*kr&&bi<159){ if(inq){if(*kr=='"')break;} else {if(*kr==',')break;} buf[bi++]=*kr++; }
                buf[bi]=0; B_sid[B_sn]=id; B_sn++; if(B_sn>=40000)break; } } }
        if(!e)break; s=e+1; }
    free(raw);
}
/* reads */
static long B_reads=0;
static int  B_R(uint64_t a,void*b,uint32_t s){ B_reads++; return rm(a,b,s); }
static uint64_t B_R64(uint64_t a){ uint64_t v=0; B_reads++; rm(a,&v,8); return v; }
static uint32_t B_R32(uint64_t a){ uint32_t v=0; B_reads++; rm(a,&v,4); return v; }

static uint32_t B_recrva=0; static int B_ncache=0;
static uint32_t B_DUR_PERPET=0xFFFFFFFFu, B_DUR_MAX=1000000u;

static void lbuff_load(const char*regpath){
    (void)regpath;
    B_VFT_BUFF = lcreg_u32("VFT_BUFF", 0x11FC5E8);
    B_MAPOFF   = lcreg_u32("BUFF_MAP_OFF", 0x260);
    B_VECOFF   = lcreg_u32("BUFF_VEC_OFF", 0x18);
    B_MASKOFF  = lcreg_u32("BUFF_MASK_OFF", 0x30);
    B_ENDOFF   = lcreg_u32("BUFF_END_OFF", 0x08);
    B_NODE_KEY = lcreg_u32("BUFF_NODE_KEY", 0x10);
    B_NODE_NEXT= lcreg_u32("BUFF_NODE_NEXT", 0x08);
    B_NODE_REP = lcreg_u32("BUFF_NODE_REP", 0x20);
    B_NODE_PTR = lcreg_u32("BUFF_BUCKET_PTR", 0x08);
    B_CASTER   = lcreg_u32("OFF_CASTER",0x10);
    B_SKILL    = lcreg_u32("OFF_SKILLID",0x14);
    B_DUR      = lcreg_u32("OFF_DURATION",0x18);
    B_STRID    = lcreg_u32("OFF_STRID",0x2C);
    B_REMAIN   = lcreg_u32("OFF_REMAIN",0x84);
    B_REFCOUNT = lcreg_u32("OFF_REFCOUNT",0x08);
    B_DUR_PERPET=lcreg_u32("BUFF_DUR_PERPET",B_DUR_PERPET);
    B_DUR_MAX  =lcreg_u32("BUFF_DUR_MAX",B_DUR_MAX);
    snprintf(B_STRCSV,sizeof(B_STRCSV),"%s",
        lcreg_resolve(lcreg_str("STRINGS_CSV","T3_maps/dec/data_string.csv.lcf.out.plain"),
                      lcreg_str("STRINGS_DIST","data/data_string.csv.lcf.out.plain")));
    B_loadStrings(B_STRCSV);
}
static void lbuff_start(void){ B_recrva = lcreg_u32("RECORD_VFT_RVA",0x11FC550); }

/* 폴링: unordered_map 노드 walk 로 활성 버프 수집. BFS 없음.
 * 10_8 배치화: map헤더 1콜 · 버킷배열 1콜/청크 · 노드헤더 1콜 · 레코드 1콜 */
static int lbuff_poll(LBuff*out,int max,DWORD now){
    (void)now; B_reads=0; B_ncache=0;
    int n=0; uint32_t seenStr[256]; int nseen=0;
    uint64_t bsub=lc_subsGet(B_VFT_BUFF);
    if(!isHeap(bsub)) return 0;
    uint64_t map=B_R64(bsub+B_MAPOFF);
    if(!isHeap(map)) return 0;
    /* map 헤더(end@0x08, vec@0x18, mask@0x30) 1콜 배치 */
    uint32_t lo=B_ENDOFF, hi=B_MASKOFF+8;
    uint8_t mh[0x80];
    if(hi<lo || hi-lo>sizeof mh) return 0;
    if(!B_R(map+lo,mh,hi-lo)) return 0;
    uint64_t end =*(uint64_t*)(mh+(B_ENDOFF-lo));
    uint64_t vec =*(uint64_t*)(mh+(B_VECOFF-lo));
    uint64_t mask=*(uint64_t*)(mh+(B_MASKOFF-lo));
    if(getenv("LBUFF_DBG")) fprintf(stderr,"[lbuff] map=%016llX end=%016llX vec=%016llX mask=%016llX\n",(unsigned long long)map,(unsigned long long)end,(unsigned long long)vec,(unsigned long long)mask);
    if(!isHeap(vec)||mask>0x100000) return 0;
    uint64_t seenAddr[512]; int nsa=0;
    uint64_t nbuck=mask+1;
    long dbgNodes=0, dbgReps=0;
    #define BUFF_BCAP 256
    static uint8_t bvec[BUFF_BCAP*16];
    for(uint64_t b0=0; b0<nbuck; ){
        uint32_t cnt=(uint32_t)((nbuck-b0>BUFF_BCAP)?BUFF_BCAP:(nbuck-b0));
        if(!B_R(vec+16*b0,bvec,cnt*16)) break;         /* 버킷배열 1콜/청크(ptr@+8) */
        for(uint32_t bi=0; bi<cnt; bi++){
            uint64_t node=*(uint64_t*)(bvec+16*bi+B_NODE_PTR);
            for(int g=0; g<8192 && isHeap(node) && node!=end; g++){
                uint8_t nh[0x30];                        /* 노드헤더 1콜: next@8, rep@0x20 */
                if(!B_R(node,nh,sizeof nh)) break;
                dbgNodes++;
                uint64_t rep =*(uint64_t*)(nh+B_NODE_REP);
                uint64_t next=*(uint64_t*)(nh+B_NODE_NEXT);
                if(isHeap(rep) && vrva(rep)==B_recrva){   /* rep 는 레코드 포인터: vft(rep) 확인 */
                    dbgReps++;
                    int dup=0; for(int k=0;k<nsa;k++) if(seenAddr[k]==rep){dup=1;break;}
                    if(!dup && nsa<512){ seenAddr[nsa++]=rep;
                        uint8_t rh[0x88];                    /* 레코드 1콜: refc/skill/dur/strid/remain */
                        if(!B_R(rep,rh,sizeof rh)){ node=next; continue; }
                        if(*(uint32_t*)(rh+B_REFCOUNT)==0){ node=next; continue; }
                        uint32_t str=*(uint32_t*)(rh+B_STRID), sk=*(uint32_t*)(rh+B_SKILL), dur=*(uint32_t*)(rh+B_DUR);
                        float rem=*(float*)(rh+B_REMAIN);
                        const char*nm=bname(str);
                        if(nm){
                            int perpet=(dur==B_DUR_PERPET)||(dur>B_DUR_MAX);
                            if(perpet || dur!=0){
                                if(!perpet && rem<=0.0f){ /* 만료 제외 */ }
                                else {
                                    int sd=0; for(int k=0;k<nseen;k++) if(seenStr[k]==str){sd=1;break;}
                                    if(!sd && n<max){ if(nseen<256) seenStr[nseen++]=str;
                                        LBuff*o=&out[n++];
                                        snprintf(o->name,sizeof(o->name),"%s",nm); o->remain=rem; o->skill=sk; o->strid=str; o->dur=dur; o->perpet=perpet; o->addr=rep; }
                                }
                            }
                        }
                    }
                }
                node=next;
            }
        }
        b0+=cnt;
    }
    B_ncache=nsa;
    if(getenv("LBUFF_DBG")) fprintf(stderr,"[lbuff] nbuck=%llu nodes=%ld reps=%ld found=%d reads=%ld\n",(unsigned long long)nbuck,dbgNodes,dbgReps,n,B_reads);
    return n;
}
#endif /* LBUFF_H */