/* confirm_listen.c — supply-only popup/confirm reader (UIdialogmon-style).
 *
 * Reads CommonMessagePopup / CommonBigMessagePopup / ChatConfirmPanel message
 * text (+CHATCONFIRM_MSG_OFF) and AmountSelector visibility.
 *
 * Quantity-input prompt heuristic (caller-side also applied): message contains
 * both "Esc" and "Enter" (case-insensitive).
 *
 * Exports:
 *   confirm_listen_snapshot(registryPath, out, outCap) -> JSON bytes
 *   confirm_listen_shutdown()
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

#define CONFIRM_LISTEN_DLL 1

static uint32_t RG_UVFT, RG_VIS, RG_VISMASK, RG_VISOPEN, RG_CVAL;
static uint32_t RG_POPVIS, RG_CMSG, RG_CPANEL, RG_CFN, RG_CFNM2, RG_CTYPE, RG_CASK;
static char RG_NS[64], RG_SUFFIX[32], RG_CHATLAYOUT[96];
static uint32_t g_chead[8], g_cnext[8];
static int g_ncont = 0;

/* UICONFIRM_CLASSES — only these (+ AmountSelector / chat layout) are watched. */
#define CFC_MAX 8
static char CFC[CFC_MAX][96];
static int CFC_N = 0;

static int rmf(uint64_t a, void* b, uint32_t s)
{
    int drv = 0;
    int ok = pg_read((uint64_t)g_pid, a, b, s, &drv);
    g_ioctl += (unsigned)drv;
    return ok;
}
static uint64_t q64f(uint64_t a)
{
    uint64_t v = 0;
    rmf(a, &v, 8);
    return v;
}

#define MAXWATCH 32
static struct { char label[48]; char cls[96]; int found; } g_watch[MAXWATCH];
static int g_nwatch = 0;

typedef struct { char label[48]; char cls[96]; uint64_t inst; uint32_t vft; } WIN;
static WIN g_win[MAXWATCH];
static int g_nwin = 0;
static int g_ready = 0;
static char g_regPath[MAX_PATH * 2];

/* confirm_registry is UI-only; MGR/HOLDER live in LC930_REGISTRY (uidialog path). */
static int file_exists(const char* p)
{
    FILE* f = fopen(p, "r");
    if (!f) return 0;
    fclose(f);
    return 1;
}

static void lcreg_set(const char* k, const char* v)
{
    int i;
    for (i = 0; i < LCREG_N; i++) {
        if (!strcmp(LCREG_K[i], k)) {
            strncpy(LCREG_V[i], v, 255);
            LCREG_V[i][255] = 0;
            return;
        }
    }
    if (LCREG_N < LCREG_MAXKEYS) {
        strncpy(LCREG_K[LCREG_N], k, 63);
        LCREG_K[LCREG_N][63] = 0;
        strncpy(LCREG_V[LCREG_N], v, 255);
        LCREG_V[LCREG_N][255] = 0;
        LCREG_N++;
    }
}

static void lcreg_overlay(const char* path)
{
    FILE* f;
    char ln[512];
    if (!path || !path[0]) return;
    f = fopen(path, "r");
    if (!f) return;
    while (fgets(ln, sizeof(ln), f)) {
        char* s = ln;
        char* eq;
        char* k;
        char* ke;
        char* v;
        char* ve;
        while (*s == ' ' || *s == '\t') s++;
        if (*s == '#' || *s == '\n' || !*s) continue;
        eq = strchr(s, '=');
        if (!eq) continue;
        *eq = 0;
        k = s;
        ke = k + strlen(k);
        while (ke > k && (ke[-1] == ' ' || ke[-1] == '\t')) *--ke = 0;
        v = eq + 1;
        while (*v == ' ' || *v == '\t') v++;
        ve = v + strlen(v);
        while (ve > v && (ve[-1] == '\n' || ve[-1] == '\r' || ve[-1] == ' ' || ve[-1] == '\t'))
            *--ve = 0;
        lcreg_set(k, v);
    }
    fclose(f);
}

