/* winmon_930.c 鈥?UI 彀?韰嶌姢韸?氇媹韯?(霃呺 氇搱)
 * ===========================================================================
 *  氇╈爜: 毂勴寘彀?韱惦炒氍胳敖 霌?**鞐煬 彀届潣 響滌嫓 韰嶌姢韸胳檧 靸來儨**毳?彀诫鞐愳劀 歆侅爲 鞚届柎 臧愳嫓頃滊嫟.
 *
 *  雽€鞗愳箼 (IOCTL 斓滌唽頇?路 瓿犾爼鞎奠护 路 瓿犾爼觳挫澑 路 旌愳嫓)
 *    1) 瓿犾爼鞎奠护  : lc_subsGet(VFT_UISUBSYSTEM)
 *    2) 瓿犾爼觳挫澑  : UIDLG_CONT (head:next 鞂? 搿?霠堨澊鞎勳泝 旎厡鞚措剤 walk
 *    3) 彀?鞁濍硠    : RTTI 韥措灅鞀る獏 (COL+0xC 鈫?TD RVA 鈫?TD+0x10 鞚措) 鈫?歆ъ潃鞚措
 *                   臧愳嫓 雽€靸侅潃 registry WINMON_LIST (靿柬憸 甑秳). "*" = 鞝?彀?
 *    4) 韰嶌姢韸?    : (a) 彀?WINSLOT_VEC 氩№劙臧€ 鞛堨溂氅?鞀’氤? *                      鞀’+WINSLOT_NAMEW(鞙勳牤) 鈫?+WIDGET_RENDERER(霠岆崝霟? 鈫?+LABEL_TEXT_OFF(std::string)
 *                    (b) 鞐嗢溂氅?彀?頃勲摐(+0..WINSCAN_LEN)毳?頉戩柎
 *                      路 Text 鞙勳牤鞚措┐ 臧欖潃 觳挫澑鞙茧 氍胳瀽鞐? *                      路 std::string* 氚办棿鞚措┐ 臧?氍胳瀽鞐? *    5) 旌愳嫓       : RTTI/霠堨澊鞎勳泝 vft 旌愳嫓, lc_pgRead 韼橃澊歆€ 旌愳嫓(靷澊韥措嫻)
 *
 *  usage: winmon_930.exe [secs] [-v] [-all] [registry] [out.txt]
 *    -all : WINMON_LIST 氍挫嫓頃橁碃 鞝?彀?於滊牓
 *  於滊牓: <EXE>\out\winmon_out.txt
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

/* 鈹€鈹€ registry 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static uint32_t RG_UVFT, RG_VIS, RG_CVAL, RG_TDNAME, RG_COLTD;
static uint32_t RG_WSVEC, RG_WSTRIDE, RG_WNAMEW, RG_RENDER, RG_TEXT;
static uint32_t RG_STRLEN, RG_STRCAP, RG_SSOMAX, RG_SCANLEN;
static uint32_t RG_CPOFF, RG_CPFN, RG_CPMSG;      /* ChatConfirmPanel */
static uint32_t g_chead[8], g_cnext[8]; static int g_ncont = 0;
static char g_list[1024]; static int g_all = 0;

