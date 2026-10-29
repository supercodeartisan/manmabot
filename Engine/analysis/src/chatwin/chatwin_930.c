/* chatwin_930.c 鈥?毂勴寘 霛检澑 氇媹韯?(霃呺 氇搱)
 * ===========================================================================
 *  氇╈爜: 毂勴寘彀届潣 **靾橃嫚 霛检澑(氅旍嫓歆€/氚滌嫚鞛?** 鞚?鞁れ嫓臧勳溂搿?鞚诫姅雼?
 *
 *  氚╈嫕 (鞀れ簲 氤戨 鞕勴檾):
 *    1) 霛检澑 霠堨綌霌?= { std::string msg, std::string msg2, std::string sender, std::string lang }
 *       (0x20 臧勱博, msg == msg2, lang 鈭?{"ko","en",...})   鈫?鞁れ浮 頇曥爼
 *    2) 氚滉铂(1須?鞚€ **觳伂 攵勴暊**(靷澊韥措嫻 DISCOVER_MB 毵岉伡) 鈫?敫旊韨?鞐嗢潓
 *    3) 氚滉铂 頉勳棎電?旌愳嫓霅?霠堨綌霌?欤检唽毵?毵?靷澊韥?鞚届潓(靾?IOCTL) 鈫?鞁れ嫓臧? *    4) 彀?靸來儨(UISubsystem walk)霃?頃粯 於滊牓
 *
 *  usage: chatwin_930.exe [secs] [-v] [-chunk MB] [registry] [out.txt]
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

static uint32_t RG_UVFT, RG_CVAL, RG_TDNAME, RG_COLTD, RG_STRLEN, RG_STRCAP, RG_SSOMAX;
static uint32_t g_chead[8], g_cnext[8]; static int g_ncont = 0;

/* 鈹€鈹€ 彀?毂勴寘) 韮愳儔 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static int classOf(uint64_t vft, char *out, int cap){
    out[0] = 0;
    if (!isMod(vft)) return 0;
    uint64_t col = q64(vft - 8);
    if (!isMod(col)){ if (col > 0 && col < (uint64_t)g_modSize) col = g_base + col; else return 0; }
    uint32_t td = 0; if (!lc_pgRead(col + RG_COLTD, &td, 4)) return 0;
    uint64_t tda = g_base + td; if (!isMod(tda)) return 0;
    char raw[512]; memset(raw, 0, sizeof raw);
    if (!lc_pgRead(tda + RG_TDNAME, raw, sizeof raw - 1)) return 0;
    const char *p = raw; if (!strncmp(p, ".?AV", 4)) p += 4;
    int n = 0;
    while (*p && n < cap - 1){ if (p[0]=='@'&&p[1]=='@') break; if (p[0]=='@'){ if(n<cap-2){out[n++]=':';out[n++]=':';} p++; } else out[n++]=*p++; }
    out[n] = 0; return n > 0;
}
static void shortCls(const char *nm, char *out, int cap){ int i=0; while(nm[i]&&nm[i]!=':'&&i<cap-1){out[i]=nm[i];i++;} out[i]=0; }

/* 鈹€鈹€ 氍胳瀽鞐?鞚疥赴(旯 氚╈: UTF-8 瓴疥硠/CP949 韽措氨/鞝滌柎氍胳瀽 鞝曤Μ) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static int utf8Valid(const unsigned char *p, int n){
    int i=0;
    while (i<n){ unsigned char c=p[i]; int L = (c<0x80)?1:((c>>5)==6?2:((c>>4)==14?3:((c>>3)==30?4:0)));
        if (!L || i+L>n) return 0;
        for (int k=1;k<L;k++) if ((p[i+k]&0xC0)!=0x80) return 0;
        i+=L; }
    return 1;
}
static int toText(const char *raw, int n, char *out, int cap){
    out[0]=0;
    while (n>0 && raw[n-1]==0) n--;
    while (n>0 && raw[0]==0){ raw++; n--; }
    if (n<=0) return 0;
    int m;
    if (utf8Valid((const unsigned char*)raw, n)){
        m = n; if (m>=cap) m = cap-1;
        while (m>0 && ((unsigned char)raw[m]&0xC0)==0x80) m--;
        if (m<=0) return 0;
        memcpy(out, raw, (size_t)m); out[m]=0;
    } else {
        wchar_t wb[512];
        int w = MultiByteToWideChar(949, 0, raw, n, wb, 512);
        if (w<=0) return 0;
        int u = WideCharToMultiByte(65001, 0, wb, w, out, cap-1, 0, 0);
        if (u<=0) return 0;
        out[u]=0;
    }
    int k=0, sp=1;
    for (char *p=out; *p; p++){ unsigned char c=(unsigned char)*p; if (c<0x20||c==0x7F) c=' ';
        if (c==' '){ if (sp) continue; sp=1; } else sp=0; out[k++]=(char)c; }
    out[k]=0;
    while (k>0 && out[k-1]==' ') out[--k]=0;
    return k;
}
static int sGet(uint64_t a, char *out, int cap){
    uint8_t h[0x20]; out[0]=0;
    if (!lc_pgRead(a, h, sizeof h)) return 0;
    uint64_t sz=*(uint64_t*)(h+RG_STRLEN), cp=*(uint64_t*)(h+RG_STRCAP);
    if (sz==0 || sz>0x1000 || cp<sz || cp>0x100000) return 0;
    static char raw[0x1000];
    uint32_t n=(uint32_t)sz; if (n>sizeof raw) n=(uint32_t)sizeof raw;
    if (cp<=RG_SSOMAX) memcpy(raw, h, n);
    else { uint64_t p=*(uint64_t*)h; if (!isHeap(p) || !lc_pgRead(p, raw, n)) return 0; }
    return toText(raw, (int)n, out, cap);
}
/* 4-氍胳瀽鞐?霠堨綌霌?瓴€靷? msg==msg2, lang 歆ъ潓 */
static int isRec(uint64_t a, char *msg, int mc, char *sender, int sc, char *lang, int lc){
    char m1[256], m2[256], sd[128], lg[16];
    if (!sGet(a,        m1, sizeof m1)) return 0;
    if (!sGet(a + 0x20, m2, sizeof m2)) return 0;
    if (strcmp(m1, m2)) return 0;
    if (!sGet(a + 0x40, sd, sizeof sd)) return 0;
    if (!sGet(a + 0x60, lg, sizeof lg)) return 0;
    if (strlen(lg) < 2 || strlen(lg) > 5) return 0;
    snprintf(msg, mc, "%s", m1); snprintf(sender, sc, "%s", sd); snprintf(lang, lc, "%s", lg);
    return 1;
}

