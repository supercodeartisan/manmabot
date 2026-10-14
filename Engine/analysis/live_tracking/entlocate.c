/* entlocate.c - T8 자동 구조복원/탐색기
 *  역할: 현 빌드에서 MGR / ACTOR_VFT(grid) / VFT_PRES_B / 부속 vft / 노드오프셋을
 *        live 로 재발견하고 entity_offsets.txt 를 갱신한다. (실패 시 기존값 유지)
 *  방식: RTTI(.ncg 아님, 생존) 로 vft 를 역추적 + MGR 후보창 스캔.
 *  usage: entlocate.exe [--write]   (--write 없으면 검증/출력만)
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "signeddrv_client.h"
static uint64_t g_pid=0,g_base=0; static uint32_t g_modSize=0;
static int rm(uint64_t a,void*b,uint32_t s){ uint32_t br=0; return SignedReadMemory(g_pid,a,b,s,&br)&&br==s; }
static uint64_t q64(uint64_t a){ uint64_t v=0; rm(a,&v,8); return v; }
static uint32_t d32(uint64_t a){ uint32_t v=0; rm(a,&v,4); return v; }
static int isHeap(uint64_t a){ return a>=0x10000000000ULL && a<0x70000000000ULL; }
static int isMod(uint64_t a){ return a>=g_base && a<g_base+g_modSize; }
static uint32_t vrva(uint64_t o){ uint64_t v=q64(o); return isMod(v)?(uint32_t)(v-g_base):0; }
static int getModule(uint64_t*base,uint32_t*size){ uint64_t peb=0,ldr=0,head=0,cur=0;
  if(!SignedGetPeb(g_pid,&peb)||!peb)return 0; if(!rm(peb+0x18,&ldr,8)||!ldr)return 0;
  if(!rm(ldr+0x20,&head,8)||!head)return 0; cur=head;
  for(int g=0;g<5000&&cur&&cur!=(ldr+0x20);g++){ uint64_t e=cur-0x10,db=0; uint32_t ds=0;
    if(rm(e+0x30,&db,8)&&db&&rm(e+0x40,&ds,4)&&ds){*base=db;*size=ds;return 1;} if(!rm(cur,&cur,8))break; }
  return 0; }
static uint64_t findStrRva(const char* s,uint32_t lo,uint32_t hi){
    size_t n=strlen(s); uint32_t CH=0x1000; uint8_t* buf=malloc(CH);
    for(uint64_t a=g_base+lo;a+CH<g_base+hi;a+=CH){ if(!rm(a,buf,CH))continue;
        for(uint32_t i=0;i+n<=CH;i++) if(!memcmp(buf+i,s,n)){ free(buf); return (uint32_t)(a+i-g_base); } }
    free(buf); return 0; }
/* RTTI 이름 -> vft RVA (module 내) */
static uint32_t rttiFindVft(const char* name){
    uint32_t td_rva = findStrRva(name,0x1000,g_modSize);
    printf("  [rtti] \"%s\" str@0x%X\n",name,td_rva);
    if(!td_rva) return 0;
    uint32_t td = td_rva-0x10;
    uint8_t nd[4]={(uint8_t)td,(uint8_t)(td>>8),(uint8_t)(td>>16),(uint8_t)(td>>24)};
    /* module 에서 4바이트 td 값(td=TypeDescriptor RVA) 검색 -> col = pos-0xC (COL+0xC=td) */
    uint32_t CH=0x40000; uint8_t* buf=malloc(CH);
    uint32_t colcand[16]; int ncc=0;
    for(uint64_t a=g_base+0x1000;a+CH<g_base+g_modSize && ncc<16;a+=CH-4){ if(!rm(a,buf,CH))continue;
        for(uint32_t i=0;i+4<=CH && ncc<16;i++){ if(memcmp(buf+i,nd,4))continue;
            uint32_t col=(uint32_t)(a+i-g_base)-0xC; if(col>=g_modSize)continue;
            /* COL 시그니처 검증(x64: +0x00 == 1) */
            if(d32(g_base+col)!=1) continue;
            colcand[ncc++]=col; } }
    free(buf);
    printf("  [rtti] td=0x%X COL 후보=%d\n",td,ncc);
    uint32_t CH2=0x100000; uint8_t* b2=malloc(CH2);
    for(int c=0;c<ncc;c++){ uint64_t need=g_base+colcand[c];
        for(uint64_t a=g_base+0x1000;a+8<g_base+g_modSize;a+=CH2-8){ uint32_t w=(uint32_t)((g_base+g_modSize-a<CH2)?(g_base+g_modSize-a):CH2);
            if(!rm(a,b2,w))continue;
            for(uint32_t i=0;i+8<=w;i+=8){ if(*(uint64_t*)(b2+i)==need){ uint32_t vft=(uint32_t)(a+i-g_base)+8;
                printf("  [rtti] COL 0x%X -> vft 0x%X\n",colcand[c],vft); free(b2); return vft; } } } }
    free(b2); return 0; }
