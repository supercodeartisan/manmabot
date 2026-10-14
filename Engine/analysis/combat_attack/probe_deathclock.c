/* probe_deathclock.c - 그리드 객체 + 이탈 후 "그림자 추적"
 * usage: probe_deathclock.exe [secs] [ms]
 * - 셀맵의 모든 후보 객체(vft 유효)를 매 틱 기록(필터 없음)
 * - 그리드에서 이탈한 객체도 주소로 계속 읽어 바이트 변화/소멸을 추적(시체 포착)
 * - vft=0x116E5B8(지상 아이템) 신규 등장을 DROP 으로 표시
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
static uint32_t vrva(uint64_t o){ uint64_t v=q64(o); return (v>=g_base&&v<g_base+g_modSize)?(uint32_t)(v-g_base):0; }
static int getModule(uint64_t* base,uint32_t* size){
    uint64_t peb=0,ldr=0,head=0,cur=0;
    if(!SignedGetPeb(g_pid,&peb)||!peb) return 0;
    if(!rm(peb+0x18,&ldr,8)||!ldr) return 0;
    if(!rm(ldr+0x20,&head,8)||!head) return 0;
    cur=head;
    for(int g=0;g<5000&&cur&&cur!=(ldr+0x20);g++){
        uint64_t e=cur-0x10, db=0; uint32_t ds=0;
        if(rm(e+0x30,&db,8)&&db&&rm(e+0x40,&ds,4)&&ds){ *base=db; *size=ds; return 1; }
        if(!rm(cur,&cur,8)) break;
    }
    return 0;
}
static uint32_t MGR=0x164E460,HOLDER_OFF=0xD0,SUB_BEG=0x180,SUB_END=0x188,ACTOR_VFT=0x116B858;
static uint32_t NODE_NEXT=8,NODE_CX=0x10,NODE_CY=0x14,NODE_BEG=0x18,NODE_END=0x20;
static uint32_t HEADS[4]={0x798,0x7D8,0,0}; static int NH=2;
static void loadReg(void){
    FILE*f=fopen("entity_offsets.txt","r"); if(!f) return; char line[256];
    while(fgets(line,sizeof(line),f)){ char*p; if((p=strchr(line,'\n')))*p=0;
        if(!strncmp(line,"MGR=",4))MGR=(uint32_t)strtoul(line+4,0,16);
        else if(!strncmp(line,"HOLDER_OFF=",11))HOLDER_OFF=(uint32_t)strtoul(line+11,0,16);
        else if(!strncmp(line,"SUBLIST_BEG=",12))SUB_BEG=(uint32_t)strtoul(line+12,0,16);
        else if(!strncmp(line,"SUBLIST_END=",12))SUB_END=(uint32_t)strtoul(line+12,0,16);
        else if(!strncmp(line,"ACTOR_VFT=",10))ACTOR_VFT=(uint32_t)strtoul(line+10,0,16);
    }
    fclose(f);
}
static uint64_t findActor(void){
    uint64_t mgr=q64(g_base+MGR); if(!mgr) return 0;
    uint64_t holder=q64(mgr+HOLDER_OFF); if(!holder) return 0;
    uint64_t b=q64(holder+SUB_BEG), e=q64(holder+SUB_END);
    for(uint64_t x=b;x+16<=e;x+=16){ uint64_t s=q64(x); if(vrva(s)==ACTOR_VFT) return s; }
    return 0;
}
#define BSZ 0x120
typedef struct { uint64_t o; int inGrid; uint32_t cx,cy; int ul; uint8_t b[BSZ]; } TRK;
static TRK g_t[512]; static int g_n=0;
static void nameOf(uint64_t o,char*out,int cap){
    out[0]=0; uint64_t H=q64(o+0x20), no=isHeap(H)?q64(H+0x20):0;
    if(isHeap(no)){ uint32_t ln=d32(no+0x50); if(ln>0&&(int)ln<cap-1&&rm(no+0x40,out,ln)) out[ln]=0; }
}
int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    int secs=(argc>1)?atoi(argv[1]):60, ms=(argc>2)?atoi(argv[2]):60;
    loadReg();
    HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0);
    PROCESSENTRY32W pe; pe.dwSize=sizeof(pe); DWORD pid=0;
    if(Process32FirstW(snap,&pe)) do{ if(_wcsicmp(pe.szExeFile,L"LC.exe")==0){pid=pe.th32ProcessID;break;} }while(Process32NextW(snap,&pe));
    CloseHandle(snap);
    if(!pid){ printf("LC.exe not running\n"); return 1; }
    if(!SignedOpen()){ printf("driver fail\n"); return 1; }
    SignedSetTarget(pid); g_pid=pid;
    if(!getModule(&g_base,&g_modSize)){ printf("module base fail\n"); return 1; }
    uint64_t actor=findActor(); if(!actor){ printf("anchor fail\n"); return 1; }
    fprintf(stderr,"[anchor] 0x%llX\n",(unsigned long long)actor);
    printf("deathclock start (drop vft=0x116E5B8)\n");
    uint64_t t0=GetTickCount64();
    while((GetTickCount64()-t0)<(uint64_t)secs*1000){
        uint64_t now=GetTickCount64()-t0;
        uint64_t inG[512]; uint32_t gcx[512],gcy[512]; int gn=0;
        for(int h=0;h<NH;h++){
            uint64_t sent=q64(actor+HEADS[h]+8), cur=q64(sent+8); int nodes=0;
            while(cur&&cur!=sent&&nodes<400){
                uint64_t vb=q64(cur+NODE_BEG),ve=q64(cur+NODE_END);
                uint32_t cx=d32(cur+NODE_CX),cy=d32(cur+NODE_CY);
                if(isHeap(vb)&&ve>vb&&(ve-vb)<0x4000)
                    for(uint64_t p=vb;p+8<=ve;p+=8){
                        uint64_t o=q64(p); if(!isHeap(o)) continue;
                        uint32_t v=vrva(o); if(!v) continue;
                        int dup=0; for(int i=0;i<gn;i++) if(inG[i]==o){dup=1;break;}
                        if(dup||gn>=512) continue;
                        inG[gn]=o; gcx[gn]=cx; gcy[gn]=cy; gn++;
                    }
                cur=q64(cur+NODE_NEXT); nodes++;
            }
        }
        for(int i=0;i<gn;i++){
            TRK*t=0; for(int j=0;j<g_n;j++) if(g_t[j].o==inG[i]){t=&g_t[j];break;}
            uint8_t b[BSZ]; int ok=rm(inG[i],b,BSZ);
            if(!t){ if(g_n>=512) continue; t=&g_t[g_n++]; memset(t,0,sizeof(*t)); t->o=inG[i]; t->ul=1;
                uint32_t v=vrva(inG[i]); char nm[64]; nameOf(inG[i],nm,64);
                if(v==0x116E5B8) printf("t=%6llu DROP  a=0x%llX vft=0x%X cell=(%u,%u)\n",(unsigned long long)now,(unsigned long long)inG[i],v,gcx[i],gcy[i]);
                else printf("t=%6llu NEW   a=0x%llX vft=0x%X cell=(%u,%u) nm=\"%s\"\n",(unsigned long long)now,(unsigned long long)inG[i],v,gcx[i],gcy[i],nm);
                if(ok){ memcpy(t->b,b,BSZ); t->ul=0; }
            } else {
                if(!t->inGrid){ printf("t=%6llu BACK  a=0x%llX (grid cell=(%u,%u))\n",(unsigned long long)now,(unsigned long long)t->o,gcx[i],gcy[i]); t->ul=1; }
                if(ok){ if(t->ul){ memcpy(t->b,b,BSZ); t->ul=0; }
                        else for(uint32_t k=0;k<BSZ;k++) if(b[k]!=t->b[k]){ printf("t=%6llu CHG   a=0x%llX +0x%03X %02X->%02X\n",(unsigned long long)now,(unsigned long long)t->o,k,t->b[k],b[k]); t->b[k]=b[k]; } }
            }
            t->inGrid=1; t->cx=gcx[i]; t->cy=gcy[i];
        }
        for(int j=0;j<g_n;j++){
            if(!g_t[j].inGrid) continue;
            int still=0; for(int i=0;i<gn;i++) if(inG[i]==g_t[j].o){still=1;break;}
            if(!still){
                int self=(q64(g_t[j].o+8)==g_t[j].o); uint64_t guid=q64(g_t[j].o+0x18);
                printf("t=%6llu LEAVE a=0x%llX self=%d guid=0x%llX (was cell=(%u,%u)) -> shadow\n",
                    (unsigned long long)now,(unsigned long long)g_t[j].o,self,(unsigned long long)guid,g_t[j].cx,g_t[j].cy);
                g_t[j].inGrid=0;
            }
        }
        /* shadow: not in grid -> keep reading, report diffs/unreadable */
        for(int j=0;j<g_n;j++){
            if(g_t[j].inGrid) continue;
            uint8_t b[BSZ];
            if(!rm(g_t[j].o,b,BSZ)){ if(!g_t[j].ul){ printf("t=%6llu SHADOW-UNREAD a=0x%llX\n",(unsigned long long)now,(unsigned long long)g_t[j].o); g_t[j].ul=1; } continue; }
            if(g_t[j].ul){ printf("t=%6llu SHADOW-READ a=0x%llX\n",(unsigned long long)now,(unsigned long long)g_t[j].o); memcpy(g_t[j].b,b,BSZ); g_t[j].ul=0; continue; }
            for(uint32_t k=0;k<BSZ;k++) if(b[k]!=g_t[j].b[k]){ printf("t=%6llu SHADOW-CHG a=0x%llX +0x%03X %02X->%02X\n",(unsigned long long)now,(unsigned long long)g_t[j].o,k,g_t[j].b[k],b[k]); g_t[j].b[k]=b[k]; }
        }
        Sleep(ms);
    }
    SignedClose(); return 0;
}
