/* uidialogmon_930.c — UI 대화창 상태 감시 정본 모듈 (10_5 규격)
 * ---------------------------------------------------------------------------
 *  목적: 인벤토리 / 엔피씨대화 / 엔피씨상점 / 엔피씨창고 / 두루마리 등 **대화·열람 창**의
 *        열림/닫힘만 감시. (HUD 등 기타 상태는 감시하지 않는다. = uistate 대체 축소판)
 *
 *  대원칙(고정앵커 + 고정체인, 런타임 BFS 없음):
 *    1) 고정앵커  : UISubsystem = lc_subsGet(VFT_UISUBSYSTEM=0x11C32D0) (sub[5]).
 *                   vft 불일치 시 RTTI 클래스명("…UISubsystem…::ui") 폴백.
 *    2) 고정체인  : UISubsystem 의 **레이아웃 컨테이너**(고정 오프셋)를 직접 walk.
 *                   head=+0x38(next@+0x18) / +0x28(next@+0x28), 값(Layout*)@+0x38.
 *                   → 컨테이너 29노드에서 레이아웃 25개 전부(창고 포함) 열거. (BFS 0회)
 *    3) 창 식별    : RTTI 클래스명 패턴(*Layout[PCImpl] @ ui::lineage) — 버전/세션 무관.
 *    4) 감시집합   : registry `UIDLG_WIN_<Label>=<ClassShortName>` 로 **명시**된 창만.
 *    5) 재스캔     : 컨테이너 walk 는 저비용(≈60 reads) → `UIDLG_SCAN_MS`(기본 2000) 주기로
 *                   갱신 → 나중에 생성/열린 창(예: 창고)도 자동 포착.
 *    6) 드라이버   : 창당 1 read(헤더 0x78: vft검증+가시플래그). 항상 Sleep, 상한 이하.
 *                   UIDLG_MAX_CALLS_PER_SEC (기본 500).
 *  usage: uidialogmon_930.exe [registry] [secs] [out.txt]
 *  출력: <EXE>\out\uidialogmon_out.txt
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

/* ── registry ─────────────────────────────────────────────────────────── */
static uint32_t RG_UVFT, RG_VIS, RG_VISMASK, RG_VISOPEN, RG_MAXCPS, RG_SCAN, RG_CVAL, RG_TDNAME, RG_COLTD;
static uint32_t RG_CPANEL, RG_CFN, RG_CFNM2, RG_CMSG, RG_CTYPE, RG_CASK, RG_POLL, RG_IDLE, RG_POPVIS, RG_MSGMS, RG_STATE;
static char     RG_SUFFIX[32], RG_NS[64], RG_CHATLAYOUT[96];
static uint32_t g_chead[8], g_cnext[8]; static int g_ncont=0;   /* 컨테이너 head/next 쌍 */

/* ── 고속 읽기(페이지 묶음) — 컨테이너 walk 전용 ─────────────────────────
 * lcore 의 lc_pgRead 경유: 같은 4KB 페이지 안의 read 를 1콜로 캐시한다.
 * (기존 rmf 는 g_ioctl++ 와 SignedReadFast 가산이 겹쳐 2배 과다계상됐다.) */
static int      rmf(uint64_t a, void*b, uint32_t s){ return lc_pgRead(a,b,s); }
static uint64_t q64f(uint64_t a){ uint64_t v=0; lc_pgRead(a,&v,8); return v; }

/* ── 감시 대상(registry UIDLG_WIN_*) ──────────────────────────────────── */
#define MAXWATCH 32
static struct { char label[48]; char cls[96]; int found; } g_watch[MAXWATCH]; static int g_nwatch=0;

/* ── 발견된(=감시) 창 ─────────────────────────────────────────────────── */
typedef struct { char label[48]; char cls[96]; uint64_t inst; uint32_t vft; } WIN;
static WIN g_win[MAXWATCH]; static int g_nwin=0;

