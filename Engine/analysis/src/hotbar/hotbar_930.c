/* hotbar_930.c — 핫바 슬롯 읽기 정본 모듈 (10_5 규격)
 * ---------------------------------------------------------------------------
 *  대원칙:
 *    1) 고정앵커  : HudSlotDataSubsystem = lc_subsGet(VFT_HUDSLOT)
 *    2) 고정체인  : 슬롯맵 = hud + HSD_MAP_HEAD (std::map<int,Slot*>)
 *                   header(0x8) → _Myhead(+HSD_MAP_HEAD) → RB 트리 노드
 *                   node: +NODE_L/PARENT/R/NIL/KEY/VAL
 *                   value(slot): +V_TYPE(1=SPELL,2=ITEM) +V_CFG +V_STR +V_ID
 *    3) 항목검증  : value 포인터 isHeap
 *    4) MmCopy단일: lcore rm() 만
 *    5) 상수외부   : registry(SEC-8) 단일출처
 *    6) 읽기최소   : 트리 1회 순회. POLL_HOTBAR_*.
 *  usage: hotbar_930.exe [registry] [secs] [out.txt]
 *  출력: <EXE>\out\hotbar_out.txt
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

static uint32_t RG_HSD, RG_HEAD, RG_SIZE, RG_ALT, RG_MAPOFF, RG_RECHDR, RG_STRLEN, RG_STRCAP, RG_SSOMAX;
static uint32_t N_L,N_P,N_R,N_NIL,N_KEY,N_VAL;
static uint32_t V_TYPE,V_CFG,V_STR,V_STRLEN,V_CAP,V_ID;
static int      T_SPELL,T_ITEM;
static uint32_t RG_ARVA,RG_MASK,RG_STRIDE,RG_NEXT,RG_RECNAME,RG_NAMEKR,RG_NODETEXT;
static uint64_t RG_FNVOFF,RG_FNVPRIME;

/* ── 묶음호출(페이지 배치) helper — lcore 의 lc_pgRead 경유 ───────────────
 * 같은 4KB 페이지 안의 read 를 1콜로 묶고 재방문은 캐시(0콜) 처리.
 * 패치 내성: 주소/오프셋을 새로 하드코딩하지 않으므로 이동 상수 증가 없음. */
static int      pgrm (uint64_t a, void*b, uint32_t s){ return lc_pgRead(a,b,s); }
static uint64_t pgq64(uint64_t a){ uint64_t v=0; lc_pgRead(a,&v,8); return v; }

/* ── mid→이름 캐시 (이름은 정적 → 최초 1회만 해석, 패치 후에도 자동 재해석) ── */
static uint32_t NC_mid[1024]; static char NC_nm[1024][128]; static int NC_n=0;
static const char* ncFind(uint32_t mid){ for(int i=0;i<NC_n;i++) if(NC_mid[i]==mid) return NC_nm[i]; return 0; }
static void ncAdd(uint32_t mid,const char* nm){ if(NC_n>=1024) return; NC_mid[NC_n]=mid; snprintf(NC_nm[NC_n],128,"%s",nm); NC_n++; }

/* SSO (MSVC std::string) */
static int readSso(uint64_t a,char*out,int cap){
    uint8_t h[0x20]; out[0]=0; if(cap<=1||!pgrm(a,h,sizeof(h))) return 0;
    uint64_t sz=*(uint64_t*)(h+RG_STRLEN), cp=*(uint64_t*)(h+RG_STRCAP);
    if(!sz||sz>0x400||cp>0x100000) return 0;
    if((int)sz>=cap) sz=cap-1;
    if(cp<RG_SSOMAX) memcpy(out,h,(size_t)sz);
    else { uint64_t p=*(uint64_t*)h; if(!isHeap(p)||!pgrm(p,out,(uint32_t)sz)) return 0; }
    out[sz]=0; return (int)sz;
}
static uint64_t fnvKey(uint32_t mid){ char s[24]; int n=snprintf(s,sizeof(s),"1_%u",mid);
    uint64_t h=RG_FNVOFF; for(int i=0;i<n;i++){ h^=(unsigned char)s[i]; h*=RG_FNVPRIME; } return h; }
static uint32_t recMid(uint64_t rec){ uint8_t h[0x20]; if(!pgrm(rec+RG_RECHDR,h,sizeof(h))) return 0;
    if(h[0]!='1'||h[1]!='_') return 0; uint64_t sz=*(uint64_t*)(h+RG_STRLEN); if(sz<3||sz>12) return 0;
    uint32_t m=0; for(uint64_t i=2;i<sz;i++){ if(h[i]<'0'||h[i]>'9') return 0; m=m*10+(h[i]-'0'); } return m; }
