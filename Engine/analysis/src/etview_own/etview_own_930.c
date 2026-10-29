/* etview_own_930.c — 엔티티 시각화 + 아이템 소유권(pickable) 오버레이 (10_5 규격)
 *  기반: src/etview/etview_930.c (원본 보존). 추가:
 *   - 아이템마다 **item+0x44**(예약/귀속 후보) 읽어 표시: !=0 → MINE(내 것)
 *   - **last-hit** 추론(소스몹 guid-인접 + AttackAction owner) 라벨 MINE/OTHER/FREE 병기
 *   - 아이템 마커 색: own!=0=청록(MINE), lh=OTHER=주황적, 그외=초록
 *  공격사건 시각화(etview 원본과 동일 규격):
 *   - 공격자→대상 주황 선 + 공격자 주황 마커 + 대상 빨간 X, 나를 공격하면 굵은 X(이중)
 *   - 신규/타깃변경 시 로그 1건 `[ATK] t=… 공격자(guid) -> 대상guid 대상이름 [<== ME]`
 *   - ASCII 로그에 활성 공격수/나를 향한 공격수 요약
 *  usage: etview_own_930.exe [registry] [secs] [out.bmp] [json]
 *  키: Q/ESC 종료, F9 BMP저장
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"
#pragma comment(lib,"gdi32.lib")
#pragma comment(lib,"user32.lib")

#define OVW 80
#define OVH 30
#define MAXM 4096
#define DELTA_MAX 8
#define SEEN_WIN 8000
#define CELL_WIN 6

static uint32_t OFF_OWN=0x44, OFF_40=0x40;
/* 최근 몹(소스 후보) */
static uint64_t mg_guid[MAXM]; static int mg_cx[MAXM],mg_cy[MAXM]; static DWORD mg_last[MAXM]; static int mg_n=0;
static void monUpd(uint64_t g,int cx,int cy,DWORD t){
    for(int i=0;i<mg_n;i++) if(mg_guid[i]==g){ mg_cx[i]=cx; mg_cy[i]=cy; mg_last[i]=t; return; }
    if(mg_n<MAXM){ mg_guid[mg_n]=g; mg_cx[mg_n]=cx; mg_cy[mg_n]=cy; mg_last[mg_n]=t; mg_n++; } }
/* last-attacker 맵 */
static uint64_t ak_v[4096], ak_o[4096]; static DWORD ak_t[4096]; static int ak_n=0;
static void atkSet(uint64_t v,uint64_t o,DWORD t){ for(int i=0;i<ak_n;i++) if(ak_v[i]==v){ ak_o[i]=o; ak_t[i]=t; return; }
    if(ak_n<4096){ ak_v[ak_n]=v; ak_o[ak_n]=o; ak_t[ak_n]=t; ak_n++; } }
static uint64_t atkGet(uint64_t v,DWORD now){ for(int i=0;i<ak_n;i++) if(ak_v[i]==v && (int)(now-ak_t[i])<=SEEN_WIN) return ak_o[i]; return 0; }
static const char* lhLabel(LC_E*X,DWORD now){
    uint64_t best=0; int bd=0;
    for(int i=0;i<mg_n;i++){ uint64_t g=mg_guid[i];
        if(X->guid<=g) continue; uint64_t d=X->guid-g; if(d>DELTA_MAX) continue;
        if((int)(now-mg_last[i])>SEEN_WIN) continue;
        if(abs(mg_cx[i]-X->cellx)>CELL_WIN||abs(mg_cy[i]-X->celly)>CELL_WIN) continue;
        if(!best||d<(uint64_t)bd){ best=g; bd=(int)d; } }
    if(!best) return "?";
    uint64_t ow=atkGet(best,now);
    return (ow==lc_meGuid&&ow)?"MINE":(ow?"OTHER":"FREE");
}

static HWND  g_wnd=0, g_gwnd=0;
static HDC   g_memDC=0; static HBITMAP g_hbm=0; static HGDIOBJ g_oldBm=0;
static BYTE* g_bits=0; static int g_stride=0,g_bw=0,g_bh=0;
static HFONT g_font=0;
static const char* g_bmpAuto=0;
static int   g_quit=0;

