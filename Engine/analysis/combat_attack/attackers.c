/* attackers.c - 전 엔티티의 ActionComponent 내 AttackAction(+0x80/+0x88 GUID) 을 조사하여
 * "누가 나를 공격하는가"를 판독. AttackAction: +0x80=소유자 GUID, +0x88=대상 GUID.
 * usage: attackers.exe
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
#define VFT_AC 0x1180DC8u
#define VFT_ATA 0x1180AB8u
#define VFT_SELF 0x11819C0u
static const char* cls(uint32_t v){ switch(v){
  case 0x11819C0u:return"MyPlayer";case 0x1181988u:return"Player";case 0x1181878u:return"Monster";
  case 0x1181E28u:return"Monster(sum)";case 0x1181808u:return"Item";default:return"?"; } }
static int nameOf(uint64_t e,char*out,int cap){ out[0]=0; uint64_t H=q64(e+0x20); if(!isHeap(H))return 0;
    uint64_t no=q64(H+0x20); if(!isHeap(no))return 0; uint64_t len=q64(no+0x50),data=q64(no+0x40);
    if(len==0||len>(uint64_t)cap-1||len>200)return 0; uint64_t src=(len>=16)?data:(no+0x40);
    if(!rm(src,out,(uint32_t)len)){out[0]=0;return 0;} out[len]=0; return 1; }
typedef struct{uint64_t e,guid,vft;int cx,cy;uint64_t ac;char nm[80];}E; static E es[2048];static int ne=0;static uint64_t meE=0,meGuid=0;
int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0); PROCESSENTRY32W pe; pe.dwSize=sizeof(pe); DWORD pid=0;
    if(Process32FirstW(snap,&pe)) do{ if(_wcsicmp(pe.szExeFile,L"LC.exe")==0){pid=pe.th32ProcessID;break;} }while(Process32NextW(snap,&pe));
    CloseHandle(snap); if(!pid){printf("no LC.exe\n");return 1;}
    if(!SignedOpen()){printf("driver fail\n");return 1;}
    SignedSetTarget(pid); g_pid=pid; if(!getModule(&g_base,&g_modSize)){printf("module fail\n");return 1;}
    uint64_t subs=q64(q64(q64(g_base+0x1668860)+0xD0)+0x180);
    uint64_t actor=q64(subs+16*22);
    for(int hi=0;hi<2;hi++){ uint64_t sent=q64(actor+(hi?0x7D8:0x798)+8); if(!isHeap(sent))continue;
        uint64_t c=q64(sent+8);int g=0;
        while(isHeap(c)&&c!=sent&&g++<4000){uint64_t vb=q64(c+0x18),ve=q64(c+0x20);
            if(isHeap(vb)&&isHeap(ve)&&ve>=vb){int n=(int)((ve-vb)/8);
                for(int i=0;i<n;i++){uint64_t e=q64(vb+i*8);if(!isHeap(e))continue;
                    int dup=0;for(int k=0;k<ne;k++)if(es[k].e==e)dup=1;if(dup||ne>=2048)continue;
                    E*X=&es[ne++];X->e=e;X->vft=vrva(e);X->guid=q64(e+0x18);X->ac=0;X->cx=-1;X->cy=-1;
                    nameOf(e,X->nm,sizeof(X->nm));
                    uint64_t H=q64(e+0x20); if(isHeap(H)){uint64_t prb=q64(H); if(isHeap(prb)){X->cx=d32(prb+0x40);X->cy=d32(prb+0x44);}
                       uint64_t ac=q64(H+0x10); if(isHeap(ac)&&vrva(ac)==VFT_AC)X->ac=ac;}
                }}
            c=q64(c+8);}}
    for(int i=0;i<ne;i++) if(es[i].vft==VFT_SELF){meE=es[i].e;meGuid=es[i].guid;break;}
    uint64_t want=argc>1?strtoull(argv[1],0,16):meGuid;
    printf("BASE=0x%llX me=0x%llX meGuid=0x%llX want=0x%llX entities=%d\n",(unsigned long long)g_base,
      (unsigned long long)meE,(unsigned long long)meGuid,(unsigned long long)want,ne);
    int atkme=0;
    for(int i=0;i<ne;i++){ E*X=&es[i]; if(!X->ac) continue;
        /* ActionComponent 내 AttackAction 을 찾는다 (AC 슬롯 스캔) */
        for(int o=0;o<0x140;o+=8){ uint64_t w=q64(X->ac+o); if(!isHeap(w)||vrva(w)!=VFT_ATA)continue;
            uint64_t owner=q64(w+0x80), tgt=q64(w+0x88);
            const char* tag=""; if(tgt==want){tag="  <== ATTACKS ME";atkme++;}
            printf("%-13s guid=0x%llX cell=(%d,%d) \"%s\"  AttackAction@+0x%X owner=0x%llX tgt=0x%llX%s\n",
              cls(X->vft),(unsigned long long)X->guid,X->cx,X->cy,X->nm,o,
              (unsigned long long)owner,(unsigned long long)tgt,tag);
        }
    }
    printf("ATTACKS_ME=%d\n", atkme);
    SignedClose(); return 0;
}