static int find_lc930_registry(const char* confirmPath, char* out, int cap)
{
    char dir[MAX_PATH * 2];
    char* slash;
    int up;
    /* Same file uidialog_listen attaches with. The old 10_21 dist path
     * and Engine/analysis/lc930/registry are not this tree. */
    if (!confirmPath || !confirmPath[0] || !out || cap < 32) return 0;
    strncpy(dir, confirmPath, sizeof(dir) - 1);
    dir[sizeof(dir) - 1] = 0;
    slash = strrchr(dir, '\\');
    if (!slash) slash = strrchr(dir, '/');
    if (slash) *slash = 0;
    for (up = 0; up < 8; up++) {
        snprintf(out, cap, "%s\\Engine\\analysis\\registry\\LC930_REGISTRY.txt", dir);
        if (file_exists(out)) return 1;
        slash = strrchr(dir, '\\');
        if (!slash) slash = strrchr(dir, '/');
        if (!slash) break;
        *slash = 0;
    }
    return 0;
}

static void load_regs(const char* confirmPath)
{
    char lc930[MAX_PATH * 2];
    /* Prefer full 10_21 dist registry, then overlay confirm_registry keys. */
    if (find_lc930_registry(confirmPath, lc930, (int)sizeof(lc930))) {
        lcreg_load(lc930);
        if (confirmPath && confirmPath[0])
            lcreg_overlay(confirmPath);
    } else {
        lcreg_load(confirmPath);
    }
    lc_reg_apply();
}

static int is_confirm_cls(const char* cls)
{
    int i;
    if (!cls || !cls[0]) return 0;
    for (i = 0; i < CFC_N; i++)
        if (!strcmp(cls, CFC[i])) return 1;
    return 0;
}

static int want_watch_cls(const char* cls)
{
    if (!cls || !cls[0]) return 0;
    if (is_confirm_cls(cls)) return 1;
    if (strstr(cls, "AmountSelector")) return 1;
    if (RG_CHATLAYOUT[0] && !strcmp(cls, RG_CHATLAYOUT)) return 1;
    return 0;
}

static void parse_confirm_classes(void)
{
    const char* v = lcreg_str(
        "UICONFIRM_CLASSES",
        "CommonMessagePopup,CommonBigMessagePopup,ChatConfirmPanel");
    char buf[256];
    char* tok;
    CFC_N = 0;
    strncpy(buf, v ? v : "", sizeof(buf) - 1);
    buf[sizeof(buf) - 1] = 0;
    tok = strtok(buf, ",");
    while (tok && CFC_N < CFC_MAX) {
        while (*tok == ' ' || *tok == '\t') tok++;
        snprintf(CFC[CFC_N++], sizeof(CFC[0]), "%s", tok);
        tok = strtok(0, ",");
    }
}

static int classOf(uint64_t vft, char* out, int cap)
{
    out[0] = 0;
    if (!isMod(vft)) return 0;
    uint64_t col = q64(vft - 8);
    if (!isMod(col)) {
        if (col > 0 && col < (uint64_t)g_modSize) col = g_base + col;
        else return 0;
    }
    uint32_t td_rva = 0;
    rm(col + 0xC, &td_rva, 4);
    uint64_t td = g_base + td_rva;
    if (!isMod(td)) return 0;
    char raw[512];
    memset(raw, 0, sizeof(raw));
    if (!rm(td + 0x10, raw, sizeof(raw) - 1)) return 0;
    const char* p = raw;
    if (strncmp(p, ".?AV", 4) == 0) p += 4;
    int n = 0;
    while (*p && n < cap - 1) {
        if (p[0] == '@' && p[1] == '@') break;
        if (p[0] == '@') {
            if (n < cap - 2) {
                out[n++] = ':';
                out[n++] = ':';
            }
            p++;
        } else
            out[n++] = *p++;
    }
    out[n] = 0;
    return n > 0;
}

#define CC_MAX 128
static uint64_t CC_vft[CC_MAX];
static char CC_nm[CC_MAX][160];
static int CC_n = 0;
static int classOfC(uint64_t vft, char* out, int cap)
{
    for (int i = 0; i < CC_n; i++)
        if (CC_vft[i] == vft) {
            snprintf(out, cap, "%s", CC_nm[i]);
            return 1;
        }
    if (!classOf(vft, out, cap)) return 0;
    if (CC_n < CC_MAX) {
        CC_vft[CC_n] = vft;
        snprintf(CC_nm[CC_n], 160, "%s", out);
        CC_n++;
    }
    return 1;
}