/* 鈹€鈹€ 氚滉铂(觳伂 攵勴暊) 瓴瓣臣 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
#define RMAX 128
static uint64_t R_addr[RMAX]; static char R_msg[RMAX][220], R_snd[RMAX][96], R_lng[RMAX][8];
static int R_n = 0;
static uint64_t g_scanCur = 0, g_scanEnd = 0;
static int g_scanDone = 0;

static void scanChunk(uint64_t chunkKB){
    if (g_scanDone) return;
    static uint8_t buf[0x1000];
    uint64_t budget = chunkKB * 1024 / 0x1000; if (budget == 0) budget = 1;
    for (uint64_t i = 0; i < budget && g_scanCur < g_scanEnd; i++, g_scanCur += 0x1000){
        if (g_scanCur < LC_HEAP_LO || g_scanCur >= LC_HEAP_HI) continue;
        if (!lc_pgRead(g_scanCur, buf, 0x1000)) continue;
        for (uint32_t o = 0; o + 0x80 <= 0x1000; o += 8){
            if (R_n >= RMAX) { g_scanDone = 1; return; }
            uint64_t a = g_scanCur + o;
            for (int k = 0; k < R_n; k++) if (R_addr[k] == a) { a = 0; break; }
            if (!a) continue;
            char m[220], s[96], l[8];
            if (isRec(a, m, sizeof m, s, sizeof s, l, sizeof l)){
                R_addr[R_n] = a;
                snprintf(R_msg[R_n], sizeof R_msg[0], "%s", m);
                snprintf(R_snd[R_n], sizeof R_snd[0], "%s", s);
                snprintf(R_lng[R_n], sizeof R_lng[0], "%s", l);
                R_n++;
            }
        }
    }
    if (g_scanCur >= g_scanEnd) g_scanDone = 1;
}

static void consoleLive(int secs, int v){
    printf("--- chatwin ---\n");
    printf("[lines] %d (scan %s)\n", R_n, g_scanDone ? "done" : "running");
    for (int i = 0; i < R_n; i++)
        printf("   %2d  \"%s\"  <- \"%s\" (%s)\n", i+1, R_msg[i], R_snd[i], R_lng[i]);
    fflush(stdout);
    (void)secs; (void)v;
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg = lcreg_resolve("10_5/registry/LC930_REGISTRY.txt", "registry/LC930_REGISTRY.txt");
    const char *outp = lcreg_outpath("chatwin_out.txt");
    int secs = 0, chunkMB = 8;
    for (int i = 1; i < argc; i++){
        if (!strcmp(argv[i], "-v")) continue;
        if (!strcmp(argv[i], "-chunk") && i+1 < argc){ chunkMB = atoi(argv[++i]); continue; }
        if (strstr(argv[i], ".txt") || strstr(argv[i], ".out")){
            if (strstr(argv[i], "REGISTRY")) reg = argv[i]; else outp = argv[i];
        } else if (atoi(argv[i]) > 0 && !strchr(argv[i], '.')) secs = atoi(argv[i]);
    }
    lcreg_load(reg); lc_reg_apply();
    RG_UVFT   = lcreg_u32("VFT_UISUBSYSTEM", 0x11E2710);
    RG_CVAL   = lcreg_u32("UIDLG_CONT_VAL", 0x38);
    RG_TDNAME = lcreg_u32("RTTI_TD_NAME_OFF", 0x10);
    RG_COLTD  = lcreg_u32("RTTI_COL_TD_OFF", 0xC);
    RG_STRLEN = lcreg_u32("OFF_STR_LEN", 0x10);
    RG_STRCAP = lcreg_u32("OFF_STR_CAP", 0x18);
    RG_SSOMAX = lcreg_u32("STR_SSO_MAX", 0x10);
    { const char *v = lcreg_str("UIDLG_CONT", "0x38:0x18,0x28:0x28");
      char buf[128]; snprintf(buf, sizeof buf, "%s", v);
      char *tok = strtok(buf, ",");
      while (tok && g_ncont < 8){ char *c = strchr(tok, ':'); if (c){ *c=0; g_chead[g_ncont]=(uint32_t)strtoul(tok,0,0); g_cnext[g_ncont]=(uint32_t)strtoul(c+1,0,0); g_ncont++; } tok = strtok(0, ","); } }
    if (lc_attach()) return 1;
    if (!lc_anchor()) return 2;
    lcreg_mkdir_for(outp);
    FILE *f = fopen(outp, "w"); if (!f) return 4;
    fprintf(f, "# chatwin_930 registry=%s chunk=%dMB heap=[0x%llX..0x%llX)\n",
            reg, chunkMB, (unsigned long long)LC_HEAP_LO, (unsigned long long)LC_HEAP_HI);
    g_scanCur = LC_HEAP_LO; g_scanEnd = LC_HEAP_HI;

    DWORD t0 = GetTickCount(); int first = 1;
    do {
        g_ioctl = 0; lc_pgc_reset();
        /* 彀?靸來儨 */
        uint64_t ui = lc_subsGet(RG_UVFT);
        char winState[160] = "chat=?"; 
        if (isHeap(ui)){
            for (int c = 0; c < g_ncont; c++){
                uint64_t node = q64(ui + g_chead[c]);
                uint32_t need = RG_CVAL+8; if (g_cnext[c]+8 > need) need = g_cnext[c]+8; if (need > 0x48) need = 0x48;
                for (int n = 0; n < 2048 && isHeap(node); n++){
                    uint8_t nb[0x48]; if (!lc_pgRead(node, nb, need)) break;
                    uint64_t lay=0, nxt=0; memcpy(&lay, nb+RG_CVAL, 8); memcpy(&nxt, nb+g_cnext[c], 8);
                    if (isHeap(lay)){
                        char nm[160], sh[80];
                        if (classOf(q64(lay), nm, sizeof nm)){ shortCls(nm, sh, sizeof sh);
                            if (strstr(sh, "HudChat")){ snprintf(winState, sizeof winState, "%s %s", sh, (q64(lay+0x70)&0xFF)==1 ? "OPEN":"closed"); if (!g_scanDone && R_n==0){ g_scanCur = (lay - 0x40000000ULL) & ~0xFFFULL; g_scanEnd = (lay + 0xC0000000ULL) & ~0xFFFULL; } } }
                    }
                    if (nxt == node) break; node = nxt;
                }
            }
        }
        scanChunk((uint64_t)chunkMB * 1024);
        fprintf(f, "\n## t=%ums %s lines=%d scan=%s ioctl=%llu\n",
                (unsigned)(GetTickCount()-t0), winState, R_n, g_scanDone?"done":"running", g_ioctl);
        for (int i = 0; i < R_n; i++){
            if (first || 1) fprintf(f, "   [%02d] \"%s\"  <- \"%s\" (%s)  @0x%llX\n",
                                    i+1, R_msg[i], R_snd[i], R_lng[i], (unsigned long long)R_addr[i]);
        }
        fflush(f);
        consoleLive(secs, 1);
        lcapi_sample(f);
        first = 0;
        if (secs) Sleep(lcreg_u32("POLL_UIDLG_INTERVAL_MS", 400));
    } while (secs && (int)(GetTickCount()-t0) < secs*1000);
    fclose(f); SignedClose();
    printf("done -> %s (lines=%d)\n", outp, R_n);
    return 0;
}


