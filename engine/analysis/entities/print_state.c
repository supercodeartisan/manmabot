/* print_state.c — liveview entity/state as JSON (no screenshot / UI).
   Reads settings_print_state.json for interval + projection + fallback RVAs,
   then overlays entity_offsets.txt in the same directory (wins on conflict).
   After a service patch, edit entity_offsets.txt (and the JSON fallbacks).

   Two-speed read (same entities[] JSON):
     slow sweep (~SLOW_MS) caches the roster + PRES_B pointer
     fast poll (every emit) reads PRES_B+0x40 once per entity
     A(+0x50) → B(+0x78) over INTERP_MS (516). screen = raw B; iscr = lerp.

   Usage:
     print_state.exe [settings_print_state.json]
     print_state.exe settings_print_state.json --once
   Output: one JSON object per interval (JSONL) to stdout or output_file.
*/
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdarg.h>
#include <math.h>
#include "signeddrv_client.h"

#define MAXENT   512
#define MAXCLS   64
#define NAME_CAP 96
#define CFG_CAP  65536

static DWORD g_pid;
static uint64_t g_base;
static uint32_t g_modSize;
static char g_cfg[CFG_CAP];

/* ---- config ---- */
static char g_procName[64] = "LC.exe";
static int g_intervalMs = 200;
static int g_once = 0;
static char g_outPath[MAX_PATH] = "";
static int g_rotateMs = 60000; /* clear output_file history this often */
static int g_range = 50;
/* Defaults match entity_offsets.txt (current service). */
static uint32_t g_offPlayerX = 0x1668710u;
static uint32_t g_offPlayerY = 0x1668714u;
static uint32_t g_offPlayerHp = 0x166871Cu;
static uint32_t g_offPlayerMaxHp = 0x1668720u;
static uint32_t g_offPlayerMp = 0x1668724u;
static uint32_t g_offPlayerMaxMp = 0x1668728u;
static uint32_t g_offPlayerLv = 0x166872Cu;
static uint32_t g_offEntMgr = 0x1668860u;
static uint32_t g_gridVft = 0x117EA88u;
static uint32_t g_vftPresA = 0x117DD28u;
static uint32_t g_vftPresB = 0x1181708u;
static uint32_t g_offLiveU = 0x78u, g_offLiveV = 0x7Cu;
static uint32_t g_offLiveAU = 0x50u, g_offLiveAV = 0x54u;
static uint32_t g_presBatchOff = 0x40u;
static float g_interpMs = 516.f;
static int g_slowMs = 1000;
static uint32_t g_offCellX = 0x50u, g_offCellY = 0x54u;
static uint32_t g_offSpecies = 0x38u;
static uint32_t g_offItemId = 0x34u;   /* Item type/species when qty lives at +0x38 */
static int g_itemQtyIsO38 = 1;
static uint32_t g_offNameH = 0x20u, g_offNameObj = 0x20u;
static uint32_t g_offNameBytes = 0x40u, g_offNameLen = 0x50u;
static uint32_t g_offHolder = 0xD0u, g_offGuard = 0xD8u, g_guardVal = 1u;
static uint32_t g_offSubBeg = 0x180u, g_offSubEnd = 0x188u;
static uint32_t g_offNodeNext = 0x08u, g_offNodeCx = 0x10u, g_offNodeCy = 0x14u;
static uint32_t g_offNodeBeg = 0x18u, g_offNodeEnd = 0x20u;
static uint32_t g_offEntSelf = 0x08u;
static uint32_t g_heads[4] = { 0x798u, 0x7D8u, 0, 0 };
static int g_nh = 2;
static uint32_t g_offCompTable = 0x20u, g_actVft = 0x1180DC8u, g_actIdx = 2u;
static uint32_t g_deadByte = 0x49u, g_deadVal = 1u;
static uint32_t g_deathVft = 0x1180950u, g_deadBodyVft = 0x1180A28u;
static uint64_t g_camGlob = 0x180A150ull;
static uint32_t g_entVft[24];
static int g_entN = 0;
static float g_pps = 0.537f;
static float g_refW = 800.f, g_refH = 600.f;
static float g_vpDx = -1.8f, g_vpDy = 56.6f;
static float g_anchorDv = 24.f, g_anchorDu = 0.f;
static float g_feetDx = 0.f, g_feetDy = 0.f;
static int g_cfgClientW = 0, g_cfgClientH = 0;
static uint32_t g_vftSelf = 0x11819C0u;
static uint32_t g_vftItem = 0x1181808u;

typedef struct { uint32_t vft; char type[32]; } ClsMap;
static ClsMap g_cls[MAXCLS];
static int g_cln;

static int isHeap(uint64_t a) {
    return a >= 0x10000000000ULL && a < 0x70000000000ULL;
}
static int rm(uint64_t a, void* b, uint32_t n) {
    uint32_t br = 0;
    return SignedReadMemory(g_pid, a, b, n, &br) && br == n;
}
static uint64_t rq(uint64_t a) { uint64_t v = 0; rm(a, &v, 8); return v; }
static uint32_t rd(uint64_t a) { uint32_t v = 0; rm(a, &v, 4); return v; }
static uint32_t vrva(uint64_t o) {
    uint64_t v = 0;
    if (!rm(o, &v, 8) || v < g_base || v - g_base > g_modSize) return 0;
    return (uint32_t)(v - g_base);
}

