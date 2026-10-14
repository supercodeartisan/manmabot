/* uidialog_listen.c — UI 대화창 상태 감시 (extra_ui / 10_5 규격, 봇 DLL)
 * ---------------------------------------------------------------------------
 *  목적: 인벤토리 / 엔피씨대화 / 엔피씨상점 / 창고 / 두루마리 등 열림/닫힘만 감시.
 *
 *  대원칙(고정앵커 + 고정체인, 런타임 BFS 없음):
 *    1) 고정앵커  : UISubsystem = lc_subsGet(VFT_UISUBSYSTEM=0x1182C50); RTTI 폴백.
 *    2) Discover  : UISubsystem 레이아웃 컨테이너 walk (UIDLG_CONT / UIDLG_CONT_VAL).
 *                   주기 UIDLG_SCAN_MS(기본 2000). 봇 경로에 BFS/힙 스캔 금지.
 *    3) Poll      : 매 snapshot(=매 틱) 창당 헤더 1 read → OPEN/CLOSED JSON.
 *    4) 창 식별    : RTTI *Layout[PCImpl] @ ui::lineage — registry UIDLG_WIN_*.
 *    5) 툴 scan()  : 동일 컨테이너 walk (+선택 힙 진단). 실시간 경로와 분리.
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
static uint32_t RG_UVFT, RG_VIS, RG_VISMASK, RG_VISOPEN, RG_NODEREAD, RG_MAXNODES, RG_STOPLAYOUT, RG_MAXCPS, RG_CVAL;
static char     RG_SUFFIX[32], RG_NS[64];
static int      RG_RESCAN=2000;
static uint32_t g_chead[8], g_cnext[8]; static int g_ncont=0;

/* ── 고속 읽기(MmCopy, VirtualQueryEx 생략) — 컨테이너 walk 전용 ───────── */
static int      rmf(uint64_t a, void*b, uint32_t s){ uint32_t br=0; g_ioctl++; return SignedReadFast(g_pid,a,b,s,&br)&&br==s; }
static uint64_t q64f(uint64_t a){ uint64_t v=0; rmf(a,&v,8); return v; }

/* ── 감시 대상(registry UIDLG_WIN_*) ──────────────────────────────────── */
#define MAXWATCH 32
static struct { char label[48]; char cls[96]; int found; } g_watch[MAXWATCH]; static int g_nwatch=0;

/* ── 발견된(=감시) 창 ─────────────────────────────────────────────────── */
typedef struct { char label[48]; char cls[96]; uint64_t inst; uint32_t vft; } WIN;
static WIN g_win[MAXWATCH]; static int g_nwin=0;
static int g_nall=0;                       /* BFS 로 발견한 전체 Layout 수 */
static char g_allcls[96][96]; static int g_nallcls=0;
static char CACHE[MAX_PATH*2]={0};

/* ── RTTI: vft → 클래스명 ─────────────────────────────────────────────── */
static int classOf(uint64_t vft, char*out, int cap){
    out[0]=0; if(!isMod(vft)) return 0;
    uint64_t col=q64(vft-8);
    if(!isMod(col)){ if(col>0 && col<(uint64_t)g_modSize) col=g_base+col; else return 0; }
    uint32_t td_rva=0; rm(col+0xC,&td_rva,4);
    uint64_t td=g_base+td_rva; if(!isMod(td)) return 0;
    char raw[512]; memset(raw,0,sizeof(raw)); if(!rm(td+0x10,raw,sizeof(raw)-1)) return 0;
    const char*p=raw; if(strncmp(p,".?AV",4)==0) p+=4;
    int n=0; while(*p && n<cap-1){ if(p[0]=='@'&&p[1]=='@')break; if(p[0]=='@'){ if(n<cap-2){out[n++]=':';out[n++]=':';} p++; } else out[n++]=*p++; }
    out[n]=0; return n>0;
}
/* 창 클래스명: "…<SUFFIX>PCImpl" / "…<SUFFIX>MobileImpl" / "…<SUFFIX>" (base) 모두 인정.
 *  예) NPCDialogLayoutPCImpl, TeleportBookLayout(PCImpl 변형 없음). */
static int isLayout(const char*nm){
    if(!nm[0] || !strstr(nm,RG_NS)) return 0;
    int t=0; while(nm[t] && nm[t]!=':' && t<200) t++;      /* short name 길이 */
    int be=t;
    if(be>=6 && !strncmp(nm+be-6,"PCImpl",6)) be-=6;
    else if(be>=10 && !strncmp(nm+be-10,"MobileImpl",10)) be-=10;
    int sl=(int)strlen(RG_SUFFIX);
    return be>=sl && strncmp(nm+be-sl,RG_SUFFIX,(size_t)sl)==0;
}
static void shortName(const char*nm, char*out, int cap){
    int t=0; while(nm[t] && nm[t]!=':' && t<cap-1){ out[t]=nm[t]; t++; } out[t]=0;
}
/* 감시집합에 있으면 라벨 반환 */
static const char* watchLabel(const char*cls){
    for(int i=0;i<g_nwatch;i++) if(!strcmp(g_watch[i].cls,cls)) return g_watch[i].label;
    return 0;
}

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

