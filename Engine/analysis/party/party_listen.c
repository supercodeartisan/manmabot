/* party_listen.c — in-process party reader.
 * Fixed chain only (registry SEC-17). No graph BFS.
 *   PartySubsystem = lc_subsGet(PARTY_VFT_SUBS)
 *   subs+REF → +HOP1 → +HOP2 = Party
 *   Q(Party-CTRL) == base+PARTY_VFT_RC
 * Leader is the member whose name matches Party+PARTY_LEADER_NAME.
 * Export: party_listen_snapshot / party_listen_shutdown
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include <stdarg.h>
#include "lcreg.h"
#include "lcore.h"

static int g_ready = 0;
static int g_anchored = 0;
static DWORD g_retry_at = 0;
static uint64_t g_party = 0;
static char g_regPath[MAX_PATH * 2] = {0};

static uint32_t P_VFT_SUBS, P_VFT_RC, P_VFT_RC_PLAYER;
static uint32_t P_REF, P_HOP1, P_HOP2, P_CTRL;
static uint32_t P_LEADER_NAME, P_LEADER_LVL;
static uint32_t P_VEC_BEG, P_VEC_END, P_COUNT, P_MAX;
static uint32_t P_NAME, P_GUID, P_LEVEL, P_CLASS, P_HP, P_MP, P_MAP, P_X, P_Y, P_LEVEL2;

static void load_offs(void) {
    P_VFT_SUBS = lcreg_u32("PARTY_VFT_SUBS", 0x1228B10u);
    P_VFT_RC = lcreg_u32("PARTY_VFT_RC", 0x1228A58u);
    P_VFT_RC_PLAYER = lcreg_u32("PARTY_VFT_RC_PLAYER", 0x1228A30u);
    P_REF = lcreg_u32("PARTY_REF_OFF", 0x4A0u);
    P_HOP1 = lcreg_u32("PARTY_HOP1_OFF", 0x00u);
    P_HOP2 = lcreg_u32("PARTY_HOP2_OFF", 0x28u);
    P_CTRL = lcreg_u32("PARTY_HOP_CTRL", 0x10u);
    P_LEADER_NAME = lcreg_u32("PARTY_LEADER_NAME", 0x08u);
    P_LEADER_LVL = lcreg_u32("PARTY_LEADER_LVL", 0x28u);
    P_VEC_BEG = lcreg_u32("PARTY_VEC_BEG", 0x30u);
    P_VEC_END = lcreg_u32("PARTY_VEC_END", 0x38u);
    P_COUNT = lcreg_u32("PARTY_MEMBER_COUNT", 0x48u);
    P_MAX = lcreg_u32("PARTY_MAX_MEMBERS", 8u);
    if (P_MAX < 1 || P_MAX > 8) P_MAX = 8;
    P_NAME = lcreg_u32("PM_NAME", 0x08u);
    P_GUID = lcreg_u32("PM_GUID", 0x28u);
    P_LEVEL = lcreg_u32("PM_LEVEL", 0x50u);
    P_CLASS = lcreg_u32("PM_CLASS", 0x58u);
    P_HP = lcreg_u32("PM_HP", 0x64u);
    P_MP = lcreg_u32("PM_MP", 0x68u);
    P_MAP = lcreg_u32("PM_MAPID", 0x6Cu);
    P_X = lcreg_u32("PM_X", 0x70u);
    P_Y = lcreg_u32("PM_Y", 0x74u);
    P_LEVEL2 = lcreg_u32("PM_LEVEL2", 0x90u);
}

static int jadd(char* out, int cap, int used, const char* fmt, ...) {
    va_list ap;
    int n;
    if (used < 0 || used >= cap) return -1;
    va_start(ap, fmt);
    n = vsnprintf(out + used, (size_t)(cap - used), fmt, ap);
    va_end(ap);
    if (n < 0 || used + n >= cap) return -1;
    return used + n;
}

static void json_esc(const char* in, char* out, int cap) {
    int o = 0;
    if (!in) { out[0] = 0; return; }
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

/* MSVC x64 std::string. Inline when capacity < 16. `obj` is 0x20 bytes. */
static int sso_copy(const uint8_t* obj, char* out, int cap) {
    uint64_t sz, scap, ptr;
    if (!obj || cap < 2) { if (out && cap > 0) out[0] = 0; return 0; }
    sz = *(const uint64_t*)(obj + 0x10);
    scap = *(const uint64_t*)(obj + 0x18);
    if (sz == 0 || sz > 96 || scap > 0x100000) { out[0] = 0; return 0; }
    if ((int)sz >= cap) sz = (uint64_t)(cap - 1);
    if (scap < 0x10) {
        memcpy(out, obj, (size_t)sz);
        out[sz] = 0;
        return 1;
    }
    ptr = *(const uint64_t*)obj;
    if (!isHeap(ptr) || !rm(ptr, out, (uint32_t)sz)) { out[0] = 0; return 0; }
    out[sz] = 0;
    return 1;
}