static int hexU32(const char* p, uint32_t* v) {
    while (*p == ' ' || *p == '\t') p++;
    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) p += 2;
    uint32_t r = 0; int d = 0;
    while ((*p >= '0' && *p <= '9') || (*p >= 'a' && *p <= 'f') || (*p >= 'A' && *p <= 'F')) {
        r = r * 16 + (uint32_t)(*p <= '9' ? *p - '0' : (*p & 0xDF) - 'A' + 10);
        p++; d = 1;
    }
    if (!d) return 0;
    *v = r; return 1;
}
static int jhas(const char* key) {
    char pat[96];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    return strstr(g_cfg, pat) != NULL;
}
static double jnum(const char* key) {
    char pat[96];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    char* p = strstr(g_cfg, pat);
    if (!p) return 0;
    p = strchr(p + strlen(pat), ':');
    if (!p) return 0;
    p++;
    while (*p == ' ' || *p == '\t' || *p == '"') p++;
    if (p[0] == '0' && (p[1] == 'x' || p[1] == 'X')) {
        uint32_t v = 0; hexU32(p, &v); return (double)v;
    }
    return atof(p);
}
static int jstr(const char* key, char* out, int cap) {
    char pat[96];
    snprintf(pat, sizeof(pat), "\"%s\"", key);
    char* p = strstr(g_cfg, pat);
    if (!p) return 0;
    p = strchr(p + strlen(pat), ':');
    if (!p) return 0;
    while (*p && *p != '"') p++;
    if (*p != '"') return 0;
    p++;
    int k = 0;
    while (*p && *p != '"' && k + 1 < cap) out[k++] = *p++;
    out[k] = 0;
    return k > 0;
}
static void setCls(uint32_t v, const char* t) {
    for (int i = 0; i < g_cln; i++) if (g_cls[i].vft == v) {
        strncpy(g_cls[i].type, t, 31); g_cls[i].type[31] = 0; return;
    }
    if (g_cln < MAXCLS) {
        g_cls[g_cln].vft = v;
        strncpy(g_cls[g_cln].type, t, 31); g_cls[g_cln].type[31] = 0;
        g_cln++;
    }
}
static void seedClasses(void) {
    char* pc = strstr(g_cfg, "\"classes\"");
    if (!pc) return;
    char* e = strchr(pc, '}'); if (!e) return;
    for (char* q = strchr(pc, '"'); q && q < e; q = strchr(q + 1, '"')) {
        if (q[1] != '0' || (q[2] != 'x' && q[2] != 'X')) continue;
        uint32_t v = 0; if (!hexU32(q + 1, &v)) continue;
        char* c = strchr(q + 1, ':'); if (!c || c > e) break;
        while (*c && *c != '"') c++;
        if (*c != '"') break;
        char t[32]; int k = 0; c++;
        while (*c && *c != '"' && k < 31) t[k++] = *c++;
        t[k] = 0;
        if (k) setCls(v, t);
        q = c;
    }
}
static const char* classOf(uint32_t vft) {
    for (int i = 0; i < g_cln; i++) if (g_cls[i].vft == vft) return g_cls[i].type;
    return "Unknown";
}
static int isWorldClass(const char* t) {
    if (!t || !t[0]) return 0;
    return !strcmp(t, "Monster") || !strcmp(t, "SummonedMonster") ||
           !strcmp(t, "InteractiveNPC") || !strcmp(t, "Item") ||
           !strcmp(t, "PLAYER") || !strcmp(t, "Player") ||
           !strcmp(t, "MyPlayer") || !strcmp(t, "SELF") ||
           !strcmp(t, "Ship") || !strcmp(t, "SegmentProp") ||
           !strcmp(t, "Actor") || !strcmp(t, "ADENA") || !strcmp(t, "ITEM");
}
static int isEntityVft(uint32_t rva) {
    int i;
    for (i = 0; i < g_entN; i++) if (g_entVft[i] == rva) return 1;
    for (i = 0; i < g_cln; i++) {
        if (g_cls[i].vft == rva && isWorldClass(g_cls[i].type)) return 1;
    }
    switch (rva) {
    case 0x11819C0u: case 0x1181988u: case 0x11817D0u:
    case 0x1181878u: case 0x1181808u: case 0x1181D28u:
    case 0x1181C80u: case 0x1181E28u: case 0x117DD98u: return 1;
    }
    return 0;
}
static void siblingPath(const char* cfg, const char* name, char* out, int cap) {
    const char* slash;
    const char* slash2;
    int n;
    out[0] = 0;
    if (!name || cap < 8) return;
    if (!cfg || !cfg[0]) { strncpy(out, name, cap - 1); out[cap - 1] = 0; return; }
    slash = strrchr(cfg, '\\');
    slash2 = strrchr(cfg, '/');
    if (slash2 > slash) slash = slash2;
    if (!slash) { strncpy(out, name, cap - 1); out[cap - 1] = 0; return; }
    n = (int)(slash - cfg + 1);
    if (n + (int)strlen(name) + 1 > cap) return;
    memcpy(out, cfg, (size_t)n);
    strcpy(out + n, name);
}
static uint8_t rd8(uint64_t a) { uint8_t v = 0; rm(a, &v, 1); return v; }
static int isDead(uint64_t e) {
    uint64_t tb, te, ac;
    uint32_t o;
    tb = rq(e + g_offCompTable);
    te = rq(e + g_offCompTable + 8);
    if (!isHeap(tb) || te <= tb || (te - tb) >= 0x2000 ||
        (te - tb) < (uint64_t)(g_actIdx + 1) * 8) return 0;
    ac = rq(tb + (uint64_t)g_actIdx * 8);
    if (!isHeap(ac) || vrva(ac) != g_actVft) return 0;
    for (o = 0; o + 8 <= 0x140; o += 8) {
        uint64_t v = rq(ac + o);
        uint32_t cv;
        if (!isHeap(v)) continue;
        cv = vrva(v);
        if (cv == g_deathVft || cv == g_deadBodyVft) return 1;
    }
    if (rd8(ac + g_deadByte) == (uint8_t)g_deadVal) return 1;
    return 0;
}
static void applyClassRoles(void) {
    int i;
    for (i = 0; i < g_cln; i++) {
        if (!strcmp(g_cls[i].type, "MyPlayer") || !strcmp(g_cls[i].type, "SELF"))
            g_vftSelf = g_cls[i].vft;
        if (!strcmp(g_cls[i].type, "Item") || !strcmp(g_cls[i].type, "ITEM") ||
            !strcmp(g_cls[i].type, "ADENA"))
            g_vftItem = g_cls[i].vft;
    }
}
static void seedDefaultClasses(void) {
    if (g_cln) return;
    setCls(0x1181878u, "Monster");
    setCls(0x11817D0u, "InteractiveNPC");
    setCls(0x1181808u, "Item");
    setCls(0x11819C0u, "MyPlayer");
    setCls(0x1181D28u, "SegmentProp");
    setCls(0x1181C80u, "Ship");
    setCls(0x1181E28u, "SummonedMonster");
    setCls(0x1181988u, "Player");
}
static void loadEntityOffsets(const char* path) {
    FILE* f;
    char line[512];
    int n = 0;
    if (!path || !path[0]) return;
    f = fopen(path, "r");
    if (!f) return;
    while (fgets(line, sizeof(line), f)) {
        char* p;
        if ((p = strchr(line, '\n'))) *p = 0;
        if ((p = strchr(line, '\r'))) *p = 0;
        if (!strncmp(line, "MGR=", 4)) g_offEntMgr = (uint32_t)strtoul(line + 4, 0, 16);
        else if (!strncmp(line, "GUARD_OFF=", 10)) g_offGuard = (uint32_t)strtoul(line + 10, 0, 16);
        else if (!strncmp(line, "GUARD_VAL=", 10)) g_guardVal = (uint32_t)strtoul(line + 10, 0, 16);
        else if (!strncmp(line, "HOLDER_OFF=", 11)) g_offHolder = (uint32_t)strtoul(line + 11, 0, 16);
        else if (!strncmp(line, "SUBLIST_BEG=", 12)) g_offSubBeg = (uint32_t)strtoul(line + 12, 0, 16);
        else if (!strncmp(line, "SUBLIST_END=", 12)) g_offSubEnd = (uint32_t)strtoul(line + 12, 0, 16);
        else if (!strncmp(line, "ACTOR_VFT=", 10)) g_gridVft = (uint32_t)strtoul(line + 10, 0, 16);
        else if (!strncmp(line, "NODE_NEXT=", 10)) g_offNodeNext = (uint32_t)strtoul(line + 10, 0, 16);
        else if (!strncmp(line, "NODE_CX=", 8)) g_offNodeCx = (uint32_t)strtoul(line + 8, 0, 16);
        else if (!strncmp(line, "NODE_CY=", 8)) g_offNodeCy = (uint32_t)strtoul(line + 8, 0, 16);
        else if (!strncmp(line, "NODE_BEG=", 9)) g_offNodeBeg = (uint32_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "NODE_END=", 9)) g_offNodeEnd = (uint32_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "ENT_SELF=", 9)) g_offEntSelf = (uint32_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "ENT_SPECIES=", 12)) g_offSpecies = (uint32_t)strtoul(line + 12, 0, 16);
        else if (!strncmp(line, "NAME_H=", 7)) g_offNameH = (uint32_t)strtoul(line + 7, 0, 16);
        else if (!strncmp(line, "NAME_OBJ=", 9)) g_offNameObj = (uint32_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "NAME_BYTES=", 11)) g_offNameBytes = (uint32_t)strtoul(line + 11, 0, 16);
        else if (!strncmp(line, "NAME_LEN=", 9)) g_offNameLen = (uint32_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "COMP_TABLE=", 11)) g_offCompTable = (uint32_t)strtoul(line + 11, 0, 16);
        else if (!strncmp(line, "ACT_VFT=", 8)) g_actVft = (uint32_t)strtoul(line + 8, 0, 16);
        else if (!strncmp(line, "ACT_IDX=", 8)) g_actIdx = (uint32_t)strtoul(line + 8, 0, 16);
        else if (!strncmp(line, "ACT_DEAD_BYTE=", 14)) g_deadByte = (uint32_t)strtoul(line + 14, 0, 16);
        else if (!strncmp(line, "ACT_DEAD_VAL=", 13)) g_deadVal = (uint32_t)strtoul(line + 13, 0, 16);
        else if (!strncmp(line, "DEATH_VFT=", 10)) g_deathVft = (uint32_t)strtoul(line + 10, 0, 16);
        else if (!strncmp(line, "DEADBODY_VFT=", 13)) g_deadBodyVft = (uint32_t)strtoul(line + 13, 0, 16);
        else if (!strncmp(line, "PLAYER_X=", 9)) g_offPlayerX = (uint32_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "PLAYER_Y=", 9)) g_offPlayerY = (uint32_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "PLAYER_HP=", 10)) g_offPlayerHp = (uint32_t)strtoul(line + 10, 0, 16);
        else if (!strncmp(line, "PLAYER_MAXHP=", 13)) g_offPlayerMaxHp = (uint32_t)strtoul(line + 13, 0, 16);
        else if (!strncmp(line, "PLAYER_MP=", 10)) g_offPlayerMp = (uint32_t)strtoul(line + 10, 0, 16);
        else if (!strncmp(line, "PLAYER_MAXMP=", 13)) g_offPlayerMaxMp = (uint32_t)strtoul(line + 13, 0, 16);
        else if (!strncmp(line, "PLAYER_LEVEL=", 13)) g_offPlayerLv = (uint32_t)strtoul(line + 13, 0, 16);
        else if (!strncmp(line, "CAM_GLOB=", 9)) g_camGlob = (uint64_t)strtoul(line + 9, 0, 16);
        else if (!strncmp(line, "VFT_PRES_A=", 11)) g_vftPresA = (uint32_t)strtoul(line + 11, 0, 16);
        else if (!strncmp(line, "VFT_PRES_B=", 11)) g_vftPresB = (uint32_t)strtoul(line + 11, 0, 16);
        else if (!strncmp(line, "OFF_LIVE_U=", 11)) g_offLiveU = (uint32_t)strtoul(line + 11, 0, 16);
        else if (!strncmp(line, "OFF_LIVE_V=", 11)) g_offLiveV = (uint32_t)strtoul(line + 11, 0, 16);
        else if (!strncmp(line, "OFF_A_U=", 8)) g_offLiveAU = (uint32_t)strtoul(line + 8, 0, 16);
        else if (!strncmp(line, "OFF_A_V=", 8)) g_offLiveAV = (uint32_t)strtoul(line + 8, 0, 16);
        else if (!strncmp(line, "INTERP_MS=", 10)) {
            float fl = (float)atof(line + 10);
            if (fl > 16.f && fl < 4000.f) g_interpMs = fl;
        }
        else if (!strncmp(line, "SLOW_MS=", 8)) {
            int v = atoi(line + 8);
            if (v >= 0 && v < 60000) g_slowMs = v;
        }
        else if (!strncmp(line, "PPS=", 4)) {
            float fl = (float)atof(line + 4);
            if (fl > 0.01f && fl < 8.f) g_pps = fl;
        }
        else if (!strncmp(line, "REF_W=", 6)) {
            float fl = (float)atof(line + 6);
            if (fl > 50.f) g_refW = fl;
        }
        else if (!strncmp(line, "REF_H=", 6)) {
            float fl = (float)atof(line + 6);
            if (fl > 50.f) g_refH = fl;
        }
        else if (!strncmp(line, "FEET_DX=", 8)) g_feetDx = (float)atof(line + 8);
        else if (!strncmp(line, "FEET_DY=", 8)) g_feetDy = (float)atof(line + 8);
        else if (!strncmp(line, "ANCHOR_DU=", 10)) g_anchorDu = (float)atof(line + 10);
        else if (!strncmp(line, "ANCHOR_DV=", 10)) g_anchorDv = (float)atof(line + 10);
        else if (!strncmp(line, "MAP_HEADS=", 10)) {
            char* s = line + 10;
            g_nh = 0;
            while (*s && g_nh < 4) {
                g_heads[g_nh++] = (uint32_t)strtoul(s, 0, 16);
                p = strchr(s, ',');
                if (!p) break;
                s = p + 1;
            }
        }
        else if (!strncmp(line, "ENT_VFT_SET=", 12)) {
            char* s = line + 12;
            g_entN = 0;
            while (*s && g_entN < 24) {
                g_entVft[g_entN++] = (uint32_t)strtoul(s, 0, 16);
                p = strchr(s, ',');
                if (!p) break;
                s = p + 1;
            }
        }
        else if (!strncmp(line, "CLASSES=", 8)) {
            char* s = line + 8;
            while (*s) {
                char* c = strchr(s, ',');
                int seg = c ? (int)(c - s) : (int)strlen(s);
                char buf[96] = { 0 };
                if (seg > 0 && seg < 95) {
                    char* col;
                    memcpy(buf, s, (size_t)seg);
                    col = strchr(buf, ':');
                    if (col) {
                        uint32_t u;
                        *col = 0;
                        u = (uint32_t)strtoul(buf, 0, 16);
                        if (isWorldClass(col + 1)) setCls(u, col + 1);
                    }
                }
                if (!c) break;
                s = c + 1;
            }
        }
        n++;
    }
    fclose(f);
    applyClassRoles();
    if (n) fprintf(stderr, "[registry] %s mgr=0x%X grid=0x%X act=0x%X death=0x%X classes=%d\n",
        path, g_offEntMgr, g_gridVft, g_actVft, g_deathVft, g_cln);
}