/* ── 컨테이너 walk: 앵커의 레이아웃 컨테이너를 직접 순회(고정체인) ──────── */
static void addWin(const char*label, const char*sh, uint64_t lay, uint32_t vft){
    for(int k=0;k<g_nwin;k++) if(!strcmp(g_win[k].cls,sh)) return;
    if(g_nwin>=MAXWATCH) return;
    WIN*W=&g_win[g_nwin++];
    strncpy(W->label,label,47); W->label[47]=0;
    strncpy(W->cls,sh,95); W->cls[95]=0;
    W->inst=lay; W->vft=vft;
    for(int i=0;i<g_nwatch;i++) if(!strcmp(g_watch[i].label,label)) g_watch[i].found=1;
}
static void containerScan(uint64_t ui){
    g_nwin=0; g_nall=0; g_nallcls=0;
    for(int i=0;i<g_nwatch;i++) g_watch[i].found=0;
    if(!isHeap(ui) || g_ncont<=0) return;
    for(int c=0;c<g_ncont;c++){
        uint64_t node=q64f(ui+g_chead[c]);
        for(int n=0;n<2048 && isHeap(node);n++){
            uint64_t lay=q64f(node+RG_CVAL);
            if(isHeap(lay)){
                uint64_t vf=q64f(lay);
                if(isMod(vf)){
                    char nm[128],sh[96];
                    classOf(vf,nm,sizeof(nm)); shortName(nm,sh,sizeof(sh));
                    if(isLayout(nm)){
                        g_nall++;
                        { int d=0; for(int k=0;k<g_nallcls;k++) if(!strcmp(g_allcls[k],sh)){d=1;break;}
                          if(!d && g_nallcls<96){ strncpy(g_allcls[g_nallcls],sh,95); g_allcls[g_nallcls][95]=0; g_nallcls++; } }
                        const char*lb=watchLabel(sh);
                        if(lb) addWin(lb,sh,lay,(uint32_t)(vf-g_base));
                    }
                }
            }
            node=q64f(node+g_cnext[c]);
        }
    }
}

/* ── seen 해시 / vft 캐시 (툴 BFS 진단용) ─────────────────────────────── */
#define SEEN_HS 262144
static uint64_t seen_k[SEEN_HS];
static int seenHas(uint64_t p){ uint32_t i=(uint32_t)((p>>4)&(SEEN_HS-1));
    for(int pr=0;pr<8;pr++){ uint32_t j=(i+pr)&(SEEN_HS-1); if(seen_k[j]==0)return 0; if(seen_k[j]==p)return 1; } return 0; }
static void seenAdd(uint64_t p){ uint32_t i=(uint32_t)((p>>4)&(SEEN_HS-1));
    for(int pr=0;pr<8;pr++){ uint32_t j=(i+pr)&(SEEN_HS-1); if(seen_k[j]==0){seen_k[j]=p;return;} if(seen_k[j]==p)return; } }
#define VC_HS 65536
static uint64_t vc_k[VC_HS]; static signed char vc_r[VC_HS];
static int vftIsLayout(uint64_t vf){ uint32_t i=(uint32_t)((vf>>4)&(VC_HS-1));
    for(int pr=0;pr<8;pr++){ uint32_t j=(i+pr)&(VC_HS-1);
        if(vc_k[j]==0){ char nm[128]; int r=classOf(vf,nm,sizeof(nm))&&isLayout(nm); vc_k[j]=vf; vc_r[j]=(signed char)(r?1:-1); return r; }
        if(vc_k[j]==vf) return vc_r[j]>0; } return 0; }

