/* etview_930.c — 엔티티 시각화(오버레이 뷰어) 모듈 (10_5 규격)
 *  공용 로직: core/lcore.h (앵커·엔티티순회·좌표보간).
 *  게임 화면을 BitBlt 로 캡처한 DIB 위에 엔티티 마커(원+십자)+이름/클래스를 그려
 *  별도 창(오버레이)에 실시간 표시한다. (etview 의 본래 목적: 시각화)
 *  같은 스냅샷을 ASCII 격자로 etview_out.txt 에도 기록(텍스트 로그/4자검증).
 *  상수는 registry(SEC-3/5), 읽기규격 POLL_ENTVIEW_*, 읽기는 MmCopy 단일.
 *  usage: etview_930.exe [registry] [secs] [out.bmp] [json]
 *  키: Q/ESC 종료, F9 BMP저장, 1/2 VP_DY, 3/4 VP_DX
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
/* 공격사건(edge) 추적: 이전 프레임 대비 신규/타깃변경 시 이벤트 1건 */
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
    BITMAPFILEHEADER fh; memset(&fh,0,sizeof(fh));
    fh.bfType=0x4D42; fh.bfOffBits=54; fh.bfSize=54+size;
    BITMAPINFOHEADER ih; memset(&ih,0,sizeof(ih));
    ih.biSize=40; ih.biWidth=w; ih.biHeight=-h; ih.biPlanes=1; ih.biBitCount=32; ih.biSizeImage=size;
    FILE*fp=fopen(path,"wb"); if(!fp) return;
    fwrite(&fh,sizeof(fh),1,fp); fwrite(&ih,sizeof(ih),1,fp); fwrite(g_bits,1,size,fp); fclose(fp);
    printf("saved %s (%dx%d)\n",path,w,h);
}
static LRESULT CALLBACK wp(HWND h,UINT m,WPARAM w,LPARAM l){
    if(m==WM_DESTROY){ PostQuitMessage(0); return 0; }
    if(m==WM_KEYDOWN){ int vk=(int)w;
        if(vk=='Q'||vk==VK_ESCAPE){ g_quit=1; PostQuitMessage(0); }
        else if(vk=='1') LC_VP_DY-=1.f;
        else if(vk=='2') LC_VP_DY+=1.f;
        else if(vk=='3') LC_VP_DX-=1.f;
        else if(vk=='4') LC_VP_DX+=1.f;
        else if(vk==VK_F9){ if(g_bmpAuto) saveBMP(g_bmpAuto); }
    }
    (void)h;(void)l; return DefWindowProcA(h,m,w,l);
}
static COLORREF colOf(LC_E* X){
    if(X->guid==lc_meGuid) return RGB(255,255,255);   /* self */
    if(X->dead) return RGB(90,90,90);
    if(X->bait) return RGB(120,80,40);
    const char* c=clsOf(X->vft);
    if(!strcmp(c,"Monster")) return RGB(255,40,40);
    if(!strcmp(c,"Player"))  return RGB(255,220,0);
    if(!strcmp(c,"Item"))    return RGB(40,255,40);
    if(!strcmp(c,"NPC"))     return RGB(0,220,220);
    if(!strcmp(c,"Ship"))    return RGB(170,80,255);
    return RGB(160,160,160);
}
static char gridChar(LC_E* X){
    if(X->vft==LC_VFT_SELF)    return '@';
    if(X->vft==LC_VFT_MONSTER) return X->bait?'b':'M';
    if(X->vft==LC_VFT_NPC)     return X->doorSeen ? (X->doorLocked?'X':(X->doorState==1?'o':'c')) : 'n';
    if(X->vft==LC_VFT_ITEM)    return 'i';
    return X->dead?'d':'?';
}
/* Door 현시 색: open=밝은 초록, close=회색, not_permitted=빨강 */
static COLORREF doorCol(const LC_E* X){
    if(X->doorLocked) return RGB(255,60,60);
    if(X->doorState==1) return RGB(80,255,80);
    return RGB(200,200,200);
}