static void shortName(const char* nm, char* out, int cap)
{
    int t = 0;
    while (nm[t] && nm[t] != ':' && t < cap - 1) {
        out[t] = nm[t];
        t++;
    }
    out[t] = 0;
}

static const char* watchLabel(const char* cls)
{
    for (int i = 0; i < g_nwatch; i++)
        if (!strcmp(g_watch[i].cls, cls)) return g_watch[i].label;
    return 0;
}

static uint32_t askOf(uint64_t panel)
{
    uint64_t cb, cap;
    if (!RG_CASK) return 0;
    cb = q64f(panel + RG_CASK);
    if (!isHeap(cb)) return 0;
    cap = q64f(cb + 0x10);
    return (uint32_t)(cap >> 32);
}

static int decU8(const uint8_t* b, int n, char* out, int cap)
{
    wchar_t wb[512];
    int wn = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, (const char*)b, n, wb, 512);
    if (wn <= 0) wn = MultiByteToWideChar(949, 0, (const char*)b, n, wb, 512);
    if (wn <= 0) wn = MultiByteToWideChar(936, 0, (const char*)b, n, wb, 512);
    if (wn <= 0) return 0;
    int un = WideCharToMultiByte(CP_UTF8, 0, wb, wn, out, cap - 1, 0, 0);
    if (un < 0) un = 0;
    out[un] = 0;
    return un > 0;
}

static int readStdStr(uint64_t p, char* out, int cap)
{
    out[0] = 0;
    if (!isHeap(p)) return 0;
    uint8_t h[0x20];
    if (!rmf(p, h, sizeof h)) return 0;
    uint64_t sz, cp;
    memcpy(&sz, h + 0x10, 8);
    memcpy(&cp, h + 0x18, 8);
    if (!(sz > 0 && sz < 0x600 && cp >= sz && cp < 0x100000)) return 0;
    uint8_t b[0x600];
    if (cp < 0x10)
        memcpy(b, h, (size_t)sz);
    else {
        uint64_t q;
        memcpy(&q, h, 8);
        if (!isHeap(q) || !rmf(q, b, (uint32_t)sz)) return 0;
    }
    return decU8(b, (int)sz, out, cap);
}

static int readMsgStr(uint64_t panel, char* buf, int cap)
{
    if (readStdStr(panel + RG_CMSG, buf, cap)) return 1;
    uint64_t dp = q64f(panel + RG_CMSG), sz = q64f(panel + RG_CMSG + 8);
    if (!isHeap(dp) || sz == 0 || sz > 0x600) return 0;
    uint8_t b[0x600];
    if (!rmf(dp, b, (uint32_t)sz)) return 0;
    return decU8(b, (int)sz, buf, cap);
}

static uint64_t anchorUI(void)
{
    uint64_t s = lc_subsGet(RG_UVFT);
    if (isHeap(s)) return s;
    if (isHeap(lc_subs)) {
        for (int i = 0; i < (int)LC_SUBCOUNT_V; i++) {
            uint64_t sub = q64(lc_subs + (uint64_t)LC_SUB_STRIDE_V * i);
            if (!isHeap(sub)) continue;
            char nm[128];
            if (classOf(q64(sub), nm, sizeof(nm)) && strstr(nm, "UISubsystem") && strstr(nm, RG_NS))
                return sub;
            if (classOf(q64(sub + 8), nm, sizeof(nm)) && strstr(nm, "UISubsystem") && strstr(nm, RG_NS))
                return sub;
        }
    }
    return 0;
}

static void addWin(const char* label, const char* sh, uint64_t lay, uint32_t vft)
{
    for (int k = 0; k < g_nwin; k++)
        if (!strcmp(g_win[k].cls, sh)) {
            g_win[k].inst = lay;
            g_win[k].vft = vft;
            return;
        }
    if (g_nwin >= MAXWATCH) return;
    WIN* W = &g_win[g_nwin++];
    strncpy(W->label, label, 47);
    W->label[47] = 0;
    strncpy(W->cls, sh, 95);
    W->cls[95] = 0;
    W->inst = lay;
    W->vft = vft;
}