/* ── 앵커 BFS → 감시 창만 수집 ────────────────────────────────────────── */
static uint64_t Q[60000]; static uint8_t ndbuf[0x800];
static void discover(uint64_t ui){
    g_nwin=0; g_nall=0; g_nallcls=0;
    for(int i=0;i<g_nwatch;i++) g_watch[i].found=0;
    memset(seen_k,0,sizeof(seen_k)); memset(vc_k,0,sizeof(vc_k));
    if(!isHeap(ui)) return;
    int qh=0,qt=0,sn=0; Q[qt++]=ui; seenAdd(ui); sn=1;
    while(qh<qt && sn<(int)RG_MAXNODES){
        uint64_t n=Q[qh++]; uint64_t vf=q64(n);
        int isL=0;
        if(isMod(vf) && vftIsLayout(vf)){
            isL=1; g_nall++;
            char nm[128]; classOf(vf,nm,sizeof(nm)); char sh[96]; shortName(nm,sh,sizeof(sh));
            { int d=0; for(int k=0;k<g_nallcls;k++) if(!strcmp(g_allcls[k],sh)){d=1;break;}
              if(!d && g_nallcls<96){ strncpy(g_allcls[g_nallcls],sh,95); g_allcls[g_nallcls][95]=0; g_nallcls++; } }
            const char*lb=watchLabel(sh);
            if(lb){
                int dup=0; for(int k=0;k<g_nwin;k++) if(!strcmp(g_win[k].cls,sh)){dup=1;break;}
                if(!dup && g_nwin<MAXWATCH){
                    strncpy(g_win[g_nwin].label,lb,47); g_win[g_nwin].label[47]=0;
                    strncpy(g_win[g_nwin].cls,sh,95); g_win[g_nwin].cls[95]=0;
                    g_win[g_nwin].inst=n; g_win[g_nwin].vft=(uint32_t)(vf-g_base);
                    g_nwin++;
                    for(int i=0;i<g_nwatch;i++) if(!strcmp(g_watch[i].label,lb)) g_watch[i].found=1;
                }
            }
        }
        if(isL && RG_STOPLAYOUT) continue;
        if(!rm(n,ndbuf,RG_NODEREAD)) continue;
        for(uint32_t o=0;o+8<=RG_NODEREAD;o+=8){ uint64_t p=*(uint64_t*)(ndbuf+o);
            if(!isHeap(p) || seenHas(p)) continue;
            if(!isMod(q64(p))) continue;
            seenAdd(p); if(sn<(int)RG_MAXNODES){ Q[qt++]=p; sn++; }
        }
    }
}
/* ── PID 캐시 ─────────────────────────────────────────────────────────── */
static int cacheLoad(void){
    if(!CACHE[0]) return 0;
    FILE*f=fopen(CACHE,"r"); if(!f) return 0;
    char line[256]; unsigned long long cpid=0,cbase=0;
    if(!fgets(line,sizeof(line),f) || sscanf(line,"pid=%llu base=%llx",&cpid,&cbase)!=2
       || cpid!=g_pid || cbase!=g_base){ fclose(f); return 0; }
    int n=0;
    while(n<MAXWATCH && fgets(line,sizeof(line),f)){
        unsigned vft; unsigned long long inst; char lab[48],cls[96];
        if(sscanf(line,"win %x %llx %47s %95s",&vft,&inst,lab,cls)!=4) continue;
        if(q64((uint64_t)inst)!=g_base+vft){ n=0; break; }
        g_win[n].vft=vft; g_win[n].inst=(uint64_t)inst;
        strncpy(g_win[n].label,lab,47); g_win[n].label[47]=0;
        strncpy(g_win[n].cls,cls,95);   g_win[n].cls[95]=0;
        n++;
    }
    fclose(f);
    if(n<1) return 0;
    g_nwin=n;
    for(int i=0;i<g_nwatch;i++){ g_watch[i].found=0;
        for(int k=0;k<g_nwin;k++) if(!strcmp(g_watch[i].label,g_win[k].label)) g_watch[i].found=1; }
    return 1;
}
static void cacheSave(void){
    if(!CACHE[0]) return;
    FILE*f=fopen(CACHE,"w"); if(!f) return;
    fprintf(f,"pid=%llu base=%llx\n",(unsigned long long)g_pid,(unsigned long long)g_base);
    for(int i=0;i<g_nwin;i++)
        fprintf(f,"win %08X %llX %s %s\n",g_win[i].vft,(unsigned long long)g_win[i].inst,g_win[i].label,g_win[i].cls);
    fclose(f);
}

/* Tool scan: one fresh walk per call. Does not replace the bot's g_win cache. */
#define SCAN_CLS 96
#define SCAN_HITS 64
typedef struct {
    char label[48];
    char cls[96];
    uint64_t inst;
    uint32_t vft;
    uint32_t vis;
    int open;
} SCANHIT;
static SCANHIT g_hits[SCAN_HITS];
static int g_nhits = 0;
static char g_scanCls[SCAN_CLS][96];
static int g_scanNcls = 0;
static int g_scanNodes = 0;
static int g_scanLayouts = 0;
static int g_heapBytes = 0;
static int g_heapTotal = 0;
static int g_heapDone = 0;
static uint64_t g_heapAddr = 0;
static struct { char label[48]; uint32_t rva; } g_vftwin[MAXWATCH];
static int g_nvftwin = 0;

static const char* vftWinLabel(uint32_t rva) {
    if (!rva) return 0;
    for (int i = 0; i < g_nvftwin; i++)
        if (g_vftwin[i].rva == rva) return g_vftwin[i].label;
    return 0;
}

static void loadWindowVfts(void) {
    g_nvftwin = 0;
    for (int i = 0; i < g_nwatch && g_nvftwin < MAXWATCH; i++) {
        char key[80];
        uint32_t rva;
        snprintf(key, sizeof(key), "WINDOW_%s", g_watch[i].label);
        rva = lcreg_u32(key, 0);
        if (!rva) continue;
        strncpy(g_vftwin[g_nvftwin].label, g_watch[i].label, 47);
        g_vftwin[g_nvftwin].label[47] = 0;
        g_vftwin[g_nvftwin].rva = rva;
        g_nvftwin++;
    }
}

