/* chat_930.c — 채팅 라인 읽기 정본 모듈 (10_5 규격)
 * ---------------------------------------------------------------------------
 *  대원칙:
 *    1) 고정앵커  : UISubsystem = lc_subsGet(VFT_UISUBSYSTEM)   (vft 식별)
 *    2) 고정체인  : UISubsystem 의 레이아웃 컨테이너(UIDLG_CONT)를 walk →
 *                   RTTI 클래스명 == CHAT_LAYOUT_CLASS(HudChatLayoutPCImpl) 인 창.
 *    3) 콘텐츠    : 창 + CHAT_LINES_OFF = std::string* 배열(stride 8) = 채팅 라인 목록.
 *                   각 엔트리 = std::string{데이터@+0, size@CHAT_STR_SIZE, cap@CHAT_STR_CAP}.
 *                   배열은 마지막 엔트리 다음 슬롯이 NULL(측정) → NULL 에서 중단.
 *    4) 인코딩    : CP949(EUC-KR) → UTF-8 변환(CHAT_ENC).
 *    5) MmCopy단일, 상수 registry 단일출처, 읽기규격 POLL_CHAT_*.
 *  usage: chat_930.exe [registry] [secs] [out.txt]
 *  출력: <EXE>\out\chat_out.txt        (라인 순서 = 오래된→최신)
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
static uint32_t RG_UVFT, RG_CVAL, RG_TDNAME, RG_COLTD;
static uint32_t RG_LINESOFF, RG_LINESTRIDE, RG_LINEMAX, RG_STRSZ, RG_STRCP, RG_SSOMAX, RG_STRMAX;
static uint32_t RG_ENC, RG_ENCFB, RG_DEDUPN, RG_STREAM;
static char     RG_CLASS[96];
static uint32_t g_chead[8], g_cnext[8]; static int g_ncont=0;

/* ── 수신메시지 dedup: 최근 N개 라인 해시 기억 → 새 라인만 통과 ───────────── */
#define CHAT_DEDUP_CAP 512
static uint64_t hring[CHAT_DEDUP_CAP]; static int hring_n=0, hring_i=0;
static void hringReset(void){ hring_n=0; hring_i=0; }
static uint64_t lineHash(const char *s){
    uint64_t h=1469598103934665603ULL;
    for(const unsigned char *p=(const unsigned char*)s; *p; p++){ h^=*p; h*=1099511628211ULL; }
    return h;
}
/* 처음이면 1(신선) → ring 에 기록. 이미 봤으면 0. */
static int hringFresh(uint64_t h){
    for(int i=0;i<hring_n;i++) if(hring[i]==h) return 0;
    hring[hring_i]=h; hring_i=(hring_i+1)%(RG_DEDUPN?RG_DEDUPN:CHAT_DEDUP_CAP);
    if(hring_n<(RG_DEDUPN?RG_DEDUPN:CHAT_DEDUP_CAP)) hring_n++;
    return 1;
}

/* ── 묶음호출(페이지 배치) helper — lcore 의 lc_pgRead 경유 ────────────── */
static int      pgrm (uint64_t a, void*b, uint32_t s){ return lc_pgRead(a,b,s); }
static uint64_t pgq64(uint64_t a){ uint64_t v=0; lc_pgRead(a,&v,8); return v; }