static void loadSettings(const char* path) {
    FILE* f = fopen(path, "rb");
    if (!f) { fprintf(stderr, "no %s — defaults\n", path); return; }
    size_t n = fread(g_cfg, 1, sizeof(g_cfg) - 1, f);
    g_cfg[n] = 0; fclose(f);
    fprintf(stderr, "loaded %s (%u bytes)\n", path, (unsigned)n);

    char tmp[64];
    if (jstr("process_name", tmp, sizeof(tmp))) {
        strncpy(g_procName, tmp, 63); g_procName[63] = 0;
    }
    if (jhas("interval_ms")) g_intervalMs = (int)jnum("interval_ms");
    if (g_intervalMs < 16) g_intervalMs = 16;
    if (jhas("once")) g_once = (int)jnum("once");
    if (jstr("output_file", tmp, sizeof(tmp))) {
        strncpy(g_outPath, tmp, MAX_PATH - 1); g_outPath[MAX_PATH - 1] = 0;
    }
    if (jhas("output_rotate_ms")) g_rotateMs = (int)jnum("output_rotate_ms");
    if (g_rotateMs < 1000) g_rotateMs = 1000;
    if (jhas("player_x_offset")) g_offPlayerX = (uint32_t)jnum("player_x_offset");
    if (jhas("player_y_offset")) g_offPlayerY = (uint32_t)jnum("player_y_offset");
    if (jhas("player_hp_offset")) g_offPlayerHp = (uint32_t)jnum("player_hp_offset");
    if (jhas("player_maxhp_offset")) g_offPlayerMaxHp = (uint32_t)jnum("player_maxhp_offset");
    if (jhas("player_mp_offset")) g_offPlayerMp = (uint32_t)jnum("player_mp_offset");
    if (jhas("player_maxmp_offset")) g_offPlayerMaxMp = (uint32_t)jnum("player_maxmp_offset");
    if (jhas("player_level_offset")) g_offPlayerLv = (uint32_t)jnum("player_level_offset");
    if (jhas("ent_mgr_offset")) g_offEntMgr = (uint32_t)jnum("ent_mgr_offset");
    if (jhas("grid_vft")) g_gridVft = (uint32_t)jnum("grid_vft");
    if (jhas("vft_pres_a")) g_vftPresA = (uint32_t)jnum("vft_pres_a");
    if (jhas("vft_pres_b")) g_vftPresB = (uint32_t)jnum("vft_pres_b");
    if (jhas("off_live_u")) g_offLiveU = (uint32_t)jnum("off_live_u");
    if (jhas("off_live_v")) g_offLiveV = (uint32_t)jnum("off_live_v");
    if (jhas("off_a_u")) g_offLiveAU = (uint32_t)jnum("off_a_u");
    if (jhas("off_a_v")) g_offLiveAV = (uint32_t)jnum("off_a_v");
    if (jhas("interp_ms") && jnum("interp_ms") > 16.0) g_interpMs = (float)jnum("interp_ms");
    if (jhas("slow_ms")) {
        int v = (int)jnum("slow_ms");
        if (v >= 0 && v < 60000) g_slowMs = v;
    }
    if (jhas("off_ent_cell_x")) g_offCellX = (uint32_t)jnum("off_ent_cell_x");
    if (jhas("off_ent_cell_y")) g_offCellY = (uint32_t)jnum("off_ent_cell_y");
    if (jhas("off_ent_species")) g_offSpecies = (uint32_t)jnum("off_ent_species");
    if (jhas("off_ent_item_id")) g_offItemId = (uint32_t)jnum("off_ent_item_id");
    if (jhas("item_qty_is_o38")) g_itemQtyIsO38 = (int)jnum("item_qty_is_o38");
    if (jhas("off_name_holder")) g_offNameH = (uint32_t)jnum("off_name_holder");
    if (jhas("off_name_obj")) g_offNameObj = (uint32_t)jnum("off_name_obj");
    if (jhas("off_name_bytes")) g_offNameBytes = (uint32_t)jnum("off_name_bytes");
    if (jhas("off_name_len")) g_offNameLen = (uint32_t)jnum("off_name_len");
    if (jhas("range")) g_range = (int)jnum("range");
    if (jhas("pps") && jnum("pps") > 0) g_pps = (float)jnum("pps");
    if (jhas("ref_w") && jnum("ref_w") > 0) g_refW = (float)jnum("ref_w");
    if (jhas("ref_h") && jnum("ref_h") > 0) g_refH = (float)jnum("ref_h");
    if (jhas("vp_dx")) g_vpDx = (float)jnum("vp_dx");
    if (jhas("vp_dy")) g_vpDy = (float)jnum("vp_dy");
    if (jhas("anchor_dv")) g_anchorDv = (float)jnum("anchor_dv");
    if (jhas("anchor_du")) g_anchorDu = (float)jnum("anchor_du");
    if (jhas("feet_dx")) g_feetDx = (float)jnum("feet_dx");
    if (jhas("feet_dy")) g_feetDy = (float)jnum("feet_dy");
    if (jhas("client_w")) g_cfgClientW = (int)jnum("client_w");
    if (jhas("client_h")) g_cfgClientH = (int)jnum("client_h");

    seedClasses();
    seedDefaultClasses();
    applyClassRoles();
    {
        char reg[MAX_PATH];
        siblingPath(path, "entity_offsets.txt", reg, sizeof(reg));
        loadEntityOffsets(reg);
    }
}
static int isItemVft(uint32_t vft) {
    if (vft == g_vftItem) return 1;
    const char* t = classOf(vft);
    return t && (!strcmp(t, "Item") || !strcmp(t, "ITEM") || !strcmp(t, "ADENA"));
}