static void containerScan(uint64_t ui)
{
    g_nwin = 0;
    if (!isHeap(ui)) return;
    pg_reset();
    for (int c = 0; c < g_ncont; c++) {
        uint64_t node = q64f(ui + g_chead[c]);
        uint32_t need = RG_CVAL + 8;
        if (g_cnext[c] + 8 > need) need = g_cnext[c] + 8;
        if (need > 0x48) need = 0x48;
        for (int n = 0; n < 2048 && isHeap(node); n++) {
            uint8_t nb[0x48];
            if (!rmf(node, nb, need)) break;
            uint64_t lay = 0, nxt = 0;
            memcpy(&lay, nb + RG_CVAL, 8);
            memcpy(&nxt, nb + g_cnext[c], 8);
            if (isHeap(lay)) {
                uint64_t vf = q64f(lay);
                if (isMod(vf)) {
                    char nm[128], sh[96];
                    classOfC(vf, nm, sizeof(nm));
                    shortName(nm, sh, sizeof(sh));
                    const char* lb = watchLabel(sh);
                    if (lb)
                        addWin(lb, sh, lay, (uint32_t)(vf - g_base));
                    else if (sh[0] && RG_CHATLAYOUT[0] && !strcmp(sh, RG_CHATLAYOUT))
                        addWin("HudChat", sh, lay, (uint32_t)(vf - g_base));
                }
            }
            if (nxt == node) break;
            node = nxt;
        }
    }
}

static int ascii_has_ci(const char* hay, const char* needle)
{
    if (!hay || !needle || !needle[0]) return 0;
    size_t nlen = strlen(needle);
    for (const char* p = hay; *p; p++) {
        size_t i = 0;
        while (i < nlen) {
            char a = p[i], b = needle[i];
            if (a >= 'A' && a <= 'Z') a = (char)(a - 'A' + 'a');
            if (b >= 'A' && b <= 'Z') b = (char)(b - 'A' + 'a');
            if (!a || a != b) break;
            i++;
        }
        if (i == nlen) return 1;
    }
    return 0;
}

static int is_qty_prompt_msg(const char* msg)
{
    /* UIdialogmon-style: drag-drop qty notice mentions Esc and Enter together. */
    return ascii_has_ci(msg, "Esc") && ascii_has_ci(msg, "Enter");
}

static void json_esc(const char* in, char* out, int cap)
{
    int j = 0;
    if (!in) {
        out[0] = 0;
        return;
    }
    for (const unsigned char* p = (const unsigned char*)in; *p && j + 2 < cap; p++) {
        if (*p == '"' || *p == '\\') {
            out[j++] = '\\';
            out[j++] = (char)*p;
        } else if (*p == '\n') {
            out[j++] = '\\';
            out[j++] = 'n';
        } else if (*p < 0x20) {
            out[j++] = '?';
        } else
            out[j++] = (char)*p;
    }
    out[j] = 0;
}