/* ── RTTI: vft → 클래스명 ─────────────────────────────────────────────── */
static int classOf(uint64_t vft, char*out, int cap){
    out[0]=0; if(!isMod(vft)) return 0;
    uint64_t col=q64(vft-8);
    if(!isMod(col)){ if(col>0 && col<(uint64_t)g_modSize) col=g_base+col; else return 0; }
    uint32_t td_rva=0; rm(col+RG_COLTD,&td_rva,4);
    uint64_t td=g_base+td_rva; if(!isMod(td)) return 0;
    char raw[512]; memset(raw,0,sizeof(raw)); if(!rm(td+RG_TDNAME,raw,sizeof(raw)-1)) return 0;
    const char*p=raw; if(strncmp(p,".?AV",4)==0) p+=4;
    int n=0; while(*p && n<cap-1){ if(p[0]=='@'&&p[1]=='@')break; if(p[0]=='@'){ if(n<cap-2){out[n++]=':';out[n++]=':';} p++; } else out[n++]=*p++; }
    out[n]=0; return n>0;
}
/* ── vft→클래스명 캐시 (컨테이너 walk 마다 RTTI 3콜 재해석 제거) ────────── */
#define CC_MAX 256
static uint64_t CC_vft[CC_MAX]; static char CC_nm[CC_MAX][160]; static int CC_n=0;
static int classOfC(uint64_t vft, char*out, int cap){
    for(int i=0;i<CC_n;i++) if(CC_vft[i]==vft){ snprintf(out,cap,"%s",CC_nm[i]); return 1; }
    if(!classOf(vft,out,cap)) return 0;
    if(CC_n<CC_MAX){ CC_vft[CC_n]=vft; snprintf(CC_nm[CC_n],160,"%s",out); CC_n++; }
    return 1;
}
/* ── layout 포인터→vft 캐시 (레이아웃 객체의 vft 는 불변 → 재읽기 제거) ── */
#define LV_MAX 1024
static uint64_t LV_lay[LV_MAX], LV_vf[LV_MAX]; static int LV_n=0;
static int lvFind(uint64_t lay, uint64_t* vf){
    for(int i=0;i<LV_n;i++) if(LV_lay[i]==lay){ *vf=LV_vf[i]; return 1; }
    return 0;
}
static void lvSet(uint64_t lay, uint64_t vf){
    if(LV_n>=LV_MAX) return;
    LV_lay[LV_n]=lay; LV_vf[LV_n]=vf; LV_n++;
}
static int isLayout(const char*nm){
    if(!nm[0] || !strstr(nm,RG_NS)) return 0;
    int t=0; while(nm[t] && nm[t]!=':' && t<200) t++;
    int be=t;
    if(be>=6 && !strncmp(nm+be-6,"PCImpl",6)) be-=6;
    else if(be>=10 && !strncmp(nm+be-10,"MobileImpl",10)) be-=10;
    int sl=(int)strlen(RG_SUFFIX);
    return be>=sl && strncmp(nm+be-sl,RG_SUFFIX,(size_t)sl)==0;
}
static void shortName(const char*nm, char*out, int cap){
    int t=0; while(nm[t] && nm[t]!=':' && t<cap-1){ out[t]=nm[t]; t++; } out[t]=0;
}
static const char* watchLabel(const char*cls){
    for(int i=0;i<g_nwatch;i++) if(!strcmp(g_watch[i].cls,cls)) return g_watch[i].label;
    return 0;
}
/* ── 문자열 판독(std::string 정본 + 레거시 {ptr,size} 폴백) ─────────────── */
static int decU8(const uint8_t*b,int n,char*out,int cap){
    wchar_t wb[512];
    int wn=MultiByteToWideChar(CP_UTF8,MB_ERR_INVALID_CHARS,(const char*)b,n,wb,512);
    if(wn<=0) wn=MultiByteToWideChar(949,0,(const char*)b,n,wb,512);
    if(wn<=0) wn=MultiByteToWideChar(936,0,(const char*)b,n,wb,512);
    if(wn<=0) return 0;
    int un=WideCharToMultiByte(CP_UTF8,0,wb,wn,out,cap-1,0,0);
    if(un<0) un=0; out[un]=0; return un>0;
}
/* p = std::string {buf/SSO@0, size@+0x10, cap@+0x18} */
static int readStdStr(uint64_t p, char*out, int cap){
    out[0]=0;
    if(!isHeap(p)) return 0;
    uint8_t h[0x20];
    if(!rmf(p,h,sizeof h)) return 0;
    uint64_t sz, cp; memcpy(&sz,h+0x10,8); memcpy(&cp,h+0x18,8);
    if(!(sz>0 && sz<0x600 && cp>=sz && cp<0x100000)) return 0;
    uint8_t b[0x600];
    if(cp<0x10) memcpy(b,h,(size_t)sz);
    else { uint64_t q; memcpy(&q,h,8); if(!isHeap(q) || !rmf(q,b,(uint32_t)sz)) return 0; }
    return decU8(b,(int)sz,out,cap);
}
static int readMsgStr(uint64_t panel, char*buf, int cap){
    if(readStdStr(panel+RG_CMSG,buf,cap)) return 1;
    /* 레거시 {ptr,size} 폴백 */
    uint64_t dp=q64f(panel+RG_CMSG), sz=q64f(panel+RG_CMSG+8);
    if(!isHeap(dp) || sz==0 || sz>0x600) return 0;
    uint8_t b[0x600]; if(!rmf(dp,b,(uint32_t)sz)) return 0;
    return decU8(b,(int)sz,buf,cap);
}