static void recreateDIB(int w,int h){
    if(g_memDC){ SelectObject(g_memDC,g_oldBm); DeleteObject(g_hbm); DeleteDC(g_memDC); g_memDC=0; }
    if(!g_font) g_font=CreateFontA(13,0,0,0,FW_BOLD,0,0,0,DEFAULT_CHARSET,
        OUT_DEFAULT_PRECIS,CLIP_DEFAULT_PRECIS,CLEARTYPE_QUALITY,DEFAULT_PITCH,"Malgun Gothic");
    HDC s=GetDC(NULL);
    g_memDC=CreateCompatibleDC(s);
    BITMAPINFO bi; memset(&bi,0,sizeof(bi));
    bi.bmiHeader.biSize=sizeof(BITMAPINFOHEADER);
    bi.bmiHeader.biWidth=w; bi.bmiHeader.biHeight=-h;
    bi.bmiHeader.biPlanes=1; bi.bmiHeader.biBitCount=32; bi.bmiHeader.biCompression=BI_RGB;
    void* pv=0; g_hbm=CreateDIBSection(s,&bi,DIB_RGB_COLORS,&pv,0,0);
    g_bits=(BYTE*)pv; g_oldBm=SelectObject(g_memDC,g_hbm); SelectObject(g_memDC,g_font);
    ReleaseDC(NULL,s);
    g_stride=w*4; g_bw=w; g_bh=h;
}
static int capture(void){
    RECT rc; if(!GetClientRect(g_gwnd,&rc)) return 0;
    int cw=rc.right, ch=rc.bottom; if(cw<2||ch<2) return 0;
    if(cw!=g_bw||ch!=g_bh) recreateDIB(cw,ch);
    HDC wdc=GetDC(g_gwnd); BOOL ok=BitBlt(g_memDC,0,0,cw,ch,wdc,0,0,SRCCOPY); ReleaseDC(g_gwnd,wdc);
    return ok?1:0;
}
static void marker(HDC dc,int x,int y,COLORREF c){
    HPEN pen=CreatePen(PS_SOLID,2,c); HGDIOBJ op=SelectObject(dc,pen);
    HGDIOBJ ob=SelectObject(dc,GetStockObject(NULL_BRUSH));
    Ellipse(dc,x-8,y-8,x+8,y+8);
    MoveToEx(dc,x-6,y,0); LineTo(dc,x+6,y);
    MoveToEx(dc,x,y-6,0); LineTo(dc,x,y+6);
    SelectObject(dc,op); SelectObject(dc,ob); DeleteObject(pen);
}
static void lineAt(HDC dc,int x0,int y0,int x1,int y1,COLORREF c,int w){
    HPEN p=CreatePen(PS_SOLID,w,c); HGDIOBJ o=SelectObject(dc,p);
    MoveToEx(dc,x0,y0,0); LineTo(dc,x1,y1); SelectObject(dc,o); DeleteObject(p);
}
static void crossX(HDC dc,int x,int y,int len,COLORREF c){
    HPEN p=CreatePen(PS_SOLID,2,c); HGDIOBJ o=SelectObject(dc,p);
    MoveToEx(dc,x-len,y-len,0); LineTo(dc,x+len,y+len);
    MoveToEx(dc,x-len,y+len,0); LineTo(dc,x+len,y-len);
    SelectObject(dc,o); DeleteObject(p);
}
static uint64_t pAtkG[LC_MAXE], pAtkT[LC_MAXE]; static int pAtkN=0;
static int prevAtk(uint64_t g,uint64_t*pt){ for(int i=0;i<pAtkN;i++) if(pAtkG[i]==g){ if(pt)*pt=pAtkT[i]; return 1; } return 0; }