static int msgName(uint32_t mid,char*out,int cap){ out[0]=0; if(!mid||!RG_ARVA) return 0;
    uint64_t A=pgq64(g_base+RG_ARVA); if(!isHeap(A)) return 0;
    uint64_t rec=pgq64(A+(fnvKey(mid)&RG_MASK)*RG_STRIDE);
    for(int st=0;isHeap(rec)&&st<64;st++){ if(recMid(rec)==mid){ uint64_t nn=pgq64(rec+RG_RECNAME); if(!isHeap(nn))return 0;
        uint64_t kr=pgq64(nn+RG_NAMEKR); if(!isHeap(kr))return 0; return readSso(kr+RG_NODETEXT,out,cap)>0; }
        uint64_t nx=pgq64(rec+RG_NEXT); if(nx==rec)break; rec=nx; } return 0; }

int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char* reg=lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    const char* outp=lcreg_outpath("hotbar_out.txt");
    int secs=0; { int seen=0;
      for(int i=1;i<argc;i++){ if(strstr(argv[i],".txt")||strstr(argv[i],".out")){ if(!seen&&strstr(argv[i],"REGISTRY")){reg=argv[i];seen=1;} else outp=argv[i]; }
        else if(atoi(argv[i])>0&&!strstr(argv[i],".")) secs=atoi(argv[i]); } }
    lcreg_load(reg); lc_reg_apply();
    RG_HSD=lcreg_u32("VFT_HUDSLOT",0x11C3900);
    RG_HEAD=lcreg_u32("HSD_MAP_HEAD",0x8); RG_SIZE=lcreg_u32("HSD_MAP_SIZE",0x10); RG_ALT=lcreg_u32("HSD_MAP_ALT",0x1D8);
    RG_MAPOFF=lcreg_u32("HSD_MAP_OFF",0xD8);
    RG_RECHDR=lcreg_u32("OFF_REC_HDR",0x10);
    RG_STRLEN=lcreg_u32("OFF_STR_LEN",0x10); RG_STRCAP=lcreg_u32("OFF_STR_CAP",0x18);
    RG_SSOMAX=lcreg_u32("STR_SSO_MAX",0x10);
    N_L=lcreg_u32("NODE_L",0x0); N_P=lcreg_u32("NODE_PARENT",0x8); N_R=lcreg_u32("NODE_R",0x10);
    N_NIL=lcreg_u32("NODE_NIL",0x19); N_KEY=lcreg_u32("NODE_KEY",0x20); N_VAL=lcreg_u32("NODE_VAL",0x28);
    V_TYPE=lcreg_u32("V_TYPE",0x8); V_CFG=lcreg_u32("V_CFG",0xC); V_STR=lcreg_u32("V_STR",0x30);
    V_STRLEN=lcreg_u32("V_STRLEN",0x40); V_CAP=lcreg_u32("V_CAP",0x48); V_ID=lcreg_u32("V_ID",0xC0);
    T_SPELL=lcreg_u32("SLOT_TYPE_SPELL",1); T_ITEM=lcreg_u32("SLOT_TYPE_ITEM",2);
    RG_ARVA=lcreg_u32("MSG_ANCHOR_RVA",0x16687B8); RG_MASK=lcreg_u32("MSG_BUCKET_MASK",0xFFFF);
    RG_STRIDE=lcreg_u32("MSG_BUCKET_STRIDE",0x10); RG_NEXT=lcreg_u32("MSG_REC_NEXT",0x00);
    RG_RECNAME=lcreg_u32("MSG_REC_NAME",0x38); RG_NAMEKR=lcreg_u32("MSG_NAME_KR",0x00);
    RG_NODETEXT=lcreg_u32("MSG_NODE_TEXT",0x30);
    RG_FNVOFF=lcreg_u64("MSG_FNV_OFFSET",0xcbf29ce484222325ULL); RG_FNVPRIME=lcreg_u64("MSG_FNV_PRIME",0x100000001b3ULL);
    lcreg_poll P=lcreg_poll_load("HOTBAR");

    if(lc_attach())return 1; if(!lc_anchor())return 2;
    lcreg_mkdir_for(outp);
    FILE*f=fopen(outp,"w"); if(!f){ fprintf(stderr,"cannot open %s\n",outp); return 4; }
    fprintf(f,"# registry=%s HSD=%X\n",reg,RG_HSD);

    DWORD t0=GetTickCount();
    do{
        LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr); QueryPerformanceCounter(&q0);
        g_ioctl=0;
        lc_pgc_reset();                       /* 묶음호출: 페이지 캐시 사이클 초기화 */
        uint64_t hud=lc_subsGet(RG_HSD); int n=0;
        if(isHeap(hud)){
            uint64_t cont=hud+RG_MAPOFF;               /* 슬롯맵 컨테이너(임베디드) */
            uint64_t hs[2]={0,0}; pgrm(cont+RG_HEAD,hs,sizeof hs);   /* myhead+size 1콜 묶음 */
            uint64_t myhead=hs[0]; uint32_t sz=(uint32_t)hs[1];
            fprintf(f,"t=%ums hud=0x%llX map=0x%llX myhead=0x%llX size=%u\n",(unsigned)(GetTickCount()-t0),
                (unsigned long long)hud,(unsigned long long)cont,(unsigned long long)myhead,sz);
            if(isHeap(myhead)){
                /* RB 트리 순회(BFS): _Myhead 의 Left/Right/Parent 를 시드로, 노드별 L/R/P 확장 */
                static uint64_t q[4096]; int qh=0,qt=0;
                uint8_t hh[0x30]; uint64_t L0=0,R0=0,P0=0;
                if(pgrm(myhead,hh,sizeof hh)){ memcpy(&L0,hh+N_L,8); memcpy(&R0,hh+N_R,8); memcpy(&P0,hh+N_P,8); }
                uint64_t seeds[3]={ L0, R0, P0 };
                for(int a=0;a<3;a++) if(isHeap(seeds[a])&&qt<4096) q[qt++]=seeds[a];
                static uint64_t seen[4096]; int ns=0;
                while(qh<qt && ns<4096){ uint64_t nd=q[qh++];
                    int dup=0; for(int k=0;k<ns;k++) if(seen[k]==nd){dup=1;break;} if(dup)continue; seen[ns++]=nd;
                    uint8_t nb[0x30]; if(!pgrm(nd,nb,sizeof nb)) continue;   /* 노드헤더 1콜 */
                    uint8_t nil=nb[N_NIL];
                    if(!nil){ int key=0; uint64_t val=0; memcpy(&key,nb+N_KEY,4); memcpy(&val,nb+N_VAL,8);
                        int type=-1; uint32_t cfg=0,id=0; char sname[96]="";
                        if(isHeap(val)){ uint8_t sb[0xC8];
                            if(pgrm(val,sb,sizeof sb)){                    /* 슬롯헤더+V_ID 1콜 묶음 */
                                memcpy(&type,sb+V_TYPE,4); memcpy(&cfg,sb+V_CFG,4); memcpy(&id,sb+V_ID,4); }
                            readSso(val+V_STR,sname,sizeof(sname)); }      /* 페이지 캐시로 보통 0콜 */
                        char nm[128]=""; if(type==T_ITEM){ int mid=0; const char* d=strchr(sname,'$'); if(d) mid=atoi(d+1);
                            const char* cch=ncFind(mid);
                            if(cch) snprintf(nm,sizeof(nm),"%s",cch);                        /* 캐시 hit → 0콜 */
                            else { if(!msgName(mid,nm,sizeof(nm))) snprintf(nm,sizeof(nm),"%s",sname[0]?sname:"(?)");
                                   if(nm[0]&&nm[0]!='(') ncAdd(mid,nm); } }
                        else if(type==T_SPELL) snprintf(nm,sizeof(nm),"%s",sname[0]?sname:"(?)");
                        else snprintf(nm,sizeof(nm),"(empty)");
                        fprintf(f,"  key=%-3d type=%-2d cfg=%-6u id=%-6u name=%s\n",key,type,cfg,id,nm); n++;
                    }
                    uint64_t L=0,R=0,P=0; memcpy(&L,nb+N_L,8); memcpy(&R,nb+N_R,8); memcpy(&P,nb+N_P,8);
                    if(isHeap(L)&&qt<4096)q[qt++]=L; if(isHeap(R)&&qt<4096)q[qt++]=R; if(isHeap(P)&&qt<4096)q[qt++]=P;
                }
            }
        } else fprintf(f,"t=%ums HudSlotDataSubsystem not found\n",(unsigned)(GetTickCount()-t0));
        QueryPerformanceCounter(&q1);
        fprintf(f,"# n=%d ioctl=%llu time=%.4fms\n",n,g_ioctl,(q1.QuadPart-q0.QuadPart)*1000.0/fr.QuadPart);
        fflush(f);
        lcapi_sample(f);
        if(secs) Sleep(lcreg_poll_sleep_ms(&P));
    } while(!lcapi_done() && secs && (int)(GetTickCount()-t0)<secs*1000);
    fclose(f); SignedClose(); printf("done -> %s\n",outp); return 0;
}