/* ── confirm(통보문) 분류: ask 코드 → 종류 (registry CHATMON_ASK_TYPES) ──
 *   ask = 확인 패널 +CHATCONFIRM_ASK_CB_OFF(0x1C0) functor 캡처 상위32bit.
 *   구조 값이므로 언어 비의존. 미등록 코드는 라벨을 만들지 않는다(추정 금지). */
#define ASK_MAX 24
static uint32_t askCode[ASK_MAX]; static char askKind[ASK_MAX][40]; static int askN=0;
static void parseAsk(const char*s){
    askN=0; const char*p=s?s:"";
    while(*p && askN<ASK_MAX){
        unsigned v=0; char nm[40]="";
        if(sscanf(p,"%x:%39[^,]",&v,nm)>=1 && v){
            askCode[askN]=v; snprintf(askKind[askN],sizeof askKind[0],"%s",nm[0]?nm:"?"); askN++;
        }
        p=strchr(p,','); if(p)p++; else break;
    }
}
static const char* askLabel(uint32_t v){
    for(int i=0;i<askN;i++) if(askCode[i]==v) return askKind[i];
    return 0;
}
static uint32_t askOf(uint64_t panel){
    uint64_t cb=q64f(panel+RG_CASK);
    if(!isHeap(cb)) return 0;
    uint64_t cap=q64f(cb+0x10);
    return (uint32_t)(cap>>32);
}

/* ── confirm 이벤트(표시/변경/닫힘) ─────────────────────────────────────── */
#ifndef CF_MAX
#define CF_MAX 24
#endif
typedef struct { uint64_t inst; uint32_t ask, type, lastMs; char kind[40]; char msg[512]; } CF;
/* confirm 감시 클래스(registry UICONFIRM_CLASSES + CHAT_LAYOUT_CLASS) */
#define CFC_MAX 8
static char CFC[CFC_MAX][96]; static int CFC_N=0;
static int isConfirmWin(const char*cls){
    if(!cls || !cls[0]) return 0;
    for(int i=0;i<CFC_N;i++) if(!strcmp(cls,CFC[i])) return 1;
    return 0;
}
static CF cfPrev[CF_MAX]; static int cfPrevN=0;
static int cfFind(CF*a,int n,uint64_t inst){ for(int i=0;i<n;i++) if(a[i].inst==inst) return i; return -1; }
static void cfEmit(const char*sign,const CF*c){
    char line[900];
    if(c->ask && c->type) snprintf(line,sizeof line,"[%s] CONFIRM kind=%s ask=%u type=%u \"%s\"",
                                   sign,c->kind[0]?c->kind:"미확인",c->ask,c->type,c->msg);
    else if(c->ask)       snprintf(line,sizeof line,"[%s] CONFIRM kind=%s ask=%u \"%s\"",
                                   sign,c->kind[0]?c->kind:"미확인",c->ask,c->msg);
    else                  snprintf(line,sizeof line,"[%s] CONFIRM kind=%s \"%s\"",
                                   sign,c->kind[0]?c->kind:"미확인",c->msg);
    printf("\n%s",line); fflush(stdout);
}
static int isHudChat(const char*cls){ return cls && !strcmp(cls,"HudChatLayoutPCImpl"); }