static void textOut(HDC dc,int x,int y,const char* u8,COLORREF c){
    if(!u8||!u8[0]) return;
    wchar_t wb[128]; int n=MultiByteToWideChar(CP_UTF8,0,u8,-1,wb,127); if(n<=0) return; wb[127]=0;
    SetBkMode(dc,TRANSPARENT);
    SetTextColor(dc,RGB(0,0,0));
    for(int dx=-1;dx<=1;dx++)for(int dy=-1;dy<=1;dy++) if(dx||dy) TextOutW(dc,x+dx,y+dy,wb,n-1);
    SetTextColor(dc,c); TextOutW(dc,x,y,wb,n-1);
}
static void saveBMP(const char* path){
    if(!g_bits) return;
    int w=g_bw,h=g_bh,size=w*4*h;
    BITMAPFILEHEADER fh; memset(&fh,0,sizeof(fh)); fh.bfType=0x4D42; fh.bfOffBits=54; fh.bfSize=54+size;
    BITMAPINFOHEADER ih; memset(&ih,0,sizeof(ih)); ih.biSize=40; ih.biWidth=w; ih.biHeight=-h; ih.biPlanes=1; ih.biBitCount=32; ih.biSizeImage=size;
    FILE*fp=fopen(path,"wb"); if(!fp) return;
    fwrite(&fh,sizeof(fh),1,fp); fwrite(&ih,sizeof(ih),1,fp); fwrite(g_bits,1,size,fp); fclose(fp);
    printf("saved %s (%dx%d)\n",path,w,h);
}
static LRESULT CALLBACK wp(HWND h,UINT m,WPARAM w,LPARAM l){
    if(m==WM_DESTROY){ PostQuitMessage(0); return 0; }
    if(m==WM_KEYDOWN){ int vk=(int)w;
        if(vk=='Q'||vk==VK_ESCAPE){ g_quit=1; PostQuitMessage(0); }
        else if(vk==VK_F9){ saveBMP(lcreg_outpath("etview_own_shot.bmp")); } }
    (void)h;(void)l; return DefWindowProcA(h,m,w,l);
}
static COLORREF colOf(LC_E* X,int own,DWORD now){
    if(X->guid==lc_meGuid) return RGB(255,255,255);
    if(X->dead) return RGB(90,90,90);
    if(X->bait) return RGB(120,80,40);
    const char* c=clsOf(X->vft);
    if(!strcmp(c,"Monster")) return RGB(255,40,40);
    if(!strcmp(c,"Player"))  return RGB(255,220,0);
    if(!strcmp(c,"Item")){
        if(own) return RGB(0,255,255);                 /* 내 것 (item+0x44!=0) */
        if(!strcmp(lhLabel(X,now),"OTHER")) return RGB(255,140,0);
        return RGB(40,255,40);
    }
    if(!strcmp(c,"NPC"))     return RGB(0,220,220);
    if(!strcmp(c,"Ship"))    return RGB(170,80,255);
    return RGB(160,160,160);
}
static char gridChar(LC_E* X){
    if(X->vft==LC_VFT_SELF)    return '@';
    if(X->vft==LC_VFT_MONSTER) return X->bait?'b':'M';
    if(X->vft==LC_VFT_NPC)     return 'n';
    if(X->vft==LC_VFT_ITEM)    return 'i';
    return X->dead?'d':'?';
}

