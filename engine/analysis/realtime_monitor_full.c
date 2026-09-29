// ============================================================================
// realtime_monitor_full.c - FULL dataset realtime monitor for LC.exe
// ----------------------------------------------------------------------------
// Polls LC.exe every 0.4-0.6s (randomized anti-pattern) and captures ALL
// datasets: player stats (HP/MP/SP/level/class/mapID/pos/EXP/tick), inventory,
// skills, party, buffs, and entities near the player.
//
// Outputs:
//   realtime_full.jsonl   - append JSONL log (one JSON object per frame)
//   realtime_full.txt     - console table (stdout)
//
// Heap structures (buff array + entity list) are located once at startup via
// the same signature scan __OneHelper__.c uses and refreshed periodically.
// ============================================================================
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <io.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include <time.h>
#include "signeddrv_client.h"

// ---------------------------------------------------------------------------
// Tunables
// ---------------------------------------------------------------------------
#define POLL_MS_DEFAULT    500     // fixed interval when no CLI arg given
#define POLL_MS_MIN        50
#define MAX_SKILLS         128
#define MAX_PARTY          8
#define MAX_BUFFS          64
#define MAX_ENTITIES       256
#define ENTITY_DIST        5000    // tiles around player

// Named pipe for --pipe mode. The exe runs elevated on its own; the Python
// program connects to this pipe and exchanges one JSON line per request.
#define PIPE_NAME          L"\\\\.\\pipe\\realtime_monitor"
#define PIPE_IN_BUFSIZE    0x10000

// ---------------------------------------------------------------------------
// Offsets are loaded from offsets.json at startup (module-relative bases and
// player-relative field offsets). Defaults mirror the last confirmed session
// so the tool still works when offsets.json is absent.
// ---------------------------------------------------------------------------
static uint64_t offPlayerBase   = 0x166871CULL;  // PlayerBase (direct=1 => module+off, completed 26.09)
static int      offPlayerDirect = 1;             // PlayerBaseDirect
static uint64_t offPosX         = 0x1668710ULL;  // PosXAbs (module-relative, pb-12)
static uint64_t offPosY         = 0x1668714ULL;  // PosYAbs
static uint64_t offPosZ         = 0x1668718ULL;  // PosZAbs
static uint64_t offTick         = 0x1668708ULL;  // ServerTick (u64 ms, pb-20)
static uint64_t offExpPct       = 0x15A8BC0ULL;  // ExperiencePct64 (live f64, rediscovered 9/16; lag copy +0x10)
static uint64_t offSkills       = 0;             // SkillListBase (stale, zeroed)
static uint64_t offParty        = 0;             // PartyBase (stale, zeroed)
static uint64_t offBuffList     = 0;             // BuffListBase (stale, zeroed)

// Player struct field offsets (module + offPlayerBase + X)
static uint32_t oHp = 0x000, oMaxHp = 0x004, oMp = 0x008, oMaxMp = 0x00C;
static uint32_t oLevel = 0x010, oClass = 0x014, oSp = 0x110;
static uint32_t oMapId = 0x134, oOnline = 0x20, oIsGm = 0x21, oChaotic = 0x22;

// Skill struct (stride oSkillStruct)
static uint32_t oSkillStruct = 0x08, oSkillId = 0x00, oSkillLevel = 0x04;

// Party member struct (stride oPartyStruct)
static uint32_t oPartyStruct = 0x18, oPartyName = 0x00, oPartyLevel = 0x10,
    oPartyClass = 0x14, oPartyHp = 0x18, oPartyMaxHp = 0x1C;

// Buff array: 11 slots x 0x90 (indices 8-18), tagged data ptr at +0x50
#define BUFF_SLOTS      11
static uint32_t oBuffStruct = 0x90, oBuffDataPtr = 0x50;
static uint32_t oBuffId = 0x178, oBuffRemain = 0x088, oBuffMaxDur = 0x084, oBuffStacks = 0x17C;

// Entity struct (heap)
static uint32_t oEntId = 0x00, oEntHp = 0x04, oEntMaxHp = 0x08, oEntLevel = 0x0C,
    oEntClass = 0x10, oEntPosX = 0x14, oEntPosY = 0x18, oEntPosZ = 0x1C;

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
static DWORD    g_pid = 0;
static uint64_t g_base = 0;
static uint32_t g_modSize = 0;
static uint64_t g_buffArray = 0;
static int      g_pollMs = POLL_MS_DEFAULT;
static int      g_maxFrames = 0;
static int      g_showEnts = 1;          /* print entity list each frame (--no-ents disables) */
static int      g_entRadius = 0;         /* --radius <n>: only show entities within distance n (0 = all) */
static int      g_serveMode = 0;         // --serve: JSON line protocol on stdin/stdout
static int      g_pipeMode = 0;          // --pipe: named-pipe server (\\.\pipe\realtime_monitor)
static int      g_extraOk = 0;           // extra offsets loaded from JSON