static DWORD findPid(const wchar_t* name) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    PROCESSENTRY32W pe; pe.dwSize = sizeof(pe); DWORD pid = 0;
    if (Process32FirstW(snap, &pe)) do {
        if (_wcsicmp(pe.szExeFile, name) == 0) { pid = pe.th32ProcessID; break; }
    } while (Process32NextW(snap, &pe));
    CloseHandle(snap); return pid;
}
static int getModule(uint64_t* base, uint32_t* size) {
    uint64_t peb = 0, ldr = 0, lh = 0, cur = 0, ent = 0, db = 0, img = 0;
    uint32_t b = 0;
    if (!SignedGetPeb(g_pid, &peb) || !peb) return 0;
    if (SignedReadMemory(g_pid, peb + 0x10, &img, 8, &b) && b == 8 && img) {
        uint32_t e = 0, sz = 0;
        if (SignedReadMemory(g_pid, img + 0x3C, &e, 4, &b) && b == 4 && e < 0x1000 &&
            SignedReadMemory(g_pid, img + e + 0x50, &sz, 4, &b) && b == 4 && sz) {
            *base = img; *size = sz; return 1;
        }
    }
    if (!(SignedReadMemory(g_pid, peb + 0x18, &ldr, 8, &b) && b == 8) || !ldr) return 0;
    if (!(SignedReadMemory(g_pid, ldr + 0x20, &lh, 8, &b) && b == 8)) return 0;
    cur = lh;
    while (cur && cur != (ldr + 0x20)) {
        ent = cur - 0x10; db = 0; uint32_t ds = 0;
        if ((SignedReadMemory(g_pid, ent + 0x30, &db, 8, &b) && b == 8 && db) &&
            (SignedReadMemory(g_pid, ent + 0x40, &ds, 4, &b) && b == 4 && ds)) {
            *base = db; *size = ds; return 1;
        }
        if (!(SignedReadMemory(g_pid, cur, &cur, 8, &b) && b == 8)) return 0;
    }
    return 0;
}