int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char* reg=lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    const char* outp=lcreg_outpath("etview_own_out.txt");
    int secs=0; int wantJson=0; int seenTxt=0;
    for(int i=1;i<argc;i++){
        if(!strcmp(argv[i],"json")){ wantJson=1; continue; }
        if(strstr(argv[i],".bmp")){ g_bmpAuto=argv[i]; continue; }
        if(atoi(argv[i])>0 && !strstr(argv[i],".")){ secs=atoi(argv[i]); continue; }
        if(strstr(argv[i],".txt")||strstr(argv[i],".out")){ if(seenTxt==0){ reg=argv[i]; seenTxt=1; } else outp=argv[i]; }
    }
    lcreg_load(lcreg_resolve(reg,"registry/LC930_REGISTRY.txt")); lc_reg_apply();
    OFF_OWN = lcreg_u32("OFF_ITEM_OWN", 0x44); OFF_40 = lcreg_u32("OFF_ITEM_40", 0x40);
    lcreg_poll P=lcreg_poll_load("ENTVIEW");
    if(lc_attach()) return 1;
    if(!lc_anchor()){ fprintf(stderr,"anchor fail\n"); return 2; }
    g_gwnd=lc_findGameWnd((DWORD)g_pid);
    if(!g_gwnd){ fprintf(stderr,"no game window\n"); return 3; }
    RECT rc; GetClientRect(g_gwnd,&rc);
    int cw=rc.right, ch=rc.bottom; if(cw<2)cw=800; if(ch<2)ch=600;
    WNDCLASSA wc; memset(&wc,0,sizeof(wc));
    wc.lpfnWndProc=wp; wc.hInstance=GetModuleHandleA(NULL); wc.lpszClassName="ETViewOwn10_5";
    wc.hCursor=LoadCursorA(NULL,IDC_ARROW); wc.hbrBackground=(HBRUSH)GetStockObject(BLACK_BRUSH);
    RegisterClassA(&wc);
    RECT adj={0,0,cw,ch}; AdjustWindowRectEx(&adj,WS_OVERLAPPEDWINDOW,FALSE,0);
    RECT gr; GetWindowRect(g_gwnd,&gr);
    g_wnd=CreateWindowExA(0,"ETViewOwn10_5",
        "ETView-OWN  item: cyan=item+0x44!=0(MINE) orange=lasthit OTHER green=else  ATK: orange=attacker->red X target  (Q quit,F9 bmp)",
        WS_OVERLAPPEDWINDOW|WS_VISIBLE, gr.left+8, gr.top, adj.right-adj.left, adj.bottom-adj.top,
        NULL,NULL,wc.hInstance,NULL);
    recreateDIB(cw,ch);
    lcreg_mkdir_for(outp);
    FILE* f=fopen(outp,"w"); if(!f) return 4;
    fprintf(f,"# registry=%s ETVIEW_OWN interval=%ums jitter=%ums view=%dx%d OFF_OWN=%X\n",
        reg,P.interval_ms,P.jitter_ms,cw,ch,OFF_OWN);
    FILE* fj=0;
    if(wantJson){ char jp[512]; snprintf(jp,sizeof(jp),"%s.json",outp); fj=fopen(jp,"w");
        if(fj) fprintf(fj,"# etview_own json\n"); }

    DWORD t0=GetTickCount(); MSG msg;
    while(!g_quit){
        while(PeekMessageA(&msg,NULL,0,0,PM_REMOVE)){ if(msg.message==WM_QUIT){ g_quit=1; break; } TranslateMessage(&msg); DispatchMessageA(&msg); }
        if(g_quit) break;
        if(secs && (int)(GetTickCount()-t0)>=secs*1000) break;
        LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr); QueryPerformanceCounter(&q0); g_ioctl=0;
        if(!capture()){ Sleep(20); continue; }
        lc_collect(); lc_pick_self(); DWORD now=GetTickCount();
        LC_VIEW V; lc_viewCalc(&V,g_bw,g_bh);

        /* last-hit 맵 갱신 */
        for(int i=0;i<lc_nc;i++){ LC_E*X=&lc_cur[i]; if(X->hasAtk&&X->atkTgt&&X->atkOwner) atkSet(X->atkTgt,X->atkOwner,now); }
        for(int i=0;i<lc_nc;i++){ LC_E*X=&lc_cur[i];
            if(X->vft==LC_VFT_MONSTER||X->vft==LC_VFT_SUMMON||X->vft==LC_VFT_NPC||X->vft==LC_VFT_PLAYER)
                monUpd(X->guid,X->cellx,X->celly,now); }

        LC_E* self=lc_findMe(); int have=0; float saU=0,saV=0,siU=0,siV=0; int sCX=0,sCY=0;
        if(self){ saU=self->aU; saV=self->aV; siU=self->iU; siV=self->iV; sCX=self->cellx; sCY=self->celly; have=1; }

        int RXE[LC_MAXE], RYE[LC_MAXE];
        for(int i=0;i<lc_nc;i++){
            LC_E* X=&lc_cur[i];
            int rx=(int)(V.sx+(X->iU-siU)*V.pxp), ry=(int)(V.sy-(X->iV-siV)*V.pyp);
            RXE[i]=rx; RYE[i]=ry;
            if(rx<-60||ry<-20||rx>g_bw+60||ry>g_bh+20) continue;
            int own=0,c40=0; if(X->vft==LC_VFT_ITEM){ own=(int)d32(X->e+OFF_OWN); c40=(int)d32(X->e+OFF_40); }
            COLORREF c=colOf(X,own,now); marker(g_memDC,rx,ry,c);
            char nm[80]; if(X->nm[0]){ strncpy(nm,X->nm,sizeof(nm)-1); nm[sizeof(nm)-1]=0; } else lc_name(X->e,nm,sizeof(nm));
            textOut(g_memDC,rx+10,ry-14,nm,c);
            if(X->vft==LC_VFT_ITEM){
                char lb[96]; snprintf(lb,sizeof lb,"contrib=%d c40=%d lh=%s",own,c40,lhLabel(X,now));
                textOut(g_memDC,rx+10,ry+1,lb,c);
            } else textOut(g_memDC,rx+10,ry+1,clsOf(X->vft),c);
        }
        if(have) marker(g_memDC,(int)V.sx,(int)V.sy,RGB(255,255,255));

        /* ── 공격사건 현시: 공격자→대상 선 + 표식 + 이벤트 로그 (etview 원본 규격) ── */
        {
            for(int i=0;i<lc_nc;i++){
                LC_E* X=&lc_cur[i];
                if(!X->hasAtk) continue;
                int ax=RXE[i], ay=RYE[i];
                COLORREF ac=RGB(255,120,0);
                marker(g_memDC,ax,ay,ac);                        /* 공격자(주황) */
                LC_E* T = X->atkTgt ? lc_findCur(X->atkTgt) : 0;
                if(T){ int ti=(int)(T-lc_cur);
                    lineAt(g_memDC,ax,ay,RXE[ti],RYE[ti],ac,2);  /* 공격자→대상 */
                    crossX(g_memDC,RXE[ti],RYE[ti],6,RGB(255,0,0)); /* 대상 X */
                    if(X->atkTgt==lc_meGuid) crossX(g_memDC,RXE[ti],RYE[ti],12,RGB(255,0,0)); /* 나를 공격: 이중 X */
                }
                textOut(g_memDC,ax+10,ay+14,(X->atkTgt==lc_meGuid)?"ATK<ME":"ATK",ac);
                uint64_t pt=0; int was=prevAtk(X->guid,&pt);
                if(!was || pt!=X->atkTgt){
                    char tn[80]="(out)";
                    if(T) snprintf(tn,sizeof(tn),"%s",T->nm[0]?T->nm:"?");
                    fprintf(f,"[ATK] t=%ums  %s(0x%08X) -> 0x%08X %s%s\n",
                        (unsigned)(now-t0), X->nm[0]?X->nm:"?", (unsigned)X->guid,
                        (unsigned)X->atkTgt, tn, (X->atkTgt==lc_meGuid)?"  <== ME":"");
                }
            }
            pAtkN=0;
            for(int i=0;i<lc_nc && pAtkN<LC_MAXE;i++) if(lc_cur[i].hasAtk){
                pAtkG[pAtkN]=lc_cur[i].guid; pAtkT[pAtkN]=lc_cur[i].atkTgt; pAtkN++; }
        }

        HDC dc=GetDC(g_wnd); BitBlt(dc,0,0,g_bw,g_bh,g_memDC,0,0,SRCCOPY); ReleaseDC(g_wnd,dc);

        /* 로그 */
        fprintf(f,"\nt=%ums entities=%d me=%08X OFF_OWN=%X (i=item; cyan=own!=0)\n",
            (unsigned)(now-t0),lc_nc,(uint32_t)lc_meGuid,OFF_OWN);
        for(int i=0;i<lc_nc;i++){ LC_E*X=&lc_cur[i];
            if(X->vft!=LC_VFT_ITEM) continue;
            int own=(int)d32(X->e+OFF_OWN); int c40=(int)d32(X->e+OFF_40);
            fprintf(f,"  ITEM guid=%016llX q=%-3u cell=(%d,%d) contrib=%-4d c40=%-6d lh=%-5s \"%s\"\n",
                (unsigned long long)X->guid,X->itemQty,X->cellx,X->celly,own,c40,lhLabel(X,now),X->nm);
        }
        /* 공격사건 요약(활성 공격수/나를 향한 공격수) */
        { int natk=0, nme=0;
          for(int i=0;i<lc_nc;i++){ if(!lc_cur[i].hasAtk) continue; natk++;
              if(lc_cur[i].atkTgt==lc_meGuid) nme++; }
          if(natk) fprintf(f,"  ATK active=%d onMe=%d\n",natk,nme);
        }
        if(fj){ lc_jsonHead(fj,t0,g_bw,g_bh,&V,sCX,sCY,V.sx,V.sy,lc_nc);
            for(int i=0;i<lc_nc;i++) lc_jsonEnt(fj,&lc_cur[i],g_bw,g_bh,i==0);
            lc_jsonFoot(fj); fflush(fj); }
        QueryPerformanceCounter(&q1);
        fprintf(f,"# reads=%llu time=%.4fms\n",g_ioctl,(q1.QuadPart-q0.QuadPart)*1000.0/fr.QuadPart); fflush(f);
        Sleep(lcreg_poll_sleep_ms(&P));
    }
    if(g_bmpAuto) saveBMP(lcreg_outpath("etview_own_shot.bmp"));
    if(fj) fclose(fj);
    fclose(f); SignedClose(); printf("done -> %s\n",outp); return 0;
}