/* 鈹€鈹€ RTTI 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static int classOf(uint64_t vft, char *out, int cap){
    out[0] = 0;
    if (!isMod(vft)) return 0;
    uint64_t col = q64(vft - 8);
    if (!isMod(col)){ if (col > 0 && col < (uint64_t)g_modSize) col = g_base + col; else return 0; }
    uint32_t td = 0;
    if (!lc_pgRead(col + RG_COLTD, &td, 4)) return 0;
    uint64_t tda = g_base + td;
    if (!isMod(tda)) return 0;
    char raw[512]; memset(raw, 0, sizeof raw);
    if (!lc_pgRead(tda + RG_TDNAME, raw, sizeof raw - 1)) return 0;
    const char *p = raw; if (!strncmp(p, ".?AV", 4)) p += 4;
    int n = 0;
    while (*p && n < cap - 1){
        if (p[0] == '@' && p[1] == '@') break;
        if (p[0] == '@'){ if (n < cap - 2){ out[n++] = ':'; out[n++] = ':'; } p++; }
        else out[n++] = *p++;
    }
    out[n] = 0;
    return n > 0;
}
static void shortCls(const char *nm, char *out, int cap){
    int i = 0; while (nm[i] && nm[i] != ':' && i < cap - 1){ out[i] = nm[i]; i++; } out[i] = 0;
}
#define CC_MAX 512
static uint64_t CC_vft[CC_MAX]; static char CC_nm[CC_MAX][160]; static int CC_n = 0;
static int classOfC(uint64_t vft, char *out, int cap){
    for (int i = 0; i < CC_n; i++) if (CC_vft[i] == vft){ snprintf(out, cap, "%s", CC_nm[i]); return 1; }
    if (!classOf(vft, out, cap)) return 0;
    if (CC_n < CC_MAX){ CC_vft[CC_n] = vft; snprintf(CC_nm[CC_n], 160, "%s", out); CC_n++; }
    return 1;
}
static int inList(const char *sh){
    if (g_all || !g_list[0]) return 1;
    char buf[1024]; snprintf(buf, sizeof buf, "%s", g_list);
    char *tok = strtok(buf, ", ");
    while (tok){
        if (strstr(sh, tok)) return 1;
        tok = strtok(0, ", ");
    }
    return 0;
}

#define TMAX 48
typedef struct { uint32_t off; char txt[180]; } TROW;
static void trim(char *s);   /* forward */
/* 의미 있는 표시 텍스트만 통과(에셋 경로/속성명/한 글자 배제) */
static int meaningful(const char *s){
    if (!s || !s[0]) return 0;
    if (strlen(s) < 2) return 0;
    static const char *bad[] = { ".png", ".csb", ".spx", ".ttf", ".plist", ".json",
                                 "Slot/", "__ui", "a_position", "a_texCoord", "a_color",
                                 "u_texture", "u_effect", "director_", "__cc_", NULL };
    for (int i = 0; bad[i]; i++) if (strstr(s, bad[i])) return 0;
    if (s[0] == '#') return 0;
    if (!strncmp(s, "a_", 2) || !strncmp(s, "u_", 2)) return 0;
    return 1;
}

/* 鈹€鈹€ 韰嶌姢韸?鞙犿嫺 (旯 氚╈) 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€
 *  路 UTF-8 鞚措┐ 氍胳瀽 瓴疥硠旯岇毵?氤奠偓(氅€韹半皵鞚错姼 鞝堧嫧 旮堨)
 *  路 UTF-8 鞚?鞎勲媹氅?CP949 鈫?UTF-8 氤€頇? *  路 鞝滌柎氍胳瀽(\r\n\t 霌? 鈫?瓿惦氨, 鞎炿挙 瓿惦氨 鞝滉卑, 瓿惦氨肟愳澑 氍胳瀽鞐挫潃 氩勲
 */