struct EInfo { HWND best; DWORD pid; LONGLONG bestArea; };
static BOOL CALLBACK eFindWnd(HWND h, LPARAM lp) {
    struct EInfo* ei = (struct EInfo*)lp;
    DWORD pid = 0; GetWindowThreadProcessId(h, &pid);
    if (pid != ei->pid || !IsWindowVisible(h)) return TRUE;
    char t[256]; if (!GetWindowTextA(h, t, sizeof(t))) return TRUE;
    RECT rc; if (!GetClientRect(h, &rc)) return TRUE;
    LONGLONG a = (LONGLONG)(rc.right - rc.left) * (rc.bottom - rc.top);
    if (a > ei->bestArea) { ei->best = h; ei->bestArea = a; }
    return TRUE;
}
static HWND findLCWnd(DWORD pid) {
    struct EInfo ei; memset(&ei, 0, sizeof(ei)); ei.pid = pid;
    EnumWindows(eFindWnd, (LPARAM)&ei);
    return ei.best;
}
static void resolveClientSize(HWND gwnd, int* W, int* H) {
    *W = g_cfgClientW;
    *H = g_cfgClientH;
    if (gwnd) {
        RECT rc;
        if (GetClientRect(gwnd, &rc)) {
            int cw = rc.right - rc.left, ch = rc.bottom - rc.top;
            if (cw > 100 && ch > 100) { *W = cw; *H = ch; }
        }
    }
    if ((*W < 100 || *H < 100) && g_camGlob) {
        uint64_t cam = rq(g_base + g_camGlob);
        if (isHeap(cam)) {
            float w = 0.f, h = 0.f;
            rm(cam + 0x18, &w, 4);
            rm(cam + 0x1C, &h, 4);
            if (w > 100.f && w < 8000.f) *W = (int)w;
            if (h > 100.f && h < 8000.f) *H = (int)h;
        }
    }
    if (*W < 100) *W = (int)g_refW;
    if (*H < 100) *H = (int)g_refH;
}

static int followComp(uint64_t q, uint32_t* rvaOut, uint64_t* entOut) {
    uint64_t cand[3] = { q, 0, (q > 0x10) ? q - 0x10 : 0 };
    uint64_t p18 = 0;
    if (rm(q + 0x18, &p18, 8) && isHeap(p18)) cand[1] = p18;
    for (int i = 0; i < 3; i++) {
        uint64_t c = cand[i]; if (!c || !isHeap(c)) continue;
        uint32_t r = vrva(c);
        if (r && isEntityVft(r)) { *rvaOut = r; *entOut = c; return 1; }
    }
    return 0;
}
static uint64_t findPres(uint64_t ent, uint32_t want) {
    uint64_t H = 0;
    if (!ent || !rm(ent + 0x20, &H, 8) || !isHeap(H)) return 0;
    for (uint32_t off = 0; off < 0x180; off += 8) {
        uint64_t p = 0;
        if (!rm(H + off, &p, 8) || !isHeap(p)) continue;
        uint32_t r = vrva(p);
        if (r == want) return p;
        if (want == g_vftPresB) {
            uint32_t r2 = vrva(p + 0x10);
            if (r2 == g_vftPresB) return p + 0x10;
        }
        for (uint32_t o2 = 0; o2 < 0xA0; o2 += 8) {
            uint64_t c = 0;
            if (!rm(p + o2, &c, 8) || !isHeap(c)) continue;
            r = vrva(c);
            if (r == want) return c;
            if (want == g_vftPresB) {
                uint32_t r2 = vrva(c + 0x10);
                if (r2 == g_vftPresB) return c + 0x10;
            }
        }
    }
    return 0;
}
static int readPresLive(uint64_t pres, float* u, float* v) {
    uint8_t b[8];
    if (!rm(pres + g_offLiveU, b, 8)) return 0;
    memcpy(u, b, 4); memcpy(v, b + 4, 4);
    if (!isfinite(*u) || !isfinite(*v)) return 0;
    if (fabsf(*u) > 1e8f || fabsf(*v) > 1e8f) return 0;
    return 1;
}
static int readEntName(uint64_t ent, char* out, int cap) {
    if (cap < 1) return 0;
    out[0] = 0;
    if (!ent || !isHeap(ent)) return 0;
    uint64_t H = 0;
    if (!rm(ent + g_offNameH, &H, 8) || !isHeap(H)) return 0;
    uint64_t nobj = 0;
    if (!rm(H + g_offNameObj, &nobj, 8) || !isHeap(nobj)) return 0;
    /* nameobj+0x40 / +0x50 mirror MSVC std::string data/size:
       short names (SSO, e.g. "아데나") are inline at +0x40;
       longer names store a heap pointer at +0x40. Treating the
       pointer bytes as UTF-8 yields empty/` garbled names — not an
       encoding bug. */
    uint8_t inlineBuf[0x58];
    if (!rm(nobj + g_offNameBytes, inlineBuf, sizeof(inlineBuf))) return 0;
    uint64_t len = 0;
    if (!rm(nobj + g_offNameLen, &len, 8)) return 0;
    if (len == 0 || len > 0x100) return 0;
    uint64_t maybePtr = 0;
    memcpy(&maybePtr, inlineBuf, 8);
    uint8_t heapBuf[0x100];
    const uint8_t* src = inlineBuf;
    if (isHeap(maybePtr)) {
        uint32_t n = (uint32_t)len;
        if (n > sizeof(heapBuf)) n = (uint32_t)sizeof(heapBuf);
        if (!rm(maybePtr, heapBuf, n)) return 0;
        src = heapBuf;
    } else if (len > 0x38) {
        return 0; /* inline payload larger than local read window */
    }
    uint64_t i = 0, k = 0;
    while (i < len && k + 3 < (uint64_t)cap) {
        uint8_t c = src[i];
        int adv = 0;
        if (c < 0x80) { adv = 1; out[k++] = (char)c; }
        else if (c >= 0xC2 && c <= 0xDF && i + 1 < len && (src[i + 1] & 0xC0) == 0x80) {
            adv = 2; out[k++] = (char)c; out[k++] = (char)src[i + 1];
        } else if (c >= 0xE0 && c <= 0xEF && i + 2 < len &&
                   (src[i + 1] & 0xC0) == 0x80 && (src[i + 2] & 0xC0) == 0x80) {
            adv = 3; out[k++] = (char)c; out[k++] = (char)src[i + 1]; out[k++] = (char)src[i + 2];
        } else break;
        i += (uint64_t)adv;
    }
    out[k] = 0;
    return k > 0;
}

typedef struct {
    uint64_t ent;
    uint64_t presB;
    uint32_t vft;
    int32_t cx, cy;
    uint32_t species;
    uint32_t qty;       /* Item stack count when item_qty_is_o38; else 0 */
    int haveQty;
    char name[NAME_CAP];
    float liveU, liveV; /* B slot (+0x78) raw iso */
    int haveLive;
    float aU, aV, bU, bV, iU, iV;
    DWORD aTime;
    int aInit;
    float scrX, scrY;
    float iScrX, iScrY;
    int haveScr;
    int haveIscr;
    const char* scrSrc;
} Ent;

static Ent g_ents[MAXENT];
static int g_nEnts = 0;
static DWORD g_lastSlow = 0;
static int32_t g_lastSweepPx = 0, g_lastSweepPy = 0;

static void resetTracks(void) {
    g_nEnts = 0;
    g_lastSlow = 0;
    g_lastSweepPx = 0;
    g_lastSweepPy = 0;
    memset(g_ents, 0, sizeof(g_ents));
}

