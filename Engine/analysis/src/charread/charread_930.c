/* charread_930.c — 캐릭터 정보 읽기 (10_5 규격, 복원본)
 *  규격:
 *    cd     = lc_subsGet(VFT_CHARDATA)          (고정앵커, vft)
 *    status = cd + CD_OFF                        (고정체인)
 *    검증   : *(status) vft == VFT_STATUS
 *    난독화 : (k,b,c) 3x u32
 *             u8=b^k ; check c==((k+K_XOR)^~u8) ; value=u8-(k*K_MUL^K_XOR)
 *    plain  : WEIGHT_CUR / WEIGHT_MAX
 *    EXP%   : cd → +EXP_CD_0/1/2 → +EXP_HUD_BAR → LoadingBar+EXP_BAR_PCT (f32)
 *             (HudCharacterInfo; Status 트리와 별도)
 *             HUD 체인은 살아있는 위젯 의존 → 상태에 따라 +EXP_CD_2 슬롯이
 *             NULL 이면 끊긴다. 이때 BSS ExperiencePct64(f64) 미러로 폴백한다.
 *             미러는 이미 매 표본 읽으므로 폴백 추가 IOCTL = 0.
 *  상수는 registry에서만. 프로그램별 읽기규격: POLL_CHAR_*.
 * usage: charread_930.exe [registry] [secs] [out.txt]
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

static int RM(uint64_t a,void*b,uint32_t s){ return rm(a,b,s); }
static uint64_t Q(uint64_t a){ uint64_t v=0; RM(a,&v,8); return v; }
static uint32_t D32(uint64_t a){ uint32_t v=0; RM(a,&v,4); return v; }

/* 트리플 난독화 디코더 */
static uint32_t g_Kmul, g_Kxor;
static int decAt(uint64_t st,uint32_t off,uint32_t*out){
    uint32_t t[3];
    if(!RM(st+off,t,12)) return 0;              /* (k,b,c) 12B 1콜 배치 */
    uint32_t k=t[0], b=t[1], c=t[2], u8=b^k;
    if(c != ((k+g_Kxor)^~u8)) return 0;
    *out = u8 - (k*g_Kmul ^ g_Kxor);
    return 1;
}

