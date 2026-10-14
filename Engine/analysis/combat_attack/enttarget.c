/* enttarget.c - 주변 엔티티들의 타겟(공격 대상) 판독.
 *  체인(T1/T2): MGR->holder->sub[22](Actor) cellmap -> entity
 *    H = ent+0x20 ; ActionComponent = H+0x10 ; Controller = H+0x90
 *    Controller+0x58 = 활성 커맨드 ; cmd vft 0x1181018(Attack) -> +0x10/+0x18 = 대상 GUID
 *  + 나(MyPlayer) GUID 를 알아 "누가 나를 공격하는가" 표시.
 * usage: enttarget.exe [targetGuidHex]   (미지정시 자동: 나를 공격하는 자)
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
#define VFT_SUMMON 0x1181E28u
#define VFT_ACTOR 0x117DD98u
#define VFT_CTL 0x1180FE8u
#define VFT_CMD_ATTACK 0x1181018u
#define VFT_CMD_MOVE 0x1180E98u
static const char* cls(uint32_t v){
    switch(v){ case 0x11819C0u:return"MyPlayer";case 0x1181988u:return"Player";
      case 0x1181878u:return"Monster";case 0x117DD98u:return"Actor";case 0x1181808u:return"Item";
      case 0x1181E28u:return"SummonedMonster";case 0x11817D0u:return"InteractiveNPC";
      case 0x1181D28u:return"SegmentProp"; default:return"?"; }
}
static int entName(uint64_t e,char*out,int cap){ out[0]=0; uint64_t H=q64(e+0x20); if(!isHeap(H)) return 0;
    uint64_t no=q64(H+0x20); if(!isHeap(no)) return 0; uint64_t len=q64(no+0x50), data=q64(no+0x40);
    if(len==0||len>(uint64_t)cap-1||len>200) return 0;
    uint64_t src=(len>=16)?data:(no+0x40);
    if(!rm(src,out,(uint32_t)len)){ out[0]=0; return 0; } out[len]=0; return 1; }

typedef struct { uint64_t e; uint32_t vft; uint64_t guid; int cx,cy; uint64_t tgt; uint32_t cmdvft; int isAtk; char nm[128]; } ENT;
static ENT ents[8192]; static int nent=0;
static uint64_t me=0, meGuid=0; static int mcx=-1,mcy=-1;

static void collect(void){
    uint64_t subs=q64(q64(q64(g_base+0x1668860)+0xD0)+0x180);
    uint64_t actor=q64(subs+16*22);
    for(int hi=0;hi<2;hi++){ uint64_t sent=q64(actor+(hi?0x7D8:0x798)+8); if(!isHeap(sent)) continue;
        uint64_t cur=q64(sent+8); int g=0;
        while(isHeap(cur)&&cur!=sent&&g++<4000){
            uint64_t vb=q64(cur+0x18),ve=q64(cur+0x20);
            if(isHeap(vb)&&isHeap(ve)&&ve>=vb){ int n=(int)((ve-vb)/8); if(n>0&&n<5000){
                for(int i=0;i<n;i++){ uint64_t e=q64(vb+i*8); if(!isHeap(e)) continue;
                    int dup=0; for(int k=0;k<nent;k++) if(ents[k].e==e){dup=1;break;}
                    if(dup||nent>=8192) continue;
                    ENT*X=&ents[nent++]; X->e=e; X->vft=vrva(e); X->guid=q64(e+0x18);
                    uint64_t H=q64(e+0x20); int px=-1,py=-1;
                    if(isHeap(H)){ uint64_t prb=q64(H); if(isHeap(prb)){ px=(int)d32(prb+0x40); py=(int)d32(prb+0x44); } }
                    X->cx=px;X->cy=py; X->tgt=0; X->cmdvft=0; X->isAtk=0; entName(e,X->nm,sizeof(X->nm));
                    /* Controller -> active cmd -> target */
                    if(isHeap(H)){ uint64_t ctl=q64(H+0x90);
                      if(isHeap(ctl)&&vrva(ctl)==VFT_CTL){ uint64_t cmd=q64(ctl+0x58); uint32_t cv=vrva(cmd);
                        X->cmdvft=cv;
                        if(cv==VFT_CMD_ATTACK){ X->isAtk=1; X->tgt=q64(cmd+0x10); if(!X->tgt) X->tgt=q64(cmd+0x18); }
                      } }
                } } }
            cur=q64(cur+8); }
    }
}
int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0); PROCESSENTRY32W pe; pe.dwSize=sizeof(pe); DWORD pid=0;
    if(Process32FirstW(snap,&pe)) do{ if(_wcsicmp(pe.szExeFile,L"LC.exe")==0){pid=pe.th32ProcessID;break;} }while(Process32NextW(snap,&pe));
    CloseHandle(snap); if(!pid){ printf("no LC.exe\n"); return 1; }
    if(!SignedOpen()){ printf("driver fail\n"); return 1; }
    SignedSetTarget(pid); g_pid=pid;
    if(!getModule(&g_base,&g_modSize)){ printf("module fail\n"); return 1; }
    printf("BASE=0x%llX\n",(unsigned long long)g_base);
    collect();
    for(int i=0;i<nent;i++){ if(ents[i].vft==VFT_SELF||ents[i].vft==VFT_PLAYER){ me=ents[i].e; meGuid=ents[i].guid; mcx=ents[i].cx; mcy=ents[i].cy; break; } }
    printf("me=0x%llX guid=0x%llX cell=(%d,%d)\n",(unsigned long long)me,(unsigned long long)meGuid,mcx,mcy);
    uint64_t want=0;
    if(argc>1) want=strtoull(argv[1],0,16); else want=meGuid;
    int atkMe=0;
    printf("entities=%d  (target==0x%llX 이면 나)\n", nent, (unsigned long long)want);
    for(int i=0;i<nent;i++){ ENT*X=&ents[i];
        const char* tag="";
        if(X->isAtk){ if(X->tgt==want){ tag="  <== ATTACKS ME"; atkMe++; } else tag="  -> other"; }
        printf("%-16s vft=0x%X guid=0x%llX cell=(%d,%d) cmd=0x%X tgt=0x%llX%s nm=\"%s\"\n",
          cls(X->vft), X->vft, (unsigned long long)X->guid, X->cx, X->cy,
          X->cmdvft, (unsigned long long)X->tgt, tag, X->nm);
    }
    printf("ATTACKING_ME=%d\n", atkMe);
    SignedClose(); return 0;
}