static int u32_at(const uint8_t* b, uint32_t off, uint32_t len, uint32_t* out) {
    if (off + 4 > len) return 0;
    *out = *(const uint32_t*)(b + off);
    return 1;
}

static int i32_at(const uint8_t* b, uint32_t off, uint32_t len, int32_t* out) {
    if (off + 4 > len) return 0;
    *out = *(const int32_t*)(b + off);
    return 1;
}

static int u64_at(const uint8_t* b, uint32_t off, uint32_t len, uint64_t* out) {
    if (off + 8 > len) return 0;
    *out = *(const uint64_t*)(b + off);
    return 1;
}

static int party_vft_ok(uint64_t party) {
    uint64_t v;
    if (!isHeap(party) || party < P_CTRL) return 0;
    v = q64(party - P_CTRL);
    return v == g_base + (uint64_t)P_VFT_RC;
}

/* 1 when PartySubsystem resolved on the last read (vft right, party or not). */
static int g_subs_ok = 0;

static uint64_t resolve_party(void) {
    uint64_t psub, a, b, party;
    psub = lc_subsGet(P_VFT_SUBS);
    g_subs_ok = isHeap(psub) ? 1 : 0;
    if (!g_subs_ok) return 0;
    a = q64(psub + P_REF);
    if (!isHeap(a)) return 0;
    b = q64(a + P_HOP1);
    if (!isHeap(b)) return 0;
    party = q64(b + P_HOP2);
    if (!party_vft_ok(party)) return 0;
    return party;
}

static int ensure(const char* registryPath) {
    DWORD now = GetTickCount();
    if (g_retry_at && (int)(now - g_retry_at) < 0 && !g_ready) return 0;
    if (!g_ready || (registryPath && registryPath[0] && strcmp(g_regPath, registryPath) != 0)) {
        const char* reg = (registryPath && registryPath[0]) ? registryPath : "registry/LC930_REGISTRY.txt";
        strncpy(g_regPath, reg, sizeof(g_regPath) - 1);
        g_regPath[sizeof(g_regPath) - 1] = 0;
        lcreg_load(g_regPath);
        lc_reg_apply();
        load_offs();
        g_anchored = 0;
        g_party = 0;
        g_ready = 1;
    }
    if (lc_attach()) {
        g_ready = 0;
        g_anchored = 0;
        g_party = 0;
        g_pid = 0;
        g_base = 0;
        g_retry_at = GetTickCount() + 2000;
        return 0;
    }
    g_retry_at = 0;
    if (!g_anchored) {
        if (!lc_anchor()) return 0;
        g_anchored = 1;
    }
    return 1;
}

static int names_eq(const char* a, const char* b) {
    if (!a || !b || !a[0] || !b[0]) return 0;
    return strcmp(a, b) == 0;
}