static int utf8SeqLen(unsigned char c){
    if (c < 0x80) return 1;
    if ((c >> 5) == 6) return 2;
    if ((c >> 4) == 14) return 3;
    if ((c >> 3) == 30) return 4;
    return 0;
}
static int utf8Valid(const unsigned char *p, int n){
    int i = 0;
    while (i < n){
        int L = utf8SeqLen(p[i]);
        if (L == 0 || i + L > n) return 0;
        for (int k = 1; k < L; k++) if ((p[i+k] & 0xC0) != 0x80) return 0;
        i += L;
    }
    return 1;
}
static int cp949ToUtf8(const char *src, int n, char *out, int cap){
    wchar_t wb[1024];
    int w = MultiByteToWideChar(949, 0, src, n, wb, 1024);
    if (w <= 0) return 0;
    int u = WideCharToMultiByte(65001, 0, wb, w, out, cap - 1, 0, 0);
    if (u <= 0) return 0;
    out[u] = 0;
    return u;
}
static int textTo(const char *raw, int n, char *out, int cap){
    out[0] = 0;
    if (n <= 0) return 0;
    if (n > 1024) n = 1024;
    while (n > 0 && raw[n-1] == 0) n--;                     /* 頉勴枆 NUL 鞝滉卑 */
    while (n > 0 && raw[0] == 0) { raw++; n--; }            /* 靹犿枆 NUL 鞝滉卑 */
    if (n <= 0) return 0;
    int m;
    if (utf8Valid((const unsigned char*)raw, n)){
        m = n; if (m >= cap) m = cap - 1;
        while (m > 0 && ((unsigned char)raw[m] & 0xC0) == 0x80) m--;   /* 氍胳瀽 瓴疥硠 */
        if (m <= 0) return 0;
        memcpy(out, raw, (size_t)m);
        out[m] = 0;
    } else {
        m = cp949ToUtf8(raw, n, out, cap);
        if (m <= 0) return 0;
    }
    int out_n = 0, sp = 1;                                   /* 鞝滌柎氍胳瀽 鞝曤Μ + 鞎曥稌 */
    for (char *p = out; *p; p++){
        unsigned char c = (unsigned char)*p;
        if (c < 0x20 || c == 0x7F) c = ' ';
        if (c == ' '){ if (sp) continue; sp = 1; }
        else sp = 0;
        out[out_n++] = (char)c;
    }
    out[out_n] = 0;
    while (out_n > 0 && out[out_n-1] == ' ') out[--out_n] = 0;
    return out_n;
}
static int strAt(uint64_t obj, char *out, int cap){
    uint8_t h[0x20];
    out[0] = 0;
    if (!lc_pgRead(obj, h, sizeof h)) return 0;
    uint64_t sz = *(uint64_t*)(h + RG_STRLEN), cp = *(uint64_t*)(h + RG_STRCAP);
    if (sz == 0 || sz > 0x1000 || cp < sz || cp > 0x100000) return 0;
    static char raw[0x1000];
    uint32_t n = (uint32_t)sz; if (n > sizeof raw) n = (uint32_t)sizeof raw;
    if (cp <= RG_SSOMAX) memcpy(raw, h, n);
    else { uint64_t p = *(uint64_t*)h; if (!isHeap(p) || !lc_pgRead(p, raw, n)) return 0; }
    return textTo(raw, (int)n, out, cap);
}
static uint32_t RG_TEXT2;   /* 雽€觳?韰嶌姢韸?鞓ろ攧靺?霛茧波 韥措灅鞀る硠 彀澊) */
static int g_scanDepth = 0;
static int widgetText(uint64_t w, char *out, int cap){
    uint64_t ren = q64(w + RG_RENDER);
    if (isHeap(ren)){
        if (strAt(ren + RG_TEXT,  out, cap)) return 1;
        if (strAt(ren + RG_TEXT2, out, cap)) return 1;
    }
    if (strAt(w + RG_TEXT,  out, cap)) return 1;   /* 鞙勳牤 鞛愳泊臧€ Label 鞚?瓴届毎 */
    if (strAt(w + RG_TEXT2, out, cap)) return 1;
    return 0;
}
/* 旯婌澊 鞝滍暅 韰嶌姢韸?鞀れ簲: 彀?頃勲摐 鈫?(旯婌澊 2) 鞛愳嫕 頃勲摐 */
static void scanTexts(uint64_t obj, int depth, uint32_t baseOff, int *nt, TROW *rows){
    uint8_t ob[0x400];
    uint32_t ln = RG_SCANLEN; if (ln > sizeof ob) ln = sizeof ob;
    if (!lc_pgRead(obj, ob, ln)) return;
    for (uint32_t o = 0; o + 8 <= ln && *nt < TMAX; o += 8){
        uint64_t p; memcpy(&p, ob + o, 8);
        if (!isHeap(p)) continue;
        char s[180];
        if (widgetText(p, s, sizeof s)){
            trim(s);
            if (s[0] && meaningful(s)){ int dup=0; for(int q=0;q<*nt;q++) if(!strcmp(rows[q].txt,s)) { dup=1; break; } if(!dup){ rows[*nt].off = (depth ? 0x80000000u : 0) | ((baseOff + o) & 0x7FFFFFFF); snprintf(rows[*nt].txt, sizeof rows[0].txt, "%s", s); (*nt)++; } }
            continue;
        }
        if (depth > 0 && !strAt(p, s, sizeof s)){           /* 氍胳瀽鞐?鞛愳泊臧€ 鞎勲媹氅?鞛愳嫕 韮愳儔 */
            int before = *nt;
            scanTexts(p, depth - 1, 0, nt, rows);
            (void)before;
        }
    }
}
static void trim(char *s){
    int n = (int)strlen(s);
    while (n > 0 && (s[n-1] == '\r' || s[n-1] == '\n' || s[n-1] == ' ')) s[--n] = 0;
    int i = 0; while (s[i] == ' ' || s[i] == '\n' || s[i] == '\r') i++;
    if (i) memmove(s, s + i, strlen(s + i) + 1);
}

