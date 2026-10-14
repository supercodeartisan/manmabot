/* enttarget2.c - 주변 엔티티 타겟 판독 (AI/액터 컨트롤러 모두 지원)
 *  엔티티 H(ent+0x20) 의 컴포넌트 중:
 *    ActorControllerComponent  vft 0x1180FE8  -> AttackCommand 0x1181018 (+0x10 대상 GUID)
 *    AIControllerComponent     vft 0x117F0D0  -> AttackCommand@AI 0x117F098 (+0x10 대상 GUID)
 *  컴포넌트 열거: H 내 shared_ptr 쌍(obj,ctrl) 순회
 * usage: enttarget2.exe [targetGuidHex]
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
static int inMod(uint64_t a){ return a>=g_base&&a<g_base+(uint64_t)g_modSize; }
static int isHeap(uint64_t a){ return a>=0x10000000000ULL&&a<0x80000000000ULL; }
static uint32_t vrva(uint64_t a){ uint64_t v=q64(a); return inMod(v)?(uint32_t)(v-g_base):0; }
static int getModule(uint64_t*base,uint32_t*size){
    uint64_t peb=0,ldr=0,head=0,cur=0;
    if(!SignedGetPeb(g_pid,&peb)||!peb)return 0;
    if(!rm(peb+0x18,&ldr,8)||!ldr)return 0;
    if(!rm(ldr+0x20,&head,8)||!head)return 0; cur=head;
    for(int g=0;g<5000&&cur&&cur!=(ldr+0x20);g++){ uint64_t e=cur-0x10,db=0; uint32_t ds=0;
        if(rm(e+0x30,&db,8)&&db&&rm(e+0x40,&ds,4)&&ds){*base=db;*size=ds;return 1;}
        if(!rm(cur,&cur,8))break; } return 0;
}
#define VFT_SELF 0x11819C0u
#define VFT_PLAYER 0x1181988u
#define VFT_MONSTER 0x1181878u
#define VFT_AI 0x1181E28u
#define VFT_ACTCTL 0x1180FE8u
#define VFT_AICTL 0x117F0D0u
#define VFT_ATK_ACT 0x1181018u
#define VFT_ATK_AI 0x117F098u
static const char* cls(uint32_t v){ switch(v){
  case 0x11819C0u:return"MyPlayer";case 0x1181988u:return"Player";case 0x1181878u:return"Monster";
  case 0x117DD98u:return"Actor";case 0x1181808u:return"Item";case 0x1181E28u:return"Monster";
  case 0x11817D0u:return"InterNPC";case 0x1181D28u:return"SegmentProp";default:return"?"; } }
static int nameOf(uint64_t e,char*out,int cap){ out[0]=0; uint64_t H=q64(e+0x20); if(!isHeap(H))return 0;
    uint64_t no=q64(H+0x20); if(!isHeap(no))return 0; uint64_t len=q64(no+0x50),data=q64(no+0x40);
    if(len==0||len>(uint64_t)cap-1||len>200)return 0; uint64_t src=(len>=16)?data:(no+0x40);
    if(!rm(src,out,(uint32_t)len)){out[0]=0;return 0;} out[len]=0; return 1; }
/* 컴포넌트 vft 스캔: H 내 모든 heap 포인터를 검사 */
static int findCmdTarget(uint64_t H, uint64_t* outTgt, uint32_t* outCtlKind){
    *outTgt=0; *outCtlKind=0;
    for(int o=0;o<0x300;o+=8){
        uint64_t obj=q64(H+o); if(!isHeap(obj)) continue;
        uint32_t v=vrva(obj);
        if(v==VFT_ACTCTL){ uint64_t cmd=q64(obj+0x58); if(vrva(obj+0x58)==VFT_ATK_ACT){ *outTgt=q64(cmd+0x10); *outCtlKind=VFT_ACTCTL; if(*outTgt) return 1; } }
        else if(v==VFT_AICTL){ uint64_t cmd=q64(obj+0x58); if(vrva(obj+0x58)==VFT_ATK_AI){ *outTgt=q64(cmd+0x10); *outCtlKind=VFT_AICTL; if(*outTgt) return 1; } }
    }
    return 0;
}
int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0); PROCESSENTRY32W pe; pe.dwSize=sizeof(pe); DWORD pid=0;
    if(Process32FirstW(snap,&pe)) do{ if(_wcsicmp(pe.szExeFile,L"LC.exe")==0){pid=pe.th32ProcessID;break;} }while(Process32NextW(snap,&pe));
    CloseHandle(snap); if(!pid){printf("no LC.exe\n");return 1;}
    if(!SignedOpen()){printf("driver fail\n");return 1;}
    SignedSetTarget(pid); g_pid=pid; if(!getModule(&g_base,&g_modSize)){printf("module fail\n");return 1;}
    uint64_t subs=q64(q64(q64(g_base+0x1668860)+0xD0)+0x180);
    uint64_t actor=q64(subs+16*22);
    uint64_t meGuid=0;
    for(int hi=0;hi<2;hi++){ uint64_t sent=q64(actor+(hi?0x7D8:0x798)+8); if(!isHeap(sent))continue;
        uint64_t c=q64(sent+8);int g=0;
        while(isHeap(c)&&c!=sent&&g++<4000){uint64_t vb=q64(c+0x18),ve=q64(c+0x20);
            if(isHeap(vb)&&isHeap(ve)&&ve>=vb){int n=(int)((ve-vb)/8);
                for(int i=0;i<n;i++){uint64_t e=q64(vb+i*8);if(isHeap(e)&&vrva(e)==VFT_SELF)meGuid=q64(e+0x18);}}
            c=q64(c+8);}}
    uint64_t want=(argc>1)?strtoull(argv[1],0,16):meGuid;
    printf("BASE=0x%llX meGuid=0x%llX want=0x%llX\n",(unsigned long long)g_base,(unsigned long long)meGuid,(unsigned long long)want);
    int atkMe=0, total=0;
    for(int hi=0;hi<2;hi++){ uint64_t sent=q64(actor+(hi?0x7D8:0x798)+8); if(!isHeap(sent))continue;
        uint64_t c=q64(sent+8);int g=0;
        while(isHeap(c)&&c!=sent&&g++<4000){
            uint64_t vb=q64(c+0x18),ve=q64(c+0x20);
            if(isHeap(vb)&&isHeap(ve)&&ve>=vb){int n=(int)((ve-vb)/8);
                for(int i=0;i<n;i++){uint64_t e=q64(vb+i*8);if(!isHeap(e))continue;
                    uint32_t v=vrva(e); if(v!=VFT_MONSTER&&v!=VFT_SELF&&v!=VFT_PLAYER&&v!=0x1181E28u) continue;
                    uint64_t H=q64(e+0x20); if(!isHeap(H))continue;
                    uint64_t cellx=(uint64_t)-1,celly=(uint64_t)-1;
                    uint64_t prb=q64(H); if(isHeap(prb)){ cellx=d32(prb+0x40); celly=d32(prb+0x44); }
                    uint64_t tgt=0; uint32_t kind=0;
                    findCmdTarget(H,&tgt,&kind);
                    char nm[96]; nameOf(e,nm,sizeof(nm));
                    const char* tag="";
                    if(tgt){ total++; if(tgt==want){tag="  <== TARGETS ME"; atkMe++;} else tag="  -> other"; }
                    printf("%-10s guid=0x%llX cell=(%lld,%lld) ctl=%s tgt=0x%llX%s nm=\"%s\"\n",
                      cls(v),(unsigned long long)q64(e+0x18),(long long)cellx,(long long)celly,
                      kind==VFT_AICTL?"AI":(kind==VFT_ACTCTL?"ACTOR":"-"),
                      (unsigned long long)tgt,tag,nm);
                }}
            c=q64(c+8);}}
    printf("ATTACKING=%d  ATTACKING_ME=%d\n", total, atkMe);
    SignedClose(); return 0;
}