static void applyInterp(Ent* t, float aU, float aV, float bU, float bV, DWORD now) {
    if (!t->aInit) {
        t->aU = aU; t->aV = aV; t->aTime = now; t->aInit = 1;
    } else if (t->aU != aU || t->aV != aV) {
        t->aU = aU; t->aV = aV; t->aTime = now;
    }
    t->bU = bU; t->bV = bV;
    float tt = (g_interpMs > 1.f) ? (float)(now - t->aTime) / g_interpMs : 1.f;
    if (tt < 0.f) tt = 0.f;
    if (tt > 1.f) tt = 1.f;
    t->iU = t->aU + (bU - t->aU) * tt;
    t->iV = t->aV + (bV - t->aV) * tt;
}

static int readPresBatch(uint64_t pres, Ent* t, DWORD now) {
    uint8_t buf[0x48];
    uint32_t aRel, bRel;
    float aU, aV, bU, bV;
    int32_t cx, cy;
    if (!pres || !isHeap(pres) || !rm(pres + g_presBatchOff, buf, sizeof(buf)))
        return 0;
    cx = *(int32_t*)(buf + 0x00);
    cy = *(int32_t*)(buf + 0x04);
    if (cx > 1000 && cx < 60000 && cy > 1000 && cy < 60000) {
        t->cx = cx; t->cy = cy;
    }
    aRel = (g_offLiveAU >= g_presBatchOff) ? (g_offLiveAU - g_presBatchOff) : 0x10u;
    bRel = (g_offLiveU >= g_presBatchOff) ? (g_offLiveU - g_presBatchOff) : 0x38u;
    {
        uint32_t aRelV = (g_offLiveAV >= g_presBatchOff) ? (g_offLiveAV - g_presBatchOff) : (aRel + 4);
        if (aRel + 4 > sizeof(buf) || aRelV + 4 > sizeof(buf) || bRel + 8 > sizeof(buf))
            return 0;
        aU = *(float*)(buf + aRel); aV = *(float*)(buf + aRelV);
        bU = *(float*)(buf + bRel); bV = *(float*)(buf + bRel + 4);
    }
    if (!isfinite(aU) || !isfinite(aV) || !isfinite(bU) || !isfinite(bV)) return 0;
    if (fabsf(bU) > 1e8f || fabsf(bV) > 1e8f) return 0;
    t->liveU = bU; t->liveV = bV;
    applyInterp(t, aU, aV, bU, bV, now);
    t->haveLive = 1;
    return 1;
}

static int slowSweep(int32_t px, int32_t py) {
    Ent old[MAXENT];
    int no = g_nEnts;
    int n = 0;
    Ent* out = g_ents;
    if (no > 0) memcpy(old, g_ents, sizeof(Ent) * (size_t)no);
    uint64_t mgr = rq(g_base + g_offEntMgr);
    if (!isHeap(mgr)) { g_nEnts = 0; return 0; }
    uint8_t grd = 0; rm(mgr + g_offGuard, &grd, 1);
    if (grd != (uint8_t)g_guardVal) { g_nEnts = 0; return 0; }
    uint64_t holder = rq(mgr + g_offHolder);
    if (!isHeap(holder)) { g_nEnts = 0; return 0; }
    uint64_t bgn = rq(holder + g_offSubBeg), end = rq(holder + g_offSubEnd);
    if (!isHeap(bgn) || end <= bgn || (end - bgn) > 0x2000) { g_nEnts = 0; return 0; }
    uint64_t best = 0;
    for (uint64_t e = bgn; e + 16 <= end; e += 16) {
        uint64_t obj = rq(e);
        if (!isHeap(obj)) continue;
        if (vrva(obj) == g_gridVft) { best = obj; break; }
    }
    if (!best) { g_nEnts = 0; return 0; }
    for (int hi = 0; hi < g_nh; hi++) {
        uint8_t hb[0x40];
        if (!rm(best + g_heads[hi], hb, sizeof(hb))) continue;
        uint64_t sent = *(uint64_t*)(hb + 8), cur = 0;
        if (!rm(sent + g_offNodeNext, &cur, 8)) continue;
        int hops = 0;
        while (cur && cur != sent && isHeap(cur) && n < MAXENT && hops++ < 1100) {
            uint8_t nb[0x30];
            if (!rm(cur, nb, sizeof(nb))) break;
            uint64_t next = *(uint64_t*)(nb + g_offNodeNext);
            int32_t cx = *(int32_t*)(nb + g_offNodeCx);
            int32_t cy = *(int32_t*)(nb + g_offNodeCy);
            uint64_t vb = *(uint64_t*)(nb + g_offNodeBeg);
            uint64_t ve = *(uint64_t*)(nb + g_offNodeEnd);
            cur = next;
            if (abs(cx - px) > g_range || abs(cy - py) > g_range) continue;
            if (!isHeap(vb) || ve < vb || (ve - vb) > 0x1000) continue;
            for (uint64_t p = vb; p + 8 <= ve && n < MAXENT; p += 8) {
                uint64_t q = 0, ent = 0; uint32_t rva = 0;
                if (!rm(p, &q, 8) || !isHeap(q) || !followComp(q, &rva, &ent)) continue;
                if (g_offEntSelf && rq(ent + g_offEntSelf) != ent) continue;
                if (isDead(ent)) continue;
                int dup = 0;
                for (int i = 0; i < n; i++) if (out[i].ent == ent) { dup = 1; break; }
                if (dup) continue;
                Ent* E = &out[n];
                memset(E, 0, sizeof(*E));
                E->ent = ent; E->vft = rva; E->cx = cx; E->cy = cy;
                E->scrSrc = "none";
                /* refresh cell from entity blob */
                {
                    int32_t ecx = 0, ecy = 0;
                    if (rm(ent + g_offCellX, &ecx, 4) && rm(ent + g_offCellY, &ecy, 4) &&
                        ecx > 1000 && ecx < 60000 && ecy > 1000 && ecy < 60000) {
                        E->cx = ecx; E->cy = ecy;
                    }
                }
                {
                    uint32_t o38 = 0;
                    rm(ent + g_offSpecies, &o38, 4);
                    if (g_itemQtyIsO38 && isItemVft(rva)) {
                        /* Item: +0x38 is stack qty; type/species lives at +0x34 */
                        uint32_t iid = 0;
                        rm(ent + g_offItemId, &iid, 4);
                        E->species = iid;
                        E->qty = o38;
                        E->haveQty = 1;
                    } else {
                        E->species = o38;
                    }
                }
                readEntName(ent, E->name, sizeof(E->name));
                /* Adena live name often embeds qty as "아데나 (N)"; strip when we
                   already expose qty so name is the species name alone. */
                if (E->haveQty && E->name[0]) {
                    char* lp = strrchr(E->name, '(');
                    char* rp = strrchr(E->name, ')');
                    if (lp && rp && rp > lp + 1 && rp[1] == 0) {
                        char* p = lp + 1;
                        unsigned long n = 0; int dig = 0;
                        while (*p >= '0' && *p <= '9') { n = n * 10 + (unsigned)(*p - '0'); p++; dig = 1; }
                        if (dig && p == rp && n == (unsigned long)E->qty) {
                            while (lp > E->name && (lp[-1] == ' ' || lp[-1] == '\t')) lp--;
                            *lp = 0;
                        }
                    }
                }
                uint64_t pb = findPres(ent, g_vftPresB);
                if (!pb) pb = findPres(ent, g_vftPresA);
                E->presB = pb;
                for (int oi = 0; oi < no; oi++) {
                    if (old[oi].ent == ent && old[oi].presB == pb && pb) {
                        E->aU = old[oi].aU; E->aV = old[oi].aV;
                        E->bU = old[oi].bU; E->bV = old[oi].bV;
                        E->iU = old[oi].iU; E->iV = old[oi].iV;
                        E->aTime = old[oi].aTime; E->aInit = old[oi].aInit;
                        E->liveU = old[oi].liveU; E->liveV = old[oi].liveV;
                        E->haveLive = old[oi].haveLive;
                        break;
                    }
                }
                n++;
            }
        }
    }
    g_nEnts = n;
    g_lastSweepPx = px;
    g_lastSweepPy = py;
    return n;
}

