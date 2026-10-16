/* realtime_party_1009.c — 파티 실시간(저호출) 어댑터. 전역/BFS 금지.
 *  고정앵커+고정체인 + 캐시 + 배치 읽기 → 갱신 1회 드라이버 호출 <10.
 *  정보: 리더/멤버수, 멤버별 name/GUID/직업/HP%/MP%/좌표(+선택: 액터조인 lvl/dead/atk).
 *  계측: 갱신당 드라이버 호출수(g_sd_ioctls)·실행시간(ms) + 누적 avg/max.
 *  usage: realtime_party_1009.exe [registry] [secs] [period_ms] [out.txt]
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"
#include "signeddrv_client.h"
#include "lparty.h"

int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg=lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    const char *outp=lcreg_outpath("realtime_party_out.txt");
    int secs=0, period=-1;
    { int seenReg=0,nnum=0;
      for(int i=1;i<argc;i++){
        if(strstr(argv[i],".txt")||strstr(argv[i],".out")){ if(!seenReg&&strstr(argv[i],"REGISTRY")){reg=argv[i];seenReg=1;} else outp=argv[i]; }
        else if(atoi(argv[i])>0 && !strstr(argv[i],".")){ if(nnum==0)secs=atoi(argv[i]); else if(nnum==1)period=atoi(argv[i]); nnum++; }
      } }
    char regdisp[512]; snprintf(regdisp,sizeof regdisp,"%s",reg);
    lcreg_load(lcreg_resolve(reg,"registry/LC930_REGISTRY.txt")); lc_reg_apply();
    load_cfg();
    lp_regions_load();
    int showmap=(int)lcreg_u32("PARTY_SHOW_MAP",1);
    if(period<0) period=(int)lcreg_u32("REALTIME_PARTY_PERIOD_MS",1000); if(period<1) period=1;
    int dojoin=(int)lcreg_u32("PARTY_JOIN_ACTOR",0);
    if(lc_attach()) return 1;
    lcreg_poll P=lcreg_poll_load("REALTIME_PARTY");

    /* 앵커: 캐시 우선, 서명검증 실패 시 재탐색(고정앵커 vft) */
    uint64_t cbase=0,psub=0,party=0; lp_cache_load(&cbase,&psub,&party);
    const char*how="cache";
    if(!(cbase==g_base && lp_verify_subs(psub) && lp_verify(party))){
        psub=lp_discover_subs(); party=lp_resolve_from(psub); how="discover"; lp_cache_save(g_base,psub,party);
    }
    lcreg_mkdir_for(outp);
    FILE*f=fopen(outp,"w"); if(!f)return 4;
    fprintf(f,"# realtime_party registry=%s period=%dms how=%s sub=%016llX party=%016llX join=%d\n",
        regdisp,period,how,(unsigned long long)psub,(unsigned long long)party,dojoin);

    DWORD t0=GetTickCount(), lastOut=0, lastResolve=0;
    LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr);
    PMem mem[64]; int plen=0; long polls=0; unsigned long long sumR=0,maxR=0; double sumMs=0,maxMs=0;
    for(;;){
        DWORD now=GetTickCount();
        QueryPerformanceCounter(&q0);
        unsigned long long io0=g_sd_ioctls;
        int n=0; char leader[128]; uint32_t cnt=0;
        { int ok = (party!=0) ? lp_verify(party) : 0;
          if(!ok){
              party = lp_resolve_from(psub);                         /* 저렴 */
              if(!party && (int)(now-lastResolve)>=(int)P_RESCAN){   /* 비싼 재발견은 주기 제한 */
                  lastResolve=now; psub=lp_discover_subs(); party=lp_resolve_from(psub);
              }
          } }
        if(party){ n=lp_read_batch(party,mem,64,leader,sizeof leader,&cnt); }
        if(dojoin && party){ lc_collect(); lc_pick_self(); join_actors(mem,n); }
        QueryPerformanceCounter(&q1);
        double ms=(double)(q1.QuadPart-q0.QuadPart)*1000.0/(double)fr.QuadPart;
        unsigned long long rc=g_sd_ioctls-io0;
        polls++; sumR+=rc; if(rc>maxR)maxR=rc; sumMs+=ms; if(ms>maxMs)maxMs=ms;
        double avgR=(double)sumR/polls, avgMs=sumMs/polls;

        { char line[1500]; int len=snprintf(line,sizeof line,
            "[PARTY] t=%ums n=%d leader=%s driver_calls=%llu (avg=%.1f max=%llu) time=%.3fms (avg=%.3f max=%.3f) |",
            (unsigned)(now-t0),n,leader[0]?leader:"?",rc,avgR,maxR,ms,avgMs,maxMs);
          for(int i=0;i<n && len<(int)sizeof(line)-90;i++){ char nmn[80]; int k=0;
            for(const char*p=mem[i].name; *p&&k<70; p++) nmn[k++]=(*p=='\n'||*p=='\r')?' ':*p; nmn[k]=0;
            len+=snprintf(line+len,sizeof(line)-len,"%s%s(%u%%,%u%% %d,%d)",
                mem[i].isLeader?"[*]":" ",nmn,mem[i].hp,mem[i].mp,mem[i].x,mem[i].y); }
          printf("\r%s",line); for(int i=len;i<plen;i++) putchar(' '); fflush(stdout); plen=len; }

        if((int)(now-lastOut)>=period){ lastOut=now;
            fprintf(f,"\n=== t=%ums leader=%s cnt=%u members=%d driver_calls=%llu time=%.3fms%s ===\n",
                (unsigned)(now-t0),leader[0]?leader:"(?)",cnt,n,rc,ms, n?"":"  (no active party / 0 members)");
            for(int i=0;i<n;i++){ PMem*m=&mem[i]; char loc[200]; loc[0]=0;
                if(showmap){ char rg[96],sg[96]; lp_regionTwo(m->mapId,m->x,m->y,rg,sizeof rg,sg,sizeof sg);
                    snprintf(loc,sizeof loc,"map=%d region=%-20s subregion=%-20s ",m->mapId,rg,sg); }
                if(dojoin) fprintf(f,"  [%d]%s name=%-16s guid=%08llX type=%s cls=%u %shp%%=%u mp%%=%u pos=%d,%d lvl=%d dead=%d atk=%s\n",
                    i,m->isLeader?" [LEADER]":"         ",m->name,(unsigned long long)m->guid,lp_className(m->cls),m->cls,loc,m->hp,m->mp,m->x,m->y,m->lvlJoin,m->dead,m->hasAtk?m->tgtName:"-");
                else fprintf(f,"  [%d]%s name=%-16s guid=%08llX type=%s cls=%u %shp%%=%u mp%%=%u pos=%d,%d lead=%d f54=%08X\n",
                    i,m->isLeader?" [LEADER]":"         ",m->name,(unsigned long long)m->guid,lp_className(m->cls),m->cls,loc,m->hp,m->mp,m->x,m->y,m->isLeader,m->f54); }
            fflush(f);
        }
        if(secs && (int)(now-t0)>=secs*1000) break;
        Sleep(lcreg_poll_sleep_ms(&P));
    }
    fprintf(f,"\n# STATS polls=%ld avg_calls=%.1f max_calls=%llu avg_time=%.3fms max_time=%.3fms\n",
        polls,(double)sumR/polls,maxR,sumMs/polls,maxMs);
    fclose(f); SignedClose();
    printf("\ndone -> %s (polls=%ld avg_calls=%.1f max_calls=%llu avg_time=%.3fms)\n",outp,polls,(double)sumR/polls,maxR,sumMs/polls);
    return 0;
}