static void addScanHit(const char* label, const char* cls, uint64_t inst,
                        uint32_t vft, uint32_t vis, int open) {
    if (!label || !label[0] || g_nhits >= SCAN_HITS) return;
    for (int i = 0; i < g_nhits; i++) if (g_hits[i].inst == inst) return;
    strncpy(g_hits[g_nhits].label, label, 47);
    g_hits[g_nhits].label[47] = 0;
    strncpy(g_hits[g_nhits].cls, cls ? cls : "", 95);
    g_hits[g_nhits].cls[95] = 0;
    g_hits[g_nhits].inst = inst;
    g_hits[g_nhits].vft = vft;
    g_hits[g_nhits].vis = vis;
    g_hits[g_nhits].open = open ? 1 : 0;
    g_nhits++;
}

static void readVis(uint64_t n, uint64_t vf, uint32_t* vis, int* openFlag) {
    uint8_t hb[0x78];
    *vis = 0;
    *openFlag = 0;
    if (!n || !rm(n, hb, sizeof(hb))) return;
    if (*(uint64_t*)hb != vf) return;
    *vis = *(uint32_t*)(hb + RG_VIS);
    *openFlag = ((*vis & RG_VISMASK) == RG_VISOPEN) ? 1 : 0;
}

/* Full UI walk for Memory Watch. Descends into layouts and keeps every hit. */
static void discoverScan(uint64_t ui) {
    g_scanNcls = 0;
    g_scanNodes = 0;
    g_scanLayouts = 0;
    memset(seen_k, 0, sizeof(seen_k));
    memset(vc_k, 0, sizeof(vc_k));
    if (!isHeap(ui)) return;
    int qh = 0, qt = 0, sn = 0;
    int cap = (int)RG_MAXNODES;
    if (cap > 8000) cap = 8000;
    Q[qt++] = ui;
    seenAdd(ui);
    sn = 1;
    while (qh < qt && sn < cap) {
        uint64_t n = Q[qh++];
        uint64_t vf = q64(n);
        g_scanNodes++;
        if (isMod(vf)) {
            uint32_t rva = (uint32_t)(vf - g_base);
            int isL = vftIsLayout(vf);
            char sh[96];
            sh[0] = 0;
            const char* lb = 0;
            if (isL) {
                char nm[128];
                g_scanLayouts++;
                classOf(vf, nm, sizeof(nm));
                shortName(nm, sh, sizeof(sh));
                if (sh[0]) {
                    int d = 0;
                    for (int k = 0; k < g_scanNcls; k++)
                        if (!strcmp(g_scanCls[k], sh)) { d = 1; break; }
                    if (!d && g_scanNcls < SCAN_CLS) {
                        strncpy(g_scanCls[g_scanNcls], sh, 95);
                        g_scanCls[g_scanNcls][95] = 0;
                        g_scanNcls++;
                    }
                }
                lb = watchLabel(sh);
            }
            if (!lb) lb = vftWinLabel(rva);
            if (lb) {
                uint32_t vis = 0;
                int openFlag = 0;
                readVis(n, vf, &vis, &openFlag);
                addScanHit(lb, sh, n, rva, vis, openFlag);
            }
        }
        /* Bot BFS only follows vft-headed pointers inside 0x100 bytes and
         * stops at the first layout, so a live dialog never enters g_win.
         * The tool walk reads a wider header and follows every heap pointer. */
        {
            uint32_t nread = 0x800;
            if (nread > sizeof(ndbuf)) nread = (uint32_t)sizeof(ndbuf);
            if (!rm(n, ndbuf, nread)) continue;
            for (uint32_t o = 0; o + 8 <= nread; o += 8) {
                uint64_t p = *(uint64_t*)(ndbuf + o);
                if (!isHeap(p) || seenHas(p)) continue;
                seenAdd(p);
                if (qt < (int)(sizeof(Q) / sizeof(Q[0])) && sn < cap) {
                    Q[qt++] = p;
                    sn++;
                }
            }
        }
    }
}

static int g_ready = 0;
static int g_discovered = 0;
static DWORD g_lastDiscover = 0;
static char g_regPath[MAX_PATH * 2] = {0};
static const char* g_src = "none"; /* "cont" | "cache" | "bfs" | "none" */
static uint64_t g_ui = 0;

static int windowsVftAliveCount(void) {
    int n = 0;
    for (int i = 0; i < g_nwin; i++) {
        uint64_t o = g_win[i].inst;
        uint8_t hb[0x78];
        if (o && rm(o, hb, sizeof(hb)) && *(uint64_t*)hb == g_base + g_win[i].vft) n++;
    }
    return n;
}

/* Bot realtime: container walk only. Poll is writeUidlgJson on every snapshot. */
static void runDiscover(uint64_t ui) {
    if (g_ncont > 0) {
        containerScan(ui);
        g_src = "cont";
    } else {
        discover(ui);
        g_src = "bfs";
    }
#ifndef UIDIALOG_LISTEN_DLL
    if (g_nwin > 0) cacheSave();
#endif
    g_lastDiscover = GetTickCount();
    g_discovered = (g_nwin > 0) ? 1 : 0; /* empty → retry next snapshot */
    g_ui = ui;
}

