/* skilllocate.c - T4 재발견: HudSlotDataSubsystem 앵커(vft/서브시스템 index/ADJ)을 재탐색
 * - skill_offsets.txt 의 모든 키를 보존하며 갱신한다.
 * - RTTI 이름으로 HudSlotDataSubsystem vtable(RVA, 복수) 재탐색.
 * - holder 서브시스템 리스트에서 그 vft를 가진 객체의 index 와 내부 오프셋(ADJ) 확정.
 * usage: skilllocate.exe
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../entities/signeddrv_client.h"
static uint64_t g_pid=0,g_base=0; static uint32_t g_modSize=0,g_br=0;
static int rm(uint64_t a,void*b,uint32_t s){ return SignedReadMemory(g_pid,a,b,s,&g_br)&&g_br==s; }
static uint64_t q64(uint64_t a){ uint64_t v=0; rm(a,&v,8); return v; }
static uint32_t d32(uint64_t a){ uint32_t v=0; rm(a,&v,4); return v; }
static int isHeap(uint64_t a){ return a>=0x10000000000ULL && a<0x70000000000ULL; }
static int isMod(uint64_t a){ return a>=g_base && a<g_base+g_modSize; }
static uint32_t vrva(uint64_t o){ uint64_t v=q64(o); return isMod(v)?(uint32_t)(v-g_base):0; }
static int getModule(uint64_t* base,uint32_t* size){
    uint64_t peb=0,ldr=0,head=0,cur=0;
    if(!SignedGetPeb(g_pid,&peb)||!peb) return 0;
    if(!rm(peb+0x18,&ldr,8)||!ldr) return 0;
    if(!rm(ldr+0x20,&head,8)||!head) return 0; cur=head;
    for(int g=0;g<5000&&cur&&cur!=(ldr+0x20);g++){ uint64_t e=cur-0x10,db=0; uint32_t ds=0;
        if(rm(e+0x30,&db,8)&&db&&rm(e+0x40,&ds,4)&&ds){*base=db;*size=ds;return 1;} if(!rm(cur,&cur,8))break; }
    return 0;
}
#define MAXL 256
static char g_lines[MAXL][256]; static int g_nl=0;
static void loadReg(void){ FILE*f=fopen("skill_offsets.txt","r"); if(!f) return; char line[256];
    while(fgets(line,sizeof(line),f)&&g_nl<MAXL){ char*p; if((p=strchr(line,'\n')))*p=0; if((p=strchr(line,'\r')))*p=0; strncpy(g_lines[g_nl],line,255); g_nl++; } fclose(f); }
static void setKV(const char* key,const char* val){ char pat[64]; snprintf(pat,sizeof(pat),"%s=",key);
    for(int i=0;i<g_nl;i++) if(!strncmp(g_lines[i],pat,strlen(pat))){ snprintf(g_lines[i],256,"%s%s",pat,val); return; }
    if(g_nl<MAXL) snprintf(g_lines[g_nl++],256,"%s%s",pat,val); }
static uint32_t getKV(const char* key,uint32_t def){ char pat[64]; snprintf(pat,sizeof(pat),"%s=",key);
    for(int i=0;i<g_nl;i++) if(!strncmp(g_lines[i],pat,strlen(pat)))
        return (uint32_t)strtoul(g_lines[i]+strlen(pat),0,strcmp(key,"HSD_IDX")?16:10);
    return def; }
static void saveReg(void){ FILE*f=fopen("skill_offsets.txt","w"); if(!f) return; for(int i=0;i<g_nl;i++) fprintf(f,"%s\n",g_lines[i]); fclose(f); }
static uint8_t* g_mod=0; static uint32_t g_modRead=0;
static void loadModule(void){ g_mod=malloc(g_modSize); if(!g_mod) return;
    for(uint32_t o=0;o<g_modSize;o+=0x10000){ uint32_t w=(g_modSize-o<0x10000)?(g_modSize-o):0x10000;
        if(!rm(g_base+o,g_mod+o,w)) memset(g_mod+o,0,w); else g_modRead+=w; } }
static int findVftsByName(const char* name,uint32_t* out,int maxn){ if(!g_mod) return 0; int n=0; size_t ln=strlen(name); int hits=0;
    for(uint32_t i=0;i+ln<g_modRead && hits<3;i++){ if(memcmp(g_mod+i,name,ln)!=0) continue; hits++; if(i<0x10) continue; uint32_t td=i-0x10;
        for(uint32_t j=0;j+4<=g_modRead;j++){ uint32_t u; memcpy(&u,g_mod+j,4); if(u!=td) continue; if(j<0xC) continue; uint32_t col=j-0xC; uint64_t cv=g_base+col;
            for(uint32_t k=0;k+8<=g_modRead;k++){ uint64_t q; memcpy(&q,g_mod+k,8); if(q==cv){ uint32_t vt=k+8; int dup=0; for(int t=0;t<n;t++) if(out[t]==vt)dup=1; if(!dup&&n<maxn) out[n++]=vt; } } } }
    return n; }
/* 슬롯 맵 재귀 순회(skill.c 와 동일 로직) — 검증용 */
static void recurse_map(uint64_t node,uint64_t header,uint32_t N_L,uint32_t N_R,uint32_t N_NIL,
                        uint32_t N_KEY,uint32_t N_VAL,uint32_t V_TYPE,int depth,int* total,int* typeSlots){
    if(!node||node==header||depth>40) return;
    unsigned char nil=0; rm(node+N_NIL,&nil,1); if(nil) return;
    recurse_map(q64(node+N_L),header,N_L,N_R,N_NIL,N_KEY,N_VAL,V_TYPE,depth+1,total,typeSlots);
    (*total)++;
    uint64_t val=q64(node+N_VAL);
    if(isHeap(val)){ uint32_t t=d32(val+V_TYPE); if(t==1||t==2) (*typeSlots)++; }
    recurse_map(q64(node+N_R),header,N_L,N_R,N_NIL,N_KEY,N_VAL,V_TYPE,depth+1,total,typeSlots);
}
/* MGR 자동 재발견 (서명: guard byte==1, holder, 40~120 subsys, 다수 module vft). 성공 1. */
static int main_mgr(uint32_t* outOff, uint64_t* outMgr, uint64_t* outHolder){
    if(!g_mod) return 0;
    int best=-1; uint32_t bo=0; uint64_t bv=0,bh=0;
    for(uint32_t off=0; off+8<=g_modSize; off+=8){
        uint64_t v; memcpy(&v,g_mod+off,8);
        if(!isHeap(v)||(v&0xF)) continue;
        unsigned char g=0; if(!rm(v+0xD8,&g,1)||g!=1) continue;
        uint64_t holder=0; if(!rm(v+0xD0,&holder,8)||!isHeap(holder)) continue;
        uint64_t bgn=0,end=0;
        if(!rm(holder+0x180,&bgn,8)||!rm(holder+0x188,&end,8)) continue;
        if(!isHeap(bgn)||end<=bgn||((end-bgn)%16)) continue;
        int cnt=(int)((end-bgn)/16); if(cnt<40||cnt>120) continue;
        int okv=0,n=0;
        for(int i=0;i<cnt&&n<24;i++){ uint64_t s=0; if(!rm(bgn+16ull*i,&s,8)) break; if(!isHeap(s)) continue; n++;
            uint64_t vf=0; if(rm(s,&vf,8)&&isMod(vf)) okv++; }
        if(okv<5) continue;
        int score=okv*10-(cnt>62?cnt-62:62-cnt);
        if(score>best){ best=score; bo=off; bv=v; bh=holder; }
    }
    if(best<0) return 0;
    *outOff=bo; *outMgr=bv; *outHolder=bh; return 1;
}
int main(void){
    SetConsoleOutputCP(CP_UTF8);
    loadReg();
    uint32_t MGR=getKV("MGR",0x164E460),HOLDER=getKV("HOLDER_OFF",0xD0),SB=getKV("SUBLIST_BEG",0x180),SE=getKV("SUBLIST_END",0x188);
    HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0); PROCESSENTRY32W pe; pe.dwSize=sizeof(pe); DWORD pid=0;
    if(Process32FirstW(snap,&pe)) do{ if(_wcsicmp(pe.szExeFile,L"LC.exe")==0){pid=pe.th32ProcessID;break;} }while(Process32NextW(snap,&pe));
    CloseHandle(snap); if(!pid){ printf("no LC.exe\n"); return 1; }
    if(!SignedOpen()) return 1; SignedSetTarget(pid); g_pid=pid;
    if(!getModule(&g_base,&g_modSize)) return 1; loadModule();
    printf("module scanned %u/0x%X\n",g_modRead,g_modSize);
    /* MGR 자동 재발견(서명: guard==1, holder, 40~120 subsys, 다수 module vft) */
    { uint32_t mo; uint64_t mv,mh;
      if(main_mgr(&mo,&mv,&mh)){
          if(mo!=MGR){ MGR=mo; char hv[16]; snprintf(hv,sizeof(hv),"0x%X",MGR); setKV("MGR",hv);
              printf("MGR REDISCOVERED 0x%X (mgr=0x%llX holder=0x%llX)\n",MGR,(unsigned long long)mv,(unsigned long long)mh); }
          else printf("MGR OK 0x%X\n",MGR);
      } else printf("MGR FAIL-KEPT 0x%X\n",MGR);
    }
    uint32_t vfts[8]; int nv=findVftsByName(".?AVHudSlotDataSubsystem@lineage@@",vfts,8);
    printf("HudSlotDataSubsystem vtables:"); for(int i=0;i<nv;i++){ char hv[16]; snprintf(hv,sizeof(hv),"%X",vfts[i]); printf(" 0x%X",vfts[i]);
        char key[32]; snprintf(key,sizeof(key),"HSD_VFT%s",i?"2":""); setKV(key,hv); } printf("\n");
    uint64_t mgr=q64(g_base+MGR), holder=q64(mgr+HOLDER);
    uint64_t b=q64(holder+SB), e=q64(holder+SE);
    int found=0;
    for(int i=0;i<nv && !found;i++){
        for(uint64_t x=b;x+16<=e && !found;x+=16){ uint64_t s=q64(x); if(!isHeap(s)) continue;
            for(uint32_t adj=0; adj<=0x40 && !found; adj+=8){
                if(vrva(s+adj)==vfts[i]){
                    int idx=(int)((x-b)/16);
                    char hv[16]; snprintf(hv,sizeof(hv),"%d",idx); setKV("HSD_IDX",hv);
                    snprintf(hv,sizeof(hv),"%X",adj); setKV("HSD_ADJ",hv);
                    printf("HSD idx=%d adj=0x%X vft=0x%X (outer vft=0x%X)\n",idx,adj,vfts[i],vrva(s));
                    found=1;
                }
            }
        }
    }
    if(!found) printf("HSD not found in subsystem list (reg fallback)\n");

    /* 슬롯 맵/밸류 오프셋 검증: HSD 에서 맵을 순회해 type∈{1,2} 슬롯이 여럿 나오는지 확인.
       실패하면 맵/밸류 오프셋 재탐색(폴백)은 하지 않고 FAIL-KEPT 경고만 남긴다(구조 안정적). */
    if(found){
        uint32_t MAP_HEAD=getKV("MAP_HEAD",0x08);
        uint32_t N_L=getKV("N_L",0x00),N_R=getKV("N_R",0x10),N_NIL=getKV("N_NIL",0x19),
                 N_KEY=getKV("N_KEY",0x20),N_VAL=getKV("N_VAL",0x28),V_TYPE=getKV("V_TYPE",0x08);
        uint64_t hsd=0;
        { uint64_t mgr=q64(g_base+MGR), holder=q64(mgr+HOLDER);
          uint64_t bb=q64(holder+SB), ee=q64(holder+SE);
          uint32_t hi=getKV("HSD_IDX",30), ha=getKV("HSD_ADJ",0x18);
          uint32_t hv=getKV("HSD_VFT",0x1182F48);
          /* vft 매칭 우선(skill.c findHSD 와 동일), 실패 시 idx+adj */
          for(uint64_t x=bb;x+16<=ee;x+=16){ uint64_t s=q64(x); if(!isHeap(s)) continue;
              if(vrva(s+ha)==hv){ hsd=s+ha; break; } }
          if(!hsd && bb+16ull*hi+16<=ee){ uint64_t s=q64(bb+16ull*hi); if(isHeap(s)&&vrva(s+ha)==hv) hsd=s+ha; } }
        int typeSlots=0, total=0;
        if(hsd){
            uint64_t header=q64(hsd+MAP_HEAD);
            struct { uint64_t header; int total,typeSlots; } st;
            st.header=header; st.total=0; st.typeSlots=0;
            recurse_map(q64(header+0x08),header,N_L,N_R,N_NIL,N_KEY,N_VAL,V_TYPE,0,&st.total,&st.typeSlots);
            total=st.total; typeSlots=st.typeSlots;
        }
        printf("slot-map verify: total=%d typeSlots=%d %s\n",total,typeSlots,(typeSlots>=3?"OK":"FAIL-KEPT"));
    }
    saveReg(); printf("wrote skill_offsets.txt\n");
    SignedClose(); return 0;
}