/* 鈹€鈹€ 彀?鞀る儏靸?鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
#define WMAX 48
typedef struct { char cls[80]; uint64_t inst; int vis, nt; TROW t[TMAX]; } WSN;
static WSN g_cur[WMAX], g_prev[WMAX]; static int g_nw = 0, g_prev_n = 0;

static int isPopupCls(const char *sh){
    return strstr(sh, "Popup") || strstr(sh, "Panel") || strstr(sh, "Message");
}
static void collectWindow(uint64_t lay, const char *sh){
    if (g_nw >= WMAX) return;
    for (int i = 0; i < g_nw; i++)                 /* 欷戨车 鞝滉卑(韥措灅鞀?鞚胳姢韯挫姢) */
        if (g_cur[i].inst == lay && !strcmp(g_cur[i].cls, sh)) return;
    WSN *W = &g_cur[g_nw++];
    memset(W, 0, sizeof *W);
    snprintf(W->cls, sizeof W->cls, "%s", sh);
    W->inst = lay;
    W->vis = (int)(q64(lay + RG_VIS) & 0xFF);
    if (W->vis != 1 && !isPopupCls(sh)) return;    /* 韱惦炒氍胳潃 vis 氍搓磤頃橁矊 韰嶌姢韸?鞁滊弰 */
    /* (a) 鞀’ 氩№劙 */
    uint64_t beg = q64(lay + RG_WSVEC), end = q64(lay + RG_WSVEC + 8);
    if (isHeap(beg) && isHeap(end) && end > beg && ((end - beg) % RG_WSTRIDE) == 0){
        int cnt = (int)((end - beg) / RG_WSTRIDE);
        if (cnt > TMAX) cnt = TMAX;
        for (int i = 0; i < cnt && W->nt < TMAX; i++){
            uint64_t slot = q64(beg + (uint64_t)i * RG_WSTRIDE);
            if (!isHeap(slot)) continue;
            char s[180];
            if (widgetText(q64(slot + RG_WNAMEW), s, sizeof s)){
                trim(s);
                if (s[0]){ W->t[W->nt].off = 0xFFFFFFFF; snprintf(W->t[W->nt].txt, sizeof W->t[0].txt, "%s", s); W->nt++; }
            }
        }
    }
    /* (b) 頃勲摐 鞀れ簲 (旯婌澊 WINSCAN_DEPTH 旯岇) */
    if (W->nt == 0){
        scanTexts(lay, g_scanDepth, 0, &W->nt, W->t);
    }
}

/* ChatConfirmPanel(HudChat+CHATCONFIRM_PANEL_OFF) 鈥?甑愴櫂 頇曥澑 韱惦炒氍?*/
static void collectConfirm(void){
    uint64_t chat = 0;
    for (int i = 0; i < g_nw; i++) if (!strcmp(g_cur[i].cls, "HudChatLayoutPCImpl")) chat = g_cur[i].inst;
    if (!isHeap(chat)) return;
    uint64_t panel = q64(chat + RG_CPOFF);
    if (!isHeap(panel)) return;
    uint64_t fn = q64(panel + RG_CPFN);
    if (!fn) return;                       /* 響滌嫓 欷?鞎勲嫎 */
    if (g_nw >= WMAX) return;
    WSN *W = &g_cur[g_nw++];
    memset(W, 0, sizeof *W);
    snprintf(W->cls, sizeof W->cls, "ChatConfirmPanel");
    W->inst = panel; W->vis = 1;
    char s[180];
    if (strAt(panel + RG_CPMSG, s, sizeof s)){
        trim(s);
        if (s[0]){ W->t[0].off = RG_CPMSG; snprintf(W->t[0].txt, sizeof W->t[0].txt, "%s", s); W->nt = 1; }
    }
}

/* 鈹€鈹€ 旖橃啍 鞁れ嫓臧?於滊牓 鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€鈹€ */
static int g_clear = 0;
static void enableAnsi(void){
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);
    DWORD m = 0;
    if (h && h != INVALID_HANDLE_VALUE && GetConsoleMode(h, &m))
        SetConsoleMode(h, m | 0x0004 /* ENABLE_VIRTUAL_TERMINAL_PROCESSING */);
}
static void consoleLive(unsigned ms){
    if (g_clear) fputs("\x1b[2J\x1b[H", stdout);
    fprintf(stdout, "--- winmon t=%ums ---\n", ms);
    for (int i = 0; i < g_nw; i++){
        WSN *C = &g_cur[i];
        fprintf(stdout, "[%s] %s", C->cls, C->vis == 1 ? "OPEN" : "closed");
        for (int k = 0; k < C->nt; k++) fprintf(stdout, "  \"%s\"", C->t[k].txt);
        fputc('\n', stdout);
    }
    fflush(stdout);
}