/* ── 앵커: vft 식별 → 실패 시 RTTI 클래스명 폴백 ──────────────────────── */
static uint64_t anchorUI(void){
    uint64_t s=lc_subsGet(RG_UVFT);
    if(isHeap(s)) return s;
    if(isHeap(lc_subs)){
        for(int i=0;i<(int)LC_SUBCOUNT_V;i++){
            uint64_t sub=q64(lc_subs+(uint64_t)LC_SUB_STRIDE_V*i);
            if(!isHeap(sub)) continue;
            char nm[128];
            if(classOf(q64(sub),nm,sizeof(nm)) && strstr(nm,"UISubsystem") && strstr(nm,RG_NS)) return sub;
            if(classOf(q64(sub+8),nm,sizeof(nm)) && strstr(nm,"UISubsystem") && strstr(nm,RG_NS)) return sub;
        }
    }
    return 0;
}

/* ── 컨테이너 walk: 앵커의 레이아웃 컨테이너를 직접 순회(고정체인) ────────
 *   head=+0x38(next@+0x18), +0x28(next@+0x28); 각 노드의 값(Layout*)@+0x38. */
static void addWin(const char*label, const char*sh, uint64_t lay, uint32_t vft){
    for(int k=0;k<g_nwin;k++) if(!strcmp(g_win[k].cls,sh)) return;   /* dedup */
    if(g_nwin>=MAXWATCH) return;
    WIN*W=&g_win[g_nwin++];
    strncpy(W->label,label,47); W->label[47]=0;
    strncpy(W->cls,sh,95); W->cls[95]=0;
    W->inst=lay; W->vft=vft;
    for(int i=0;i<g_nwatch;i++) if(!strcmp(g_watch[i].label,label)) g_watch[i].found=1;
}
static void containerScan(uint64_t ui){
    g_nwin=0;
    for(int i=0;i<g_nwatch;i++) g_watch[i].found=0;
    if(!isHeap(ui)) return;
    lc_pgc_reset();                        /* 묶음호출: 페이지 캐시 초기화 */
    for(int c=0;c<g_ncont;c++){
        uint64_t node=q64f(ui+g_chead[c]);
        /* 노드 값(RG_CVAL)과 next 를 한 묶음으로 (1콜). next 오프셋이 더 크면 그만큼. */
        uint32_t need = RG_CVAL + 8; if(g_cnext[c]+8 > need) need = g_cnext[c]+8;
        if(need > 0x48) need = 0x48;
        for(int n=0;n<2048 && isHeap(node);n++){
            uint8_t nb[0x48]; if(!rmf(node,nb,need)) break;
            uint64_t lay=0,nxt=0;
            memcpy(&lay,nb+RG_CVAL,8); memcpy(&nxt,nb+g_cnext[c],8);
            if(isHeap(lay)){
                uint64_t vf=0;
                if(!lvFind(lay,&vf)){ vf=q64f(lay); lvSet(lay,vf); }   /* 2회차부터 0콜 */
                if(isMod(vf)){ char nm[128],sh[96]; classOfC(vf,nm,sizeof(nm)); shortName(nm,sh,sizeof(sh));
                    /* 감시집합(UIDLG_WIN_*)에 **명시**된 클래스는 Layout 접미사 규칙과 무관하게 감시한다.
                       (예: CommonMessagePopup = 교환 응답 확인 통보문, CommonBigMessagePopup) */
                    { const char*lb=watchLabel(sh);
                      if(lb) addWin(lb,sh,lay,(uint32_t)(vf-g_base));
                      /* HUD 창은 항시 켜져 있으므로 '열림 감시' 대상이 아니다.
                       * 단, 확인 패널(chat+CHATCONFIRM_PANEL_OFF) 판독을 위해
                       * 채팅 레이아웃 인스턴스만 내부적으로 보관한다(출력/카운트 제외). */
                      else if(sh[0] && RG_CHATLAYOUT[0] && !strcmp(sh,RG_CHATLAYOUT))
                          addWin("HudChat",sh,lay,(uint32_t)(vf-g_base)); } }
            }
            if(nxt==node) break;
            node=nxt;
        }
    }
}