// Route diagnostics to stderr in serve mode so stdout carries only protocol
// lines (one JSON object per line, ready for a line-based Python reader).
#define LOG(fmt, ...) do { \
    if (g_serveMode) fprintf(stderr, fmt, ##__VA_ARGS__); \
    else printf(fmt, ##__VA_ARGS__); \
} while (0)
static int32_t  g_offLawful = -1, g_offWeight = -1, g_offFood = -1, g_offMaxWeight = -1;
static int32_t  g_offStats[6] = { -1,-1,-1,-1,-1,-1 }; // STR,DEX,CON,INT,WIS,CHA

/* CharacterDataSubsystem registry (char_offsets.txt). 26.09.23b defaults. */
static uint32_t g_chMgr = 0x1668860u, g_chCdVft = 0x11852A0u, g_chCdOff = 0x498u;
static uint32_t g_chVftStatus = 0x11852F0u;
static uint32_t g_chKXor = 0x2f8b1064u, g_chKMul = 0x7f4a7c15u;
static uint32_t g_chHolder = 0xD0u, g_chSubBeg = 0x180u, g_chSubEnd = 0x188u;
static uint32_t g_chStr = 0x128u, g_chInt = 0x134u, g_chCon = 0x140u;
static uint32_t g_chDex = 0x14Cu, g_chWis = 0x158u, g_chCha = 0x164u;
static uint32_t g_chLevel = 0x248u, g_chHp = 0x2C4u, g_chMp = 0x2D0u, g_chMaxMp = 0x2DCu;
static uint32_t g_chFood = 0x2F4u, g_chWeight = 0x300u, g_chWeightCur = 0x3ACu, g_chWeightMax = 0x3B0u;
static uint32_t g_chLawful = 0x30Cu, g_chAc = 0x348u;
static uint32_t g_stBlock = 0x1668700u, g_stX = 0x10u, g_stY = 0x14u;
static uint32_t g_stHp = 0x1Cu, g_stMaxHp = 0x20u, g_stMp = 0x24u, g_stMaxMp = 0x28u, g_stLevel = 0x2Cu;
static int g_charOk = 0;

// ---------------------------------------------------------------------------
// Low-level helpers
// ---------------------------------------------------------------------------
static DWORD findPid(const wchar_t* name) {
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    if (snap == INVALID_HANDLE_VALUE) return 0;
    PROCESSENTRY32W pe; pe.dwSize = sizeof(pe);
    DWORD pid = 0;
    if (Process32FirstW(snap, &pe)) do {
        if (_wcsicmp(pe.szExeFile, name) == 0) { pid = pe.th32ProcessID; break; }
    } while (Process32NextW(snap, &pe));
    CloseHandle(snap);
    return pid;
}

static BOOL readMem(uint64_t addr, void* buf, uint32_t size) {
    uint32_t br = 0;
    return SignedReadMemory(g_pid, addr, buf, size, &br) && br == size;
}

static int getModuleBase(uint64_t* base) {
    uint64_t peb = 0, ldr = 0, listHead = 0, cur = 0;
    if (!SignedGetPeb(g_pid, &peb) || !peb) return 0;
    if (!readMem(peb + 0x18, &ldr, 8) || !ldr) return 0;
    if (!readMem(ldr + 0x20, &listHead, 8) || !listHead) return 0;
    cur = listHead;
    for (int guard = 0; guard < 5000 && cur && cur != (ldr + 0x20); guard++) {
        uint64_t entry = cur - 0x10;
        uint64_t dllBase = 0;
        uint32_t dllSize = 0;
        if (readMem(entry + 0x30, &dllBase, 8) && dllBase) {
            readMem(entry + 0x40, &dllSize, 4);
            *base = dllBase;
            if (dllSize) g_modSize = dllSize;
            return 1;
        }
        if (!readMem(cur, &cur, 8)) return 0;
    }
    return 0;
}
static uint32_t rd32(uint64_t a) { uint32_t v = 0; readMem(a, &v, 4); return v; }
static uint64_t rd64(uint64_t a) { uint64_t v = 0; readMem(a, &v, 8); return v; }
static int chIsMod(uint64_t a) {
    if (!g_base || !a) return 0;
    if (g_modSize) return a >= g_base && a < g_base + g_modSize;
    return a >= g_base && a - g_base < 0x4000000ULL;
}
static uint32_t chVrva(uint64_t o) {
    uint64_t v = rd64(o);
    return chIsMod(v) ? (uint32_t)(v - g_base) : 0;
}

// Directory of the offsets file. The exe still defaults to the working
// directory; the DLL passes an absolute offsets.json path.
static char g_dataDir[MAX_PATH] = "";

static void rememberDataDir(const char* path) {
    char* cut;
    char* cut2;
    if (!path || !path[0]) { g_dataDir[0] = 0; return; }
    strncpy(g_dataDir, path, MAX_PATH - 1);
    g_dataDir[MAX_PATH - 1] = 0;
    cut = strrchr(g_dataDir, '\\');
    cut2 = strrchr(g_dataDir, '/');
    if (cut2 > cut) cut = cut2;
    if (cut && cut != g_dataDir) *cut = 0;
    else g_dataDir[0] = 0;
}

static void pathInDataDir(char* dest, size_t cap, const char* name) {
    if (g_dataDir[0]) snprintf(dest, cap, "%s\\%s", g_dataDir, name);
    else snprintf(dest, cap, "%s", name);
}

// Load optional extra offsets from offsets_discovered.json (hand-curatable).
// Only fills fields that were NOT already resolved from offsets.json.
static void loadExtraOffsets(void) {
    char path[MAX_PATH];
    pathInDataDir(path, sizeof(path), "offsets_discovered.json");
    FILE* f = fopen(path, "r");
    if (f) {
        char line[512];
        while (fgets(line, sizeof(line), f)) {
            int32_t v = -1;
            if (sscanf(line, "  \"lawful\": %d", &v) == 1 && v >= 0 && g_offLawful < 0) g_offLawful = v;
            else if (sscanf(line, "  \"weight\": %d", &v) == 1 && v >= 0 && g_offWeight < 0) g_offWeight = v;
            else if (sscanf(line, "  \"maxWeight\": %d", &v) == 1 && v >= 0 && g_offMaxWeight < 0) g_offMaxWeight = v;
            else if (sscanf(line, "  \"food\": %d", &v) == 1 && v >= 0 && g_offFood < 0) g_offFood = v;
            else if (sscanf(line, "  \"str\": %d", &v) == 1 && v >= 0 && g_offStats[0] < 0) g_offStats[0] = v;
            else if (sscanf(line, "  \"dex\": %d", &v) == 1 && v >= 0 && g_offStats[1] < 0) g_offStats[1] = v;
            else if (sscanf(line, "  \"con\": %d", &v) == 1 && v >= 0 && g_offStats[2] < 0) g_offStats[2] = v;
            else if (sscanf(line, "  \"int\": %d", &v) == 1 && v >= 0 && g_offStats[3] < 0) g_offStats[3] = v;
            else if (sscanf(line, "  \"wis\": %d", &v) == 1 && v >= 0 && g_offStats[4] < 0) g_offStats[4] = v;
            else if (sscanf(line, "  \"cha\": %d", &v) == 1 && v >= 0 && g_offStats[5] < 0) g_offStats[5] = v;
        }
        fclose(f);
    }
    g_extraOk = g_offLawful >= 0 || g_offWeight >= 0 || g_offFood >= 0 || g_offMaxWeight >= 0 ||
        g_offStats[0] >= 0 || g_offStats[1] >= 0 || g_offStats[2] >= 0 ||
        g_offStats[3] >= 0 || g_offStats[4] >= 0 || g_offStats[5] >= 0;
}

// Match a "  \"key\": <decimal>" line and return the integer value, else -1.
static long long jsonNum(const char* line, const char* key) {
    char k[64];
    long long v = 0;
    if (sscanf(line, "  \"%63[^\"]\": %lld", k, &v) == 2 && strcmp(k, key) == 0) return v;
    return -1;
}

// String-valued JSON numbers ("0x..." or decimal); presence-based variant
// so explicit "0" can override defaults (needed to disable HeapLo/Hi).
static int jsonU64Key(const char* line, const char* key, uint64_t* out) {
    char k[64], vstr[64];
    if (sscanf(line, "  \"%63[^\"]\": \"%63[^\"]\"", k, vstr) == 2 && strcmp(k, key) == 0) {
        *out = strtoull(vstr, NULL, 0);
        return 1;
    }
    return 0;
}

// String-valued JSON numbers ("0x..." or decimal), for RVA/range keys.
static uint64_t jsonU64(const char* line, const char* key) {
    uint64_t h = 0;
    if (jsonU64Key(line, key, &h)) return h;
    long long v = jsonNum(line, key);
    return (v > 0) ? (uint64_t)v : 0;
}

// Forward decls: discovery ranges + entity vftables (defined below).
static uint64_t g_heapLo, g_heapHi, g_validPtrLo, g_validPtrHi;
static uint64_t g_entCompVftRva, g_entActorVftRva, g_entMonsterVftRva, g_entPlayerVftRva;
static uint64_t g_ctrlSegmentProp, g_ctrlBuffNpc, g_ctrlMonster, g_ctrlSummonMon,
    g_ctrlPet, g_ctrlMyPlayer, g_ctrlPlayer, g_ctrlNpc;

// Load all module/field offsets from offsets.json (plain decimal integers).
// Base pointers (module-relative) are only applied when non-zero; field
// offsets and struct strides apply even when zero.
static void loadOffsets(const char* path) {
    if (!path || !path[0]) path = "offsets.json";
    rememberDataDir(path);
    FILE* f = fopen(path, "r");
    if (!f) return;
    char line[512];
    long long v;
    while (fgets(line, sizeof(line), f)) {
        if ((v = jsonNum(line, "PlayerBase")) > 0)          offPlayerBase = (uint64_t)v;
        if ((v = jsonNum(line, "PlayerBaseDirect")) >= 0)   offPlayerDirect = (int)v;
        if ((v = jsonNum(line, "PosXAbs")) > 0)             offPosX = (uint64_t)v;
        if ((v = jsonNum(line, "PosYAbs")) > 0)             offPosY = (uint64_t)v;
        if ((v = jsonNum(line, "PosZAbs")) > 0)             offPosZ = (uint64_t)v;
        if ((v = jsonNum(line, "ServerTick")) > 0)          offTick = (uint64_t)v;
        if ((v = jsonNum(line, "ExperiencePct64")) > 0)     offExpPct = (uint64_t)v;
        if ((v = jsonNum(line, "SkillListBase")) > 0)       offSkills = (uint64_t)v;
        if ((v = jsonNum(line, "PartyBase")) > 0)           offParty = (uint64_t)v;
        if ((v = jsonNum(line, "BuffListBase")) > 0)        offBuffList = (uint64_t)v;

        if ((v = jsonNum(line, "Hp")) >= 0)          oHp = (uint32_t)v;
        if ((v = jsonNum(line, "MaxHp")) >= 0)       oMaxHp = (uint32_t)v;
        if ((v = jsonNum(line, "Mp")) >= 0)          oMp = (uint32_t)v;
        if ((v = jsonNum(line, "MaxMp")) >= 0)       oMaxMp = (uint32_t)v;
        if ((v = jsonNum(line, "Sp")) >= 0)          oSp = (uint32_t)v;
        if ((v = jsonNum(line, "Level")) >= 0)       oLevel = (uint32_t)v;
        if ((v = jsonNum(line, "ClassId")) >= 0)     oClass = (uint32_t)v;
        if ((v = jsonNum(line, "MapId")) >= 0)       oMapId = (uint32_t)v;
        if ((v = jsonNum(line, "IsOnline")) >= 0)    oOnline = (uint32_t)v;
        if ((v = jsonNum(line, "IsGM")) >= 0)        oIsGm = (uint32_t)v;
        if ((v = jsonNum(line, "IsChaotic")) >= 0)   oChaotic = (uint32_t)v;

        if ((v = jsonNum(line, "SkillStructSize")) > 0) oSkillStruct = (uint32_t)v;
        if ((v = jsonNum(line, "SkillId")) >= 0)    oSkillId = (uint32_t)v;
        if ((v = jsonNum(line, "SkillLevel")) >= 0) oSkillLevel = (uint32_t)v;

        if ((v = jsonNum(line, "PartyStructSize")) > 0) oPartyStruct = (uint32_t)v;
        if ((v = jsonNum(line, "PartyName")) >= 0)  oPartyName = (uint32_t)v;
        if ((v = jsonNum(line, "PartyLevel")) >= 0) oPartyLevel = (uint32_t)v;
        if ((v = jsonNum(line, "PartyClassId")) >= 0) oPartyClass = (uint32_t)v;
        if ((v = jsonNum(line, "PartyHp")) >= 0)    oPartyHp = (uint32_t)v;
        if ((v = jsonNum(line, "PartyMaxHp")) >= 0) oPartyMaxHp = (uint32_t)v;

        if ((v = jsonNum(line, "BuffStructSize")) > 0) oBuffStruct = (uint32_t)v;
        if ((v = jsonNum(line, "BuffId")) >= 0)     oBuffId = (uint32_t)v;
        if ((v = jsonNum(line, "BuffDurationLeft")) >= 0) oBuffRemain = (uint32_t)v;
        if ((v = jsonNum(line, "BuffMaxDuration")) >= 0) oBuffMaxDur = (uint32_t)v;
        if ((v = jsonNum(line, "BuffStacks")) >= 0) oBuffStacks = (uint32_t)v;

        if ((v = jsonNum(line, "EntityId")) >= 0)   oEntId = (uint32_t)v;
        if ((v = jsonNum(line, "EntityHp")) >= 0)   oEntHp = (uint32_t)v;
        if ((v = jsonNum(line, "EntityMaxHp")) >= 0) oEntMaxHp = (uint32_t)v;
        if ((v = jsonNum(line, "EntityLevel")) >= 0) oEntLevel = (uint32_t)v;
        if ((v = jsonNum(line, "EntityTypeId")) >= 0) oEntClass = (uint32_t)v;
        if ((v = jsonNum(line, "EntityPosX")) >= 0) oEntPosX = (uint32_t)v;
        if ((v = jsonNum(line, "EntityPosY")) >= 0) oEntPosY = (uint32_t)v;
        if ((v = jsonNum(line, "EntityPosZ")) >= 0) oEntPosZ = (uint32_t)v;

        {
            uint64_t h;
            if (jsonU64Key(line, "HeapLo", &h)) g_heapLo = h;            // "0" = disabled -> coarse map
            if (jsonU64Key(line, "HeapHi", &h)) g_heapHi = h;
            if ((h = jsonU64(line, "ValidPtrLo")) > 0) g_validPtrLo = h;
            if ((h = jsonU64(line, "ValidPtrHi")) > 0) g_validPtrHi = h;
            if ((h = jsonU64(line, "EntCompVftRva")) > 0)          g_entCompVftRva = h;
            if ((h = jsonU64(line, "EntActorVftRva")) > 0)         g_entActorVftRva = h;
            if ((h = jsonU64(line, "EntMonsterVftRva")) > 0)       g_entMonsterVftRva = h;
            if ((h = jsonU64(line, "EntPlayerVftRva")) > 0)        g_entPlayerVftRva = h;
            if ((h = jsonU64(line, "EntCtrlSegmentPropRva")) > 0)  g_ctrlSegmentProp = h;
            if ((h = jsonU64(line, "EntCtrlBuffNpcRva")) > 0)      g_ctrlBuffNpc = h;
            if ((h = jsonU64(line, "EntCtrlMonsterRva")) > 0)      g_ctrlMonster = h;
            if ((h = jsonU64(line, "EntCtrlSummonedMonsterRva")) > 0) g_ctrlSummonMon = h;
            if ((h = jsonU64(line, "EntCtrlPetRva")) > 0)          g_ctrlPet = h;
            if ((h = jsonU64(line, "EntCtrlMyPlayerRva")) > 0)     g_ctrlMyPlayer = h;
            if ((h = jsonU64(line, "EntCtrlPlayerRva")) > 0)       g_ctrlPlayer = h;
            if ((h = jsonU64(line, "EntCtrlInteractiveNpcRva")) > 0) g_ctrlNpc = h;
        }

        if ((v = jsonNum(line, "Str")) > 0) g_offStats[0] = (int32_t)v;
        if ((v = jsonNum(line, "Dex")) > 0) g_offStats[1] = (int32_t)v;
        if ((v = jsonNum(line, "Con")) > 0) g_offStats[2] = (int32_t)v;
        if ((v = jsonNum(line, "Int")) > 0) g_offStats[3] = (int32_t)v;
        if ((v = jsonNum(line, "Wis")) > 0) g_offStats[4] = (int32_t)v;
        if ((v = jsonNum(line, "Cha")) > 0) g_offStats[5] = (int32_t)v;
        if ((v = jsonNum(line, "Weight")) > 0) g_offWeight = (int32_t)v;
        if ((v = jsonNum(line, "MaxWeight")) > 0) g_offMaxWeight = (int32_t)v;
        if ((v = jsonNum(line, "Food")) > 0) g_offFood = (int32_t)v;
        if ((v = jsonNum(line, "Lawful")) > 0) g_offLawful = (int32_t)v;
    }
fclose(f);
     g_extraOk = g_offLawful >= 0 || g_offWeight >= 0 || g_offFood >= 0 || g_offMaxWeight >= 0 ||
         g_offStats[0] >= 0 || g_offStats[1] >= 0 || g_offStats[2] >= 0 ||
         g_offStats[3] >= 0 || g_offStats[4] >= 0 || g_offStats[5] >= 0;
 }

static void loadCharOffsets(const char* path) {
    FILE* f;
    char line[128];
    if (!path || !path[0]) {
        char buf[MAX_PATH];
        pathInDataDir(buf, sizeof(buf), "char_offsets.txt");
        path = buf;
        f = fopen(path, "r");
    } else {
        f = fopen(path, "r");
    }
    if (!f) return;
    while (fgets(line, sizeof(line), f)) {
        char k[64];
        unsigned v = 0;
        if (sscanf(line, "%63[^= \t]=%x", k, &v) != 2) continue;
        if (!strcmp(k, "MGR")) g_chMgr = v;
        else if (!strcmp(k, "CD_VFT")) g_chCdVft = v;
        else if (!strcmp(k, "CD_OFF")) g_chCdOff = v;
        else if (!strcmp(k, "VFT_STATUS")) g_chVftStatus = v;
        else if (!strcmp(k, "K_XOR")) g_chKXor = v;
        else if (!strcmp(k, "K_MUL")) g_chKMul = v;
        else if (!strcmp(k, "HOLDER_OFF")) g_chHolder = v;
        else if (!strcmp(k, "SUBLIST_BEG")) g_chSubBeg = v;
        else if (!strcmp(k, "SUBLIST_END")) g_chSubEnd = v;
        else if (!strcmp(k, "ST_BLOCK")) g_stBlock = v;
        else if (!strcmp(k, "ST_X")) g_stX = v;
        else if (!strcmp(k, "ST_Y")) g_stY = v;
        else if (!strcmp(k, "ST_HP")) g_stHp = v;
        else if (!strcmp(k, "ST_MAXHP")) g_stMaxHp = v;
        else if (!strcmp(k, "ST_MP")) g_stMp = v;
        else if (!strcmp(k, "ST_MAXMP")) g_stMaxMp = v;
        else if (!strcmp(k, "ST_LEVEL")) g_stLevel = v;
        else if (!strcmp(k, "STR")) g_chStr = v;
        else if (!strcmp(k, "INT")) g_chInt = v;
        else if (!strcmp(k, "CON")) g_chCon = v;
        else if (!strcmp(k, "DEX")) g_chDex = v;
        else if (!strcmp(k, "WIS")) g_chWis = v;
        else if (!strcmp(k, "CHA")) g_chCha = v;
        else if (!strcmp(k, "LEVEL")) g_chLevel = v;
        else if (!strcmp(k, "HP")) g_chHp = v;
        else if (!strcmp(k, "MP")) g_chMp = v;
        else if (!strcmp(k, "MAXMP")) g_chMaxMp = v;
        else if (!strcmp(k, "FOOD")) g_chFood = v;
        else if (!strcmp(k, "WEIGHT")) g_chWeight = v;
        else if (!strcmp(k, "WEIGHT_CUR")) g_chWeightCur = v;
        else if (!strcmp(k, "WEIGHT_MAX")) g_chWeightMax = v;
        else if (!strcmp(k, "LAWFUL")) g_chLawful = v;
        else if (!strcmp(k, "AC")) g_chAc = v;
    }
    fclose(f);
}

static uint32_t decodeAt(uint64_t obj, uint32_t off, int* ok) {
    uint32_t k = rd32(obj + off), b = rd32(obj + off + 4), c = rd32(obj + off + 8);
    uint32_t u8 = b ^ k;
    if (c != ((k + g_chKXor) ^ ~u8)) { if (ok) *ok = 0; return 0; }
    if (ok) *ok = 1;
    return u8 - (k * g_chKMul ^ g_chKXor);
}

static uint64_t findCharDataSubsystem(void) {
    uint64_t mgr, holder, bgn, end, e;
    if (!g_base || !g_chMgr) return 0;
    mgr = rd64(g_base + g_chMgr);
    if (!mgr) return 0;
    holder = rd64(mgr + g_chHolder);
    if (!holder) return 0;
    bgn = rd64(holder + g_chSubBeg);
    end = rd64(holder + g_chSubEnd);
    for (e = bgn; e + 16 <= end; e += 16) {
        uint64_t sub = rd64(e);
        if (sub && chVrva(sub) == g_chCdVft) return sub;
    }
    return 0;
}

static uint64_t anchorStatus(void) {
    uint64_t cd = findCharDataSubsystem();
    uint64_t st;
    if (!cd) return 0;
    st = cd + g_chCdOff;
    if (chVrva(st) == g_chVftStatus) return st;
    return 0;
}
 
// ---------------------------------------------------------------------------
// Datasets
// ---------------------------------------------------------------------------
typedef struct {
    uint32_t hp, maxHp, mp, maxMp, sp, level, classId, mapId, instanceId;
    uint32_t posX, posY, posZ;
    uint64_t tickMs;
    double   expPct;
    uint8_t  online, isGm, isChaotic;
    int      lawfulOk, weightOk, foodOk, maxWeightOk, acOk;
    int32_t  lawful, weight, food, maxWeight, ac;
    int      statsOk[6];
    uint32_t stats[6];
} PlayerData;

typedef struct { uint32_t id, level; } SkillData;
typedef struct { uint32_t level, classId, hp, maxHp; char name[64]; } PartyData;
typedef struct { uint32_t slot, id, stacks; float remain, maxDur; } BuffData;

typedef struct {
    uint64_t addr;
    uint32_t id;
    uint64_t hash;
} EntityRef;

static uint64_t hash5(uint32_t a, uint32_t b, uint32_t c, uint32_t d, uint32_t e) {
    uint64_t h = 1469598103934665603ULL;
    uint32_t v[5] = { a, b, c, d, e };
    for (int i = 0; i < 5; i++) {
        h ^= v[i]; h *= 1099511628211ULL;
    }
    return h;
}

typedef struct {
    uint32_t id, hp, maxHp, level, classId, posX, posY, posZ;
    uint32_t templateId;
    uint32_t targetId;
    float    dist;
    char     name[64];
    char     target[64];
    uint64_t objAddr, compAddr;
} EntityData;

// qsort comparator: entities ordered by distance, nearest first.
static int entDistCmp(const void* pa, const void* pb) {
    float a = ((const EntityData*)pa)->dist;
    float b = ((const EntityData*)pb)->dist;
    return (a > b) - (a < b);
}

// Sort entities by distance (ascending) and drop any beyond g_entRadius.
// Returns the new count. Mutates `ents` in place.
static int finalizeEnts(EntityData* ents, int nEnts) {
    if (nEnts > 1) qsort(ents, (size_t)nEnts, sizeof(EntityData), entDistCmp);
    if (g_entRadius > 0) {
        int w = 0;
        for (int i = 0; i < nEnts; i++)
            if (ents[i].dist <= (float)g_entRadius) ents[w++] = ents[i];
        nEnts = w;
    }
    return nEnts;
}

static uint64_t playerBase(void) {
    uint64_t b = g_base + offPlayerBase;
    if (!offPlayerDirect) readMem(b, &b, 8);   // indirect: module+off holds a pointer
    return b;
}

static void readPlayer(PlayerData* p) {
    memset(p, 0, sizeof(*p));
    uint64_t pb = playerBase();
    readMem(pb + oHp, &p->hp, 4);
    readMem(pb + oMaxHp, &p->maxHp, 4);
    readMem(pb + oMp, &p->mp, 4);
    readMem(pb + oMaxMp, &p->maxMp, 4);
    readMem(pb + oSp, &p->sp, 4);
    readMem(pb + oLevel, &p->level, 4);
    readMem(pb + oClass, &p->classId, 4);
    readMem(oMapId >= 0x400000 ? g_base + oMapId : pb + oMapId, &p->mapId, 4);
    readMem(pb + oOnline, &p->online, 1);
    readMem(pb + oIsGm, &p->isGm, 1);
    readMem(pb + oChaotic, &p->isChaotic, 1);
    p->instanceId = p->mapId;
    readMem(g_base + offPosX, &p->posX, 4);
    readMem(g_base + offPosY, &p->posY, 4);
    readMem(g_base + offPosZ, &p->posZ, 4);
    readMem(g_base + offTick, &p->tickMs, 8);
    readMem(g_base + offExpPct, &p->expPct, 8);
    // Lawful/Weight/MaxWeight/Food from offsets.json are module-relative globals
    // (large offsets >= 0x400000); discovered ones are player-relative (small).
    uint64_t lawfulA = (g_offLawful >= 0) ? (uint64_t)(g_offLawful >= 0x400000 ? g_base + g_offLawful : pb + g_offLawful) : 0;
    uint64_t weightA = (g_offWeight >= 0) ? (uint64_t)(g_offWeight >= 0x400000 ? g_base + g_offWeight : pb + g_offWeight) : 0;
    uint64_t maxWtA  = (g_offMaxWeight >= 0) ? (uint64_t)(g_offMaxWeight >= 0x400000 ? g_base + g_offMaxWeight : pb + g_offMaxWeight) : 0;
    uint64_t foodA   = (g_offFood >= 0) ? (uint64_t)(g_offFood >= 0x400000 ? g_base + g_offFood : pb + g_offFood) : 0;
    if (lawfulA) { p->lawfulOk = 1; readMem(lawfulA, &p->lawful, 4); }
    if (weightA) { p->weightOk = 1; readMem(weightA, &p->weight, 4); }
    if (maxWtA)  { p->maxWeightOk = 1; readMem(maxWtA, &p->maxWeight, 4); }
    if (foodA)   { p->foodOk = 1;   readMem(foodA, &p->food, 4); }
    for (int i = 0; i < 6; i++)
        if (g_offStats[i] >= 0) { p->statsOk[i] = 1; readMem(pb + g_offStats[i], &p->stats[i], 4); }
    {
        uint64_t st = anchorStatus();
        int ok = 0;
        g_charOk = st != 0;
        if (st) {
            uint32_t v;
            v = decodeAt(st, g_chStr, &ok); if (ok) { p->statsOk[0] = 1; p->stats[0] = v; }
            v = decodeAt(st, g_chDex, &ok); if (ok) { p->statsOk[1] = 1; p->stats[1] = v; }
            v = decodeAt(st, g_chCon, &ok); if (ok) { p->statsOk[2] = 1; p->stats[2] = v; }
            v = decodeAt(st, g_chInt, &ok); if (ok) { p->statsOk[3] = 1; p->stats[3] = v; }
            v = decodeAt(st, g_chWis, &ok); if (ok) { p->statsOk[4] = 1; p->stats[4] = v; }
            v = decodeAt(st, g_chCha, &ok); if (ok) { p->statsOk[5] = 1; p->stats[5] = v; }
            v = decodeAt(st, g_chLevel, &ok); if (ok && v) p->level = v;
            v = decodeAt(st, g_chHp, &ok); if (ok && v) p->hp = v;
            v = decodeAt(st, g_chMp, &ok); if (ok) p->mp = v;
            v = decodeAt(st, g_chMaxMp, &ok); if (ok && v) p->maxMp = v;
            v = decodeAt(st, g_chFood, &ok); if (ok) { p->foodOk = 1; p->food = (int32_t)v; }
            v = decodeAt(st, g_chLawful, &ok); if (ok) { p->lawfulOk = 1; p->lawful = (int32_t)v; }
            v = decodeAt(st, g_chAc, &ok); if (ok) { p->acOk = 1; p->ac = (int32_t)v; }
            p->weight = (int32_t)rd32(st + g_chWeightCur);
            p->maxWeight = (int32_t)rd32(st + g_chWeightMax);
            if (p->maxWeight > 0) { p->weightOk = 1; p->maxWeightOk = 1; }
            if (!p->hp && g_stBlock) p->hp = rd32(g_base + g_stBlock + g_stHp);
            if (!p->maxHp && g_stBlock) p->maxHp = rd32(g_base + g_stBlock + g_stMaxHp);
            if (!p->mp && g_stBlock) p->mp = rd32(g_base + g_stBlock + g_stMp);
            if (!p->maxMp && g_stBlock) p->maxMp = rd32(g_base + g_stBlock + g_stMaxMp);
            if (!p->level && g_stBlock) p->level = rd32(g_base + g_stBlock + g_stLevel);
            if (!p->posX && g_stBlock) p->posX = rd32(g_base + g_stBlock + g_stX);
            if (!p->posY && g_stBlock) p->posY = rd32(g_base + g_stBlock + g_stY);
        }
    }
    if (p->hp > p->maxHp * 2) p->hp = 0, p->maxHp = 0;
}

static int readSkills(SkillData* skills, int max) {
    uint64_t arr = g_base + offSkills;
    int cap = max > 256 ? 256 : max;
    uint32_t stride = oSkillStruct;
    uint8_t* buf = malloc((size_t)cap * stride);
    if (!buf) return 0;
    if (!readMem(arr, buf, (uint32_t)(cap * stride))) { free(buf); return 0; }
    int n = 0;
    for (int i = 0; i < cap; i++) {
        uint32_t id;
        memcpy(&id, buf + (size_t)i * stride + oSkillId, 4);
        if (id == 0) break;
        SkillData* d = &skills[n];
        d->id = id;
        memcpy(&d->level, buf + (size_t)i * stride + oSkillLevel, 4);
        n++;
    }
    free(buf);
    return n;
}

static int readParty(PartyData* members, int max) {
    uint64_t arr = g_base + offParty;
    int cap = max > 8 ? 8 : max;
    uint32_t stride = oPartyStruct;
    uint8_t* buf = malloc((size_t)cap * stride);
    if (!buf) return 0;
    if (!readMem(arr, buf, (uint32_t)(cap * stride))) { free(buf); return 0; }
    int n = 0;
    for (int i = 0; i < cap; i++) {
        uint32_t lvl = 0, hp = 0, mhp = 0, cls = 0;
        memcpy(&lvl, buf + (size_t)i * stride + oPartyLevel, 4);
        memcpy(&hp, buf + (size_t)i * stride + oPartyHp, 4);
        memcpy(&mhp, buf + (size_t)i * stride + oPartyMaxHp, 4);
        if (lvl == 0 && hp == 0 && mhp == 0) continue;
        PartyData* d = &members[n];
        d->level = lvl; d->hp = hp; d->maxHp = mhp;
        memcpy(&cls, buf + (size_t)i * stride + oPartyClass, 4); d->classId = cls;
        d->name[0] = 0;
        n++;
    }
    free(buf);
    return n;
}

// Read active buffs from the (discovered) 11-slot buff array.
static int readBuffs(BuffData* buffs, int max, uint64_t buffArray) {
    if (!buffArray) return 0;
    int n = 0;
    for (int i = 0; i < BUFF_SLOTS && n < max; i++) {
        uint64_t slot = buffArray + (uint64_t)i * oBuffStruct;
        uint64_t tagged = 0;
        if (!readMem(slot + oBuffDataPtr, &tagged, 8) || !tagged) continue;
        uint64_t real = tagged & 0xFFFFFFFFFFFULL;
        if (!real) continue;
        BuffData* b = &buffs[n];
        b->slot = (uint32_t)(8 + i);
        readMem(real + oBuffId, &b->id, 4);
        if (!b->id) continue;
        readMem(real + oBuffRemain, &b->remain, 4);
        readMem(real + oBuffMaxDur, &b->maxDur, 4);
        readMem(real + oBuffStacks, &b->stacks, 4);
        n++;
    }
    return n;
}

// ---------------------------------------------------------------------------
// Heap discovery (background thread, adaptive readable-window caching)
// ---------------------------------------------------------------------------
// LC.exe heap placement moves with ASLR (observed 0x1B.. in the current
// session, 0x1C.. in earlier ones). A fixed range is unreliable and a full
// sweep is ~7s, so a worker thread owns the scan, caches the readable
// 1MB windows after the first pass, and only re-sweeps every 8th pass.
// The main loop never blocks on discovery.
// ---------------------------------------------------------------------------
#define HEAP_LO         0    /* disabled: use coarse [ValidPtrLo..Hi) map */
#define HEAP_HI         0
#define HEAP_WIN        0x10000
#define MAX_READABLE    262144
#define DISC_INTERVAL_MS 1000     // how often entity/buff detection rescans cached windows
#define DISC_REENUM_EVERY 64      // full heap sweep cadence (passes); keeps ASLR-moved heaps found
#define VALID_PTR_LO    0x10000000000ULL
#define VALID_PTR_HI    0x40000000000ULL
#define COARSE_STRIDE   0x20000000ULL   /* 512MB coarse-map stride */
#define COARSE_SAMPLES  2

// Heap/valid ranges: defaults above, overridable from offsets.json (strings).
static uint64_t g_heapLo = HEAP_LO, g_heapHi = HEAP_HI;
static uint64_t g_validPtrLo = VALID_PTR_LO, g_validPtrHi = VALID_PTR_HI;

// Entity discovery (state_8_23 port): movement-component vftable + owner
// ctrl-block classification. Movement comp layout: vft@+0, owner ptr@+0x18,
// cur(x,y)@+0x50/0x54 (verified live: module+vft 0x1160128 with ctrl-block
// tags 0x1160xxx for this build). True most-derived class comes from the
// shared_ptr control block at owner-0x10 (_Ref_count_obj2<T>: vft,uses,weaks;
// inline object at ctrl+0x10).
static uint64_t g_entCompVftRva    = 0x1160128; // lineage movement component vft
static uint64_t g_entActorVftRva   = 0x11601E8; // lineage::Actor
static uint64_t g_entMonsterVftRva = 0x1163BB8; // lineage::Monster
static uint64_t g_entPlayerVftRva  = 0x1163D00; // lineage::Player
static uint64_t g_ctrlSegmentProp  = 0x11603E0; // world props -> skip
static uint64_t g_ctrlBuffNpc      = 0x11602F0; // BuffNPC -> npc
static uint64_t g_ctrlMonster      = 0x1160480; // Monster -> monster
static uint64_t g_ctrlSummonMon    = 0x11604A8; // SummonedMonster -> monster
static uint64_t g_ctrlPet          = 0x1160390; // Pet -> pet
static uint64_t g_ctrlMyPlayer     = 0x11604D0; // MyPlayer -> self player
static uint64_t g_ctrlNpc          = 0x1160430; // InteractiveNPC -> npc

static CRITICAL_SECTION g_discCs;
static volatile BOOL    g_discRunning = FALSE;
static HANDLE           g_discThread = NULL;
static int              g_nRefs = 0;
static EntityRef        g_refs[MAX_ENTITIES];
static uint64_t         g_readable[MAX_READABLE];
static int              g_nReadable = 0;

// Classify an entity by its shared_ptr control block: _Ref_count_obj2<T>
// header sits at owner-0x10 (vft,uses,weaks), inline object at ctrl+0x10.
// Ctrl-block vft is the true most-derived type tag (entity+0 vft can be a
// base like Actor even for SegmentProp props).
// Returns: -1 = ctrl table not configured (caller falls back to owner vft),
//           0 = unknown/SegmentProp -> drop,
//          >0 = classId (1 monster, 2 player, 4 pet, 5 npc, 6 my-player).
static int classifyOwner(uint64_t owner) {
    if (!g_ctrlMyPlayer && !g_ctrlMonster && !g_ctrlNpc) return -1;
    if (owner < 0x1000) return 0;
    uint64_t cv = 0;
    if (!readMem(owner - 0x10, &cv, 8)) return 0;
    if (cv < g_base || cv - g_base > 0x4000000ULL) return 0;
    uint64_t rva = cv - g_base;
    if (g_ctrlSegmentProp && rva == g_ctrlSegmentProp) return 0;
    if ((g_ctrlMonster && rva == g_ctrlMonster) ||
        (g_ctrlSummonMon && rva == g_ctrlSummonMon)) return 1;
    if (g_ctrlPlayer && rva == g_ctrlPlayer) return 2;
    if (g_ctrlPet && rva == g_ctrlPet) return 4;
    if (g_ctrlMyPlayer && rva == g_ctrlMyPlayer) return 6;
    if ((g_ctrlNpc && rva == g_ctrlNpc) ||
        (g_ctrlBuffNpc && rva == g_ctrlBuffNpc)) return 5;
    return 0;
}

// Scan one 1MB window for the buff array and entities. Shared by the
// background discovery thread and the synchronous discoverNow().
static void scanWindow(const uint8_t* win, uint32_t br, uint64_t winAddr,
                       uint64_t* buffArr, int* nRefs, EntityRef* refs,
                       int32_t px, int32_t py, uint32_t sp) {
    (void)sp;

    // Buff array: 11 slots x 0x90, tagged data ptr (+0x50) per slot.
    if (!*buffArr) {
        for (uint32_t i = 0; i + 0x58 <= br; i += 4) {
            uint64_t tagged = *(uint64_t*)(win + i);
            uint64_t real = tagged & 0xFFFFFFFFFFFULL;
            if (real < g_validPtrLo || real >= g_validPtrHi) continue;
            int matches = 0;
            for (int s = 0; s < BUFF_SLOTS; s++) {
                uint32_t off = i + (uint32_t)s * oBuffStruct + oBuffDataPtr;
                if (off + 8 > br) break;
                uint64_t t = *(uint64_t*)(win + off);
                uint64_t r = t & 0xFFFFFFFFFFFULL;
                if (r >= g_validPtrLo && r < g_validPtrHi) matches++;
            }
            if (matches >= 8) { *buffArr = winAddr + i - oBuffDataPtr; break; }
        }
    }

    // Entities near player: movement-component vftable scan (lineage engine).
    // comp+0x00 = component vft, comp+0x18 = owner entity ptr,
    // comp+0x50/0x54 = current x/y.
    if (!g_entCompVftRva) return;
    {
        uint64_t cvft = g_base + g_entCompVftRva;
        for (uint32_t i = 0; i + 0x70 <= br && *nRefs < MAX_ENTITIES; i += 8) {
            if (*(uint64_t*)(win + i) != cvft) continue;
            uint64_t owner = *(uint64_t*)(win + i + 0x18);
            if (owner < g_validPtrLo || owner >= g_validPtrHi) continue;
            uint32_t cx = *(uint32_t*)(win + i + 0x50);
            uint32_t cy = *(uint32_t*)(win + i + 0x54);
            if (cx > 60000 || cy > 60000 || cx == 0 || cy == 0) continue;
            int dx = (int)cx - px; if (dx < 0) dx = -dx;
            int dy = (int)cy - py; if (dy < 0) dy = -dy;
            if (dx >= ENTITY_DIST || dy >= ENTITY_DIST) continue;
            // classify by ctrl-block tag; legacy owner-vft fallback
            int cls = classifyOwner(owner);
            if (cls < 0) {
                uint64_t ovft = 0;
                readMem(owner, &ovft, 8);
                if (g_entMonsterVftRva && ovft == g_base + g_entMonsterVftRva) cls = 1;
                else if (g_entPlayerVftRva && ovft == g_base + g_entPlayerVftRva) cls = 2;
                else if (g_entActorVftRva && ovft == g_base + g_entActorVftRva) cls = 3;
                else continue;
            } else if (cls == 0) continue;
            int dup = 0;
            for (int d = 0; d < *nRefs; d++)
                if (refs[d].addr == winAddr + i) { dup = 1; break; }
            if (dup) continue;
            refs[*nRefs].addr = winAddr + i;
            refs[*nRefs].id = (uint32_t)(owner >> 4);
            refs[*nRefs].hash = (uint64_t)cls;
            (*nRefs)++;
        }
    }
}

// Enumerate readable HEAP_WIN windows. Prefers the explicit [HeapLo..HeapHi)
// band; otherwise coarse-probes [ValidPtrLo..ValidPtrHi) in 512MB strides
// (two samples per stride) and enumerates windows inside hit strides only.
static int enumerateReadable(uint64_t* readable, int maxReadable, uint8_t* win) {
    int n = 0;
    if (g_heapLo && g_heapHi && g_heapHi > g_heapLo) {
        for (uint64_t addr = g_heapLo; addr < g_heapHi && n < maxReadable; addr += HEAP_WIN) {
            uint32_t br = 0;
            if (SignedReadMemory(g_pid, addr, win, HEAP_WIN, &br) && br >= 0x1000)
                readable[n++] = addr;
        }
        return n;
    }
    for (uint64_t sa = g_validPtrLo & ~(COARSE_STRIDE - 1);
         sa < g_validPtrHi && n < maxReadable; sa += COARSE_STRIDE) {
        int hit = 0;
        for (int sm = 0; sm < COARSE_SAMPLES && !hit; sm++) {
            uint64_t pa = sa + sm * (COARSE_STRIDE / COARSE_SAMPLES);
            if (pa < g_validPtrLo) pa = g_validPtrLo;
            if (pa >= g_validPtrHi) break;
            uint32_t pbr = 0;
            if (!SignedReadMemory(g_pid, pa, win, HEAP_WIN, &pbr) || pbr < 0x1000)
                continue;
            hit = 1;
            uint64_t blo = sa < g_validPtrLo ? g_validPtrLo : sa;
            uint64_t bhi = sa + COARSE_STRIDE;
            if (bhi > g_validPtrHi) bhi = g_validPtrHi;
            for (uint64_t wa = blo; wa < bhi && n < maxReadable; wa += HEAP_WIN) {
                uint32_t br = 0;
                if (SignedReadMemory(g_pid, wa, win, HEAP_WIN, &br) && br >= 0x1000)
                    readable[n++] = wa;
            }
        }
    }
    return n;
}

static DWORD WINAPI discoveryThread(LPVOID arg) {
    (void)arg;
    uint8_t* win = malloc(HEAP_WIN);
    if (!win) return 1;
    static uint64_t readable[MAX_READABLE];   /* too big for the stack */
    int nReadable = 0;
    int pass = 0;
    int32_t px = 0, py = 0;

    while (g_discRunning) {
        // Renumerate readable windows on the first pass and every 64th pass.
        if (nReadable == 0 || (pass % DISC_REENUM_EVERY == 0)) {
            nReadable = enumerateReadable(readable, MAX_READABLE, win);
            EnterCriticalSection(&g_discCs);
            g_nReadable = nReadable;
            if (nReadable) memcpy(g_readable, readable, sizeof(uint64_t) * (size_t)nReadable);
            LeaveCriticalSection(&g_discCs);
        }

        // Player pos for the entity distance filter.
        uint32_t v = 0, sp = 0;
        if (readMem(g_base + offPosX, &v, 4)) px = (int32_t)v;
        if (readMem(g_base + offPosY, &v, 4)) py = (int32_t)v;
        readMem(playerBase() + oSp, &sp, 4);

        // Buff array: prefer the known module-relative base from offsets.json
        // (BuffListBase); otherwise fall back to the heap signature scan.
        uint64_t buffArr = offBuffList ? (g_base + offBuffList) : 0;
        EntityRef refs[MAX_ENTITIES];
        int nRefs = 0;

        for (int w = 0; w < nReadable && (!buffArr || nRefs < MAX_ENTITIES); w++) {
            uint32_t br = 0;
            if (!SignedReadMemory(g_pid, readable[w], win, HEAP_WIN, &br) || br < 0x1000) continue;
            scanWindow(win, br, readable[w], &buffArr, &nRefs, refs, px, py, sp);
        }

        EnterCriticalSection(&g_discCs);
        g_buffArray = buffArr;
        g_nRefs = nRefs;
        if (nRefs) memcpy(g_refs, refs, sizeof(EntityRef) * (size_t)nRefs);
        LeaveCriticalSection(&g_discCs);

        /* Entity-set rescan follows the user's --interval (same cadence as
         * HP/MP/level), floored at 250ms so tiny intervals can't flood the
         * driver with full-window sweeps. */
        Sleep(g_pollMs < 250 ? 250 : (DWORD)g_pollMs);
        pass++;
    }
    free(win);
    return 0;
}

// Take a consistent snapshot of the discovery worker's output.
static void snapshotDiscovery(uint64_t* buffArray, EntityRef* refs, int* nRefs) {
    EnterCriticalSection(&g_discCs);
    *buffArray = g_buffArray;
    *nRefs = g_nRefs;
    if (g_nRefs > 0) memcpy(refs, g_refs, sizeof(EntityRef) * (size_t)g_nRefs);
    LeaveCriticalSection(&g_discCs);
}

// Synchronous on-demand discovery, called on a "fresh" snapshot request.
// Rescans the cached readable windows right now so entities/buffs are as new
// as the request moment. If the cache is empty (cold start before the worker
// finished its first sweep) it does a synchronous full sweep so the very first
// request still returns data.
static void discoverNow(void) {
    uint8_t* win = (uint8_t*)malloc(HEAP_WIN);
    if (!win) return;
    uint64_t buffArr = offBuffList ? (g_base + offBuffList) : 0;
    EntityRef refs[MAX_ENTITIES];
    int nRefs = 0;
    int32_t px = 0, py = 0; uint32_t sp = 0;
    readMem(g_base + offPosX, &px, 4);
    readMem(g_base + offPosY, &py, 4);
    readMem(playerBase() + oSp, &sp, 4);

    EnterCriticalSection(&g_discCs);
    int nRead = g_nReadable;
    LeaveCriticalSection(&g_discCs);

    if (nRead == 0) {
        // Cold start: synchronous full sweep (can take a few seconds).
        static uint64_t wbuf[MAX_READABLE];       /* too big for the stack */
        int nw = enumerateReadable(wbuf, MAX_READABLE, win);
        for (int i = 0; i < nw && nRefs < MAX_ENTITIES; i++) {
            uint32_t br = 0;
            if (!SignedReadMemory(g_pid, wbuf[i], win, HEAP_WIN, &br) || br < 0x1000) continue;
            scanWindow(win, br, wbuf[i], &buffArr, &nRefs, refs, px, py, sp);
        }
        EnterCriticalSection(&g_discCs);
        g_nReadable = nw;
        if (nw) memcpy(g_readable, wbuf, sizeof(uint64_t) * (size_t)nw);
        LeaveCriticalSection(&g_discCs);
    } else {
        for (int w = 0; w < nRead && nRefs < MAX_ENTITIES; w++) {
            uint64_t waddr;
            EnterCriticalSection(&g_discCs);
            waddr = g_readable[w];
            LeaveCriticalSection(&g_discCs);
            uint32_t br = 0;
            if (!SignedReadMemory(g_pid, waddr, win, HEAP_WIN, &br) || br < 0x1000) continue;
            scanWindow(win, br, waddr, &buffArr, &nRefs, refs, px, py, sp);
        }
    }

    EnterCriticalSection(&g_discCs);
    g_buffArray = buffArr;
    g_nRefs = nRefs;
    if (nRefs) memcpy(g_refs, refs, sizeof(EntityRef) * (size_t)nRefs);
    LeaveCriticalSection(&g_discCs);
    free(win);
}

static int g_discStarted = 0;

static void startDiscovery(void) {
    if (g_discStarted) return;
    InitializeCriticalSection(&g_discCs);
    g_discStarted = 1;
    g_discRunning = TRUE;
    g_discThread = CreateThread(NULL, 0, discoveryThread, NULL, 0, NULL);
    if (!g_discThread) g_discRunning = FALSE;
}

static void stopDiscovery(void) {
    if (!g_discStarted) return;
    if (g_discRunning) {
        g_discRunning = FALSE;
        if (g_discThread) {
            WaitForSingleObject(g_discThread, 5000);
            CloseHandle(g_discThread);
            g_discThread = NULL;
        }
    }
    DeleteCriticalSection(&g_discCs);
    g_discStarted = 0;
}


/* content guard for target names: hangul or plain identifier chars */
static int validNameBytes(const unsigned char* p, int n) {
    for (int k = 0; k < n; k++) {
        unsigned char c = p[k];
        if (!c) return 0;
        if (c >= 0xE0 && c <= 0xED) {
            if (k + 2 >= n || (p[k+1] & 0xC0) != 0x80 ||
                (p[k+2] & 0xC0) != 0x80) return 0;
            k += 2;
        } else if (!((c >= 'A' && c <= 'Z') || (c >= 'a' && c <= 'z') ||
                     (c >= '0' && c <= '9') || c == '_' || c == ' ')) {
            return 0;
        }
    }
    return n >= 2;
}

static int readSsoTargetName(uint64_t tp, char* dst, int cap_) {
    dst[0] = 0;
    if (!tp || tp < g_validPtrLo || tp >= g_validPtrHi) return 0;
    unsigned char hdr[32];
    if (!readMem(tp + 0x10, hdr, sizeof(hdr))) return 0;
    uint64_t size, capacity;
    memcpy(&size,     hdr + 16, 8);
    memcpy(&capacity, hdr + 24, 8);
    if (size < 2 || size > 128) return 0;
    if (capacity == 0xF) {                       // inline SSO buffer
        int n = size < (uint64_t)(cap_ - 1) ? (int)size : cap_ - 1;
        if (n > 15) n = 15;                      // hdr holds only 32 bytes
        if (!validNameBytes(hdr, n)) return 0;
        memcpy(dst, hdr, n); dst[n] = 0;
        return n;
    }
    if (capacity > 0xF && capacity <= 0x1000) {  // heap-allocated buffer
        uint64_t dp;
        if (!readMem(tp + 0x10, &dp, 8)) return 0;
        if (dp < g_validPtrLo || dp >= g_validPtrHi) return 0;
        int n = size < (uint64_t)(cap_ - 1) ? (int)size : cap_ - 1;
        char buf[128];
        int m = n < (int)sizeof(buf) ? n : (int)sizeof(buf) - 1;
        if (m > 0 && readMem(dp, buf, m)) {
            if (!validNameBytes((const unsigned char*)buf, m)) return 0;
            memcpy(dst, buf, m); dst[m] = 0;
            return m;
        }
        dst[0] = 0;
    }
    return 0;
}

// Refresh entity live fields from cached movement-component addresses.
// comp+0x50/0x54 = cur x/y; owner ptr at comp+0x18; id = owner>>4;
// class re-derived from the ctrl-block tag each frame (types can change).
static int refreshEntities(const EntityRef* refs, int nRefs, EntityData* ents, int maxEnts,
                           const PlayerData* player) {
    int n = 0;
    for (int i = 0; i < nRefs && n < maxEnts; i++) {
        uint8_t buf[0x70];
        EntityData* e = &ents[n];
        memset(e, 0, sizeof(*e));
        if (!readMem(refs[i].addr, buf, sizeof(buf))) continue;
        if (g_entCompVftRva && *(uint64_t*)buf != g_base + g_entCompVftRva) continue;
        e->posX = *(uint32_t*)(buf + 0x50);
        e->posY = *(uint32_t*)(buf + 0x54);
        uint64_t owner = *(uint64_t*)(buf + 0x18);
        int cls = classifyOwner(owner);
        if (cls < 0) {
            uint64_t ovft = 0;
            if (owner >= g_validPtrLo && owner < g_validPtrHi) readMem(owner, &ovft, 8);
            if (g_entMonsterVftRva && ovft == g_base + g_entMonsterVftRva) cls = 1;
            else if (g_entPlayerVftRva && ovft == g_base + g_entPlayerVftRva) cls = 2;
            else if (g_entActorVftRva && ovft == g_base + g_entActorVftRva) cls = 3;
            else continue;
        } else if (cls == 0) continue;
        e->classId = (uint32_t)cls;
        e->id = refs[i].id;
        e->compAddr = refs[i].addr;
        e->objAddr  = owner;
        if (owner >= g_validPtrLo && owner < g_validPtrHi) {
            uint64_t tp = 0;
            if (readMem(owner + 0x2E0, &tp, 8))
                readSsoTargetName(tp, e->target, (int)sizeof(e->target));
            if (e->classId == 6)
                readMem(owner + 0x130, &e->level, 2);

            // Template ID: class-specific candidate offsets, first plausible hit.
            uint32_t tpl = 0;
            static const uint32_t tplOffsetsSelf[] = { 0x80, 0x130, 0x140, 0x60, 0x30, 0x40, 0x50 };
            static const uint32_t tplOffsetsNPC[] = { 0x80, 0x60, 0x30, 0x40, 0x50, 0xA0, 0xC0, 0x120, 0x180 };
            static const uint32_t tplOffsetsMonster[] = { 0x30, 0x80, 0x60, 0x40, 0x50, 0xA0 };
            const uint32_t* offsets = tplOffsetsNPC;
            size_t nOffsets = sizeof(tplOffsetsNPC)/sizeof(tplOffsetsNPC[0]);
            if (e->classId == 6) { offsets = tplOffsetsSelf; nOffsets = sizeof(tplOffsetsSelf)/sizeof(tplOffsetsSelf[0]); }
            else if (e->classId == 1) { offsets = tplOffsetsMonster; nOffsets = sizeof(tplOffsetsMonster)/sizeof(tplOffsetsMonster[0]); }
            for (size_t k = 0; k < nOffsets; k++) {
                if (readMem(owner + offsets[k], &tpl, 4)) {
                    if (tpl != 0 && tpl != 0xFFFFFFFF && tpl < 100000) {
                        e->templateId = tpl;
                        break;
                    }
                }
            }

            // Target ID: candidate offsets around the target-name pointer (0x2E0).
            uint32_t tgt = 0;
            static const uint32_t tgtOffsets[] = { 0x2D0, 0x2D8, 0x2E8, 0x2F0, 0x2F8, 0x300, 0x310, 0x320 };
            for (size_t k = 0; k < sizeof(tgtOffsets)/sizeof(tgtOffsets[0]); k++) {
                if (readMem(owner + tgtOffsets[k], &tgt, 4)) {
                    if (tgt != 0 && tgt != 0xFFFFFFFF && tgt < 0x10000000) {
                        e->targetId = tgt;
                        break;
                    }
                }
            }

            // Name: candidate offsets as string pointers.
            uint64_t namePtr = 0;
            static const uint32_t nameOffsets[] = { 0x30, 0x40, 0x50, 0x60, 0x70, 0x80, 0x90, 0xA0, 0xB0, 0xC0 };
            for (size_t k = 0; k < sizeof(nameOffsets)/sizeof(nameOffsets[0]); k++) {
                if (readMem(owner + nameOffsets[k], &namePtr, 8)) {
                    if (namePtr >= g_validPtrLo && namePtr < g_validPtrHi) {
                        char tmp[64] = {0};
                        readMem(namePtr, tmp, 63);
                        int valid = 1, len = 0;
                        for (int c = 0; c < 63 && tmp[c]; c++) {
                            unsigned char ch = (unsigned char)tmp[c];
                            if (ch < 32 || ch > 126) { valid = 0; break; }
                            len++;
                        }
                        if (valid && len >= 1 && len <= 32) {
                            strncpy(e->name, tmp, 63);
                            break;
                        }
                    }
                }
            }
        }
        int fx = (int)e->posX - (int)player->posX, fy = (int)e->posY - (int)player->posY;
        e->dist = (float)sqrt((double)(fx*fx + fy*fy));
        n++;
    }
    return n;
}

// ---------------------------------------------------------------------------
// zone_table.json: coordinate -> zone name (UTF-8) lookup
// ---------------------------------------------------------------------------
#define MAX_ZONES 64
static struct { char name[96]; unsigned map, x, y; } g_zones[MAX_ZONES];
static int g_nZones = 0;
static unsigned g_zoneRadius = 170;

static void LoadZoneTable(void) {
    char path[MAX_PATH];
    pathInDataDir(path, sizeof(path), "zone_table.json");
    FILE* f = fopen(path, "rb");
    if (!f) return;
    static char buf[16384];
    size_t n = fread(buf, 1, sizeof(buf) - 1, f);
    fclose(f);
    buf[n] = 0;
    const char* rad = strstr(buf, "\"default_radius\"");
    if (rad) {
        const char* colon = strchr(rad, ':');
        if (colon) g_zoneRadius = (unsigned)strtoul(colon + 1, NULL, 10);
    }
    const char* p = strstr(buf, "\"zones\"");
    const char* arr = p ? strchr(p, '[') : NULL;
    if (!arr) return;
    const char* q = arr + 1;
    while (g_nZones < MAX_ZONES) {
        const char* e = strchr(q, '[');          // each entry opens with '['
        if (!e) break;
        const char* q0 = strchr(e, '"');
        if (!q0) break;
        const char* q1 = strchr(q0 + 1, '"');
        if (!q1) break;
        size_t len = (size_t)(q1 - q0 - 1);
        if (len >= sizeof(g_zones[g_nZones].name)) len = sizeof(g_zones[g_nZones].name) - 1;
        memcpy(g_zones[g_nZones].name, q0 + 1, len);
        g_zones[g_nZones].name[len] = 0;
        unsigned vals[3] = { 0, 0, 0 };
        const char* r = q1 + 1;
        for (int i = 0; i < 3; i++) {
            while (*r == ',' || *r == ' ' || *r == '\t' || *r == '\r' || *r == '\n') r++;
            vals[i] = (unsigned)strtoul(r, (char**)&r, 10);
            while (*r && *r != ',' && *r != ']') r++;
        }
        g_zones[g_nZones].map = vals[0];
        g_zones[g_nZones].x   = vals[1];
        g_zones[g_nZones].y   = vals[2];
        g_nZones++;
        q = q1;
    }
}

static const char* ZoneLookup(unsigned map, unsigned x, unsigned y) {
    long long best = -1;
    int bi = -1;
    for (int i = 0; i < g_nZones; i++) {
        if (g_zones[i].map != map) continue;
        long long dx = (long long)x - g_zones[i].x;
        long long dy = (long long)y - g_zones[i].y;
        long long d2 = dx * dx + dy * dy;
        if (bi < 0 || d2 < best) { best = d2; bi = i; }
    }
    if (bi < 0 || best > (long long)g_zoneRadius * g_zoneRadius) return NULL;
    return g_zones[bi].name;
}

// ---------------------------------------------------------------------------
// JSON output
// ---------------------------------------------------------------------------
static void writeFrame(FILE* f, int frame, double ts, const PlayerData* p,
                       const SkillData* skills, int nSkills,
                       const PartyData* party, int nParty,
                       const BuffData* buffs, int nBuffs,
                       const EntityData* ents, int nEnts) {
    fprintf(f, "{\"frame\":%d,\"ts\":%.3f,\"player\":{", frame, ts);
    fprintf(f, "\"hp\":%u,\"maxHp\":%u,\"mp\":%u,\"maxMp\":%u,\"sp\":%u,",
        p->hp, p->maxHp, p->mp, p->maxMp, p->sp);
    fprintf(f, "\"level\":%u,\"classId\":%u,\"expPct\":%.6f,",
        p->level, p->classId, p->expPct);
    {
        const char* zn = ZoneLookup(p->mapId, p->posX, p->posY);
        if (zn) fprintf(f, "\"zone\":\"%s\",", zn);
    }
    fprintf(f, "\"pos\":[%u,%u,%u],\"online\":%u,\"isGm\":%u,\"isChaotic\":%u,\"tickMs\":%llu",
        p->posX, p->posY, p->posZ, p->online, p->isGm, p->isChaotic, (unsigned long long)p->tickMs);
    if (p->lawfulOk) fprintf(f, ",\"lawful\":%d", p->lawful);
    if (p->weightOk) fprintf(f, ",\"weight\":%d", p->weight);
    if (p->maxWeightOk) fprintf(f, ",\"maxWeight\":%d", p->maxWeight);
    if (p->foodOk)   fprintf(f, ",\"food\":%d", p->food);
    if (p->acOk)     fprintf(f, ",\"ac\":%d", p->ac);
    if (p->statsOk[0] || p->statsOk[1] || p->statsOk[2] || p->statsOk[3] || p->statsOk[4] || p->statsOk[5]) {
        const char* sn[6] = { "str","dex","con","int","wis","cha" };
        fprintf(f, ",\"stats\":{");
        int first = 1;
        for (int i = 0; i < 6; i++)
            if (p->statsOk[i]) { fprintf(f, "%s\"%s\":%u", first ? "" : ",", sn[i], p->stats[i]); first = 0; }
        fprintf(f, "}");
    }
    fprintf(f, "},\"skills\":[");
    for (int i = 0; i < nSkills; i++) {
        if (i) fprintf(f, ",");
        fprintf(f, "{\"id\":%u,\"level\":%u}", skills[i].id, skills[i].level);
    }
    fprintf(f, "],\"party\":[");
    for (int i = 0; i < nParty; i++) {
        if (i) fprintf(f, ",");
        fprintf(f, "{\"name\":\"%s\",\"level\":%u,\"classId\":%u,\"hp\":%u,\"maxHp\":%u}",
            party[i].name[0] ? party[i].name : "?", party[i].level, party[i].classId,
            party[i].hp, party[i].maxHp);
    }
    fprintf(f, "],\"buffs\":[");
    for (int i = 0; i < nBuffs; i++) {
        if (i) fprintf(f, ",");
        fprintf(f, "{\"slot\":%u,\"id\":%u,\"remain\":%.1f,\"maxDur\":%.1f,\"stacks\":%u}",
            buffs[i].slot, buffs[i].id, buffs[i].remain, buffs[i].maxDur, buffs[i].stacks);
    }
    fprintf(f, "],\"entities\":[");
    for (int i = 0; i < nEnts; i++) {
        if (i) fprintf(f, ",");
        fprintf(f, "{\"id\":%u,\"hp\":%u,\"maxHp\":%u,\"level\":%u,\"classId\":%u,\"templateId\":%u,\"targetId\":%u,\"pos\":[%u,%u,%u],\"dist\":%.1f,\"name\":\"%s\",\"target\":\"%s\"}",
            ents[i].id, ents[i].hp, ents[i].maxHp, ents[i].level, ents[i].classId,
            ents[i].templateId, ents[i].targetId,
            ents[i].posX, ents[i].posY, ents[i].posZ, ents[i].dist,
            ents[i].name[0] ? ents[i].name : "",
            ents[i].target[0] ? ents[i].target : "");
    }
    fprintf(f, "]}\n");
}

// Build one full snapshot and write it as a single JSON line to `out`.
// Used by --serve (stdout) and --pipe (named-pipe client).
static void buildSnapshot(FILE* out, int frame, double ts,
                          uint64_t* buffArray, EntityRef* refs, int* nRefs) {
    PlayerData p; SkillData skills[MAX_SKILLS];
    PartyData party[MAX_PARTY]; BuffData buffs[MAX_BUFFS];
    EntityData ents[MAX_ENTITIES];
    memset(&p, 0, sizeof(p));
    memset(skills, 0, sizeof(skills));
    memset(party, 0, sizeof(party));
    memset(buffs, 0, sizeof(buffs));
    readPlayer(&p);
    int nSkills = readSkills(skills, MAX_SKILLS);
    int nParty = readParty(party, MAX_PARTY);
    snapshotDiscovery(buffArray, refs, nRefs);
    int nBuffs = readBuffs(buffs, MAX_BUFFS, *buffArray);
    int nEnts = *nRefs ? refreshEntities(refs, *nRefs, ents, MAX_ENTITIES, &p) : 0;
    nEnts = finalizeEnts(ents, nEnts);
    writeFrame(out, frame, ts, &p, skills, nSkills,
               party, nParty, buffs, nBuffs, ents, nEnts);
    fflush(out);
}

// Handle one request line (already trimmed): "ping" -> ack, "snapshot" ->
// full JSON dataset, anything else -> error JSON. Writes to `out`.
static void handleRequest(FILE* out, const char* line, int frame, double ts,
                          uint64_t* buffArray, EntityRef* refs, int* nRefs,
                          LARGE_INTEGER* start, LARGE_INTEGER* freq) {
    if (strstr(line, "ping")) {
        LARGE_INTEGER now; QueryPerformanceCounter(&now);
        fprintf(out, "{\"cmd\":\"ping\",\"pong\":true,\"pid\":%lu,\"base\":\"0x%llX\",\"ts\":%.3f}\n",
            (unsigned long)g_pid, (unsigned long long)g_base,
            (double)(now.QuadPart - start->QuadPart) / (double)freq->QuadPart);
    } else if (strstr(line, "snapshot")) {
        if (strstr(line, "fresh"))
            discoverNow();   // re-scan cached windows now for newest entities/buffs
        buildSnapshot(out, frame, ts, buffArray, refs, nRefs);
    } else {
        fprintf(out, "{\"error\":\"unknown_cmd\",\"raw\":\"%s\"}\n", line);
    }
    fflush(out);
}

static const char* entClsName(uint32_t cls) {
    switch (cls) {
        case 1: return "Monster";
        case 2: return "Player";
        case 3: return "Actor";
        case 4: return "Pet";
        case 5: return "NPC";
        case 6: return "Self";
        default: return "?";
    }
}

static void printEnts(const EntityData* ents, int nEnts) {
    if (!g_showEnts) return;
    for (int i = 0; i < nEnts; i++) {
        const EntityData* e = &ents[i];
        printf("  #%02d id=%08X tpl=%u %-7s pos=(%5u,%5u) dist=%6.1f%s\n",
            i + 1, e->id, e->templateId, entClsName(e->classId), e->posX, e->posY,
            e->dist, e->classId == 6 ? "  <- you" : "");
    }
}

static void printConsole(const PlayerData* p,
                         int nSkills, int nParty, int nBuffs, int nEnts, int frame) {
    HANDLE h = GetStdHandle(STD_OUTPUT_HANDLE);
    if (frame > 1) {
        CONSOLE_SCREEN_BUFFER_INFO ci;
        if (GetConsoleScreenBufferInfo(h, &ci)) {
            COORD tl = { 0, 0 };
            SetConsoleCursorPosition(h, tl);
        }
    }
    printf("=== Frame %d  (fixed %d ms interval) ===\n", frame, g_pollMs);
    printf("HP=%-4u/%-4u  MP=%-3u/%-3u  SP=%-4u  Lv=%-3u Class=%-3u\n",
        p->hp, p->maxHp, p->mp, p->maxMp, p->sp, p->level, p->classId);
    {
        const char* zn = ZoneLookup(p->mapId, p->posX, p->posY);
        if (zn) printf("Zone=%s\n", zn);
    }
    if (p->weightOk) {
        if (p->maxWeightOk)
            printf("Wt=%d/%d", p->weight, p->maxWeight);
        else
            printf("Wt=%d", p->weight);
        if (p->foodOk) printf("  Food=%d", p->food);
        if (p->lawfulOk) printf("  Lawful=%d", p->lawful);
        if (p->statsOk[0] || p->statsOk[1]) {
            printf("  STR=%u DEX=%u CON=%u INT=%u WIS=%u CHA=%u",
                p->statsOk[0] ? p->stats[0] : 0, p->statsOk[1] ? p->stats[1] : 0,
                p->statsOk[2] ? p->stats[2] : 0, p->statsOk[3] ? p->stats[3] : 0,
                p->statsOk[4] ? p->stats[4] : 0, p->statsOk[5] ? p->stats[5] : 0);
        }
        printf("\n");
    }
    printf("Pos=(%u,%u,%u)  EXP=%.4f%%  Tick=%llums\n",
        p->posX, p->posY, p->posZ, p->expPct, (unsigned long long)p->tickMs);
    printf("Datasets: skills=%d party=%d buffs=%d entities=%d\n",
        nSkills, nParty, nBuffs, nEnts);
}

// ---------------------------------------------------------------------------
// Main loop
// ---------------------------------------------------------------------------
// One in-process snapshot. Same JSON line as --pipe, without a console.
// Loaded by the bot. This is not injected into LC.exe.
// Returns JSON bytes, or <0 on failure.
static int g_monAttached = 0;
static int g_monClock = 0;
static int g_monFrame = 0;
static LARGE_INTEGER g_monFreq, g_monStart;

static void monitorDetach(void) {
    stopDiscovery();
    if (g_monAttached) SignedClose();
    g_monAttached = 0;
    g_pid = 0;
}

static int monitorEnsure(const char* offsetsPath) {
    const char* path = (offsetsPath && offsetsPath[0]) ? offsetsPath : "offsets.json";
    DWORD pid;
    loadOffsets(path);
    loadExtraOffsets();
    {
        char chPath[MAX_PATH];
        pathInDataDir(chPath, sizeof(chPath), "char_offsets.txt");
        loadCharOffsets(chPath);
    }
    if (!g_nZones) LoadZoneTable();
    if (!g_monClock) {
        QueryPerformanceFrequency(&g_monFreq);
        QueryPerformanceCounter(&g_monStart);
        g_monClock = 1;
        if (g_pollMs < 200) g_pollMs = 200;
    }
    pid = findPid(L"LC.exe");
    if (!pid) { monitorDetach(); return 0; }
    if (g_monAttached && pid == g_pid) return 1;
    if (g_monAttached) monitorDetach();
    if (!SignedOpen()) return 0;
    g_pid = pid;
    SignedSetTarget(g_pid);
    if (!getModuleBase(&g_base)) { SignedClose(); g_pid = 0; return 0; }
    g_monAttached = 1;
    startDiscovery();
    return 1;
}

__declspec(dllexport) int realtime_monitor_snapshot(const char* offsetsPath, int fresh, char* out, int outCap) {
    FILE* tf;
    long n;
    size_t got;
    uint64_t buffArray = 0;
    static EntityRef refs[MAX_ENTITIES];
    int nRefs = 0;
    LARGE_INTEGER now;
    double ts;
    if (!out || outCap < 16) return -1;
    if (!monitorEnsure(offsetsPath)) return -1;
    if (fresh) discoverNow();
    QueryPerformanceCounter(&now);
    ts = (double)(now.QuadPart - g_monStart.QuadPart) / (double)g_monFreq.QuadPart;
    tf = tmpfile();
    if (!tf) return -1;
    g_monFrame++;
    buildSnapshot(tf, g_monFrame, ts, &buffArray, refs, &nRefs);
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

__declspec(dllexport) void realtime_monitor_shutdown(void) { monitorDetach(); }

#ifndef REALTIME_MONITOR_DLL
int main(int argc, char** argv) {
    SetConsoleOutputCP(65001);   /* UTF-8 console: Korean zone names print correctly */
    int pollMs = POLL_MS_DEFAULT;
    for (int a = 1; a < argc; a++) {
        if (strcmp(argv[a], "--interval") == 0 && a + 1 < argc)
            pollMs = atoi(argv[++a]);
        else if (strcmp(argv[a], "--frames") == 0 && a + 1 < argc)
            g_maxFrames = atoi(argv[++a]);
        else if (strcmp(argv[a], "--radius") == 0 && a + 1 < argc) {
            g_entRadius = atoi(argv[++a]);
            if (g_entRadius < 0) g_entRadius = 0;
        }
        else if (strcmp(argv[a], "--ents") == 0)
            g_showEnts = 1;
        else if (strcmp(argv[a], "--no-ents") == 0)
            g_showEnts = 0;
        else if (strcmp(argv[a], "--serve") == 0)
            g_serveMode = 1;
        else if (strcmp(argv[a], "--pipe") == 0)
            g_pipeMode = 1;
        else if (strcmp(argv[a], "--help") == 0) {
            printf("usage: realtime_monitor_full [--interval <ms>] [--frames <n>] [--radius <n>] [--ents|--no-ents] [--serve] [--pipe]\n");
            return 0;
        }
    }
    if (pollMs < POLL_MS_MIN) pollMs = POLL_MS_MIN;
    g_pollMs = pollMs;
    srand((unsigned)time(NULL));
    if (!SignedOpen()) { printf("driver open FAILED\n"); return 1; }
    g_pid = findPid(L"LC.exe");
    if (!g_pid) { printf("LC.exe not running\n"); SignedClose(); return 1; }
    SignedSetTarget(g_pid);

    if (!getModuleBase(&g_base)) {
        g_base = 0x7FF70EC80000ULL;
        LOG("WARN: PEB walk failed, using fallback base 0x%llX\n", (unsigned long long)g_base);
    }
    LOG("LC.exe pid=%lu base=0x%llX\n", g_pid, (unsigned long long)g_base);

    loadOffsets("offsets.json");
    LOG("Offsets: player=0x%llX pos=0x%llX,0x%llX,0x%llX tick=0x%llX exp=0x%llX "
        "skills=0x%llX party=0x%llX bufflist=0x%llX direct=%d\n",
        (unsigned long long)offPlayerBase, (unsigned long long)offPosX,
        (unsigned long long)offPosY, (unsigned long long)offPosZ,
        (unsigned long long)offTick, (unsigned long long)offExpPct,
        (unsigned long long)offSkills,
        (unsigned long long)offParty, (unsigned long long)offBuffList, offPlayerDirect);

    loadExtraOffsets();
    loadCharOffsets("char_offsets.txt");
    if (g_extraOk) {
        LOG("Extra offsets loaded: lawful=%d weight=%d maxWeight=%d food=%d stats=%d,%d,%d,%d,%d,%d\n",
            g_offLawful, g_offWeight, g_offMaxWeight, g_offFood,
            g_offStats[0], g_offStats[1], g_offStats[2], g_offStats[3], g_offStats[4], g_offStats[5]);
    } else {
        LOG("No extra offsets (offsets_discovered.json absent) - lawful/weight/maxWeight/food/stats omitted\n");
    }
    LoadZoneTable();
    LOG("Zone table: %d zones, radius %u\n", g_nZones, g_zoneRadius);

    // Heap discovery (buffs + entities) runs in a background worker thread.
    startDiscovery();

    LARGE_INTEGER freq, start;
    QueryPerformanceFrequency(&freq);
    QueryPerformanceCounter(&start);

    if (g_serveMode || g_pipeMode) {
        uint64_t buffArray = 0;
        static EntityRef refs[MAX_ENTITIES];
        int nRefs = 0, frame = 0;

        if (g_serveMode) {
            LOG("Serve mode active: request -> snapshot JSON line on stdout. Ctrl+C to stop.\n");
            char line[4096];
            while (fgets(line, sizeof(line), stdin)) {
                char* e = line + strlen(line);
                while (e > line && (e[-1] == '\n' || e[-1] == '\r')) *--e = '\0';
                frame++;
                LARGE_INTEGER now; QueryPerformanceCounter(&now);
                double ts = (double)(now.QuadPart - start.QuadPart) / freq.QuadPart;
                handleRequest(stdout, line, frame, ts, &buffArray, refs, &nRefs, &start, &freq);
            }
            LOG("stdin closed - shutting down\n");
            stopDiscovery();
            SignedClose();
            return 0;
        }

        // --pipe: accept one client at a time, serve JSON-line requests until
        // the client disconnects, then wait for the next connection.
        LOG("Pipe mode active: %ls (run the exe as admin; Python connects here)\n", PIPE_NAME);
        for (;;) {
            HANDLE h = CreateNamedPipeW(PIPE_NAME, PIPE_ACCESS_DUPLEX,
                PIPE_TYPE_BYTE | PIPE_READMODE_BYTE | PIPE_WAIT,
                PIPE_UNLIMITED_INSTANCES, PIPE_IN_BUFSIZE, PIPE_IN_BUFSIZE, 0, NULL);
            if (h == INVALID_HANDLE_VALUE) {
                LOG("CreateNamedPipe failed error=%u\n", GetLastError());
                Sleep(1000);
                continue;
            }
            LOG("Waiting for client...\n");
            BOOL ok = ConnectNamedPipe(h, NULL);
            if (!ok && GetLastError() != ERROR_PIPE_CONNECTED) {
                CloseHandle(h);
                LOG("ConnectNamedPipe failed error=%u\n", GetLastError());
                Sleep(500);
                continue;
            }
            LOG("Client connected\n");

            int fd = _open_osfhandle((intptr_t)h, _O_BINARY);
            FILE* out = fd >= 0 ? _fdopen(fd, "wb") : NULL;
            if (!out) {
                if (fd >= 0) _close(fd); else CloseHandle(h);
                continue;
            }

            char buf[PIPE_IN_BUFSIZE];
            size_t acc = 0;
            while (1) {
                DWORD rd = 0;
                if (!ReadFile(h, buf + acc, (DWORD)(sizeof(buf) - 1 - acc), &rd, NULL) || rd == 0)
                    break;   // client disconnected or pipe closed
                acc += rd;
                buf[acc] = '\0';
                char* nl;
                while (acc > 0 && (nl = (char*)memchr(buf, '\n', acc)) != NULL) {
                    *nl = '\0';
                    char* e = nl;
                    while (e > buf && (e[-1] == '\r')) *--e = '\0';
                    frame++;
                    LARGE_INTEGER now; QueryPerformanceCounter(&now);
                    double ts = (double)(now.QuadPart - start.QuadPart) / freq.QuadPart;
                    handleRequest(out, buf, frame, ts, &buffArray, refs, &nRefs, &start, &freq);
                    size_t used = (size_t)(nl - buf) + 1;
                    memmove(buf, nl + 1, acc - used);
                    acc -= used;
                }
                if (acc >= sizeof(buf) - 1) acc = 0;   // drop oversized junk
            }
            fclose(out);   // closes the pipe handle
            LOG("Client disconnected\n");
        }
    }

    FILE* f = fopen("realtime_full.jsonl", "w");
    if (!f) { printf("cannot open realtime_full.jsonl\n"); stopDiscovery(); SignedClose(); return 1; }

    static EntityRef refs[MAX_ENTITIES];
    static EntityData ents[MAX_ENTITIES];
    uint64_t buffArray = 0;
    int nRefs = 0, nEnts = 0;
    int frame = 0;

    printf("Monitoring every %d ms (fixed interval, drift-free). Ctrl+C to stop.\n", pollMs);
    printf("Heap discovery (buffs/entities) is running in the background...\n\n");

    // Drift-free scheduling: each frame targets absolute time T0 + n*interval.
    LARGE_INTEGER t0;
    QueryPerformanceCounter(&t0);
    long long nextTick = 0;
    double intervalQpc = (double)freq.QuadPart * (double)pollMs / 1000.0;

    PlayerData p; SkillData skills[MAX_SKILLS];
    PartyData party[MAX_PARTY]; BuffData buffs[MAX_BUFFS];

    while (1) {
        LARGE_INTEGER now;
        QueryPerformanceCounter(&now);
        double ts = (double)(now.QuadPart - start.QuadPart) / freq.QuadPart;
        frame++;

        memset(&p, 0, sizeof(p));
        memset(skills, 0, sizeof(skills));
        memset(party, 0, sizeof(party));
        memset(buffs, 0, sizeof(buffs));

        readPlayer(&p);
        int nSkills = readSkills(skills, MAX_SKILLS);
        int nParty = readParty(party, MAX_PARTY);

        // Pull the latest discovery snapshot; refresh entity live fields.
        snapshotDiscovery(&buffArray, refs, &nRefs);
        int nBuffs = readBuffs(buffs, MAX_BUFFS, buffArray);
        nEnts = nRefs ? refreshEntities(refs, nRefs, ents, MAX_ENTITIES, &p) : 0;
        nEnts = finalizeEnts(ents, nEnts);

        writeFrame(f, frame, ts, &p, skills, nSkills, party, nParty,
                   buffs, nBuffs, ents, nEnts);
        fflush(f);
        printConsole(&p, nSkills, nParty, nBuffs, nEnts, frame);
        printEnts(ents, nEnts);

        // Wait until the next fixed tick (no cumulative drift).
        nextTick += (long long)intervalQpc;
        long long target = t0.QuadPart + nextTick;
        while (1) {
            QueryPerformanceCounter(&now);
            if (now.QuadPart >= target) break;
            LONGLONG remUs = (LONGLONG)((target - now.QuadPart) * 1000000.0 / freq.QuadPart);
            if (remUs > 4000) Sleep(3);
        }
        if (g_maxFrames > 0 && frame >= g_maxFrames) break;
    }
    fclose(f);
    stopDiscovery();
    SignedClose();
    return 0;
}
#endif
