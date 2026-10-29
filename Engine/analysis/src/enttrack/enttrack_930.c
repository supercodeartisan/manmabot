/* enttrack_930.c — 엔티티 종합 결과자료 출력 어댑터 (10_5 규격)
 *  공용 로직: core/lcore.h (엔티티·좌표보간·공격사건·가짜몬스터·거리·월드타일·수량)
 *  이 파일은 "출력 형식"을 담당. 원본 enttrack 양식(JSON)을 유지하고 확장.
 *  상수는 registry에서만. 프로그램별 읽기규격: POLL_ENTTRACK_*.
 * usage: enttrack_930.exe [registry] [secs] [text]
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char*reg=lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    const char*outp=lcreg_outpath("enttrack_out.txt");
    int secs=0, text=0;
    /* 인자: [registry(.txt) 觳矆歆竇 [secs] [text] [out(.txt/.out) 두번歆?於滊牓] */
    { int seenTxt=0;
      for(int i=1;i<argc;i++){
        if(!strcmp(argv[i],"text")){ text=1; continue; }
        if(atoi(argv[i])>0 && !strstr(argv[i],".")){ secs=atoi(argv[i]); continue; }
        if(strstr(argv[i],".txt")||strstr(argv[i],".out")){
          if(seenTxt==0){ reg=argv[i]; seenTxt=1; } else { outp=argv[i]; }
        }
      }
    }
    lcreg_load(reg);
    lc_reg_apply();
    LC_PPS=(float)lcreg_f("PPS",0.53); LC_VP_DX=(float)lcreg_f("VP_DX",1.8); LC_VP_DY=(float)lcreg_f("VP_DY",63.0);
    lcreg_poll P=lcreg_poll_load("ENTTRACK");

    if(lc_attach())return 1;
    if(!lc_anchor()){ fprintf(stderr,"anchor fail\n"); return 2; }
    HWND hwnd=lc_findGameWnd(g_pid); RECT rc={0,0,800,600}; if(hwnd)GetClientRect(hwnd,&rc);
    int cw=rc.right-rc.left, ch=rc.bottom-rc.top; if(cw<=0)cw=800; if(ch<=0)ch=600;
    LC_VIEW V; lc_viewCalc(&V,cw,ch);

    lcreg_mkdir_for(outp);
    FILE*f=fopen(outp,"w"); if(!f)return 4;
    DWORD t0=GetTickCount();
    do{
        LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr); QueryPerformanceCounter(&q0);
        g_ioctl=0;
        lc_collect(); lc_pick_self(); lc_derive(&V);
        LC_E*self=lc_findMe();
        int sCX=self?self->cellx:0, sCY=self?self->celly:0;
        float sScr=(float)V.sx, sScrY=(float)V.sy;

        if(text){
            fprintf(f,"\n=== t=%ums n=%d me=%08X cell=%d,%d scr=%.1f,%.1f scale=%.4f ===\n",
                (unsigned)(GetTickCount()-t0),lc_nc,(uint32_t)lc_meGuid,sCX,sCY,sScr,sScrY,V.sc);
            fprintf(f,"%-4s %-9s %-4s %-14s %-11s %-13s %-13s %-13s %-13s %-7s %-5s %-4s %-4s %-5s %-6s %-7s\n",
                "idx","cls","sp","name","tile","scr(확정)","iscr(보간)","iso","iiso","distT","dsn","qty","bait","self","own","contrib");
            for(int i=0;i<lc_nc;i++){ LC_E*X=&lc_cur[i];
                int qty=(X->vft==LC_VFT_ITEM||X->vft==VFT_SEGPROP)?(int)X->itemQty:-1;
                const char* own=(X->vft==LC_VFT_ITEM)?(X->itemOwn==1?"MINE":X->itemOwn==2?"OTHER":X->itemOwn==3?"FREE":"-"):"-";
                int contrib=(X->vft==LC_VFT_ITEM)?(int)X->itemContrib:-1;
                fprintf(f,"%-4d %-9s %-4u %-14s %5d,%5d %5d,%5d %5d,%5d %6.0f,%5.0f %6.0f,%5.0f %7.2f %-5d %-4d %-4d %-5d %-6s %-7d\n",
                    i,clsOf(X->vft),X->sp,X->nm,X->cellx,X->celly,
                    X->scrAX,X->scrAY,X->scrIX,X->scrIY,X->aU,X->aV,
                    X->iU,X->iV,X->distTile,(int)X->dead,qty,X->bait,(X->guid==lc_meGuid),own,contrib);
            }
        } else {
            /* 공용 스키마(lcore)로 출력 — etview 와 동일 */
            lc_jsonHead(f,t0,cw,ch,&V,sCX,sCY,sScr,sScrY,lc_nc);
            for(int i=0;i<lc_nc;i++) lc_jsonEnt(f,&lc_cur[i],cw,ch,i==0);
            lc_jsonFoot(f);
        }
        QueryPerformanceCounter(&q1);
        fprintf(f,"# ioctl=%llu time=%.4fms\n",g_ioctl,(q1.QuadPart-q0.QuadPart)*1000.0/fr.QuadPart);
        fflush(f);
        lcapi_sample(f);
        if(secs) Sleep(lcreg_poll_sleep_ms(&P));
    } while(!lcapi_done() && secs && (int)(GetTickCount()-t0)<secs*1000);
    fclose(f); SignedClose(); printf("done -> %s\n",outp); return 0;
}