int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char* reg=lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    const char* outp=lcreg_outpath("etview_out.txt");
    int secs=0; int wantJson=0;
    int seenTxt=0;
    for(int i=1;i<argc;i++){
        if(!strcmp(argv[i],"json")||!strcmp(argv[i],"--json")){ wantJson=1; continue; }
        if(strstr(argv[i],".bmp")){ g_bmpAuto=argv[i]; continue; }
        if(atoi(argv[i])>0 && !strstr(argv[i],".")){ secs=atoi(argv[i]); continue; }
        if(strstr(argv[i],".txt")||strstr(argv[i],".out")){
            if(seenTxt==0){ reg=argv[i]; seenTxt=1; } else { outp=argv[i]; }
        }
    }
    lcreg_load(reg); lc_reg_apply();
    lcreg_poll P=lcreg_poll_load("ENTVIEW");
    if(lc_attach()) return 1;
    if(!lc_anchor()){ fprintf(stderr,"anchor fail\n"); return 2; }

    g_gwnd=lc_findGameWnd((DWORD)g_pid);
    if(!g_gwnd){ fprintf(stderr,"no game window\n"); return 3; }
    RECT rc; GetClientRect(g_gwnd,&rc);
    int cw=rc.right, ch=rc.bottom; if(cw<2)cw=800; if(ch<2)ch=600;

    WNDCLASSA wc; memset(&wc,0,sizeof(wc));
    wc.lpfnWndProc=wp; wc.hInstance=GetModuleHandleA(NULL); wc.lpszClassName="ETView10_5";
    wc.hCursor=LoadCursorA(NULL,IDC_ARROW); wc.hbrBackground=(HBRUSH)GetStockObject(BLACK_BRUSH);
    RegisterClassA(&wc);
    RECT adj={0,0,cw,ch}; AdjustWindowRectEx(&adj,WS_OVERLAPPEDWINDOW,FALSE,0);
    RECT gr; GetWindowRect(g_gwnd,&gr);
    g_wnd=CreateWindowExA(0,"ETView10_5",
        "ETView 10_5  self=white mob=red ply=yellow item=green npc=cyan  (Q quit, F9 bmp, 1/2 VP_DY 3/4 VP_DX)",
        WS_OVERLAPPEDWINDOW|WS_VISIBLE, gr.left+8, gr.top, adj.right-adj.left, adj.bottom-adj.top,
        NULL,NULL,wc.hInstance,NULL);
    recreateDIB(cw,ch);

    lcreg_mkdir_for(outp);
    FILE* f=fopen(outp,"w"); if(!f) return 4;
    fprintf(f,"# registry=%s ENTVIEW interval=%ums jitter=%ums view=%dx%d\n",
        reg,P.interval_ms,P.jitter_ms,cw,ch);
    FILE* fj=0;
    if(wantJson){ char jp[512]; snprintf(jp,sizeof(jp),"%s.json",outp); fj=fopen(jp,"w");
        if(fj) fprintf(fj,"# registry=%s ENTVIEW json (공용 스키毵?\n",reg); }

    DWORD t0=GetTickCount(); MSG msg;
    while(!g_quit){
        while(PeekMessageA(&msg,NULL,0,0,PM_REMOVE)){ if(msg.message==WM_QUIT){ g_quit=1; break; } TranslateMessage(&msg); DispatchMessageA(&msg); }
        if(g_quit) break;
        if(secs && (int)(GetTickCount()-t0)>=secs*1000) break;
        LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr); QueryPerformanceCounter(&q0); g_ioctl=0;
        if(!capture()){ Sleep(20); continue; }

        lc_collect(); lc_pick_self();
        LC_VIEW V; lc_viewCalc(&V,g_bw,g_bh);

        /* self 확정(A)/보간(I) iso */
        LC_E* self=lc_findMe(); int have=0;
        float saU=0,saV=0,siU=0,siV=0; int sCX=0,sCY=0;
        if(self){ saU=self->aU; saV=self->aV; siU=self->iU; siV=self->iV; sCX=self->cellx; sCY=self->celly; have=1; }
        else {
            uint32_t px=lcreg_u32("PLAYER_X",0x16BB990), py=lcreg_u32("PLAYER_Y",0x16BB994);
            int cx=(int)d32(g_base+px), cy=(int)d32(g_base+py);
            if(cx||cy){ lc_selfIsoFromTile(cx,cy,&siU,&siV); saU=siU; saV=siV; sCX=cx; sCY=cy; have=1; }
        }

        /* ── 마커: 실시간 보간(I) 위치에 그린다(부드러운 이동) ── */
        int RXE[LC_MAXE], RYE[LC_MAXE];
        for(int i=0;i<lc_nc;i++){
            LC_E* X=&lc_cur[i];
            int rx=(int)(V.sx+(X->iU-siU)*V.pxp), ry=(int)(V.sy-(X->iV-siV)*V.pyp);
            RXE[i]=rx; RYE[i]=ry;
            if(rx<-60||ry<-20||rx>g_bw+60||ry>g_bh+20) continue;
            COLORREF c=colOf(X);
            int isDoor = X->doorSeen;
            if(isDoor) c = doorCol(X);                 /* 문은 상태색으로 */
            marker(g_memDC,rx,ry,c);
            char nm[80]; if(X->nm[0]){ strncpy(nm,X->nm,sizeof(nm)-1); nm[sizeof(nm)-1]=0; } else lc_name(X->e,nm,sizeof(nm));
            textOut(g_memDC,rx+10,ry-14,nm,c);
            if(isDoor){
                /* Door 상태 현시: open / close / not_permitted */
                char lbd[64]; snprintf(lbd,sizeof lbd,"DOOR %s",lc_doorToken(X));
                textOut(g_memDC,rx+10,ry+1,lbd,c);
            } else if(X->vft==LC_VFT_ITEM){
                char lb[64]; const char* ow=(X->itemOwn==1?"MINE":X->itemOwn==2?"OTHER":X->itemOwn==3?"FREE":"-");
                snprintf(lb,sizeof lb,"%s contrib=%d",ow,(int)X->itemContrib);
                textOut(g_memDC,rx+10,ry+1,lb,c);
            } else { char lb2[64];
                snprintf(lb2,sizeof lb2,"%s av=%d",clsOf(X->vft),X->atkValid);
                textOut(g_memDC,rx+10,ry+1,lb2,c); }
        }
        if(have) marker(g_memDC,(int)V.sx,(int)V.sy,RGB(255,255,255));

        /* ── 공격사건 현시: 공격자→대상 선 + 표식 + 이벤트 로그 ── */
        {
            for(int i=0;i<lc_nc;i++){
                LC_E* X=&lc_cur[i];
                if(!X->hasAtk) continue;
                int ax=RXE[i], ay=RYE[i];
                COLORREF ac=RGB(255,120,0);
                marker(g_memDC,ax,ay,ac);                       /* 공격鞛?臧曥“(주황) */
                LC_E* T = X->atkTgt ? lc_findCur(X->atkTgt) : 0;
                if(T){ int ti=(int)(T-lc_cur);
                    lineAt(g_memDC,ax,ay,RXE[ti],RYE[ti],ac,2);  /* 공격자→대상 */
                    crossX(g_memDC,RXE[ti],RYE[ti],6,RGB(255,0,0)); /* 대상 X */
                }
                { char ab2[48];
                  snprintf(ab2,sizeof ab2,"ATK v=%d%s",X->atkValid,X->atkBlocked?" BLK":"");
                  textOut(g_memDC,ax+10,ay+14,ab2,ac); }
                uint64_t pt=0; int was=prevAtk(X->guid,&pt);
                if(!was || pt!=X->atkTgt){
                    char tn[80]="(out)";
                    if(T) snprintf(tn,sizeof(tn),"%s",T->nm[0]?T->nm:"?");
                    fprintf(f,"[ATK] t=%ums  %s(0x%08X) -> 0x%08X %s\n",
                        (unsigned)(GetTickCount()-t0), X->nm[0]?X->nm:"?", (unsigned)X->guid,
                        (unsigned)X->atkTgt, tn);
                }
            }
            pAtkN=0;
            for(int i=0;i<lc_nc && pAtkN<LC_MAXE;i++) if(lc_cur[i].hasAtk){
                pAtkG[pAtkN]=lc_cur[i].guid; pAtkT[pAtkN]=lc_cur[i].atkTgt; pAtkN++; }
        }

        HDC dc=GetDC(g_wnd); BitBlt(dc,0,0,g_bw,g_bh,g_memDC,0,0,SRCCOPY); ReleaseDC(g_wnd,dc);

        /* ── Door 상태 전이 로그 (open / close / not_permitted) ── */
        {
            static uint64_t pG[LC_MAXE]; static char pS[LC_MAXE][16]; static int pN = 0;
            for(int i=0;i<lc_nc;i++){
                LC_E* X=&lc_cur[i];
                if(!X->doorSeen) continue;
                const char* s=lc_doorToken(X);
                int k=-1; for(int j=0;j<pN;j++) if(pG[j]==X->guid){ k=j; break; }
                if(k<0){
                    if(pN<LC_MAXE){ pG[pN]=X->guid; snprintf(pS[pN],sizeof pS[0],"%s",s); pN++; }
                    fprintf(f,"[DOOR] t=%ums  %s(0x%X) tile=%d,%d  => %s\n",
                        (unsigned)(GetTickCount()-t0), X->nm[0]?X->nm:"Door",
                        (unsigned)X->guid, X->cellx, X->celly, s);
                } else if(strcmp(pS[k],s)){
                    fprintf(f,"[DOOR] t=%ums  %s(0x%X) tile=%d,%d  %s -> %s\n",
                        (unsigned)(GetTickCount()-t0), X->nm[0]?X->nm:"Door",
                        (unsigned)X->guid, X->cellx, X->celly, pS[k], s);
                    snprintf(pS[k],sizeof pS[0],"%s",s);
                }
            }
        }

        /* ── ASCII 로그: scrA(확정) + scrI(보간) 동시 현시 ── */
        {
            char cv[OVH][OVW+1];
            for(int y=0;y<OVH;y++){ for(int x=0;x<OVW;x++) cv[y][x]='.'; cv[y][OVW]=0; }
            for(int i=0;i<lc_nc;i++){
                LC_E* X=&lc_cur[i];
                int rx=(int)(V.sx+(X->iU-siU)*V.pxp), ry=(int)(V.sy-(X->iV-siV)*V.pyp);
                int gx=(int)(rx/(float)g_bw*OVW), gy=(int)(ry/(float)g_bh*OVH);
                if(gx<0||gx>=OVW||gy<0||gy>=OVH) continue;
                cv[gy][gx]=gridChar(X);
            }
            fprintf(f,"\nt=%ums  entities=%d  me=%08X  (@=self M=monster b=bait n=npc i=item d=dead)  [I=보간현시]\n",
                (unsigned)(GetTickCount()-t0),lc_nc,(uint32_t)lc_meGuid);
            for(int y=0;y<OVH;y++) fprintf(f,"  %s\n",cv[y]);
            fprintf(f,"%-6s %-10s %-16s %-13s %-13s %-9s %-13s %-5s %-5s %-4s %-13s\n",
                "idx","cls","name","scr(확정)","iscr(보간)","iso","iiso","distT","worldT","dead","atk","door");
            for(int i=0;i<lc_nc;i++){
                LC_E* X=&lc_cur[i];
                char nm[80]; if(X->nm[0]){ strncpy(nm,X->nm,sizeof(nm)-1); nm[sizeof(nm)-1]=0; } else lc_name(X->e,nm,sizeof(nm));
                int ax=(int)(V.sx+(X->aU-saU)*V.pxp), ay=(int)(V.sy-(X->aV-saV)*V.pyp);
                int ix=(int)(V.sx+(X->iU-siU)*V.pxp), iy=(int)(V.sy-(X->iV-siV)*V.pyp);
                float dtx=(float)(X->cellx-sCX), dty=(float)(X->celly-sCY);
                fprintf(f,"%-6d %-10s %-16s %5d,%5d  %5d,%5d  %6.0f,%4.0f %6.0f,%4.0f %-9.2f %5d,%4d %-5d %-4s %-13s\n",
                    i,clsOf(X->vft),nm,ax,ay,ix,iy,X->aU,X->aV,X->iU,X->iV,
                    sqrtf(dtx*dtx+dty*dty),X->cellx,X->celly,X->dead,X->hasAtk?"ATK":"-",
                    X->doorSeen?lc_doorToken(X):"-");
            }
            if(fj){ lc_jsonHead(fj,t0,g_bw,g_bh,&V,sCX,sCY,V.sx,V.sy,lc_nc);
                for(int i=0;i<lc_nc;i++) lc_jsonEnt(fj,&lc_cur[i],g_bw,g_bh,i==0);
                lc_jsonFoot(fj); fflush(fj); }
        }
        while(PeekMessageA(&msg,NULL,0,0,PM_REMOVE)){ if(msg.message==WM_QUIT){ g_quit=1; break; } TranslateMessage(&msg); DispatchMessageA(&msg); }
        QueryPerformanceCounter(&q1);
        fprintf(f,"# reads=%llu time=%.4fms\n",g_ioctl,(q1.QuadPart-q0.QuadPart)*1000.0/fr.QuadPart); fflush(f);
        Sleep(lcreg_poll_sleep_ms(&P));
    }
    if(g_bmpAuto) saveBMP(g_bmpAuto);
    if(fj) fclose(fj);
    fclose(f); SignedClose(); printf("done -> %s\n",outp); return 0;
}