static void setRootFromRegistry(const char* reg) {
    char dir[MAX_PATH * 2];
    char* slash;
    snprintf(dir, sizeof(dir), "%s", reg ? reg : "");
    slash = strrchr(dir, '\\'); if (!slash) slash = strrchr(dir, '/');
    if (slash) *slash = 0;
    slash = strrchr(dir, '\\'); if (!slash) slash = strrchr(dir, '/');
    if (slash) *slash = 0;
    snprintf(LCREG_UP, sizeof(LCREG_UP), "%s", dir);
    snprintf(LCREG_BASE, sizeof(LCREG_BASE), "%s", dir);
    if (dir[0]) SetCurrentDirectoryA(dir);
}

static int protectReadable(DWORD prot) {
    if (prot & 0x100) return 0;
    switch (prot & 0xFF) {
        case 0x02: case 0x04: case 0x08:
        case 0x10: case 0x20: case 0x40: case 0x80:
            return 1;
    }
    return 0;
}

/* Dialog widgets are not linked inside the UISubsystem pointer neighborhood.
 * Find instances by their registry WINDOW_* vft qword in private heap. */
static void refreshScanHits(void) {
    int w = 0;
    for (int i = 0; i < g_nhits; i++) {
        uint64_t vf = g_base + g_hits[i].vft;
        uint32_t vis = 0;
        int openFlag = 0;
        uint8_t hb[8];
        if (!rm(g_hits[i].inst, hb, 8) || *(uint64_t*)hb != vf) continue;
        readVis(g_hits[i].inst, vf, &vis, &openFlag);
        g_hits[w] = g_hits[i];
        g_hits[w].vis = vis;
        g_hits[w].open = openFlag;
        w++;
    }
    g_nhits = w;
}

static void scanHeapForVfts(void) {
    HANDLE hp;
    MEMORY_BASIC_INFORMATION mbi;
    uint64_t addr;
    uint64_t targets[MAXWATCH];
    static uint8_t win[0x10000];
    DWORD t0;
    g_heapBytes = 0;
    g_heapDone = 0;
    if (!g_nvftwin || !g_pid || !g_base) return;
    for (int i = 0; i < g_nvftwin; i++) targets[i] = g_base + g_vftwin[i].rva;
    hp = OpenProcess(PROCESS_QUERY_INFORMATION, FALSE, (DWORD)g_pid);
    if (!hp) hp = OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, FALSE, (DWORD)g_pid);
    if (!hp) return;
    addr = g_heapAddr;
    t0 = GetTickCount();
    while (g_nhits < SCAN_HITS && (GetTickCount() - t0) < 700) {
        SIZE_T got = VirtualQueryEx(hp, (LPCVOID)(uintptr_t)addr, &mbi, sizeof(mbi));
        uint64_t base, sz, next;
        if (!got) break;
        base = (uint64_t)(uintptr_t)mbi.BaseAddress;
        sz = (uint64_t)mbi.RegionSize;
        if (!sz) break;
        next = base + sz;
        if (mbi.State == 0x1000 && mbi.Type == 0x20000 &&
            protectReadable(mbi.Protect) && sz >= 0x1000 && sz < 0x80000000ULL &&
            isHeap(base) && !(base < g_base + g_modSize && next > g_base)) {
            for (uint64_t p = base; p + 8 <= next && g_nhits < SCAN_HITS; ) {
                uint32_t want = 0x10000;
                uint32_t br = 0;
                if (next - p < want) want = (uint32_t)(next - p);
                if (want < 8) break;
                if (!SignedReadMemory(g_pid, p, win, want, &br) || br < 8) {
                    p += want;
                    continue;
                }
                g_heapBytes += (int)br;
                for (uint32_t o = 0; o + 8 <= br; o += 8) {
                    uint64_t q = *(uint64_t*)(win + o);
                    for (int k = 0; k < g_nvftwin; k++) {
                        char nm[128], sh[96];
                        const char* expect = 0;
                        uint64_t inst;
                        uint32_t vis = 0;
                        int openFlag = 0;
                        if (q != targets[k]) continue;
                        if (!classOf(q, nm, sizeof(nm))) continue;
                        shortName(nm, sh, sizeof(sh));
                        for (int w = 0; w < g_nwatch; w++) {
                            if (!strcmp(g_watch[w].label, g_vftwin[k].label)) {
                                expect = g_watch[w].cls;
                                break;
                            }
                        }
                        if (!expect || strcmp(sh, expect) != 0) continue;
                        inst = p + o;
                        readVis(inst, q, &vis, &openFlag);
                        /* A copied vft pointer in the middle of another object
                         * fails the visibility dword (not 0..VIS_MASK). */
                        if (vis > RG_VISMASK) continue;
                        addScanHit(g_vftwin[k].label, sh, inst, g_vftwin[k].rva, vis, openFlag);
                    }
                }
                p += br;
                if ((GetTickCount() - t0) >= 2500) break;
            }
        }
        if (next <= addr) break;
        addr = next;
        if (addr >= 0x0000800000000000ULL) { g_heapDone = 1; addr = 0; g_heapTotal = 0; break; }
    }
    g_heapAddr = addr;
    g_heapTotal += g_heapBytes;
    CloseHandle(hp);
}

