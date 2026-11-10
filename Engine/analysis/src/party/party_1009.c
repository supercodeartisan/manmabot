/* party_1009.c — 파티(PartySubsystem) 읽기 출력 어댑터 (10_9 규격, 저호출)
 *  공용엔진 src/party/lparty.h. 전역/BFS 금지: 고정앵커(vft)+고정체인+캐시+배치.
 *  usage: party_1009.exe [registry] [secs] [out.txt]
 *  output: <exe>\out\party_out.txt (파일=이력, 콘솔=현재값)
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
    const char *outp=lcreg_outpath("party_out.txt");
    int secs=0;
    { int seenReg=0;
      for(int i=1;i<argc;i++){
        if(strstr(argv[i],".txt")||strstr(argv[i],".out")){ if(!seenReg&&strstr(argv[i],"REGISTRY")){reg=argv[i];seenReg=1;} else outp=argv[i]; }
        else if(atoi(argv[i])>0 && !strstr(argv[i],".")) secs=atoi(argv[i]);
      } }
    char regdisp[512]; snprintf(regdisp,sizeof regdisp,"%s",reg);
    lcreg_load_first(reg, "registry/LC930_REGISTRY.txt"); lc_reg_apply();
    load_cfg();
    lp_regions_load();
    int showmap=(int)lcreg_u32("PARTY_SHOW_MAP",1);
    int dojoin=(int)lcreg_u32("PARTY_JOIN_ACTOR",0);
    if(lc_attach()) return 1;
    lcreg_poll P=lcreg_poll_load("PARTY");

    /* No party_cache.txt. Each sample walks PartySubsystem again. */
    const char*how="discover";
    lcreg_mkdir_for(outp);
    FILE*f=fopen(outp,"w"); if(!f)return 4;
    fprintf(f,"# registry=%s sub=%016llX rc=%08X how=%s join=%d\n",regdisp,0ull,P_VFT_RC,how,dojoin);

    DWORD t0=GetTickCount(); PMem mem[64]; int nmc=0, plen=0;
    do{
        LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr); QueryPerformanceCounter(&q0);
        unsigned long long io0=g_sd_ioctls;
        DWORD now=GetTickCount();
        uint64_t psub=lp_discover_subs();
        uint64_t mem_party=psub?lp_resolve_from(psub):0;
        int n=0, blind=0; char leader[128]={0}; uint32_t lf28=0,cnt=0;
        if(!psub) blind=1;
        else if(mem_party){ rm(mem_party+P_LLVL,&lf28,4); n=lp_read_batch(mem_party,mem,64,leader,sizeof leader,&cnt);
            if(n<0){ blind=1; n=0; }
            else if(dojoin){ lc_collect(); lc_pick_self(); join_actors(mem,n); } }
        nmc=n;
        QueryPerformanceCounter(&q1);
        unsigned long long rc=g_sd_ioctls-io0;
        fprintf(f,"# party t=%ums how=%s leader=%s lf28=%u cnt=%u members=%d driver_calls=%llu time=%.4fms%s\n",
            (unsigned)(now-t0),how,leader[0]?leader:"(?)",lf28,cnt,n,rc,(q1.QuadPart-q0.QuadPart)*1000.0/fr.QuadPart,
            blind ? "  (party verify blind)" : (n? "":"  (no active party / 0 members)"));
        if(blind) fprintf(f,"party_verify=blind\n");
        for(int i=0; !blind && i<n; i++){ PMem*m=&mem[i];
            if(showmap){ char rg[96],sg[96]; lp_regionTwo(m->mapId,m->x,m->y,rg,sizeof rg,sg,sizeof sg);
                fprintf(f,"  [%d]%s name=%-16s guid=%08llX type=%s cls=%u map=%d region=%-20s subregion=%-20s hp%%=%u mp%%=%u pos=%d,%d lvl=%d dead=%d atk=%s(%08llX)\n",
                    i,m->isLeader?" [LEADER]":"         ",m->name,(unsigned long long)m->guid,lp_className(m->cls),m->cls,m->mapId,rg,sg,m->hp,m->mp,m->x,m->y,m->lvlJoin,m->dead,
                    m->hasAtk?m->tgtName:"-",(unsigned long long)(m->hasAtk?m->atkTgt:0)); }
            else fprintf(f,"  [%d]%s name=%-16s guid=%08llX type=%s cls=%u hp%%=%u mp%%=%u pos=%d,%d lvl=%d dead=%d atk=%s(%08llX)\n",
                    i,m->isLeader?" [LEADER]":"         ",m->name,(unsigned long long)m->guid,lp_className(m->cls),m->cls,m->hp,m->mp,m->x,m->y,m->lvlJoin,m->dead,
                    m->hasAtk?m->tgtName:"-",(unsigned long long)(m->hasAtk?m->atkTgt:0)); }
        fflush(f);
        lcapi_sample(f);
        { char line[1400]; int len=snprintf(line,sizeof line,"[PARTY] t=%ums n=%d leader=%s driver_calls=%llu |",(unsigned)(now-t0),nmc,leader[0]?leader:"?",rc);
          for(int i=0;i<nmc && len<(int)sizeof(line)-90;i++){ char nmn[80]; int k=0;
            for(const char*p=mem[i].name; *p&&k<70; p++) nmn[k++]=(*p=='\n'||*p=='\r')?' ':*p; nmn[k]=0;
            len+=snprintf(line+len,sizeof(line)-len,"%s%s(%u%%,%u%% %d,%d)",mem[i].isLeader?"[*]":" ",nmn,mem[i].hp,mem[i].mp,mem[i].x,mem[i].y); }
          printf("\r%s",line); for(int i=len;i<plen;i++) putchar(' '); fflush(stdout); plen=len; }
        if(secs) Sleep(lcreg_poll_sleep_ms(&P));
    } while(!lcapi_done() && secs && (int)(GetTickCount()-t0)<secs*1000);
    fclose(f); SignedClose(); printf("\ndone -> %s\n",outp); return 0;
}
