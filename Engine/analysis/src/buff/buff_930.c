/* buff_930.c — 버프(스킬) 읽기 정본 모듈 (10_5 규격) · 공용엔진(lbuff.h) 어댑터
 *  로직: core/lbuff.h (고정앵커 hud → cont → vft 서명 레코드, MmCopy 단일, 상수 registry)
 *  usage: buff_930.exe [registry] [secs] [out.txt]
 *  output: <exe>\out\buff_out.txt
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"
#include "lbuff.h"

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg = lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    const char *outp = lcreg_outpath("buff_out.txt");
    int secs = 0;
    { int seenReg=0;
      for(int i=1;i<argc;i++){
        if(strstr(argv[i],".txt")||strstr(argv[i],".out")){
          if(!seenReg && strstr(argv[i],"REGISTRY")){ reg=argv[i]; seenReg=1; } else outp=argv[i];
        } else if(atoi(argv[i])>0 && !strstr(argv[i],".")) secs=atoi(argv[i]);
      } }
    lcreg_load_first(reg, "registry/LC930_REGISTRY.txt"); lc_reg_apply();
    lbuff_load(reg);
    if(lc_attach()) return 1;
    if(!lc_anchor()){ fprintf(stderr,"anchor fail\n"); return 2; }
    lbuff_start();
    lcreg_poll P = lcreg_poll_load("BUFF");

    lcreg_mkdir_for(outp);
    FILE *f = fopen(outp,"w"); if(!f){ fprintf(stderr,"cannot open output: %s\n",outp); return 4; }
    fprintf(f,"# registry=%s strings=%d (BuffSubsystem+0x%X unordered_map walk, no BFS)\n",
        reg, B_sn, lcreg_u32("BUFF_MAP_OFF",0x260));

    DWORD t0=GetTickCount();
    LBuff out[128];
    int plen=0;                       /* 콘솔 직전 줄 길이(잔상 제거용) */
    do{
        LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr); QueryPerformanceCounter(&q0);
        g_ioctl=0;
        DWORD now=GetTickCount();
        int n = lbuff_poll(out, 128, now);
        for(int i=0;i<n;i++){
            LBuff *o=&out[i];
            fprintf(f,"  t=%ums name=%-26s 남은=%.1fs dur=%s skill=%-5u strID=%u%s\n",
                (unsigned)(now-t0), o->name, o->remain, o->perpet?"PERM":"", o->skill, o->strid,
                (o->remain<=0.0f ? (o->perpet?" [상시]":" [만료]") : ""));
        }
        QueryPerformanceCounter(&q1);
        fprintf(f,"# cache=%d n=%d ioctl=%llu time=%.4fms\n",
            B_ncache, n, g_ioctl, (q1.QuadPart-q0.QuadPart)*1000.0/fr.QuadPart);
        fflush(f);
        lcapi_sample(f);
        /* 실행창(콘솔): '현재 시점' 버프값만 한 줄로 실시간 갱신(\r). 이력 아님. */
        { char line[1200]; int len=snprintf(line,sizeof line,"[BUFF] t=%ums n=%d |",(unsigned)(now-t0),n);
          for(int i=0;i<n && len<(int)sizeof(line)-80;i++){ char nm[160]; int k=0;
            for(const char*p=out[i].name; *p && k<150; p++) nm[k++]=(*p=='\n'||*p=='\r')?' ':*p; nm[k]=0;
            len+=snprintf(line+len,sizeof(line)-len," %s(%.1f)",nm,out[i].remain); }
          printf("\r%s",line); for(int i=len;i<plen;i++) putchar(' '); fflush(stdout); plen=len; }
        if(secs) Sleep(lcreg_poll_sleep_ms(&P));
    } while(!lcapi_done() && secs && (int)(GetTickCount()-t0) < secs*1000);
    fclose(f); SignedClose();
    printf("\ndone -> %s\n", outp);
    return 0;
}