static int uidlgEnsure(const char* registryPath) {
    const char* reg = registryPath && registryPath[0] ? registryPath : g_regPath;
    if (!reg || !reg[0]) reg = "registry/LC930_REGISTRY.txt";
    if (!g_ready || (registryPath && registryPath[0] && strcmp(g_regPath, registryPath) != 0)) {
        if (registryPath && registryPath[0]) {
            strncpy(g_regPath, registryPath, sizeof(g_regPath) - 1);
            g_regPath[sizeof(g_regPath) - 1] = 0;
            reg = g_regPath;
        }
        setRootFromRegistry(reg);
        snprintf(CACHE, sizeof(CACHE), "%s\\out\\uidialogmon_cache.txt", LCREG_BASE);
        lcreg_mkdir_for(CACHE);
        lcreg_load(reg);
        lc_reg_apply();
        RG_UVFT = lcreg_u32("VFT_UISUBSYSTEM", 0x1182C50);
        RG_VIS = lcreg_u32("VIS_FLAG", 0x70);
        RG_VISMASK = lcreg_u32("VIS_MASK", 0xFF);
        RG_VISOPEN = lcreg_u32("VIS_OPEN", 1);
        RG_NODEREAD = lcreg_u32("UI_BFS_NODE_READ", 0x100);
        if (RG_NODEREAD > 0x800) RG_NODEREAD = 0x800;
        if (RG_NODEREAD < 0x40) RG_NODEREAD = 0x40;
        RG_MAXNODES = lcreg_u32("UI_BFS_MAX_NODES", 60000);
        RG_STOPLAYOUT = lcreg_u32("UI_BFS_STOP_AT_LAYOUT", 1);
        RG_MAXCPS = lcreg_u32("UIDLG_MAX_CALLS_PER_SEC", 500);
        if (!RG_MAXCPS) RG_MAXCPS = 500;
        /* Prefer UIDLG_SCAN_MS (extra_ui); fall back to UIDLG_RESCAN_MS. Default 2s. */
        RG_RESCAN = (int)lcreg_u32("UIDLG_SCAN_MS", 0);
        if (RG_RESCAN <= 0) RG_RESCAN = (int)lcreg_u32("UIDLG_RESCAN_MS", 2000);
        if (RG_RESCAN <= 0) RG_RESCAN = 2000;
        RG_CVAL = lcreg_u32("UIDLG_CONT_VAL", 0x38);
        g_ncont = 0;
        {
            const char* v = lcreg_str("UIDLG_CONT", "0x38:0x18,0x28:0x28");
            char buf[128];
            strncpy(buf, v, 127); buf[127] = 0;
            char* tok = strtok(buf, ",");
            while (tok && g_ncont < 8) {
                char* colon = strchr(tok, ':');
                if (colon) {
                    *colon = 0;
                    g_chead[g_ncont] = (uint32_t)strtoul(tok, 0, 0);
                    g_cnext[g_ncont] = (uint32_t)strtoul(colon + 1, 0, 0);
                    g_ncont++;
                }
                tok = strtok(0, ",");
            }
        }
        snprintf(RG_SUFFIX, sizeof(RG_SUFFIX), "%s", lcreg_str("UI_LAYOUT_SUFFIX", "Layout"));
        snprintf(RG_NS, sizeof(RG_NS), "%s", lcreg_str("UI_LAYOUT_NS", "ui::lineage"));
        g_nwatch = 0;
        for (int i = 0; i < LCREG_N && g_nwatch < MAXWATCH; i++) {
            if (strncmp(LCREG_K[i], "UIDLG_WIN_", 10) == 0) {
                snprintf(g_watch[g_nwatch].label, sizeof(g_watch[g_nwatch].label), "%s", LCREG_K[i] + 10);
                snprintf(g_watch[g_nwatch].cls, sizeof(g_watch[g_nwatch].cls), "%s", LCREG_V[i]);
                g_watch[g_nwatch].found = 0;
                g_nwatch++;
            }
        }
        loadWindowVfts();
        g_discovered = 0;
        g_lastDiscover = 0;
        g_nwin = 0;
        g_src = "none";
        g_ui = 0;
        g_ready = 1;
    }
    if (lc_attach()) return 0;
    if (!lc_anchor()) return 0;
    {
        uint64_t ui = anchorUI();
        DWORD now = GetTickCount();
        int needDiscover = 0;
        g_ui = ui;
        if (!isHeap(ui)) return 0;
        if (!g_discovered) {
#ifdef UIDIALOG_LISTEN_DLL
            needDiscover = 1; /* never trust disk cache in the bot DLL */
#else
            if (cacheLoad() && g_nwin > 0) {
                g_discovered = 1;
                g_lastDiscover = now;
                g_src = "cache";
            } else {
                needDiscover = 1;
            }
#endif
        } else if (g_nwin == 0) {
            needDiscover = 1;
        } else if (RG_RESCAN > 0 && g_lastDiscover != 0
                   && (now - g_lastDiscover) >= (DWORD)RG_RESCAN) {
            needDiscover = 1; /* periodic container rediscover (~2s) */
        } else if (g_nwin > 0 && windowsVftAliveCount() == 0) {
            needDiscover = 1; /* all cached inst dead → session churn */
        }
        if (needDiscover) runDiscover(ui);
    }
    return 1;
}