static int write_party_json(char* out, int cap) {
    uint8_t hdr[0x60];
    char leader[128], esc[160];
    uint64_t beg = 0, end = 0;
    uint32_t headerCount = 0, headerLvl = 0;
    int n = 0, used, first = 1, leaderIdx = -1;
    unsigned long long io0;
    typedef struct {
        char name[96];
        uint64_t guid;
        uint32_t cls, hp, mp, mapId, level, level2;
        int32_t x, y;
        int isLeader;
    } Mem;
    Mem mem[8];

    memset(hdr, 0, sizeof(hdr));
    leader[0] = 0;
    io0 = g_sd_ioctls;
    if (g_party && !party_vft_ok(g_party)) g_party = 0;
    if (g_party) g_subs_ok = 1;
    else g_party = resolve_party();
    if (!g_party) {
        g_anchored = 0;
        if (lc_anchor()) {
            g_anchored = 1;
            g_party = resolve_party();
        }
    }
    if (g_party && rm(g_party, hdr, sizeof(hdr))) {
        if (P_LEADER_NAME + 0x20 <= sizeof(hdr))
            sso_copy(hdr + P_LEADER_NAME, leader, (int)sizeof(leader));
        u32_at(hdr, P_LEADER_LVL, sizeof(hdr), &headerLvl);
        u64_at(hdr, P_VEC_BEG, sizeof(hdr), &beg);
        u64_at(hdr, P_VEC_END, sizeof(hdr), &end);
        u32_at(hdr, P_COUNT, sizeof(hdr), &headerCount);
        if (isHeap(beg) && end >= beg && ((end - beg) % 0x10ull) == 0)
            n = (int)((end - beg) / 0x10ull);
        if (n < 0 || n > (int)P_MAX) n = 0;
    } else {
        g_party = 0;
        n = 0;
    }

    for (int i = 0; i < n; i++) {
        uint8_t slot[16], body[0xA0];
        uint64_t ptr = 0, rep = 0, vft = 0;
        Mem* m = &mem[i];
        memset(m, 0, sizeof(*m));
        memset(slot, 0, sizeof(slot));
        if (!rm(beg + (uint64_t)i * 0x10ull, slot, sizeof(slot))) continue;
        ptr = *(uint64_t*)slot;
        rep = *(uint64_t*)(slot + 8);
        if (!isHeap(ptr) || !isHeap(rep)) continue;
        vft = q64(rep);
        if (vft != g_base + (uint64_t)P_VFT_RC_PLAYER) continue;
        memset(body, 0, sizeof(body));
        if (!rm(ptr, body, sizeof(body))) continue;
        if (P_NAME + 0x20 <= sizeof(body))
            sso_copy(body + P_NAME, m->name, (int)sizeof(m->name));
        u64_at(body, P_GUID, sizeof(body), &m->guid);
        u32_at(body, P_LEVEL, sizeof(body), &m->level);
        u32_at(body, P_LEVEL2, sizeof(body), &m->level2);
        u32_at(body, P_CLASS, sizeof(body), &m->cls);
        u32_at(body, P_HP, sizeof(body), &m->hp);
        u32_at(body, P_MP, sizeof(body), &m->mp);
        u32_at(body, P_MAP, sizeof(body), &m->mapId);
        i32_at(body, P_X, sizeof(body), &m->x);
        i32_at(body, P_Y, sizeof(body), &m->y);
        m->isLeader = names_eq(m->name, leader);
        if (m->isLeader && leaderIdx < 0) leaderIdx = i;
    }

    used = jadd(out, cap, 0,
        "{\"cmd\":\"party\",\"subs_ok\":%s,\"in_party\":%s,\"count\":%d,\"header_count\":%u,"
        "\"leader_name\":\"",
        g_subs_ok ? "true" : "false", n > 0 ? "true" : "false", n, headerCount);
    json_esc(leader, esc, (int)sizeof(esc));
    used = jadd(out, cap, used, "%s\",\"leader\":", esc);
    if (leaderIdx >= 0) {
        Mem* m = &mem[leaderIdx];
        uint32_t lvl = m->level ? m->level : (m->level2 ? m->level2 : headerLvl);
        json_esc(m->name, esc, (int)sizeof(esc));
        used = jadd(out, cap, used,
            "{\"name\":\"%s\",\"guid\":\"%llX\",\"cls\":%u,\"hp\":%u,\"mp\":%u,"
            "\"x\":%d,\"y\":%d,\"map_id\":%u,\"level\":%u}",
            esc, (unsigned long long)m->guid, m->cls, m->hp, m->mp,
            m->x, m->y, m->mapId, lvl);
    } else {
        used = jadd(out, cap, used, "null");
    }
    used = jadd(out, cap, used, ",\"members\":[");
    for (int i = 0; i < n; i++) {
        Mem* m = &mem[i];
        uint32_t lvl;
        if (!m->name[0] && !m->guid) continue;
        lvl = m->level ? m->level : m->level2;
        json_esc(m->name, esc, (int)sizeof(esc));
        used = jadd(out, cap, used,
            "%s{\"name\":\"%s\",\"guid\":\"%llX\",\"cls\":%u,\"hp\":%u,\"mp\":%u,"
            "\"x\":%d,\"y\":%d,\"map_id\":%u,\"level\":%u,\"is_leader\":%s}",
            first ? "" : ",",
            esc, (unsigned long long)m->guid, m->cls, m->hp, m->mp,
            m->x, m->y, m->mapId, lvl, m->isLeader ? "true" : "false");
        first = 0;
    }
    used = jadd(out, cap, used, "],\"reads\":%llu}",
        (unsigned long long)(g_sd_ioctls - io0));
    return used;
}

__declspec(dllexport) int party_listen_snapshot(const char* registryPath, char* out, int outCap) {
    int n;
    if (!out || outCap < 32) return -1;
    if (!ensure(registryPath)) return -1;
    n = write_party_json(out, outCap);
    if (n < 2) return -2;
    return n;
}

__declspec(dllexport) void party_listen_shutdown(void) {
    SignedClose();
    g_ready = 0;
    g_anchored = 0;
    g_party = 0;
    g_pid = 0;
    g_base = 0;
    g_retry_at = 0;
}

#ifndef PARTY_LISTEN_DLL
int main(int argc, char** argv) {
    char buf[1 << 16];
    const char* reg = argc > 1 ? argv[1] : "registry/LC930_REGISTRY.txt";
    int n;
    SetConsoleOutputCP(CP_UTF8);
    n = party_listen_snapshot(reg, buf, (int)sizeof(buf));
    if (n < 0) {
        fprintf(stderr, "party snapshot fail %d\n", n);
        return 1;
    }
    fwrite(buf, 1, (size_t)n, stdout);
    fputc('\n', stdout);
    party_listen_shutdown();
    return 0;
}
#endif
