/* probe_owner.c - from a msg record node, follow +0x00 link back to list head, then find the
 * object that points to the head (the container owner). Record stride 0x80, key@+0x10. */
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
int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    uint64_t node = argc>1?strtoull(argv[1],0,16):0;
    HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0); PROCESSENTRY32W pe; pe.dwSize=sizeof(pe); DWORD pid=0;
    if(Process32FirstW(snap,&pe)) do{ if(_wcsicmp(pe.szExeFile,L"LC.exe")==0){pid=pe.th32ProcessID;break;} }while(Process32NextW(snap,&pe));
    CloseHandle(snap);
    if(!pid){printf("no LC.exe\n");return 1;}
    if(!SignedOpen())return 1;
    SignedSetTarget(pid); g_pid=pid;
    if(!getModule(&g_base,&g_modSize))return 1;
    /* walk +0x00 links backward */
    printf("== node chain via +0x00 (origin 0x%llX) ==\n",(unsigned long long)node);
    uint64_t n=node;
    for(int i=0;i<16;i++){ uint64_t nx=q(n);
        printf("  [%d] 0x%llX +00=0x%llX +08=0x%llX\n",i,(unsigned long long)n,(unsigned long long)nx,(unsigned long long)q(n+8));
        if(!isHeap(nx)||nx==n) break; n=nx; }
    printf("head guess=0x%llX\n",(unsigned long long)n);

    /* find refs to head (owner container) */
    printf("-- refs to head 0x%llX --\n",(unsigned long long)n);
    HANDLE hp=OpenProcess(0x1000,FALSE,pid); if(!hp){SignedClose();return 1;}
    MEMORY_BASIC_INFORMATION mbi; uint64_t addr=0x100000000ULL; uint8_t* buf=(uint8_t*)malloc(0x100000);
    int reads=0, found=0;
    while(addr<0x0000800000000000ULL && reads<40000 && found<40){
        if(!VirtualQueryEx(hp,(LPCVOID)(uintptr_t)addr,&mbi,sizeof(mbi))) break;
        uint64_t b=(uint64_t)(uintptr_t)mbi.BaseAddress,sz=(uint64_t)mbi.RegionSize;
        if(!sz)break;
        if(mbi.State==0x1000&&mbi.Type==0x20000&&!(mbi.Protect&0x100)&&(mbi.Protect&0xFF)!=0x01
           &&sz>=0x1000&&sz<0x80000000ULL&&isHeap(b)){
            for(uint64_t o=0;o<sz&&reads<40000&&found<40;o+=0x100000){
                uint32_t want=(uint32_t)((sz-o<0x100000)?(sz-o):0x100000);
                if(!rm(b+o,buf,want)){reads++;continue;} reads++;
                for(uint32_t i=0;i+8<=want;i+=8){
                    if(*(uint64_t*)(buf+i)==n){ printf("  @0x%llX\n",(unsigned long long)(b+o+i)); found++; }
                }
            }
        }
        uint64_t nx=b+sz; if(nx<=addr)break; addr=nx;
    }
    free(buf); CloseHandle(hp);
    printf("refs=%d\n",found);
    SignedClose(); return 0;
}