static int crClassOf(uint64_t vft, uint32_t colt, uint32_t tdno, char*out, int cap){
    out[0]=0; if(!isMod(vft)) return 0;
    uint64_t col=q64(vft-8); if(!isMod(col)) return 0;
    uint32_t td=0; if(!rm(col+colt,&td,4)) return 0;
    uint64_t t=g_base+td; if(!isMod(t)) return 0;
    char raw[256]; memset(raw,0,sizeof raw);
    if(!rm(t+tdno,raw,sizeof raw-1)) return 0;
    const char*p=raw; if(!strncmp(p,".?AV",4)) p+=4;
    int n=0; while(*p && *p!='@' && n<cap-1) out[n++]=*p++; out[n]=0;
    return n>0;
}
static uint64_t crFindWin(uint64_t ui, const char*want, uint32_t cval, uint32_t colt, uint32_t tdno){
    const uint32_t heads[2]={0x38,0x28}, nexts[2]={0x18,0x28};
    if(!isHeap(ui)) return 0;
    for(int c=0;c<2;c++){
        uint64_t n=q64(ui+heads[c]);
        for(int k=0; isHeap(n) && k<4096; k++){
            uint64_t x=q64(n+cval);
            if(isHeap(x)){
                char nm[192];
                if(crClassOf(q64(x),colt,tdno,nm,sizeof nm) && !strcmp(nm,want)) return x;
            }
            uint64_t nx=q64(n+nexts[c]); if(nx==n) break; n=nx;
        }
    }
    return 0;
}
int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char*reg=lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    const char*outp=lcreg_outpath("charread_out.txt");
    int secs=0;
    { int seenReg=0;
      for(int i=1;i<argc;i++){
        if(strstr(argv[i],".txt")||strstr(argv[i],".out")){
          if(!seenReg && strstr(argv[i],"REGISTRY")){ reg=argv[i]; seenReg=1; } else { outp=argv[i]; }
        } else if(atoi(argv[i])>0 && !strstr(argv[i],".")){ secs=atoi(argv[i]); }
      }
    }
    lcreg_load(reg);
    lc_reg_apply();
    if(lc_attach())return 1;
    if(!lc_anchor()){ fprintf(stderr,"anchor fail\n"); return 2; }

    lcreg_mkdir_for(outp);
    FILE*f=fopen(outp,"w"); if(!f)return 4;
    uint32_t VFT_CD=lcreg_u32("VFT_CHARDATA",0x11C5CC0);
    uint32_t VFT_ST=lcreg_u32("VFT_STATUS",0x11C5D30);
    uint32_t CD_OFF=lcreg_u32("CD_OFF",0x498);
    g_Kmul=lcreg_u32("K_MUL",0x7f4a7c15);
    g_Kxor=lcreg_u32("K_XOR",0x2f8b1064);
    lcreg_poll P=lcreg_poll_load("CHAR");

    struct{const char*k;uint32_t d;}OF[]={
        {"STAT_STR",0x128},{"STAT_INT",0x134},{"STAT_CON",0x140},{"STAT_DEX",0x14C},
        {"STAT_WIS",0x158},{"STAT_CHA",0x164},{"STAT_LEVEL",0x248},{"STAT_HP",0x2B8},{"STAT_MAXHP",0x2C4},
        {"STAT_MP",0x2D0},{"STAT_MAXMP",0x2DC},{"STAT_FOOD",0x2F4},{"STAT_WEIGHT",0x300},
        {"STAT_LAWFUL",0x30C},{"STAT_AC",0x348}
    };
    enum{STR,INT_,CON,DEX,WIS,CHA,LV,HP,MHP,MP,MMP,FOOD,W,LW,AC};
    uint32_t O[15]; for(int i=0;i<15;i++) O[i]=lcreg_u32(OF[i].k,OF[i].d);
    uint32_t O_WC=lcreg_u32("STAT_WEIGHT_CUR",0x3AC), O_WM=lcreg_u32("STAT_WEIGHT_MAX",0x3B0);
    /* POS: PLAYER_X/Y 전역(셀=월드 타일) — 구 static 블록(ST_*)은 폐기 */
    uint32_t RG_PX=lcreg_u32("PLAYER_X",0x16ED4F0), RG_PY=lcreg_u32("PLAYER_Y",0x16ED4F4);
    /* EXP% 고정체인: CharData → HudZone → HudCharInfo → LoadingBar+PCT */
    uint32_t EXP0=lcreg_u32("EXP_CD_0",0x1B0), EXP1=lcreg_u32("EXP_CD_1",0x28),
             EXP2=lcreg_u32("EXP_CD_2",0x110), EXP_BAR=lcreg_u32("EXP_HUD_BAR",0xE8),
             EXP_PCT=lcreg_u32("EXP_BAR_PCT",0x704);
    uint32_t VFT_BAR=lcreg_u32("VFT_LOADINGBAR",0x12A99E0);
    uint32_t VFT_HCI=lcreg_u32("VFT_HUDCHARINFO",0x127D0A8);
    uint32_t EXP_MIRROR=lcreg_u32("ExperiencePct64",0x1636BD0);

    /* ── EXP%: UI 컨테이너(고정체인)에서 HudCharacterInfoLayout 을 찾아 LoadingBar+0x704 판독 ── */
    uint32_t UVFT = lcreg_u32("VFT_UISUBSYSTEM",0x11EDB98);
    uint32_t UCV  = lcreg_u32("UIDLG_CONT_VAL",0x38);
    uint32_t COLT = lcreg_u32("RTTI_COL_TD_OFF",0xC);
    uint32_t TDNO = lcreg_u32("RTTI_TD_NAME_OFF",0x10);
    char HCICLS[96]; snprintf(HCICLS,sizeof HCICLS,"%s",lcreg_str("HCI_CLASS","HudCharacterInfoLayoutPCImpl"));


    fprintf(f,"registry=%s  CHAR: interval=%ums jitter=%ums\n",reg,P.interval_ms,P.jitter_ms);
    DWORD t0=GetTickCount();
    do{
        g_ioctl=0;
        LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr); QueryPerformanceCounter(&q0);
        uint64_t cd=lc_subsGet(VFT_CD);
        int ok=0;
        if(isHeap(cd)){
            uint64_t st=cd+CD_OFF;
            /* 10_8: status 블록 전체(vft+스탯 트리플+무게)를 1콜 배치로 읽고 오프셋 디코드 */
            uint32_t blk=0x10;
            for(int i=0;i<15;i++){ if(O[i]+12>blk) blk=O[i]+12; }
            if(O_WM+4>blk) blk=O_WM+4; if(blk>0x800) blk=0x800;
            uint8_t stb[0x800];
            uint64_t vft=0; int vok=0; uint32_t val[15]; int valid=0; uint32_t wc=0,wm=0;
            if(RM(st,stb,blk)){
                memcpy(&vft,stb,8);
                vok = isMod(vft) && (uint32_t)(vft-g_base)==VFT_ST;
                for(int i=0;i<15;i++){
                    uint32_t k,b,c;
                    memcpy(&k,stb+O[i],4); memcpy(&b,stb+O[i]+4,4); memcpy(&c,stb+O[i]+8,4);
                    uint32_t u8=b^k;
                    if(c==((k+g_Kxor)^~u8)){ val[i]=u8-(k*g_Kmul^g_Kxor); valid++; } else val[i]=0;
                }
                memcpy(&wc,stb+O_WC,4); memcpy(&wm,stb+O_WM,4);
            }   /* 무게 1콜 배치 */
            fprintf(f,"t=%ums cd=0x%llX status=0x%llX vft=%08X(vok=%d) decode=%d/15\n",
                (unsigned)(GetTickCount()-t0),(unsigned long long)cd,(unsigned long long)st,
                isMod(vft)?(uint32_t)(vft-g_base):0, vok, valid);
            if(vok){
                fprintf(f,"  Lv=%d HP=%d/%d MP=%d/%d  STR=%d INT=%d CON=%d DEX=%d WIS=%d CHA=%d\n",
                    (int)val[LV],(int)val[HP],(int)val[MHP],(int)val[MP],(int)val[MMP],
                    (int)val[STR],(int)val[INT_],(int)val[CON],(int)val[DEX],(int)val[WIS],(int)val[CHA]);
                fprintf(f,"  FOOD=%d WEIGHT%%=%d  W=%u/%u  LAWFUL=%d AC=%d\n",
                    (int)val[FOOD],(int)val[W],wc,wm,(int)val[LW],(int)val[AC]);
                /* 월드 좌표: PLAYER_X/Y 전역(셀=월드 타일). static 블록은 폐기. */
                uint32_t px=0, py=0;
                RM(g_base+RG_PX,&px,4); RM(g_base+RG_PY,&py,4);
                fprintf(f,"  POS: X=%d Y=%d\n",(int)px,(int)py);
                /* EXP%: HUD 고정체인(정본) + BSS 미러 폴백.
                 *  체인은 상태 의존(HudZone+EXP_CD_2 == NULL → HudCharacterInfo 미부착).
                 *  미러는 상시 유효하며 체인 성공값과 일치. 추가 IOCTL 0(이미 읽음). */
                {
                    float expf=0.f; double expm=0.0; int exp_ok=0, mir_ok=0;
                    uint64_t p0=Q(cd+EXP0), p1=isHeap(p0)?Q(p0+EXP1):0;
                    uint64_t p2=isHeap(p1)?Q(p1+EXP2):0, bar=isHeap(p2)?Q(p2+EXP_BAR):0;
                    uint32_t hci_v=isHeap(p2)?vrva(p2):0, bar_v=isHeap(bar)?vrva(bar):0;
                    if(isHeap(bar) && bar_v==VFT_BAR && hci_v==VFT_HCI){
                        RM(bar+EXP_PCT,&expf,4);
                        exp_ok=1;
                    }
                    /* UI 고정체인(정본): HudCharacterInfoLayout → LoadingBar → +EXP_BAR_PCT */
                    if(!exp_ok){
                        static uint64_t cBar = 0;
                        if(!isHeap(cBar) || vrva(cBar)!=VFT_BAR){
                            uint64_t ui2 = lc_subsGet(UVFT);
                            uint64_t hci2 = crFindWin(ui2, HCICLS, UCV, COLT, TDNO);
                            cBar = isHeap(hci2) ? q64(hci2 + EXP_BAR) : 0;
                        }
                        if(isHeap(cBar) && vrva(cBar)==VFT_BAR){ RM(cBar+EXP_PCT,&expf,4); exp_ok=1; }
                    }
                    if(EXP_MIRROR && RM(g_base+EXP_MIRROR,&expm,8)) mir_ok=1;
                    if(exp_ok)
                        fprintf(f,"  EXP=%.4f%%  (src=chain bar=0x%llX)  mirror=%.4f%%\n",
                            (double)expf,(unsigned long long)bar,expm);
                    else if(mir_ok)
                        fprintf(f,"  EXP=%.4f%%  (src=mirror; chain fail hci=%08X bar=%08X)\n",
                            expm,hci_v,bar_v);
                    else
                        fprintf(f,"  EXP=?  (chain fail hci=%08X bar=%08X; mirror unavailable)\n",
                            hci_v,bar_v);
                }
                ok=1;
            }
        } else fprintf(f,"CharData not found\n");
        QueryPerformanceCounter(&q1);
        fprintf(f,"  -> ioctl=%llu time=%.4fms ok=%d\n",g_ioctl,(q1.QuadPart-q0.QuadPart)*1000.0/fr.QuadPart,ok);
        fflush(f);
        lcapi_sample(f);
        if(secs) Sleep(lcreg_poll_sleep_ms(&P));
    } while(!lcapi_done() && secs && (int)(GetTickCount()-t0)<secs*1000);
    fclose(f); SignedClose(); printf("done -> %s\n",outp); return 0;
}