static int writeJson(char* out, int outCap)
{
    char body[1 << 15];
    int used = 0;
    int qty = 0;
    int n = 0;
    used += snprintf(body + used, (int)sizeof(body) - used,
                     "{\"cmd\":\"confirm\",\"pid\":%llu,\"mgr\":\"0x%X\",\"uvft\":\"0x%X\",\"confirms\":[",
                     (unsigned long long)g_pid,
                     (unsigned)lcreg_u32("MGR", 0),
                     (unsigned)RG_UVFT);
    for (int i = 0; i < g_nwin; i++) {
        uint64_t inst = g_win[i].inst;
        uint32_t type = 0, ask = 0;
        if (!isHeap(inst)) continue;
        char msg[512];
        msg[0] = 0;
        int visible = 0;
        /* uidialogmon: HudChat → panel@+CHATCONFIRM_PANEL_OFF, open if +FN != 0 */
        if (!strcmp(g_win[i].cls, RG_CHATLAYOUT) || !strcmp(g_win[i].label, "HudChat")
            || !strcmp(g_win[i].cls, "HudChatLayoutPCImpl")) {
            uint64_t panel = q64f(inst + RG_CPANEL);
            if (!isHeap(panel)) continue;
            if (!q64f(panel + RG_CFN)) continue;
            visible = 1;
            type = (uint32_t)q64f(panel + RG_CTYPE);
            ask = askOf(panel);
            readMsgStr(panel, msg, sizeof(msg));
        } else if (is_confirm_cls(g_win[i].cls)
                   || strstr(g_win[i].cls, "MessagePopup")
                   || strstr(g_win[i].cls, "ConfirmPanel")) {
            /* +POPUP_VIS_OFF != 0 → visible; msg @ +POPUP_MSG_OFF / CHATCONFIRM_MSG_OFF */
            if (!q64f(inst + RG_POPVIS)) continue;
            visible = 1;
            readMsgStr(inst, msg, sizeof(msg));
            if (!msg[0]) continue;
        } else if (strstr(g_win[i].cls, "AmountSelector")) {
            uint8_t hb[0x78];
            if (!rmf(inst, hb, sizeof(hb))) continue;
            if (*(uint64_t*)hb != g_base + g_win[i].vft) continue;
            uint32_t vis = *(uint32_t*)(hb + RG_VIS);
            if ((vis & RG_VISMASK) != RG_VISOPEN) continue;
            visible = 1;
            snprintf(msg, sizeof(msg), "[AmountSelector]");
        } else
            continue;

        int prompt = is_qty_prompt_msg(msg) || strstr(g_win[i].cls, "AmountSelector") != 0;
        if (prompt) qty = 1;
        char esc[1024];
        json_esc(msg, esc, sizeof(esc));
        if (n) used += snprintf(body + used, (int)sizeof(body) - used, ",");
        used += snprintf(body + used, (int)sizeof(body) - used,
                         "{\"label\":\"%s\",\"cls\":\"%s\",\"visible\":%s,\"qty_prompt\":%s,"
                         "\"type\":%u,\"ask\":%u,\"msg\":\"%s\"}",
                         g_win[i].label, g_win[i].cls,
                         visible ? "true" : "false",
                         prompt ? "true" : "false",
                         (unsigned)type, (unsigned)ask,
                         esc);
        n++;
        if (used > (int)sizeof(body) - 256) break;
    }
    used += snprintf(body + used, (int)sizeof(body) - used,
                     "],\"n\":%d,\"qty_prompt\":%s}",
                     n, qty ? "true" : "false");
    if (used + 1 > outCap) return -2;
    memcpy(out, body, (size_t)used + 1);
    return used;
}

/* Negative codes: -10 arg, -11 ensure/reg, -12 attach, -13 anchor,
 * -14 no UISubsystem, -15 json overflow. Positive = JSON byte count. */
static int g_last_err = 0;

__declspec(dllexport) int confirm_listen_last_error(void)
{
    return g_last_err;
}