static int writeUidlgJson(FILE* f) {
    int nopen = 0, first = 1;
    fprintf(f,
            "{\"cmd\":\"uidialog\",\"pid\":%llu,\"base\":\"0x%llX\",\"ui\":\"0x%llX\","
            "\"src\":\"%s\",\"layouts\":%d,\"watched\":%d,\"windows\":{",
            (unsigned long long)g_pid, (unsigned long long)g_base,
            (unsigned long long)g_ui, g_src ? g_src : "none", g_nall, g_nwin);
    for (int i = 0; i < g_nwin; i++) {
        uint64_t o = g_win[i].inst;
        uint8_t hb[0x78];
        int alive = o && rm(o, hb, sizeof(hb)) && *(uint64_t*)hb == g_base + g_win[i].vft;
        uint32_t vis = alive ? *(uint32_t*)(hb + RG_VIS) : 0u;
        alive = alive && (vis & RG_VISMASK) == RG_VISOPEN;
        if (!first) fputc(',', f);
        first = 0;
        fprintf(f, "\"%s\":%s", g_win[i].label, alive ? "true" : "false");
        if (alive) nopen++;
    }
    /* Also emit absent watch labels as false. */
    for (int i = 0; i < g_nwatch; i++) {
        int seen = 0;
        for (int k = 0; k < g_nwin; k++) if (!strcmp(g_watch[i].label, g_win[k].label)) { seen = 1; break; }
        if (seen) continue;
        if (!first) fputc(',', f);
        first = 0;
        fprintf(f, "\"%s\":false", g_watch[i].label);
    }
    fprintf(f, "},\"open\":[");
    first = 1;
    for (int i = 0; i < g_nwin; i++) {
        uint64_t o = g_win[i].inst;
        uint8_t hb[0x78];
        int alive = o && rm(o, hb, sizeof(hb)) && *(uint64_t*)hb == g_base + g_win[i].vft;
        uint32_t vis = alive ? *(uint32_t*)(hb + RG_VIS) : 0u;
        alive = alive && (vis & RG_VISMASK) == RG_VISOPEN;
        if (!alive) continue;
        if (!first) fputc(',', f);
        first = 0;
        fprintf(f, "\"%s\"", g_win[i].label);
    }
    fprintf(f, "],\"n_open\":%d,\"n_watch\":%d}", nopen, g_nwatch);
    return 1;
}

static void jsonEsc(const char* in, char* out, int cap) {
    int o = 0;
    if (!in) { if (cap > 0) out[0] = 0; return; }
    for (int i = 0; in[i] && o < cap - 2; i++) {
        unsigned char c = (unsigned char)in[i];
        if (c == '"' || c == '\\') {
            if (o + 2 >= cap) break;
            out[o++] = '\\';
            out[o++] = (char)c;
        } else if (c < 0x20) {
            continue;
        } else {
            out[o++] = (char)c;
        }
    }
    out[o] = 0;
}

static int hitOpen(const char* label) {
    for (int i = 0; i < g_nhits; i++)
        if (!strcmp(g_hits[i].label, label) && g_hits[i].open) return 1;
    return 0;
}