int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char*reg=lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    const char*outp=lcreg_outpath("uidialogmon_out.txt");
    int secs=0; { int seen=0;
      for(int i=1;i<argc;i++){ if(strstr(argv[i],".txt")||strstr(argv[i],".out")){ if(!seen&&strstr(argv[i],"REGISTRY")){reg=argv[i];seen=1;} else outp=argv[i]; }
        else if(atoi(argv[i])>0&&!strstr(argv[i],".")) secs=atoi(argv[i]); } }
    char OUTF[MAX_PATH*2]; snprintf(OUTF,sizeof(OUTF),"%s",outp); outp=OUTF;
    reg = lcreg_resolve(reg,"registry/LC930_REGISTRY.txt");
    lcreg_load(reg); lc_reg_apply();

    RG_UVFT    = lcreg_u32("VFT_UISUBSYSTEM",0x11C32D0);   /* 실제 UISubsystem(sub[5]) */
    RG_VIS     = lcreg_u32("VIS_FLAG",0x70);
    RG_VISMASK = lcreg_u32("VIS_MASK",0xFF);
    RG_VISOPEN = lcreg_u32("VIS_OPEN",1);
    RG_MAXCPS  = lcreg_u32("UIDLG_MAX_CALLS_PER_SEC",500); if(!RG_MAXCPS)RG_MAXCPS=500;
    RG_SCAN    = lcreg_u32("UIDLG_SCAN_MS",2000); if(!RG_SCAN)RG_SCAN=2000;
    RG_CVAL    = lcreg_u32("UIDLG_CONT_VAL",0x38);
    RG_TDNAME  = lcreg_u32("RTTI_TD_NAME_OFF",0x10);
    RG_COLTD   = lcreg_u32("RTTI_COL_TD_OFF",0xC);
    RG_CPANEL  = lcreg_u32("CHATCONFIRM_PANEL_OFF",0x150);
    RG_CFN     = lcreg_u32("CHATCONFIRM_FN_OFF",0x78);
    RG_CFNM2   = lcreg_u32("CHATCONFIRM_FN2_OFF",0xB8);
    RG_CMSG    = lcreg_u32("CHATCONFIRM_MSG_OFF",0xC8);
    RG_CTYPE   = lcreg_u32("CHATCONFIRM_TYPE_OFF",0xC0);
    RG_CASK    = lcreg_u32("CHATCONFIRM_ASK_CB_OFF",0x1C0);
    RG_POPVIS  = lcreg_u32("POPUP_VIS_OFF",0x78);
    RG_POLL    = lcreg_u32("UICONFIRM_POLL_MS",100);   if(!RG_POLL) RG_POLL=100;
    RG_IDLE    = lcreg_u32("UICONFIRM_IDLE_MS",250);   if(!RG_IDLE) RG_IDLE=250;
    RG_MSGMS   = lcreg_u32("UICONFIRM_MSG_MS",500);    if(!RG_MSGMS) RG_MSGMS=500;
    RG_STATE   = lcreg_u32("UIDLG_STATE_MS",1000);     if(!RG_STATE) RG_STATE=1000;
    parseAsk(lcreg_str("CHATMON_ASK_TYPES",""));
    { const char*v=lcreg_str("UICONFIRM_CLASSES","CommonMessagePopup,CommonBigMessagePopup,ChatConfirmPanel");
      char buf[256]; snprintf(buf,sizeof buf,"%s",v?v:"");
      for(char*t=strtok(buf,","); t && CFC_N<CFC_MAX; t=strtok(0,",")) snprintf(CFC[CFC_N++],sizeof CFC[0],"%s",t);
      const char*cl=lcreg_str("CHAT_LAYOUT_CLASS","HudChatLayoutPCImpl");
      int dup=0; for(int i=0;i<CFC_N;i++) if(!strcmp(CFC[i],cl)) dup=1;
      if(!dup && CFC_N<CFC_MAX) snprintf(CFC[CFC_N++],sizeof CFC[0],"%s",cl); }
    snprintf(RG_CHATLAYOUT,sizeof(RG_CHATLAYOUT),"%s",lcreg_str("CHAT_LAYOUT_CLASS","HudChatLayoutPCImpl"));
    snprintf(RG_SUFFIX,sizeof(RG_SUFFIX),"%s",lcreg_str("UI_LAYOUT_SUFFIX","Layout"));
    snprintf(RG_NS,sizeof(RG_NS),"%s",lcreg_str("UI_LAYOUT_NS","ui::lineage"));
    /* 컨테이너 head:next 쌍 파싱: "0x38:0x18,0x28:0x28" */
    { const char*v=lcreg_str("UIDLG_CONT","0x38:0x18,0x28:0x28"); char buf[128]; strncpy(buf,v,127); buf[127]=0;
      char*tok=strtok(buf,","); while(tok && g_ncont<8){ char*colon=strchr(tok,':'); if(colon){ *colon=0;
          g_chead[g_ncont]=(uint32_t)strtoul(tok,0,0); g_cnext[g_ncont]=(uint32_t)strtoul(colon+1,0,0); g_ncont++; }
        tok=strtok(0,","); } }
    /* 감시집합: registry 의 UIDLG_WIN_<Label>=<ClassShortName> 를 모두 읽는다 */
    for(int i=0;i<LCREG_N && g_nwatch<MAXWATCH;i++){
        if(strncmp(LCREG_K[i],"UIDLG_WIN_",10)==0){
            snprintf(g_watch[g_nwatch].label,sizeof(g_watch[g_nwatch].label),"%s",LCREG_K[i]+10);
            snprintf(g_watch[g_nwatch].cls,sizeof(g_watch[g_nwatch].cls),"%s",LCREG_V[i]);
            g_watch[g_nwatch].found=0; g_nwatch++;
        }
    }
    lcreg_poll P=lcreg_poll_load("UIDLG");

    if(lc_attach())return 1; if(!lc_anchor())return 2;
    uint64_t ui=anchorUI();
    if(!isHeap(ui)){ fprintf(stderr,"UI anchor not found\n"); return 2; }
    LARGE_INTEGER fr; QueryPerformanceFrequency(&fr);
    unsigned long long r0=g_ioctl; LARGE_INTEGER s0,s1; QueryPerformanceCounter(&s0);
    containerScan(ui);
    QueryPerformanceCounter(&s1);
    unsigned long long scanReads=g_ioctl-r0;
    double scanMs=(double)(s1.QuadPart-s0.QuadPart)*1000.0/(double)fr.QuadPart;

    lcreg_mkdir_for(outp);
    FILE*f=fopen(outp,"w"); if(!f){ fprintf(stderr,"cannot open %s\n",outp); return 4; }
    /* 출력양식: 설정/이력 덤프 없이 "현재 열려 있는 창"만 실시간 스냅샷으로 출력. */
    fprintf(f,"# uidialogmon registry=%s windows=%d src=cont anchor=%llX scanReads=%llu scanMs=%.3f\n",
        reg,g_nwin,(unsigned long long)ui,scanReads,scanMs);
    fprintf(f,"# build=2026-10-20(13차) confirm=on hud=off\n");
    fprintf(f,"# watch:"); for(int i=0;i<g_nwin;i++) fprintf(f," %s=%s",g_win[i].label,g_win[i].cls);
    fprintf(f,"\n# confirm classes:"); for(int i=0;i<CFC_N;i++) fprintf(f," %s",CFC[i]);
    fprintf(f,"\n");

    uint32_t minIv=(uint32_t)(((uint64_t)g_nwin*1000u + RG_MAXCPS - 1)/RG_MAXCPS);
    uint32_t interval=P.interval_ms; if(interval<minIv) interval=minIv;

    DWORD t0=GetTickCount(), lastScan=GetTickCount(), lastRep=GetTickCount(), lastState=GetTickCount();
    unsigned long long rRep=g_ioctl; double msAcc=0;
    int firstState=1;                 /* 첫 샘플은 즉시 현재 open 상태를 평가 */
    int plen=0;                       /* 콘솔 직전 줄 길이(잔상 제거용) */
    for(;;){
        DWORD now=GetTickCount();
        LARGE_INTEGER q0; QueryPerformanceCounter(&q0);
        lc_pgc_reset();                       /* 묶음호출: 매 폴링 페이지 캐시 초기화 */
        if(now-lastScan>=(DWORD)RG_SCAN){ containerScan(ui); lastScan=now; }  /* 저비용 재스캔 */
        /* 창 열림 상태: 전체 창 스캔은 UIDLG_STATE_MS(기본 1000ms) 주기로만(호출 절감). */
        static int nopen=0; static char opn[1024]="";
        if(firstState || now-lastState>=(DWORD)RG_STATE){
            firstState=0; lastState=now; nopen=0; opn[0]=0; size_t op=0;
            for(int i=0;i<g_nwin;i++){
                uint64_t o=g_win[i].inst; static uint8_t hb[0x78];
                int alive = o && rmf(o,hb,sizeof(hb)) && *(uint64_t*)hb==g_base+g_win[i].vft;
                uint32_t vis = alive ? *(uint32_t*)(hb+RG_VIS) : 0u;
                alive = alive && (vis&RG_VISMASK)==RG_VISOPEN;
                /* HUD 클래스는 항시 표시 상태 → 열림 목록에서 제외 */
                if(alive && strncmp(g_win[i].cls,"Hud",3)!=0){
                    nopen++; if(op<sizeof(opn)-48) op+=snprintf(opn+op,sizeof(opn)-op,"%s%s",op?" ":"",g_win[i].label);
                }
            }
        }
        unsigned el=(unsigned)(now-t0);
        /* ── 통보문(confirm) 수집: **confirm 대상 창만** 매 주기 확인 ──
         *   비용: 대상(팝업 2 + 채팅 레이아웃 1)의 가시플래그 1읽기.
         *   문자열은 새로 뜬 경우/메시지 갱신주기(UICONFIRM_MSG_MS)에만 판독. */
        CF cur[CF_MAX]; int curN=0;
        for(int i=0;i<g_nwin && curN<CF_MAX;i++){
            uint64_t inst=g_win[i].inst; if(!isHeap(inst)) continue;
            if(!isConfirmWin(g_win[i].cls)) continue;
            if(isHudChat(g_win[i].cls)){
                uint64_t panel=q64f(inst+RG_CPANEL);
                if(!isHeap(panel)) continue;
                if(!q64f(panel+RG_CFN)) continue;              /* +0x78 == 0 → 표시중 아님 */
                int j=cfFind(cfPrev,cfPrevN,panel);
                if(j>=0 && (unsigned)(now-cfPrev[j].lastMs)<RG_MSGMS){ memcpy(&cur[curN++],&cfPrev[j],sizeof(CF)); continue; }
                CF*c=&cur[curN++]; memset(c,0,sizeof(*c));
                c->inst=panel; c->lastMs=now;
                c->type=(uint32_t)q64f(panel+RG_CTYPE);
                c->ask=askOf(panel);
                readMsgStr(panel,c->msg,sizeof(c->msg));
                const char*k=askLabel(c->ask);
                snprintf(c->kind,sizeof(c->kind),"%s",k?k:"확인");
            } else {
                if(!q64f(inst+RG_POPVIS)) continue;
                int j=cfFind(cfPrev,cfPrevN,inst);
                if(j>=0 && (unsigned)(now-cfPrev[j].lastMs)<RG_MSGMS){ memcpy(&cur[curN++],&cfPrev[j],sizeof(CF)); continue; }
                CF*c=&cur[curN++]; memset(c,0,sizeof(*c));
                c->inst=inst; c->lastMs=now;
                readMsgStr(inst,c->msg,sizeof(c->msg));
                if(!c->msg[0]) continue;
                snprintf(c->kind,sizeof(c->kind),"%s",g_win[i].label);
            }
        }
        /* ── 이벤트(표시/변경/닫힘) — 바뀔 때만 1줄 출력 ── */
        int cfEvents=0;
        for(int i=0;i<curN;i++){
            int j=cfFind(cfPrev,cfPrevN,cur[i].inst);
            if(j<0){ cfEmit("+",&cur[i]); cfEvents++;
                fprintf(f,"[+] CONFIRM kind=%s ask=%u type=%u inst=0x%llX \"%s\"\n",cur[i].kind,cur[i].ask,cur[i].type,(unsigned long long)cur[i].inst,cur[i].msg); }
            else if(strcmp(cfPrev[j].msg,cur[i].msg) || cfPrev[j].ask!=cur[i].ask){ cfEmit("~",&cur[i]); cfEvents++;
                fprintf(f,"[~] CONFIRM kind=%s ask=%u type=%u \"%s\"\n",cur[i].kind,cur[i].ask,cur[i].type,cur[i].msg); }
        }
        for(int i=0;i<cfPrevN;i++){
            if(cfFind(cur,curN,cfPrev[i].inst)<0){ cfEmit("-",&cfPrev[i]); cfEvents++;
                fprintf(f,"[-] CONFIRM kind=%s\n",cfPrev[i].kind); }
        }
        memcpy(cfPrev,cur,sizeof(CF)*(size_t)curN); cfPrevN=curN;
        if(cfEvents) fflush(f);
        if(!cfEvents){
            fprintf(f,"t=%ums open=%d [%s] confirm=%d",el,nopen,opn,curN);
            if(curN && cur[0].msg[0]) fprintf(f," msg=\"%s\"",cur[0].msg);
            fprintf(f,"\n");
            fflush(f);
        }
        lcapi_sample(f);
        /* 실행창(콘솔): 상태 1줄(이벤트가 있으면 그 아래 갱신) */
        { char line[1100]; int len=snprintf(line,sizeof line,"[UIDLG] t=%ums open=%d [%s] confirm=%d",el,nopen,opn,curN);
          if(curN && cur[0].msg[0]){ size_t L=strlen(line); snprintf(line+L,sizeof line-L," %s",cur[0].msg); len=(int)strlen(line); }
          printf("\r%s",line); for(int i=len;i<plen;i++) putchar(' '); fflush(stdout); plen=len; }
        { LARGE_INTEGER q1; QueryPerformanceCounter(&q1); msAcc+=(double)(q1.QuadPart-q0.QuadPart)*1000.0/(double)fr.QuadPart; }
        if(now-lastRep>=1000){ fprintf(f,"# ioctl=%llu time=%.3fms/1s windows=%d\n",g_ioctl-rRep,msAcc,g_nwin); rRep=g_ioctl; lastRep=now; msAcc=0; }
        /* 실시간: 표시중이면 짧게(기본 100ms), 없으면 유휴(기본 250ms) — 호출 상한 유지 */
        uint32_t sl = (curN>0) ? RG_POLL : RG_IDLE;
        if(sl < minIv) sl = minIv;
        if(P.jitter_ms) sl+=(uint32_t)(rand()%(P.jitter_ms+1));
        Sleep(sl);
        if(lcapi_done() || (secs && (int)(GetTickCount()-t0)>=secs*1000)) break;
    }
    fclose(f); SignedClose(); printf("\ndone -> %s\n",outp); return 0;
}
