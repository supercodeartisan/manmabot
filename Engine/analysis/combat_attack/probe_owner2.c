/* probe_owner2.c - dump the msg owner object and its +0x00 child (string node with keys),
 * to find the exact path: owner -> node pool -> key record -> entry -> text. */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "signeddrv_client.h"
#define MGR 0x1668860u
static uint64_t g_pid=0,g_base=0; static uint32_t g_modSize=0,g_br=0;
static int rm(uint64_t a,void*b,uint32_t s){return SignedReadMemory(g_pid,a,b,s,&g_br)&&g_br==s;}
static uint64_t q(uint64_t a){uint64_t v=0;rm(a,&v,8);return v;}
static uint32_t d32(uint64_t a){uint32_t v=0;rm(a,&v,4);return v;}
static int isHeap(uint64_t a){return a>=0x10000000000ULL&&a<0x70000000000ULL;}
static int isMod(uint64_t a){return a>=g_base&&a<g_base+g_modSize;}
static uint32_t vrva(uint64_t o){uint64_t v=q(o);return isMod(v)?(uint32_t)(v-g_base):0;}
static int getModule(uint64_t*base,uint32_t*size){
    uint64_t peb=0,ldr=0,head=0,cur=0;
    if(!SignedGetPeb(g_pid,&peb)||!peb)return 0;
    if(!rm(peb+0x18,&ldr,8)||!ldr)return 0;
    if(!rm(ldr+0x20,&head,8)||!head)return 0;
    cur=head;
    for(int g=0;g<5000&&cur&&cur!=(ldr+0x20);g++){
        uint64_t e=cur-0x10,db=0;uint32_t ds=0;
        if(rm(e+0x30,&db,8)&&db&&rm(e+0x40,&ds,4)&&ds){*base=db;*size=ds;return 1;}
        if(!rm(cur,&cur,8))break;
    }
    return 0;
}
static int readSso(uint64_t a, char* out, int outSz){
    uint8_t h[0x20]; if(outSz<2||!rm(a,h,sizeof(h))) return -1;
    uint64_t size=*(uint64_t*)(h+0x10), cap=*(uint64_t*)(h+0x18);
    if(size==0||size>0x300||cap>0x100000) return -1;
    if((int)size>=outSz) size=outSz-1;
    if(cap<=0xF) memcpy(out,h,(size_t)size);
    else { uint64_t p=*(uint64_t*)h; if(!isHeap(p)||!rm(p,out,(uint32_t)size)) return -1; }
    out[size]=0; return (int)size;
}
static void dump(const char* tag,uint64_t o,int n){
    printf("-- %s 0x%llX --\n",tag,(unsigned long long)o);
    for(int i=0;i<n;i+=8){ uint64_t v=q(o+i);
        char s[96]; int hs=(readSso(o+i,s,sizeof(s))>0&&s[0]);
        printf("  +%03X %016llX mod=%X heap=%d %s%s\n",i,(unsigned long long)v,vrva(o+i),isHeap(v),hs?"[sso]":"",hs?s:""); }
}
int main(void){
    SetConsoleOutputCP(CP_UTF8);
    HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0); PROCESSENTRY32W pe; pe.dwSize=sizeof(pe); DWORD pid=0;
    if(Process32FirstW(snap,&pe)) do{ if(_wcsicmp(pe.szExeFile,L"LC.exe")==0){pid=pe.th32ProcessID;break;} }while(Process32NextW(snap,&pe));
    CloseHandle(snap);
    if(!pid){printf("no LC.exe\n");return 1;}
    if(!SignedOpen())return 1;
    SignedSetTarget(pid); g_pid=pid;
    if(!getModule(&g_base,&g_modSize))return 1;
    uint64_t mgr=q(g_base+MGR);
    uint64_t owner=q(mgr+0x18);
    printf("mgr=0x%llX owner(mgr+0x18)=0x%llX\n",(unsigned long long)mgr,(unsigned long long)owner);
    dump("owner",owner,0x80);
    uint64_t c0=q(owner); if(isHeap(c0)) dump("owner+0x00",c0,0xC0);
    uint64_t c8=q(owner+8); if(isHeap(c8)) dump("owner+0x08",c8,0xA0);
    SignedClose(); return 0;
}