int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    int write=0; for(int i=1;i<argc;i++) if(!strcmp(argv[i],"--write")) write=1;
    HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0); PROCESSENTRY32W pe; pe.dwSize=sizeof(pe); DWORD pid=0;
    if(Process32FirstW(snap,&pe)) do{ if(_wcsicmp(pe.szExeFile,L"LC.exe")==0){pid=pe.th32ProcessID;break;} }while(Process32NextW(snap,&pe));
    CloseHandle(snap); if(!pid){printf("no LC\n");return 1;}
    if(!SignedOpen())return 1; SignedSetTarget(pid); g_pid=pid;
    if(!getModule(&g_base,&g_modSize))return 1;
    printf("BASE=0x%llX SIZE=0x%X write=%d\n",(unsigned long long)g_base,g_modSize,write);
    uint32_t actor=rttiFindVft(".?AVActorSubsystem@lineage@@");
    uint32_t presb=rttiFindVft(".?AVTransformComponent@lineage@@");
    uint32_t death=rttiFindVft(".?AVDeathAction@lineage@@");
    uint32_t deadb=rttiFindVft(".?AVAppearDeadBody@lineage@@");
    uint32_t act  =rttiFindVft(".?AVActionComponent@lineage@@");
    printf("ACTOR_VFT=0x%X  VFT_PRES_B=0x%X  DEATH=0x%X  DEADBODY=0x%X  ACT=0x%X\n",
        actor,presb,death,deadb,act);
    if(!actor){ printf("FAIL: ActorSubsystem vft 복원 실패\n"); SignedClose(); return 1; }
    /* MGR 복원: 후보창(0x1600000..0x1720000)에서 heap ptr → +0xD0 holder → sublist 에 actor 포함 */
    uint32_t mgr=0;
    for(uint32_t rva=0x1600000; rva<0x1720000 && !mgr; rva+=0x1000){
        uint8_t buf[0x1000]; if(!rm(g_base+rva,buf,0x1000))continue;
        for(uint32_t i=0;i+8<=0x1000;i+=8){ uint64_t obj=*(uint64_t*)(buf+i);
            if(!isHeap(obj))continue; uint32_t vf=vrva(obj); if(!isMod(g_base+vf))continue;
            uint64_t holder=q64(obj+0xD0); if(!isHeap(holder))continue;
            uint64_t b=q64(holder+0x180), e=q64(holder+0x188);
            if(!isHeap(b)||e<=b||(e-b)>0x2000)continue;
            for(uint64_t x=b;x+16<=e;x+=16){ uint64_t s=q64(x); if(vrva(s)==actor){ mgr=rva+i; break; } }
            if(mgr)break; } }
    printf("MGR=0x%X (기존 0x1668860)\n",mgr);
    if(write && mgr){
        /* Production registry: entities/entity_offsets.txt (same folder pair as print_state). */
        char path[MAX_PATH], exe[MAX_PATH];
        GetModuleFileNameA(NULL, exe, MAX_PATH);
        { char* slash=strrchr(exe,'\\'); if(slash) *slash=0; else strcpy(exe,"."); }
        snprintf(path, sizeof(path), "%s\\..\\entities\\entity_offsets.txt", exe);
        FILE* f=fopen(path,"r");
        static char keep[512][256]; int nk=0;
        if(f){ while(nk<512 && fgets(keep[nk],sizeof(keep[nk]),f)) nk++; fclose(f); }
        FILE* o=fopen(path,"w");
        if(!o){ printf("cannot write %s\n", path); SignedClose(); return 1; }
        const char* keys[]={"MGR=","ACTOR_VFT=","VFT_PRES_B=","DEATH_VFT=","DEADBODY_VFT=","ACT_VFT="};
        uint32_t vals[]={mgr,actor,presb,death,deadb,act};
        int seen[6]={0,0,0,0,0,0};
        for(int i=0;i<nk;i++){
            int done=0;
            for(int k=0;k<6;k++){ size_t kl=strlen(keys[k]);
                if(!strncmp(keep[i],keys[k],kl)){ fprintf(o,"%s0x%X\n",keys[k],vals[k]); seen[k]=1; done=1; break; } }
            if(!done) fputs(keep[i],o);
        }
        for(int k=0;k<6;k++) if(!seen[k] && vals[k]) fprintf(o,"%s0x%X\n",keys[k],vals[k]);
        fclose(o);
        printf("wrote %s (%d lines)\n", path, nk);
    }
    SignedClose(); return 0;
}
