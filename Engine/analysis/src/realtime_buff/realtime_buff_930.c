/* realtime_buff_930.c — 실시간 버프 출력 어댑터 (출력주기 설정)
 * ===========================================================================
 *  공용엔진 core/lbuff.h 를 그대로 사용. "출력주기(period)"마다 그 시점의
 *  버프값만 스냅샷으로 출력한다(안정성 검사용: 주기마다 값이 튀는지 확인).
 *
 *  usage: realtime_buff_930.exe [registry] [secs] [period_ms] [out.txt]
 *    secs      0=무한(종료는 Ctrl+C)
 *    period_ms 출력 주기(기본 registry REALTIME_BUFF_PERIOD_MS=1000)
 *  output: <exe>\out\realtime_buff_out.txt
 *
 *  폴링 간격: registry POLL_REALTIME_BUFF_INTERVAL_MS(+JITTER)
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
    const char *outp = lcreg_outpath("realtime_buff_out.txt");
    int secs=0, period=-1;
    { int seenReg=0, nnum=0;
      for(int i=1;i<argc;i++){
        if(strstr(argv[i],".txt")||strstr(argv[i],".out")){
          if(!seenReg && strstr(argv[i],"REGISTRY")){ reg=argv[i]; seenReg=1; } else outp=argv[i];
        } else if(atoi(argv[i])>0 && !strstr(argv[i],".")){
          if(nnum==0) secs=atoi(argv[i]); else if(nnum==1) period=atoi(argv[i]);
          nnum++;
        }
      } }
    lcreg_load(lcreg_resolve(reg, "registry/LC930_REGISTRY.txt")); lc_reg_apply();
    if(period<0) period = (int)lcreg_u32("REALTIME_BUFF_PERIOD_MS", 1000);
    if(period<1) period = 1;
    lbuff_load(reg);
    if(lc_attach()) return 1;
    if(!lc_anchor()){ fprintf(stderr,"anchor fail\n"); return 2; }
    lbuff_start();
    lcreg_poll P = lcreg_poll_load("REALTIME_BUFF");

    lcreg_mkdir_for(outp);
    FILE *f = NULL;

    DWORD t0=GetTickCount(), lastOut=0;
    LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr);
    LBuff out[128];
    int plen=0;                       /* 콘솔 직전 줄 길이(잔상 제거용) */
    for(;;){
        DWORD now=GetTickCount();
        QueryPerformanceCounter(&q0);
        g_ioctl=0;
        int n = lbuff_poll(out, 128, now);
        QueryPerformanceCounter(&q1);
        double ms=(double)(q1.QuadPart-q0.QuadPart)*1000.0/(double)fr.QuadPart;
        /* 현재 결과 한 줄 조립: [BUFF] t=..ms n=.. reads=.. time=..ms | name(rem) ... */
        char line[1400]; int len=snprintf(line,sizeof line,"[BUFF] t=%ums n=%d ioctl=%llu time=%.3fms |",
            (unsigned)(now-t0),n,(unsigned long long)g_ioctl,ms);
        for(int i=0;i<n && len<(int)sizeof(line)-80;i++){ char nm[160]; int k=0;
            for(const char*p=out[i].name; *p && k<150; p++) nm[k++]=(*p=='\n'||*p=='\r')?' ':*p; nm[k]=0;
            len+=snprintf(line+len,sizeof(line)-len," %s(%.1f)",nm,out[i].remain); }
        /* 실행창: 현재 결과 한 줄(\r 갱신). 이력 아님. */
        printf("\r%s",line); for(int i=len;i<plen;i++) putchar(' '); fflush(stdout); plen=len;
        /* 파일: '현재 결과 한 줄'만 — 주기마다 덮어씀(이력 아님) */
        if(lcapi_on() || (int)(now-lastOut) >= period){
            lastOut=now;
            if(lcapi_on()){ if(!f) f=fopen(outp,"a"); }
            else { if(f) fclose(f); f=fopen(outp,"w"); }
            if(f){ fprintf(f,"%s\n",line); fflush(f); lcapi_sample(f); }
        }
        if(lcapi_done() || (secs && (int)(now-t0) >= secs*1000)) break;
        Sleep(lcreg_poll_sleep_ms(&P));
    }
    if(f) fclose(f); SignedClose();
    printf("\ndone -> %s (period=%dms)\n", outp, period);
    return 0;
}