__declspec(dllexport) int confirm_listen_snapshot(const char* registryPath, char* out, int outCap)
{
    uint64_t ui;
    int att;
    if (!out || outCap < 32) {
        g_last_err = -10;
        return -10;
    }
    pg_reset();
    /* Split ensure so callers see attach vs anchor failure. */
    {
        const char* reg = registryPath && registryPath[0] ? registryPath : g_regPath;
        if (!reg || !reg[0]) {
            g_last_err = -11;
            return -11;
        }
        if (!g_ready || (registryPath && registryPath[0] && strcmp(g_regPath, registryPath) != 0)) {
            if (registryPath && registryPath[0]) {
                strncpy(g_regPath, registryPath, sizeof(g_regPath) - 1);
                g_regPath[sizeof(g_regPath) - 1] = 0;
            }
            /* 10_21 confirm_registry (MGR/VFT/confirm offs) — uidialogmon path. */
            load_regs(g_regPath);
            if (!LCREG_N || !lcreg_raw("MGR")) {
                g_last_err = -11;
                return -11;
            }
            /* Defaults from dist registry BUILD 26.10.20.2001 */
            RG_UVFT = lcreg_u32("VFT_UISUBSYSTEM", 0x11EDB98);
            RG_VIS = lcreg_u32("VIS_FLAG", 0x70);
            RG_VISMASK = lcreg_u32("VIS_MASK", 0xFF);
            RG_VISOPEN = lcreg_u32("VIS_OPEN", 1);
            RG_CVAL = lcreg_u32("UIDLG_CONT_VAL", 0x38);
            RG_POPVIS = lcreg_u32("POPUP_VIS_OFF", 0x78);
            /* POPUP_MSG_OFF and CHATCONFIRM_MSG_OFF are both 0xC8 in 10_21 */
            RG_CMSG = lcreg_u32("CHATCONFIRM_MSG_OFF", lcreg_u32("POPUP_MSG_OFF", 0xC8));
            RG_CPANEL = lcreg_u32("CHATCONFIRM_PANEL_OFF", 0x150);
            RG_CFN = lcreg_u32("CHATCONFIRM_FN_OFF", 0x78);
            RG_CFNM2 = lcreg_u32("CHATCONFIRM_FN2_OFF", 0xB8);
            RG_CTYPE = lcreg_u32("CHATCONFIRM_TYPE_OFF", 0xC0);
            RG_CASK = lcreg_u32("CHATCONFIRM_ASK_CB_OFF", 0x1C0);
            (void)RG_CFNM2;
            snprintf(RG_SUFFIX, sizeof(RG_SUFFIX), "%s", lcreg_str("UI_LAYOUT_SUFFIX", "Layout"));
            snprintf(RG_NS, sizeof(RG_NS), "%s", lcreg_str("UI_LAYOUT_NS", "ui::lineage"));
            snprintf(RG_CHATLAYOUT, sizeof(RG_CHATLAYOUT), "%s",
                     lcreg_str("CHAT_LAYOUT_CLASS", "HudChatLayoutPCImpl"));
            parse_confirm_classes();
            g_ncont = 0;
            {
                const char* v = lcreg_str("UIDLG_CONT", "0x38:0x18,0x28:0x28");
                char buf[128];
                strncpy(buf, v, 127);
                buf[127] = 0;
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
            /* Only confirm / AmountSelector / chat — ignore Engine's full UIDLG list. */
            g_nwatch = 0;
            for (int i = 0; i < LCREG_N && g_nwatch < MAXWATCH; i++) {
                if (strncmp(LCREG_K[i], "UIDLG_WIN_", 10) != 0) continue;
                if (!want_watch_cls(LCREG_V[i])) continue;
                snprintf(g_watch[g_nwatch].label, sizeof(g_watch[0].label), "%s", LCREG_K[i] + 10);
                snprintf(g_watch[g_nwatch].cls, sizeof(g_watch[0].cls), "%s", LCREG_V[i]);
                g_watch[g_nwatch].found = 0;
                g_nwatch++;
            }
            if (RG_CHATLAYOUT[0] && !watchLabel(RG_CHATLAYOUT) && g_nwatch < MAXWATCH) {
                snprintf(g_watch[g_nwatch].label, sizeof(g_watch[0].label), "%s", "HudChat");
                snprintf(g_watch[g_nwatch].cls, sizeof(g_watch[0].cls), "%s", RG_CHATLAYOUT);
                g_watch[g_nwatch].found = 0;
                g_nwatch++;
            }
            g_nwin = 0;
            CC_n = 0;
            g_ready = 1;
        }
    }
    att = lc_attach();
    if (att) {
        g_last_err = -12;
        return -12;
    }
    if (!lc_anchor()) {
        g_last_err = -13;
        return -13;
    }
    ui = anchorUI();
    if (!isHeap(ui)) {
        g_last_err = -14;
        return -14;
    }
    containerScan(ui);
    {
        int n = writeJson(out, outCap);
        if (n < 0) {
            g_last_err = -15;
            return -15;
        }
        g_last_err = 0;
        return n;
    }
}

__declspec(dllexport) void confirm_listen_shutdown(void)
{
    SignedClose();
    g_ready = 0;
    g_nwin = 0;
    g_pid = 0;
    g_base = 0;
}