/* ── RTTI: vft → 클래스명 ─────────────────────────────────────────────── */
static int classOf(uint64_t vft, char*out, int cap){
    out[0]=0; if(!isMod(vft)) return 0;
    uint64_t col=pgq64(vft-8);
    if(!isMod(col)){ if(col>0 && col<(uint64_t)g_modSize) col=g_base+col; else return 0; }
    uint32_t td_rva=0; if(!pgrm(col+RG_COLTD,&td_rva,4)) return 0;
    uint64_t td=g_base+td_rva; if(!isMod(td)) return 0;
    char raw[512]; memset(raw,0,sizeof(raw)); if(!pgrm(td+RG_TDNAME,raw,sizeof(raw)-1)) return 0;
    const char*p=raw; if(strncmp(p,".?AV",4)==0) p+=4;
    int n=0; while(*p && n<cap-1){ if(p[0]=='@'&&p[1]=='@')break; if(p[0]=='@'){ if(n<cap-2){out[n++]=':';out[n++]=':';} p++; } else out[n++]=*p++; }
    out[n]=0; return n>0;
}
static void shortName(const char*nm, char*out, int cap){
    int t=0; while(nm[t] && nm[t]!=':' && t<cap-1){ out[t]=nm[t]; t++; } out[t]=0;
}
/* UISubsystem 컨테이너 walk → 클래스명 일치 창 반환 (BFS 없음). */
static uint64_t findChatWindow(uint64_t ui){
    if(!isHeap(ui)) return 0;
    for(int c=0;c<g_ncont;c++){
        uint64_t node=pgq64(ui+g_chead[c]);
        uint32_t need = RG_CVAL + 8; if(g_cnext[c]+8 > need) need = g_cnext[c]+8;
        if(need > 0x48) need = 0x48;
        for(int n=0; isHeap(node)&&n<4000; n++){
            uint8_t nb[0x48]; if(!pgrm(node,nb,need)) break;
            uint64_t lay=0,nxt=0;
            memcpy(&lay,nb+RG_CVAL,8); memcpy(&nxt,nb+g_cnext[c],8);
            if(isHeap(lay)){
                uint64_t vf=pgq64(lay);
                if(isMod(vf)){ char nm[128],sh[96]; classOf(vf,nm,sizeof(nm)); shortName(nm,sh,sizeof(sh));
                    if(!strcmp(sh,RG_CLASS)) return lay; }
            }
            if(nxt==node) break;
            node=nxt;
        }
    }
    return 0;
}
/* 인코딩 이름 → 코드페이지. 미지정/미상이면 CP_ACP. */
static uint32_t encId(const char* e){
    if(!e || !e[0]) return 0;
    if(!_stricmp(e,"UTF-8")||!_stricmp(e,"UTF8")||!_stricmp(e,"65001")) return CP_UTF8;
    if(!_stricmp(e,"CP949")||!_stricmp(e,"EUC-KR")||!_stricmp(e,"949")) return 949;
    if(!_stricmp(e,"CP932")||!_stricmp(e,"SHIFT-JIS")||!_stricmp(e,"932")) return 932;
    if(!_stricmp(e,"CP936")||!_stricmp(e,"GBK")||!_stricmp(e,"936")) return 936;
    return CP_ACP;
}
static int mbToUtf8(uint32_t cp, const uint8_t* b, int n, char* out, int cap, uint32_t flags){
    wchar_t wb[0x400];
    int wn=MultiByteToWideChar(cp,flags,(const char*)b,n,wb,0x400);
    if(wn<=0) return 0;
    int un=WideCharToMultiByte(CP_UTF8,0,wb,wn,out,cap-1,0,0);
    if(un<0) un=0; out[un]=0; return un;
}
/* std::string → UTF-8. 1차 인코딩(엄격) → 1차(관대) → 폴백(엄격/관대). 성공 시 1. */
static int decString(uint64_t p, char*out, int cap){
    uint8_t h[0x20]; out[0]=0;
    if(!pgrm(p,h,sizeof(h))) return 0;
    uint64_t sz=*(uint64_t*)(h+RG_STRSZ), cp=*(uint64_t*)(h+RG_STRCP);
    if(!(sz>0 && sz<RG_STRMAX && cp>=sz && cp<0x10000)) return 0;
    uint8_t buf[0x400]; uint64_t src=(cp<RG_SSOMAX)?p:*(uint64_t*)h;
    if(cp>=RG_SSOMAX && !isHeap(src)) return 0;
    if(sz>=sizeof buf) sz=sizeof buf-1;
    if(!pgrm(src,buf,(uint32_t)sz)) return 0;
    buf[sz]=0;
    if(mbToUtf8(RG_ENC,buf,(int)sz,out,cap,MB_ERR_INVALID_CHARS)>0) return 1;
    if(mbToUtf8(RG_ENC,buf,(int)sz,out,cap,0)>0) return 1;
    if(RG_ENCFB && mbToUtf8(RG_ENCFB,buf,(int)sz,out,cap,MB_ERR_INVALID_CHARS)>0) return 1;
    if(RG_ENCFB && mbToUtf8(RG_ENCFB,buf,(int)sz,out,cap,0)>0) return 1;
    return 0;
}