static void fastPoll(void) {
    DWORD now = GetTickCount();
    int i;
    for (i = 0; i < g_nEnts; i++) {
        Ent* t = &g_ents[i];
        if (!t->presB) { t->haveLive = 0; continue; }
        if (readPresBatch(t->presB, t, now)) continue;
        if (readPresLive(t->presB, &t->liveU, &t->liveV)) {
            t->iU = t->liveU; t->iV = t->liveV;
            t->haveLive = 1;
        } else {
            t->haveLive = 0;
        }
    }
}

static int tickTracks(int32_t px, int32_t py) {
    DWORD now = GetTickCount();
    int moved = (abs(px - g_lastSweepPx) > 8 || abs(py - g_lastSweepPy) > 8);
    int due = (g_nEnts == 0) || (g_slowMs <= 0) ||
              (now - g_lastSlow >= (DWORD)g_slowMs) || moved;
    if (due) {
        if (!slowSweep(px, py) && g_nEnts == 0) {
            g_lastSlow = now;
            return 0;
        }
        g_lastSlow = now;
    }
    fastPoll();
    return g_nEnts;
}

static void projectPresPx(float du, float dv, float selfScrX, float selfScrY,
                          float pxp, float pyp, float* rx, float* ry) {
    *rx = selfScrX + du * pxp;
    *ry = selfScrY - dv * pyp;
}
static void projectCell(float dx, float dy, float selfScrX, float selfScrY,
                        float pxp, float pyp, float* rx, float* ry) {
    float du = 48.0f * (dx + dy), dv = 24.0f * (dx - dy);
    projectPresPx(du, dv, selfScrX, selfScrY, pxp, pyp, rx, ry);
}

typedef struct Out {
    FILE* file;
    char* buf;
    int cap;
    int len;
    int overflow;
} Out;

static void outRaw(Out* o, const char* s, int n) {
    if (n <= 0) return;
    if (o->file) fwrite(s, 1, (size_t)n, o->file);
    if (o->buf && o->cap > 0) {
        int room = o->cap - o->len - 1;
        if (room < 0) room = 0;
        int copy = n < room ? n : room;
        if (copy > 0) memcpy(o->buf + o->len, s, (size_t)copy);
        if (n > room) o->overflow = 1;
    }
    o->len += n;
}

static void outc(Out* o, char c) { outRaw(o, &c, 1); }

static void outf(Out* o, const char* fmt, ...) {
    char stack[2048];
    va_list ap;
    va_start(ap, fmt);
    int n = vsnprintf(stack, sizeof(stack), fmt, ap);
    va_end(ap);
    if (n < 0) return;
    if (n < (int)sizeof(stack)) {
        outRaw(o, stack, n);
        return;
    }
    char* big = (char*)malloc((size_t)n + 1);
    if (!big) { o->overflow = 1; return; }
    va_start(ap, fmt);
    vsnprintf(big, (size_t)n + 1, fmt, ap);
    va_end(ap);
    outRaw(o, big, n);
    free(big);
}

static void jsonEscape(Out* o, const char* s) {
    outc(o, '"');
    if (!s) { outc(o, '"'); return; }
    for (const unsigned char* p = (const unsigned char*)s; *p; p++) {
        if (*p == '"' || *p == '\\') { outc(o, '\\'); outc(o, (char)*p); }
        else if (*p < 0x20) outf(o, "\\u%04x", *p);
        else outc(o, (char)*p);
    }
    outc(o, '"');
}

static void emitState(Out* out, DWORD t0, int W, int H, Ent* ents, int n,
                      uint32_t px, uint32_t py,
                      uint32_t hp, uint32_t maxhp, uint32_t mp, uint32_t maxmp, uint32_t lv) {
    float sx = (float)W / g_refW, sy = (float)H / g_refH;
    float cx0 = (float)W * 0.5f + g_vpDx * sx;
    float cy0 = (float)H * 0.5f - g_vpDy * sy;
    float selfScrX = cx0 + g_feetDx * sx;
    float selfScrY = cy0 + g_feetDy * sy - g_anchorDv * g_pps * sy;
    selfScrX += g_anchorDu * g_pps * sx;
    float pxp = g_pps * sx, pyp = g_pps * sy;

    /* self live for relative projection (raw B + interpolated A→B) */
    float selfU = 0, selfV = 0, selfIU = 0, selfIV = 0;
    int selfLive = 0;
    uint64_t selfEnt = 0;
    for (int i = 0; i < n; i++) {
        if (ents[i].vft == g_vftSelf) {
            selfEnt = ents[i].ent;
            if (ents[i].haveLive) {
                selfU = ents[i].liveU; selfV = ents[i].liveV;
                selfIU = ents[i].iU; selfIV = ents[i].iV;
                selfLive = 1;
            }
            break;
        }
    }
    (void)selfEnt;

    for (int i = 0; i < n; i++) {
        Ent* E = &ents[i];
        if (E->vft == g_vftSelf) {
            E->scrX = selfScrX; E->scrY = selfScrY;
            E->iScrX = selfScrX; E->iScrY = selfScrY;
            E->haveScr = 1; E->haveIscr = 1; E->scrSrc = "self";
            continue;
        }
        if (selfLive && E->haveLive) {
            projectPresPx(E->liveU - selfU, E->liveV - selfV,
                          selfScrX, selfScrY, pxp, pyp, &E->scrX, &E->scrY);
            projectPresPx(E->iU - selfIU, E->iV - selfIV,
                          selfScrX, selfScrY, pxp, pyp, &E->iScrX, &E->iScrY);
            E->haveScr = 1; E->haveIscr = 1; E->scrSrc = "pres";
        } else {
            projectCell((float)E->cx - (float)px, (float)E->cy - (float)py,
                        selfScrX, selfScrY, pxp, pyp, &E->scrX, &E->scrY);
            E->iScrX = E->scrX; E->iScrY = E->scrY;
            E->haveScr = 1; E->haveIscr = 0; E->scrSrc = "cell";
        }
    }

    outf(out,
        "{\"t_ms\":%lu,\"client_w\":%d,\"client_h\":%d,"
        "\"player\":{\"x\":%u,\"y\":%u,\"hp\":%u,\"max_hp\":%u,\"mp\":%u,\"max_mp\":%u,\"lv\":%u},"
        "\"entities\":[",
        (unsigned long)(GetTickCount() - t0), W, H,
        px, py, hp, maxhp, mp, maxmp, lv);

    for (int i = 0; i < n; i++) {
        Ent* E = &ents[i];
        if (i) outc(out, ',');
        outf(out,
            "{\"ent\":\"0x%llX\",\"vft\":\"0x%X\",\"class\":",
            (unsigned long long)E->ent, E->vft);
        jsonEscape(out, classOf(E->vft));
        outf(out, ",\"name\":");
        jsonEscape(out, E->name);
        outf(out, ",\"species\":%u", E->species);
        if (E->haveQty) outf(out, ",\"qty\":%u", E->qty);
        outf(out, ",\"world\":{\"cx\":%d,\"cy\":%d}", E->cx, E->cy);
        if (E->haveScr)
            outf(out, ",\"screen\":{\"x\":%.2f,\"y\":%.2f,\"src\":\"%s\"}",
                E->scrX, E->scrY, E->scrSrc);
        else
            outf(out, ",\"screen\":null");
        if (E->haveIscr)
            outf(out, ",\"iscr\":{\"x\":%.2f,\"y\":%.2f}", E->iScrX, E->iScrY);
        outc(out, '}');
    }
    outf(out, "]}\n");
    if (out->file) fflush(out->file);
    if (out->buf && out->len >= 0 && out->len < out->cap) out->buf[out->len] = 0;
}