static int sameSnap(const WSN *a, const WSN *b){
    if (a->inst != b->inst || a->vis != b->vis || a->nt != b->nt) return 0;
    for (int i = 0; i < a->nt; i++) if (strcmp(a->t[i].txt, b->t[i].txt)) return 0;
    return 1;
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg  = lcreg_resolve("10_5/registry/LC930_REGISTRY.txt", "registry/LC930_REGISTRY.txt");
    const char *outp = lcreg_outpath("winmon_out.txt");
    int secs = 0, verbose = 0;
    for (int i = 1; i < argc; i++){
        if (!strcmp(argv[i], "-v")){ verbose = 1; continue; }
        if (!strcmp(argv[i], "-all")){ g_all = 1; continue; }
        if (!strcmp(argv[i], "-clear")){ g_clear = 1; continue; }
        if (!strcmp(argv[i], "-deep")){ g_scanDepth = 1; continue; }
        if (strstr(argv[i], ".txt") || strstr(argv[i], ".out")){
            if (strstr(argv[i], "REGISTRY")) reg = argv[i]; else outp = argv[i];
        } else if (atoi(argv[i]) > 0 && !strchr(argv[i], '.')) secs = atoi(argv[i]);
    }
    lcreg_load(reg); lc_reg_apply();

    RG_UVFT    = lcreg_u32("VFT_UISUBSYSTEM", 0x11E2710);
    RG_VIS     = lcreg_u32("VIS_FLAG", 0x70);
    RG_CVAL    = lcreg_u32("UIDLG_CONT_VAL", 0x38);
    RG_TDNAME  = lcreg_u32("RTTI_TD_NAME_OFF", 0x10);
    RG_COLTD   = lcreg_u32("RTTI_COL_TD_OFF", 0xC);
    RG_WSVEC   = lcreg_u32("WINSLOT_VEC", 0x100);
    RG_WSTRIDE = lcreg_u32("WINSLOT_STRIDE", 0x10);
    RG_WNAMEW  = lcreg_u32("WINSLOT_NAMEW", 0x18);
    RG_RENDER  = lcreg_u32("WIDGET_RENDERER", 0x740);
    RG_TEXT    = lcreg_u32("LABEL_TEXT_OFF", 0x378);
    RG_TEXT2   = lcreg_u32("WIN_LABEL_TEXT2", 0x358);
    RG_STRLEN  = lcreg_u32("OFF_STR_LEN", 0x10);
    RG_STRCAP  = lcreg_u32("OFF_STR_CAP", 0x18);
    RG_SSOMAX  = lcreg_u32("STR_SSO_MAX", 0x10);
    RG_SCANLEN = lcreg_u32("WINSCAN_LEN", 0x400);
    RG_CPOFF   = lcreg_u32("CHATCONFIRM_PANEL_OFF", 0x150);
    RG_CPFN    = lcreg_u32("CHATCONFIRM_FN_OFF", 0x78);
    RG_CPMSG   = lcreg_u32("CHATCONFIRM_MSG_OFF", 0xC8);
    if (!g_all) snprintf(g_list, sizeof g_list, "%s",
                         lcreg_str("WINMON_LIST",
                                   "HudChatLayoutPCImpl,CommonMessagePopup,CommonBigMessagePopup"));
    { const char *v = lcreg_str("UIDLG_CONT", "0x38:0x18,0x28:0x28");
      char buf[128]; snprintf(buf, sizeof buf, "%s", v);
      char *tok = strtok(buf, ",");
      while (tok && g_ncont < 8){ char *c = strchr(tok, ':');
        if (c){ *c = 0; g_chead[g_ncont] = (uint32_t)strtoul(tok, 0, 0); g_cnext[g_ncont] = (uint32_t)strtoul(c + 1, 0, 0); g_ncont++; }
        tok = strtok(0, ","); } }

    if (lc_attach()) return 1;
    if (!lc_anchor()) return 2;
    enableAnsi();
    lcreg_mkdir_for(outp);
    FILE *f = fopen(outp, "w");
    if (!f) return 4;
    fprintf(f, "# winmon_930 (霃呺 氇搱) registry=%s all=%d list=\"%s\"\n", reg, g_all, g_list);
    fprintf(f, "# anchor=UISubsystem(%X) cont=%d  韰嶌姢韸? 鞀’(彀?0x%X) 霕愲姅 頃勲摐鞀れ簲(0x%X)\n",
            RG_UVFT, g_ncont, RG_WSVEC, RG_SCANLEN);

    DWORD t0 = GetTickCount(); int first = 1;
    do {
        g_ioctl = 0; lc_pgc_reset();
        uint64_t ui = lc_subsGet(RG_UVFT);
        g_nw = 0;
        if (isHeap(ui)){
            for (int c = 0; c < g_ncont && g_nw < WMAX; c++){
                uint64_t node = q64(ui + g_chead[c]);
                uint32_t need = RG_CVAL + 8; if (g_cnext[c] + 8 > need) need = g_cnext[c] + 8;
                if (need > 0x48) need = 0x48;
                for (int n = 0; n < 2048 && isHeap(node); n++){
                    uint8_t nb[0x48];
                    if (!lc_pgRead(node, nb, need)) break;
                    uint64_t lay = 0, nxt = 0;
                    memcpy(&lay, nb + RG_CVAL, 8); memcpy(&nxt, nb + g_cnext[c], 8);
                    if (isHeap(lay)){
                        char nm[160], sh[80];
                        if (classOfC(q64(lay), nm, sizeof nm)){
                            shortCls(nm, sh, sizeof sh);
                            if (inList(sh)) collectWindow(lay, sh);
                        }
                    }
                    if (nxt == node) break;
                    node = nxt;
                }
            }
            collectConfirm();
        }
        fprintf(f, "\n## cycle t=%ums ui=0x%llX wins=%d ioctl=%llu\n",
                (unsigned)(GetTickCount()-t0), (unsigned long long)ui, g_nw, g_ioctl);
        int anyChange = 0;
        for (int i = 0; i < g_nw; i++){
            WSN *C = &g_cur[i];
            /* 鞚挫爠 鞀る儏靸?毵れ弓(韥措灅鞀?旮办) */
            WSN *P = 0;
            for (int j = 0; j < (first ? 0 : g_prev_n); j++) if (!strcmp(g_prev[j].cls, C->cls)) { P = &g_prev[j]; break; }
            int ch = first || !P || !sameSnap(P, C);
            if (ch) anyChange = 1;
            fprintf(f, "# [%s] inst=0x%llX %s texts=%d%s\n", C->cls, (unsigned long long)C->inst,
                    C->vis == 1 ? "OPEN" : "closed", C->nt, ch ? "" : " (unchanged)");
            if (verbose || ch){
                for (int k = 0; k < C->nt; k++)
                    fprintf(f, "   %2d  (+0x%X) \"%s\"\n", k + 1, C->t[k].off, C->t[k].txt);
            }
            if (ch && P){
                for (int k = 0; k < C->nt; k++){
                    int found = 0;
                    for (int m = 0; m < P->nt; m++) if (!strcmp(P->t[m].txt, C->t[k].txt)){ found = 1; break; }
                    if (!found) fprintf(f, "   [+] \"%s\"\n", C->t[k].txt);
                }
                for (int m = 0; m < P->nt; m++){
                    int found = 0;
                    for (int k = 0; k < C->nt; k++) if (!strcmp(C->t[k].txt, P->t[m].txt)){ found = 1; break; }
                    if (!found) fprintf(f, "   [-] \"%s\"\n", P->t[m].txt);
                }
            }
        }
        g_prev_n = g_nw; memcpy(g_prev, g_cur, sizeof(WSN) * (size_t)g_nw);
        consoleLive((unsigned)(GetTickCount()-t0));   /* 旖橃啍 鞁れ嫓臧?靸來儨 */
        first = 0;
        (void)anyChange;
        fflush(f);
        lcapi_sample(f);
        if (secs) Sleep(lcreg_u32("POLL_UIDLG_INTERVAL_MS", 500));
    } while (!lcapi_done() && secs && (int)(GetTickCount()-t0) < secs * 1000);

    fclose(f); SignedClose();
    printf("done -> %s\n", outp);
    return 0;
}