static int writeScanJson(FILE* f) {
    int nopen = 0, first = 1;
    char esc[160];
    fprintf(f,
            "{\"cmd\":\"uidialog_scan\",\"pid\":%llu,\"base\":\"0x%llX\",\"ui\":\"0x%llX\","
            "\"src\":\"%s\",\"nodes\":%d,\"layouts\":%d,\"heap_bytes\":%d,\"heap_total\":%d,\"heap_done\":%s,\"classes\":[",
            (unsigned long long)g_pid, (unsigned long long)g_base,
            (unsigned long long)g_ui, g_src ? g_src : "scan", g_scanNodes, g_scanLayouts,
            g_heapBytes, g_heapTotal, g_heapDone ? "true" : "false");
    for (int i = 0; i < g_scanNcls; i++) {
        jsonEsc(g_scanCls[i], esc, (int)sizeof(esc));
        if (i) fputc(',', f);
        fprintf(f, "\"%s\"", esc);
    }
    fprintf(f, "],\"hits\":[");
    for (int i = 0; i < g_nhits; i++) {
        jsonEsc(g_hits[i].cls, esc, (int)sizeof(esc));
        if (i) fputc(',', f);
        fprintf(f,
                "{\"label\":\"%s\",\"cls\":\"%s\",\"vft\":\"0x%X\",\"inst\":\"0x%llX\","
                "\"vis\":%u,\"open\":%s}",
                g_hits[i].label, esc, g_hits[i].vft,
                (unsigned long long)g_hits[i].inst, g_hits[i].vis,
                g_hits[i].open ? "true" : "false");
    }
    fprintf(f, "],\"windows\":{");
    for (int i = 0; i < g_nwatch; i++) {
        int op = hitOpen(g_watch[i].label);
        if (i) fputc(',', f);
        fprintf(f, "\"%s\":%s", g_watch[i].label, op ? "true" : "false");
        if (op) nopen++;
    }
    fprintf(f, "},\"open\":[");
    first = 1;
    for (int i = 0; i < g_nwatch; i++) {
        if (!hitOpen(g_watch[i].label)) continue;
        if (!first) fputc(',', f);
        first = 0;
        fprintf(f, "\"%s\"", g_watch[i].label);
    }
    fprintf(f, "],\"n_open\":%d,\"n_hits\":%d,\"n_watch\":%d}", nopen, g_nhits, g_nwatch);
    return 1;
}

__declspec(dllexport) int uidialog_listen_scan(const char* registryPath, char* out, int outCap) {
    FILE* tf;
    long n;
    size_t got;
    uint64_t ui;
    if (!out || outCap < 16) return -1;
    if (!uidlgEnsure(registryPath)) return -1;
    ui = g_ui ? g_ui : anchorUI();
    g_ui = ui;
    /* Prefer same discover as the bot; heap only if container found nothing. */
    g_nhits = 0;
    if (isHeap(ui) && g_ncont > 0) {
        containerScan(ui);
        g_src = "cont";
        g_lastDiscover = GetTickCount();
        g_discovered = (g_nwin > 0) ? 1 : 0;
        g_scanNodes = 0;
        g_scanLayouts = g_nall;
        g_scanNcls = g_nallcls;
        for (int i = 0; i < g_nallcls && i < SCAN_CLS; i++) {
            strncpy(g_scanCls[i], g_allcls[i], 95);
            g_scanCls[i][95] = 0;
        }
        for (int i = 0; i < g_nwin; i++) {
            uint32_t vis = 0;
            int openFlag = 0;
            readVis(g_win[i].inst, g_base + g_win[i].vft, &vis, &openFlag);
            addScanHit(g_win[i].label, g_win[i].cls, g_win[i].inst, g_win[i].vft, vis, openFlag);
        }
    }
    if (g_nwin == 0) {
        refreshScanHits();
        discoverScan(ui);
        scanHeapForVfts();
    }
    tf = tmpfile();
    if (!tf) return -1;
    writeScanJson(tf);
    fflush(tf);
    if (fseek(tf, 0, SEEK_END) != 0) { fclose(tf); return -1; }
    n = ftell(tf);
    if (n < 2 || n >= outCap) { fclose(tf); return -2; }
    fseek(tf, 0, SEEK_SET);
    got = fread(out, 1, (size_t)n, tf);
    fclose(tf);
    if (got < 2) return -1;
    out[got] = 0;
    return (int)got;
}

__declspec(dllexport) int uidialog_listen_snapshot(const char* registryPath, char* out, int outCap) {
    FILE* tf;
    long n;
    size_t got;
    if (!out || outCap < 16) return -1;
    if (!uidlgEnsure(registryPath)) return -1;
    tf = tmpfile();
    if (!tf) return -1;
    writeUidlgJson(tf);
    fflush(tf);
    if (fseek(tf, 0, SEEK_END) != 0) { fclose(tf); return -1; }
    n = ftell(tf);
    if (n < 2 || n >= outCap) { fclose(tf); return -2; }
    fseek(tf, 0, SEEK_SET);
    got = fread(out, 1, (size_t)n, tf);
    fclose(tf);
    if (got < 2) return -1;
    out[got] = 0;
    return (int)got;
}

__declspec(dllexport) void uidialog_listen_shutdown(void) {
    SignedClose();
    g_ready = 0;
    g_discovered = 0;
    g_lastDiscover = 0;
    g_pid = 0;
    g_base = 0;
    g_nwin = 0;
}

#ifndef UIDIALOG_LISTEN_DLL
int main(int argc, char** argv) {
    char buf[1 << 16];
    const char* reg = argc > 1 ? argv[1] : "registry/LC930_REGISTRY.txt";
    int n;
    SetConsoleOutputCP(CP_UTF8);
    n = uidialog_listen_snapshot(reg, buf, (int)sizeof(buf));
    if (n < 0) { fprintf(stderr, "uidialog snapshot fail %d\n", n); return 1; }
    fwrite(buf, 1, (size_t)n, stdout);
    fputc('\n', stdout);
    uidialog_listen_shutdown();
    return 0;
}
#endif