/* ── 입력줄 판별 ──────────────────────────────────────────────────────────
 *  실측: 채팅 배열의 '마지막' 엔트리는 내가 입력 중인 텍스트를 포함하며,
 *        타이핑 중에는 cocos2d-x 커서 마커 CHAT_INPUT_CURSOR(기본 '\') 가 뒤에 붙는다.
 *        (예: "poorboy 힐해달라\" → 전송 후 "poorboy 힐해달라")
 *  실측: UICustomTextField(+0xC0) 서브트리에는 사용자 텍스트가 없고 cocos2d 내부
 *        문자열만 있으므로, CHAT_INPUT_LABEL 오프셋 경로는 사용하지 않는다.
 */
static uint32_t RG_INPOFF, RG_INPCUR;
static char     RG_CURCHAR[8];
#define RG_LINEMAX_MAX 128

/* 마지막(최신) 엔트리이고 커서 마커로 끝나면 '수신'이 아니라 '입력 중' */
static int isInputLine(int isLast, const char *line){
    if(!isLast || !line || !line[0]) return 0;
    if(!RG_CURCHAR[0]) return 0;
    size_t L=strlen(line), C=strlen(RG_CURCHAR);
    if(L<C) return 0;
    return !strcmp(line+L-C, RG_CURCHAR);
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char* reg=lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    const char* outp=lcreg_outpath("chat_out.txt");
    int secs=0, forceStream=0;
    { int seenReg=0;
      for(int i=1;i<argc;i++){
        if(!strcmp(argv[i],"-s")||!strcmp(argv[i],"-stream")){ forceStream=1; continue; }
        if(strstr(argv[i],".txt")||strstr(argv[i],".out")){
          if(!seenReg && strstr(argv[i],"REGISTRY")){ reg=argv[i]; seenReg=1; } else { outp=argv[i]; }
        } else if(atoi(argv[i])>0 && !strstr(argv[i],".")){ secs=atoi(argv[i]); }
      }
    }
    lcreg_load(reg); lc_reg_apply();
    RG_UVFT    = lcreg_u32("VFT_UISUBSYSTEM", 0x11E2710);
    RG_CVAL    = lcreg_u32("UIDLG_CONT_VAL", 0x38);
    RG_TDNAME  = lcreg_u32("RTTI_TD_NAME_OFF", 0x10);
    RG_COLTD   = lcreg_u32("RTTI_COL_TD_OFF", 0xC);
    RG_LINESOFF= lcreg_u32("CHAT_LINES_OFF", 0xF8);
    RG_LINESTRIDE=lcreg_u32("CHAT_LINE_STRIDE", 0x8);
    RG_LINEMAX = lcreg_u32("CHAT_LINE_MAX", 64);
    RG_STRSZ   = lcreg_u32("CHAT_STR_SIZE", 0x10);
    RG_STRCP   = lcreg_u32("CHAT_STR_CAP", 0x18);
    RG_SSOMAX  = lcreg_u32("STR_SSO_MAX", 0x10);
    RG_STRMAX  = lcreg_u32("CHAT_STR_MAX", 0x200);
    snprintf(RG_CLASS,sizeof(RG_CLASS),"%s",lcreg_str("CHAT_LAYOUT_CLASS","HudChatLayoutPCImpl"));
    RG_ENC = encId(lcreg_str("CHAT_ENC","UTF-8"));
    RG_ENCFB = encId(lcreg_str("CHAT_ENC_FALLBACK","CP949"));
    if(RG_ENCFB==RG_ENC) RG_ENCFB = 0;
    RG_DEDUPN = lcreg_u32("CHAT_DEDUP_N", 256);
    RG_STREAM = lcreg_u32("CHAT_STREAM", 0);
    RG_INPOFF = lcreg_u32("CHAT_INPUT_FIELD", 0xC0);
    snprintf(RG_CURCHAR, sizeof RG_CURCHAR, "%s", lcreg_str("CHAT_INPUT_CURSOR", "\\"));
    if(forceStream) RG_STREAM = 1;
    if(RG_DEDUPN > CHAT_DEDUP_CAP) RG_DEDUPN = CHAT_DEDUP_CAP;
    if(!RG_DEDUPN) RG_DEDUPN = 256;
    /* 컨테이너 head:next 쌍 파싱: "0x38:0x18,0x28:0x28" */
    { const char*v=lcreg_str("UIDLG_CONT","0x38:0x18,0x28:0x28"); char buf[128]; strncpy(buf,v,127); buf[127]=0;
      char*tok=strtok(buf,","); while(tok && g_ncont<8){ char*colon=strchr(tok,':'); if(colon){ *colon=0;
          g_chead[g_ncont]=(uint32_t)strtoul(tok,0,0); g_cnext[g_ncont]=(uint32_t)strtoul(colon+1,0,0); g_ncont++; }
        tok=strtok(0,","); } }
    lcreg_poll P = lcreg_poll_load("CHAT");

    if(lc_attach())return 1;
    if(!lc_anchor()){ fprintf(stderr,"anchor fail\n"); return 2; }

    lcreg_mkdir_for(outp);
    FILE *f=fopen(outp,"w"); if(!f){ fprintf(stderr,"cannot open %s\n",outp); return 4; }
    fprintf(f,"# registry=%s VFT_UISUBSYSTEM=%X class=%s enc=%u\n", reg, RG_UVFT, RG_CLASS, RG_ENC);

    DWORD t0=GetTickCount();
    long seq=0, newn=0;
    do{
        LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr); QueryPerformanceCounter(&q0);
        g_ioctl=0;
        lc_pgc_reset();                       /* 묶음호출: 페이지 캐시 사이클 초기화 */
        uint64_t ui = lc_subsGet(RG_UVFT);
        uint64_t chat = isHeap(ui) ? findChatWindow(ui) : 0;
        uint64_t lines = isHeap(chat) ? pgq64(chat+RG_LINESOFF) : 0;
        int n=0, fresh=0, ninp=0;
        fprintf(f,"t=%ums ui=0x%llX chat=0x%llX lines=0x%llX\n",
            (unsigned)(GetTickCount()-t0),(unsigned long long)ui,(unsigned long long)chat,(unsigned long long)lines);
        if(isHeap(lines)){
            /* 1차: 디코드하고 마지막 유효 인덱스를 구한다(커서 마커는 최신 항목에만 적용) */
            static char buf[RG_LINEMAX_MAX][0x400];
            static uint32_t idxof[RG_LINEMAX_MAX];
            uint32_t m=0;
            for(uint32_t i=0;i<RG_LINEMAX;i++){
                uint64_t p=pgq64(lines+(uint64_t)i*RG_LINESTRIDE);
                if(!isHeap(p)) break;                       /* 마지막 다음 슬롯=NULL → 중단 */
                if(decString(p,buf[m],sizeof buf[0])<=0) continue;
                idxof[m]=i; m++;
                if(m>=RG_LINEMAX_MAX) break;
            }
            for(uint32_t k=0;k<m;k++){
                const char *u8=buf[k]; uint32_t i=idxof[k];
                n++;
                if(isInputLine(k==m-1,u8)){                   /* 최신+커서 = 입력 중 → 제외 */
                    ninp++;
                    if(!RG_STREAM) fprintf(f,"  [%2u] IN  \"%s\"\n",i,u8);
                    continue;
                }
                int isnew = hringFresh(lineHash(u8));
                if(isnew) fresh++;
                /* 스트리밍 모드: 새 수신메시지만 출력 / 스냅샷 모드: 전부 */
                if(!RG_STREAM || isnew)
                    fprintf(f,"  [%2u]%s \"%s\"\n",i,isnew?" NEW":"",u8);
            }
        }
        QueryPerformanceCounter(&q1);
        seq+=fresh; newn+=fresh;
        fprintf(f,"# n=%d new=%d input=%d seq=%ld ioctl=%llu time=%.4fms\n",
            n,fresh,ninp,seq,(unsigned long long)g_ioctl,(q1.QuadPart-q0.QuadPart)*1000.0/fr.QuadPart);
        fflush(f);
        lcapi_sample(f);
        if(secs) Sleep(lcreg_poll_sleep_ms(&P));
    } while(!lcapi_done() && secs && (int)(GetTickCount()-t0)<secs*1000);

    fprintf(f,"# TOTAL cycles_new=%ld\n",newn);
    fclose(f); SignedClose(); printf("done -> %s\n",outp); return 0;
}
