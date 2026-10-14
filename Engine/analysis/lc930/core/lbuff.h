/* lbuff.h - 공용 버프(스킬) 읽기 엔진 (header-only)  ·  (2026-10-06 재작성)
 * ===========================================================================
 *  정적/라이브 규명 결과: 활성 버프는 BuffSubsystem 의 **unordered_map** 에 있다.
 *
 *    BuffSubsystem = lc_subsGet(VFT_BUFF=0x11BB770)      (고정앵커, vft식별)
 *    map   = *( BuffSubsystem + BUFF_MAP_OFF(0x260) )     (std::unordered_map<u32,shared_ptr<BuffInstance>>)
 *    vec   = *( map + BUFF_VEC_OFF(0x18) )   (버킷 배열)
 *    mask  = *( map + BUFF_MASK_OFF(0x30) )
 *    end   = *( map + BUFF_END_OFF(0x08) )
 *    버킷 i: node = *( vec + 16*i + 8 ) ; node != end ; node = *( node + NODE_NEXT(0x08) )
 *    노드: key u32@+NODE_KEY(0x10), shared_ptr{_Ptr@+0x18,_Rep@+0x20}
 *          record = _Rep (vft = base+RECORD_VFT_RVA=0x11BB628) = _Ref_count_obj2<BuffInstance> 제어블록
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
static const char* bname(int id){ for(int i=0;i<B_sn;i++) if(B_sid[i]==id) return B_skr[i]; return 0; }
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

static void lbuff_load(const char*regpath){
    (void)regpath;
    B_VFT_BUFF = lcreg_u32("VFT_BUFF", 0x11BB770);
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
    snprintf(B_STRCSV,sizeof(B_STRCSV),"%s",
        lcreg_resolve(lcreg_str("STRINGS_CSV","T3_maps/dec/data_string.csv.lcf.out.plain"),
                      lcreg_str("STRINGS_DIST","data/data_string.csv.lcf.out.plain")));
    B_loadStrings(B_STRCSV);
}
static void lbuff_start(void){ B_recrva = lcreg_u32("RECORD_VFT_RVA",0x11BB628); }

/* 폴링: unordered_map 노드 walk 로 활성 버프 수집. BFS 없음. */
static int lbuff_poll(LBuff*out,int max,DWORD now){
    (void)now; B_reads=0; B_ncache=0;
    int n=0; uint32_t seenStr[256]; int nseen=0;
    uint64_t bsub=lc_subsGet(B_VFT_BUFF);
    if(!isHeap(bsub)) return 0;
    uint64_t map=B_R64(bsub+B_MAPOFF);
    if(!isHeap(map)) return 0;
    uint64_t vec=B_R64(map+B_VECOFF), mask=B_R64(map+B_MASKOFF), end=B_R64(map+B_ENDOFF);
    /* mask 0 is a one-bucket map (bucket_count-1). Walking i=0..0 is valid. */
    if(!isHeap(vec)||mask>0x100000) return 0;
    uint64_t seenAddr[512]; int nsa=0;
    for(uint64_t i=0;i<=mask;i++){
        uint64_t node=B_R64(vec+16*i+B_NODE_PTR);
        for(int g=0; g<8192 && isHeap(node) && node!=end; g++){
            uint64_t rep=B_R64(node+B_NODE_REP);
            uint64_t next=B_R64(node+B_NODE_NEXT);
            uint64_t obj=B_R64(node+0x18);
            (void)obj;
            if(isHeap(rep) && vrva(rep)==B_recrva){
                int dup=0; for(int k=0;k<nsa;k++) if(seenAddr[k]==rep){dup=1;break;}
                if(!dup && nsa<512){ seenAddr[nsa++]=rep;
                    if(B_R32(rep+B_REFCOUNT)==0) { node=next; continue; }   /* 고아 제어블록 */
                    uint32_t str=B_R32(rep+B_STRID), sk=B_R32(rep+B_SKILL), dur=B_R32(rep+B_DUR);
                    float rem=0; B_R(rep+B_REMAIN,&rem,4);
                    const char*nm=bname(str);
                    if(nm){
                        int perpet=(dur==0xFFFFFFFFu)||(dur>1000000u);
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
    B_ncache=nsa;
    return n;
}
#endif /* LBUFF_H */