static int g_attached = 0;
static int g_cfgLoaded = 0;

static void detach(void) {
    if (g_attached) SignedClose();
    g_attached = 0;
    g_pid = 0;
    resetTracks();
}

static int ensureAttached(const char* cfgPath) {
    if (!g_cfgLoaded) {
        if (!cfgPath || !cfgPath[0]) cfgPath = "settings_print_state.json";
        loadSettings(cfgPath);
        g_cfgLoaded = 1;
    }
    wchar_t wname[64];
    MultiByteToWideChar(CP_UTF8, 0, g_procName, -1, wname, 64);
    DWORD pid = findPid(wname);
    if (!pid) { detach(); return 0; }
    if (g_attached && pid == g_pid) return 1;
    detach();
    if (!SignedOpen()) return 0;
    g_pid = pid;
    if (!getModule(&g_base, &g_modSize)) { SignedClose(); g_pid = 0; return 0; }
    SignedSetTarget(g_pid);
    g_attached = 1;
    return 1;
}

/* One snapshot: fast PRES_B poll; roster refreshes about every SLOW_MS.
   Loaded by the bot process. This is not injected into LC.exe.
   Returns JSON bytes, or <0 on failure. */
__declspec(dllexport) int print_state_snapshot(const char* cfgPath, char* out, int outCap) {
    if (!out || outCap < 8) return -1;
    if (!ensureAttached(cfgPath)) return -1;
    HWND gwnd = findLCWnd(g_pid);
    int W = 0, H = 0;
    resolveClientSize(gwnd, &W, &H);
    uint32_t px = rd(g_base + g_offPlayerX);
    uint32_t py = rd(g_base + g_offPlayerY);
    uint32_t hp = rd(g_base + g_offPlayerHp);
    uint32_t maxhp = rd(g_base + g_offPlayerMaxHp);
    uint32_t mp = rd(g_base + g_offPlayerMp);
    uint32_t maxmp = rd(g_base + g_offPlayerMaxMp);
    uint32_t lv = rd(g_base + g_offPlayerLv);
    int n = tickTracks((int32_t)px, (int32_t)py);
    Out wrapped; memset(&wrapped, 0, sizeof(wrapped));
    wrapped.buf = out;
    wrapped.cap = outCap;
    emitState(&wrapped, GetTickCount(), W, H, g_ents, n, px, py, hp, maxhp, mp, maxmp, lv);
    if (wrapped.overflow) return -2;
    return wrapped.len;
}

__declspec(dllexport) void print_state_shutdown(void) { detach(); }

#ifndef PRINT_STATE_DLL
int main(int argc, char** argv) {
    const char* cfgPath = "settings_print_state.json";
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--once")) g_once = 1;
        else if (argv[i][0] != '-') cfgPath = argv[i];
    }
    loadSettings(cfgPath);
    /* CLI --once overrides json after load if passed */
    for (int i = 1; i < argc; i++) if (!strcmp(argv[i], "--once")) g_once = 1;

    wchar_t wname[64];
    MultiByteToWideChar(CP_UTF8, 0, g_procName, -1, wname, 64);

    if (!SignedOpen()) { fprintf(stderr, "SignedOpen FAIL\n"); return 1; }
    g_pid = findPid(wname);
    if (!g_pid || !getModule(&g_base, &g_modSize)) {
        fprintf(stderr, "attach FAIL (process=%s)\n", g_procName);
        SignedClose(); return 1;
    }
    SignedSetTarget(g_pid);
    fprintf(stderr, "pid=%lu base=0x%llX interval=%dms once=%d classes=%d\n",
        (unsigned long)g_pid, (unsigned long long)g_base,
        g_intervalMs, g_once, g_cln);

    HWND gwnd = findLCWnd(g_pid);
    FILE* out = stdout;
    DWORD lastRotate = GetTickCount();
    if (g_outPath[0]) {
        out = fopen(g_outPath, "wb"); /* start fresh; rotate clears history */
        if (!out) { fprintf(stderr, "cannot open %s\n", g_outPath); SignedClose(); return 1; }
        fprintf(stderr, "output=%s rotate_ms=%d\n", g_outPath, g_rotateMs);
    }

    DWORD t0 = GetTickCount();
    resetTracks();
    for (;;) {
        /* Periodically wipe prior JSONL history so the file stays bounded. */
        if (g_outPath[0] && out != stdout) {
            DWORD now = GetTickCount();
            if (now - lastRotate >= (DWORD)g_rotateMs) {
                fclose(out);
                out = fopen(g_outPath, "wb");
                if (!out) {
                    fprintf(stderr, "rotate reopen FAIL %s\n", g_outPath);
                    SignedClose(); return 1;
                }
                lastRotate = now;
                fprintf(stderr, "[+%lus] output rotated (history cleared)\n",
                    (unsigned long)((now - t0) / 1000));
            }
        }

        int W = 0, H = 0;
        resolveClientSize(gwnd, &W, &H);

        uint32_t px = rd(g_base + g_offPlayerX);
        uint32_t py = rd(g_base + g_offPlayerY);
        uint32_t hp = rd(g_base + g_offPlayerHp);
        uint32_t maxhp = rd(g_base + g_offPlayerMaxHp);
        uint32_t mp = rd(g_base + g_offPlayerMp);
        uint32_t maxmp = rd(g_base + g_offPlayerMaxMp);
        uint32_t lv = rd(g_base + g_offPlayerLv);

        int n = tickTracks((int32_t)px, (int32_t)py);
        Out wrapped; memset(&wrapped, 0, sizeof(wrapped)); wrapped.file = out;
        emitState(&wrapped, t0, W, H, g_ents, n, px, py, hp, maxhp, mp, maxmp, lv);

        if (g_once) break;
        Sleep((DWORD)g_intervalMs);
    }

    if (out != stdout) fclose(out);
    SignedClose();
    return 0;
}
#endif
