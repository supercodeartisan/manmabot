/* lcore.h - shared live-read core for the combined entity/attack/dungeon/item work.
 *
 * Follows the proven 9.23\live_tracking design:
 *   enttrack.c : 2-speed loop  - slow sweep (structure sweep / ledger cache)
 *                              + fast poll  (1 batched IOCTL per entity)
 *                PRES_B +0x50 (A) -> +0x78 (B) A/B pipeline, commit step 516 ms
 *   etview.c   : iso->screen projection  PPS=0.53, VP_DX=1.8, VP_DY=63, REF_H=600
 *                and the DIB/overlay drawing conventions
 *
 * Added on top of the reference (the four-way join):
 *   - current map rect  MapSubsystem(by vft) -> +0x768 child -> +0x3C
 *   - AttackAction owner/target  (ActionComponent @ H+0x10, +0x80 / +0x88)
 *   - static assets: dossier.tsv, dungeon_entrances.tsv, exit_candidates.tsv,
 *                    gate_tiles.tsv, obstacle_tiles_raw/map_<id>.bin
 *
 * No heap global scan is used anywhere: every address is reached from the anchor
 * chain or from an entity pointer already found through it.
 */
#ifndef LCORE_H
#define LCORE_H

#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <math.h>
#include "signeddrv_client.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ── 1. driver + address helpers ─────────────────────────────────────────── */
static uint64_t g_pid = 0, g_base = 0;
static uint32_t g_modSize = 0;
/* g_ioctl = 실제 드라이버 IOCTL 호출 수(클라이언트 카운터). 모듈이 g_ioctl=0 으로 리셋해 구간 측정. */
#define g_ioctl g_sd_ioctls

/* �T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T
 * �� IRON RULE (??) �� 2026-10-04 �� ?? ??
 * ������������������������������������������������������������������������������������������������������������������������������������������������������
 *   ??(LC.exe) ??? ??? ?? signeddrv.sys ? MmCopy ?? IOCTL,
 *   ? SignedReadMemory / SignedReadFast ?? ??.
 *
 *   rm()/q64()/d32()/f32() ? ?? ????, ??? ???? ???.
 *   ??: ReadProcessMemory / NtReadVirtualMemory / ???? deref(???)
 *         / ??? ??? ??? ??? ??? ?? / ???? ????.
 *   VirtualQueryEx ? "?? ??"?? ??, ???? ??? rm().
 *   ?? ??: rm �� SignedReadMemory �� IOCTL 0x222060 �� ?? MmCopyVirtualMemory.
 *   ??: 10_4_test/docs/IRON_RULE_MMCOPY.md
 * �T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T�T */
/* [DEV] 읽기 호출 분해 계측 (환경변수 LC_STATS=1 → stderr 전용, 출력/파일 불변) */
static unsigned long long gst_hdrS=0,gst_node=0,gst_vec=0,gst_hdrP=0,gst_pres=0,gst_acblk=0,gst_slot=0,gst_item=0,gst_io0=0,gst_n0=0,gst_n1=0;
static unsigned long long *gst_cur=0;
static int rm(uint64_t a, void *b, uint32_t s)
{
    uint64_t _b = (uint64_t)g_ioctl;
    uint32_t br = 0;
    int ok = SignedReadMemory(g_pid, a, b, s, &br) && br == s;
    if (gst_cur) *gst_cur += (unsigned long long)((uint64_t)g_ioctl - _b);
    return ok;
}
static uint64_t q64(uint64_t a) { uint64_t v = 0; rm(a, &v, 8); return v; }
static uint32_t d32(uint64_t a) { uint32_t v = 0; rm(a, &v, 4); return v; }
static float    f32(uint64_t a) { float    v = 0; rm(a, &v, 4); return v; }
static uint64_t LC_HEAP_LO=0x10000000000ULL, LC_HEAP_HI=0x80000000000ULL;
static int isHeap(uint64_t a) { return a >= LC_HEAP_LO && a < LC_HEAP_HI; }
static int isMod(uint64_t a)  { return a >= g_base && a < g_base + (uint64_t)g_modSize; }
static uint32_t vrva(uint64_t o) { uint64_t v = q64(o); return isMod(v) ? (uint32_t)(v - g_base) : 0; }

static int getModule(uint64_t *base, uint32_t *size)
{
    uint64_t peb = 0, ldr = 0, head = 0, cur = 0;
    if (!SignedGetPeb(g_pid, &peb) || !peb) return 0;
    if (!rm(peb + 0x18, &ldr, 8) || !ldr) return 0;
    if (!rm(ldr + 0x20, &head, 8) || !head) return 0;
    int g;
    for (cur = head, g = 0; g < 5000 && cur && cur != ldr + 0x20; g++) {
        uint64_t e = cur - 0x10, db = 0; uint32_t ds = 0;
        if (rm(e + 0x30, &db, 8) && db && rm(e + 0x40, &ds, 4) && ds) { *base = db; *size = ds; return 1; }
        if (!rm(cur, &cur, 8)) break;
    }
    return 0;
}

static int lc_attach(void)
{
    HANDLE snap = CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0);
    PROCESSENTRY32W pe; pe.dwSize = sizeof(pe);
    DWORD pid = 0;
    if (Process32FirstW(snap, &pe))
        do { if (_wcsicmp(pe.szExeFile, L"LC.exe") == 0) { pid = pe.th32ProcessID; break; } }
        while (Process32NextW(snap, &pe));
    CloseHandle(snap);
    if (!pid) { fprintf(stderr, "LC.exe not running\n"); return 1; }
    if (!SignedOpen()) { fprintf(stderr, "driver open failed (WinNotify)\n"); return 2; }
    SignedSetTarget(pid); g_pid = pid;
    if (!getModule(&g_base, &g_modSize)) { fprintf(stderr, "module base fail\n"); return 3; }
    return 0;
}

/* ── 2. constants (vft RVAs refreshed 2026-10-07 via RTTI; live-verified) ── */
#define VFT_SELF       0x11EC4C8u
#define VFT_PLAYER     0x11EC490u
#define VFT_MONSTER    0x11EC380u
#define VFT_SUMMON     0x11EC930u
#define VFT_ITEM       0x11EC2D8u
#define VFT_NPC        0x11EC2A0u
#define VFT_SEGPROP    0x11EC830u
#define VFT_ACTOR      0x11E88C8u
#define VFT_PRES_B     0x11EC1D8u   /* TransformComponent (PRES_B)          */
#define VFT_AC         0x11EB908u   /* ActionComponent                      */
/* ActionComponent state fields (RESULTS_T2 sec14 / 9.30 entity.c isDead) */
#define AC_DEAD_OFF   0x49u        /* byte  : 1 = dead/corpse              */
#define AC_DEAD_VAL   1
#define AC_BAIT_OFF   0x40u        /* dword : 0x78 = bait(dormant, not shown) */
#define AC_BAIT_VAL   0x78u
#define VFT_ATTACKACT  0x11EB490u   /* AttackAction  +0x80 owner +0x88 target */
#define VFT_DEATH      0x11EB400u
#define VFT_DEADBODY   0x11EB568u
#define VFT_MOVINGACT  0x11EB7B8u
#define VFT_MOVINGBACK 0x11EB770u
#define VFT_ACTIONBASE 0x11EB718u
#define VFT_SPELLACT   0x11EB3B8u
#define VFT_CHANGEDIR  0x11EB5B0u
#define VFT_CMDMOVE    0x11EBA50u
#define VFT_CMDATTACK  0x11EBBD0u
#define VFT_CMDINTERACT 0x11EBA88u
#define VFT_BREATHACT  0x11EB4D8u
#define VFT_MAPSUBSYS  0x1233630u   /* MapSubsystem   (live-verified)        */
#define VFT_ACTORSUBS  0x11E9430u   /* ActorSubsystem (live-verified)        */
#define VFT_BEHAVIORS 0x11C3620u   /* BehaviorSubsystem                    */
#define VFT_CTLCOMP   0x11C1828u   /* ActorControllerComponent             */
#define VFT_SHIP      0x11C2420u   /* Ship   (RTTI-indexed, +0x30)          */

/* ---- subsystems resolved OFFLINE by class-name lookup (delta_930.py) ----
 * These sit in the sub[64] array and are found by lc_subsGet(vft).  They are
 * RTTI-indexed in the 9.30 build (62 subsystems total), so the deltas below
 * are exact and were NOT guessed.  Regenerate on the next build with
 * T3_maps/delta_930.py -- game access is not required.                */
#define VFT_CHARDATA  0x11C5CC0u   /* CharacterDataSubsystem sub[12]  (+0xA0) */
#define VFT_INVENTORY 0x12079A0u   /* InventorySubsystem   sub[26]  (-0x370) */
#define VFT_HUDSLOT   0x11C3900u   /* HudSlotDataSubsystem sub[30]  (+0x78)  */
#define VFT_ITEMENT   0x1207430u   /* ItemEntity    (live-verified, no RTTI)  */
#define VFT_SHOP      0x120AE68u   /* ShopSubsystem             sub[36] (+0x88)  */
#define VFT_PLAYERSHOP 0x120A9B0u  /* PlayerShopSubsystem               (+0x? ) */
#define VFT_BUYITEM   0x121F740u   /* BuyListItem record           (+0x558)  */
#define VFT_SELLITEM  0x121F7A8u   /* SellListItem record          (+0x558)  */
#define VFT_EQUIPINFO 0x1207390u   /* EquipmentInfoSubsystem  (UI foothold)   */
#define VFT_DUNGEON   0x1206948u   /* DungeonSubsystem   (portal/dungeon)     */
#define VFT_SPELL     0x120BED8u   /* SpellSubsystem                            */
#define VFT_STORAGE   0x120C330u   /* StorageSubsystem                           */
#define VFT_BUFF      0x11FC5E8u   /* BuffSubsystem                              */
#define VFT_MAIL      0x11C3890u   /* MailSubsystem                              */
#define VFT_CAMERA    0x11CBD80u   /* CameraSubsystem                            */
#define VFT_INPUT     0x11C3380u   /* InputSubsystem                             */
#define VFT_GAMESTATE 0x11C34E0u   /* GameStateSubsystem                         */
#define VFT_NETWORK   0x11DAA28u   /* NetworkSubsystem                           */
#define VFT_CHAT      0x11FCC98u   /* ChatSubsystem                              */
#define VFT_PORTALACT 0x11C9AA0u   /* PortalInteraction (portal track)           */

/* enttrack / etview geometry */
#define LC_MGR    0x16BBAE0u
#define LC_HOLDER 0xD0u
#define LC_SUBB   0x180u
#define LC_PLAYER_X 0x16BB990u    /* was 0x1668710 (moved this build) */
#define LC_PLAYER_Y 0x16BB994u
static float LC_STEP_MS = 516.0f;  /* measured A->B commit period (registry CTRL_STEP_MS) */
static float LC_REF_H   = 600.0f;
static float LC_PPS   = 0.53f;
static float LC_VP_DX = 1.8f;
static float LC_VP_DY = 63.0f;
/* iso(등각) 좌표: U=U_SCALE*(cx+cy)-U_BIAS ; V=V_SCALE*(cx-cy) */
static float LC_U_SCALE = 48.0f, LC_U_BIAS = 3145680.0f, LC_V_SCALE = 24.0f;

/* ── 오프셋 런타임 변수 (registry 오버라이드 대상, SEC-3) ────────────────
 * 원칙: 구조 오프셋도 상수이므로 registry 단일출처에서 온다. 아래 기본값은
 * registry 부재 시 폴백이며 값은 종전 하드코딩과 동일하다(동작 불변). */
static uint32_t LC_ENT_SELF      = 0x08u, LC_ENT_GUID = 0x18u, LC_ENT_H = 0x20u;
static uint32_t LC_ENT_SPECIES   = 0x38u, LC_ENT_ITEM_FLAG = 0x48u;
static uint32_t LC_H_AC_OFF      = 0x10u, LC_H_NAME_OFF = 0x20u;
static uint32_t LC_NAME_BYTES    = 0x40u, LC_NAME_LEN = 0x50u;
static uint32_t LC_CELL_NEXT     = 0x08u, LC_CELL_VEC_BEG = 0x18u, LC_CELL_VEC_END = 0x20u;
static uint32_t LC_CELLMAP1      = 0x7A0u, LC_CELLMAP2 = 0x7E0u;
static uint32_t LC_PRESB_BASE    = 0x40u, LC_PRESB_A_OFF = 0x50u, LC_PRESB_B_OFF = 0x78u;
static uint32_t LC_PRESB_SCAN    = 0x200u;
static uint32_t LC_ACT_ATK_OWNER = 0x80u, LC_ACT_ATK_TARGET = 0x88u, LC_AC_SCAN = 0x140u;
static uint32_t LC_ITEM_OWN_BEG  = 0x10u, LC_ITEM_OWN_END = 0xC0u;
static uint32_t LC_ITEM_CONTRIB  = 0x44u;   /* ground item: 내 데미지 기여율(0~100) */
static uint32_t LC_LH_DELTA      = 8u;      /* 소스몹 guid 인접 허용(delta) */
static uint32_t LC_SUB_STRIDE    = 16u, LC_SUBCOUNT = 64u;
static uint32_t LC_MAP_CHILD     = 0x768u, LC_MAP_RECT_SCAN = 0x400u, LC_MAP_SCAN = 0x800u;
/* ActorSubsystem 셀맵 head 슬롯 (registry CELL_MAP_OFF1/2 로 갱신) */
static uint32_t LC_HEADS[2] = { 0x7A0u, 0x7E0u };
/* 10_8: 평면 액터 벡터 {Actor*,Comp*} (registry ACTOR_VEC_OFF/END). 열거 O(1)콜. */
static uint32_t LC_ACTOR_VEC_V = 0x8A8u, LC_ACTOR_VEC_END_V = 0x8B0u;

/* ���� registry ????? (??) ����������������������������������������������������������������������������������������
 * ??? #include "lcreg.h" ? ? lc_reg_apply() ? ????, registry ??
 * ? ??(#define/???)? ????. registry ??? ? ?? ??? ??.
 * (lcreg.h ??? ????? ????? __has_include ? ??) */
#if defined(__has_include)
#  if __has_include("lcreg.h")
#    include "lcreg.h"
#    define LC_HAS_REG 1
#  endif
#endif

static uint32_t LC_MGR_V     = LC_MGR;
static uint32_t LC_HOLDER_V  = LC_HOLDER;
static uint32_t LC_SUBB_V    = LC_SUBB;
static uint32_t LC_VFT_SELF  = VFT_SELF,   LC_VFT_PLAYER=VFT_PLAYER, LC_VFT_MONSTER=VFT_MONSTER;
static uint32_t LC_VFT_ITEM  = VFT_ITEM,   LC_VFT_NPC=VFT_NPC,       LC_VFT_SEGPROP=VFT_SEGPROP;
static uint32_t LC_VFT_ACTOR = VFT_ACTOR,  LC_VFT_SUMMON=VFT_SUMMON, LC_VFT_SHIP=VFT_SHIP;
static uint32_t LC_VFT_PRESB = VFT_PRES_B, LC_VFT_AC=VFT_AC,         LC_VFT_ATTACKACT=VFT_ATTACKACT;
static uint32_t LC_VFT_DEATH = VFT_DEATH,  LC_VFT_DEADBODY=VFT_DEADBODY;
static uint32_t LC_VFT_ACTORSUBS=VFT_ACTORSUBS, LC_VFT_MAPSUBSYS=VFT_MAPSUBSYS;
static uint32_t LC_AC_DEAD_OFF=AC_DEAD_OFF, LC_AC_DEAD_VAL=AC_DEAD_VAL;
static uint32_t LC_AC_BAIT_OFF=AC_BAIT_OFF, LC_AC_BAIT_VAL=AC_BAIT_VAL;
/* 향후 모듈용 서브시스템/컴포넌트 vft (SEC-2/SEC-3, registry 적용) */
static uint32_t LC_VFT_BREATHACT=VFT_BREATHACT, LC_VFT_CTLCOMP=VFT_CTLCOMP;
static uint32_t LC_VFT_MOVINGACT=VFT_MOVINGACT, LC_VFT_MOVINGBACK=VFT_MOVINGBACK;
static uint32_t LC_VFT_DAMAGEDACTION=0x11E0418u, LC_VFT_DAMAGEDREACTION=0x11E0460u;
static uint32_t LC_VFT_EFFECTACTION=0x11E02B0u;
static uint32_t LC_VFT_ACTIONBASE=VFT_ACTIONBASE, LC_VFT_SPELLACT=VFT_SPELLACT;
static uint32_t LC_VFT_CHANGEDIR=VFT_CHANGEDIR;
static uint32_t LC_VFT_CMDMOVE=VFT_CMDMOVE, LC_VFT_CMDATTACK=VFT_CMDATTACK, LC_VFT_CMDINTERACT=VFT_CMDINTERACT;
static uint32_t LC_H_CTL_OFF_V=0x90u, LC_CTL_CMD_OFF_V=0x58u;
static uint32_t LC_VFT_ITEMENT=VFT_ITEMENT, LC_VFT_SHOP=VFT_SHOP, LC_VFT_SPELL=VFT_SPELL;
static uint32_t LC_VFT_BUFF=VFT_BUFF, LC_VFT_HUDSLOT=VFT_HUDSLOT, LC_VFT_INVENTORY=VFT_INVENTORY;
static uint32_t LC_VFT_CHARDATA=VFT_CHARDATA, LC_VFT_DUNGEON=VFT_DUNGEON, LC_VFT_STORAGE=VFT_STORAGE;
static uint32_t LC_VFT_EQUIPINFO=VFT_EQUIPINFO, LC_VFT_MAIL=VFT_MAIL, LC_VFT_CAMERA=VFT_CAMERA;
static uint32_t LC_VFT_INPUT=VFT_INPUT, LC_VFT_GAMESTATE=VFT_GAMESTATE, LC_VFT_NETWORK=VFT_NETWORK;
static uint32_t LC_VFT_CHAT=VFT_CHAT, LC_VFT_PLAYERSHOP=VFT_PLAYERSHOP, LC_VFT_PORTALACT=VFT_PORTALACT;
static uint32_t LC_ENT_SELF_V=0x08u, LC_ENT_GUID_V=0x18u, LC_ENT_H_V=0x20u,
                LC_ENT_SPECIES_V=0x38u, LC_ENT_ITEM_FLAG_V=0x48u;
static uint32_t LC_H_AC_OFF_V=0x10u, LC_H_NAME_OFF_V=0x20u,
                LC_NAME_BYTES_V=0x40u, LC_NAME_LEN_V=0x50u;
static uint32_t LC_CELL_NEXT_V=0x08u, LC_CELL_VEC_BEG_V=0x18u,
                LC_CELL_VEC_END_V=0x20u;
static uint32_t LC_PRESB_BASE_V=0x40u, LC_PRESB_A_OFF_V=0x50u,
                LC_PRESB_B_OFF_V=0x78u, LC_PRESB_SCAN_V=0x200u,
                LC_PRESB_CELL_OFF_V=0x00u, LC_PRESB_CELL_DY_V=0x04u,
                LC_STR_SSO_MAX_V=0x10u;
static uint32_t LC_ACT_ATK_OWNER_V=0x80u, LC_ACT_ATK_TARGET_V=0x88u,
                LC_AC_SCAN_V=0x140u, LC_AC_ACTION_OFF=0xC0u, LC_AC_ACTION_WIN=0x20u;
static int LC_SELF_REVAL_TICKS = 32; /* bodyact FAST: sticky AC/CTL re-resolve ticks */
/* ── Door(문) 개폐 상태 (2026-10-19 확정 · 동적 전이 관측) ───────────────
 *  Door = InteractiveNPC 중 종(SPECIES)=DOOR_SP(8) 이거나 이름="Door".
 *  [상태] ActionComponent + DOOR_STATE_OFF(0xD8) dword: 0x1C=열림 / 0x1D=닫힘
 *     근거: 같은 문 C6C 가 1D(닫힘)→1C(열림)→1D(닫힘) 로 실시간 전이.
 *  [종류] Presentation + DOOR_GFX_OFF(0x38) dword: 0x800A=여닫이 / 0x8009=고정(열 수 없음)
 *     근거: C6C 가 개폐를 오가는 동안 gfx 불변 → 상태 아님.
 *  (registry DOOR_* 주석 / docs/DOOR_STATE.md) */
static char     LC_DOOR_NAME[32]   = "Door";
static uint32_t LC_DOOR_SP_V       = 8;
static uint32_t LC_DOOR_STATE_OFF_V= 0xD8u;
static uint32_t LC_DOOR_STATE_OPEN = 0x1Cu;
static uint32_t LC_DOOR_STATE_CLOSED=0x1Du;
static uint32_t LC_DOOR_GFX_OFF_V  = 0x38u;
static uint32_t LC_DOOR_GFX_NORMAL = 0x800Au;
static uint32_t LC_DOOR_GFX_LOCKED = 0x8009u;
static uint32_t LC_DOOR_AC_FLAG_V  = 0x108u;
static uint32_t LC_ITEM_OWN_BEG_V=0x10u, LC_ITEM_OWN_END_V=0xC0u;
/* ── [2026-10-14.6] 플레이 과정 오프셋 (Actor 객체 자체 기준) ──────────────
 *  주의: 위의 LC_AC_* / LC_ACT_* 는 ActionComponent(=Actor+0x10) 기준이라
 *  아래와 '다른 좌표계'다. 혼용하지 않는다.
 *  근거: ATS bt::FindTarget / MoveToTarget / Interact / UseBuff 가 실제로 읽는
 *        필드를 라이브 디스어셈블로 확인 (docs/ATS_MODULE.md §7).
 *
 *  이동     : ENT_X/ENT_Y 월드좌표, ENT_ATKRANGE 공격사거리
 *  공격     : ENT_ATKRANGE, ENT_ACTLIST(주변 액터 목록)
 *  피격/사망: ENT_SEL_FLAG_A/B (후보 선별·사망 판정 바이트)
 *  스펠사용 : ENT_BUFF_BEG/END (버프 목록), ENT_BUFF_ID (버프 ID)
 */
static uint32_t LC_ENT_SEL_FLAG_A_V=0x46u, LC_ENT_SEL_FLAG_B_V=0x47u;
static uint32_t LC_ENT_ATKRANGE_V   =0x590u;
static uint32_t LC_ENT_BUFF_BEG_V   =0x438u, LC_ENT_BUFF_END_V=0x440u;
static uint32_t LC_ENT_BUFF_ID_V    =0x08u;
static uint32_t LC_ENT_X_V          =0x844u, LC_ENT_Y_V=0x848u;
static uint32_t LC_ENT_ACTLIST_BEG_V=0x8A8u, LC_ENT_ACTLIST_END_V=0x8B0u;
static uint32_t LC_SUB_STRIDE_V=16u, LC_SUBCOUNT_V=64u;
static uint32_t LC_MAP_CHILD_V=0x768u, LC_MAP_RECT_SCAN_V=0x400u,
                LC_MAP_SCAN_V=0x800u;
static int LC_SWEEP_EVERY = 2;   /* 셀맵 구조 스윕 주기(프레임): 1=매프레임, 2=2프레임에 1회 */
/* ── 10_8 엔티티 읽기 분리: 스냅샷(읽기) 주기를 소비(렌더/출력) 루프에서 분리 ──
 * 소비 루프가 빠르게(øFPS) 돌아도 드라이버 읽기는 이 주기로만 일어난다. */
static uint32_t LC_READ_INTERVAL_MS = 200;  /* 스냅샷 갱신 주기(ENT_READ_INTERVAL_MS) */
static uint32_t LC_READ_JITTER_MS   = 30;   /* 주기 지터(ENT_READ_JITTER_MS) */
/* 10_8: 전투(근접 몬스터) 시에만 엔티티 폴링 3배 상향, 이탈 시 복귀. */
static uint32_t LC_READ_COMBAT_MS   = 66;    /* 전투 주기(ENT_READ_INTERVAL_COMBAT_MS) */
static uint32_t LC_COMBAT_CELLS     = 12;    /* 근접 판정 셀 반경(ENT_COMBAT_CELLS) */
static uint32_t LC_COMBAT_HOLD_MS   = 1500;  /* 이탈 후 유지(ENT_COMBAT_HOLD_MS) */
static DWORD    lc_combatUntil = 0;          /* 전투 활성 만료 시각 */
static int      lc_combatOn = 0;             /* 진단용 */
static uint32_t LC_SWEEP_MS         = 400;  /* 셀맵 구조 스윕 주기 ms(ENT_SWEEP_MS) */

#ifdef LC_HAS_REG
static void lc_reg_apply(void){
    if(!LCREG_N) return;
    LC_MGR_V      = lcreg_u32("MGR", LC_MGR_V);
    LC_HOLDER_V   = lcreg_u32("HOLDER_OFF", LC_HOLDER_V);
    LC_SUBB_V     = lcreg_u32("SUBB", LC_SUBB_V);
    LC_VFT_SELF   = lcreg_u32("VFT_SELF", LC_VFT_SELF);
    LC_VFT_PLAYER = lcreg_u32("VFT_PLAYER", LC_VFT_PLAYER);
    LC_VFT_MONSTER= lcreg_u32("VFT_MONSTER", LC_VFT_MONSTER);
    LC_VFT_ITEM   = lcreg_u32("VFT_ITEM", LC_VFT_ITEM);
    LC_VFT_NPC    = lcreg_u32("VFT_NPC", LC_VFT_NPC);
    LC_VFT_SEGPROP= lcreg_u32("VFT_SEGPROP", LC_VFT_SEGPROP);
    LC_VFT_ACTOR  = lcreg_u32("VFT_ACTOR", LC_VFT_ACTOR);
    LC_VFT_SUMMON = lcreg_u32("VFT_SUMMON", LC_VFT_SUMMON);
    LC_VFT_SHIP   = lcreg_u32("VFT_SHIP", LC_VFT_SHIP);
    LC_VFT_PRESB  = lcreg_u32("VFT_PRES_B", LC_VFT_PRESB);
    LC_VFT_AC     = lcreg_u32("VFT_AC", LC_VFT_AC);
    LC_VFT_ATTACKACT=lcreg_u32("VFT_ATTACKACT", LC_VFT_ATTACKACT);
    LC_VFT_DEATH  = lcreg_u32("VFT_DEATH", LC_VFT_DEATH);
    LC_VFT_DEADBODY=lcreg_u32("VFT_DEADBODY", LC_VFT_DEADBODY);
    LC_VFT_ACTORSUBS=lcreg_u32("VFT_ACTORSUBS", LC_VFT_ACTORSUBS);
    LC_VFT_MAPSUBSYS=lcreg_u32("VFT_MAPSUBS", LC_VFT_MAPSUBSYS);
    LC_AC_DEAD_OFF= lcreg_u32("AC_DEAD_OFF", LC_AC_DEAD_OFF);
    LC_AC_DEAD_VAL= lcreg_u32("AC_DEAD_VAL", LC_AC_DEAD_VAL);
    LC_AC_BAIT_OFF= lcreg_u32("AC_BAIT_OFF", LC_AC_BAIT_OFF);
    LC_AC_BAIT_VAL= lcreg_u32("AC_BAIT_VAL", LC_AC_BAIT_VAL);
    /* 추가 서브시스템/컴포넌트 vft */
    LC_VFT_BREATHACT=lcreg_u32("VFT_BREATHACT", LC_VFT_BREATHACT);
    LC_VFT_MOVINGACT=lcreg_u32("VFT_MOVINGACT", LC_VFT_MOVINGACT);
    LC_VFT_DAMAGEDACTION=lcreg_u32("VFT_DAMAGEDACTION", LC_VFT_DAMAGEDACTION);
    LC_VFT_DAMAGEDREACTION=lcreg_u32("VFT_DAMAGEDREACTION", LC_VFT_DAMAGEDREACTION);
    LC_VFT_EFFECTACTION=lcreg_u32("VFT_EFFECTACTION", LC_VFT_EFFECTACTION);
    LC_VFT_MOVINGBACK=lcreg_u32("VFT_MOVINGBACK", LC_VFT_MOVINGBACK);
    LC_VFT_ACTIONBASE=lcreg_u32("VFT_ACTIONBASE", LC_VFT_ACTIONBASE);
    LC_VFT_SPELLACT=lcreg_u32("VFT_SPELLACT", LC_VFT_SPELLACT);
    LC_VFT_CHANGEDIR=lcreg_u32("VFT_CHANGEDIR", LC_VFT_CHANGEDIR);
    LC_VFT_CMDMOVE=lcreg_u32("VFT_CMDMOVE", LC_VFT_CMDMOVE);
    LC_VFT_CMDATTACK=lcreg_u32("VFT_CMDATTACK", LC_VFT_CMDATTACK);
    LC_VFT_CMDINTERACT=lcreg_u32("VFT_CMDINTERACT", LC_VFT_CMDINTERACT);
    LC_H_CTL_OFF_V=lcreg_u32("H_CTL_OFF", LC_H_CTL_OFF_V);
    LC_CTL_CMD_OFF_V=lcreg_u32("CTL_CMD_OFF", LC_CTL_CMD_OFF_V);
    LC_VFT_CTLCOMP  =lcreg_u32("VFT_ACTORCTL",  LC_VFT_CTLCOMP);
    LC_VFT_ITEMENT  =lcreg_u32("ITEM_VFT",      LC_VFT_ITEMENT);
    LC_VFT_SHOP     =lcreg_u32("VFT_SHOP",      LC_VFT_SHOP);
    LC_VFT_SPELL    =lcreg_u32("VFT_SPELL",     LC_VFT_SPELL);
    LC_VFT_BUFF     =lcreg_u32("VFT_BUFF",      LC_VFT_BUFF);
    LC_VFT_HUDSLOT  =lcreg_u32("VFT_HUDSLOT",   LC_VFT_HUDSLOT);
    LC_VFT_INVENTORY=lcreg_u32("VFT_INVENTORY", LC_VFT_INVENTORY);
    LC_VFT_CHARDATA =lcreg_u32("VFT_CHARDATA",  LC_VFT_CHARDATA);
    LC_VFT_DUNGEON  =lcreg_u32("VFT_DUNGEON",   LC_VFT_DUNGEON);
    LC_VFT_STORAGE  =lcreg_u32("VFT_STORAGE",   LC_VFT_STORAGE);
    LC_VFT_EQUIPINFO=lcreg_u32("VFT_EQUIPINFO", LC_VFT_EQUIPINFO);
    LC_VFT_MAIL     =lcreg_u32("VFT_MAIL",      LC_VFT_MAIL);
    LC_VFT_CAMERA   =lcreg_u32("VFT_CAMERA",    LC_VFT_CAMERA);
    LC_VFT_INPUT    =lcreg_u32("VFT_INPUT",     LC_VFT_INPUT);
    LC_VFT_GAMESTATE=lcreg_u32("VFT_GAMESTATE", LC_VFT_GAMESTATE);
    LC_VFT_NETWORK  =lcreg_u32("VFT_NETWORK",   LC_VFT_NETWORK);
    LC_VFT_CHAT     =lcreg_u32("VFT_CHAT",      LC_VFT_CHAT);
    LC_VFT_PLAYERSHOP=lcreg_u32("VFT_PLAYERSHOP",LC_VFT_PLAYERSHOP);
    LC_VFT_PORTALACT=lcreg_u32("VFT_PORTALACT", LC_VFT_PORTALACT);
    /* 구조 오프셋 (SEC-3) */
    LC_ENT_SELF_V    =lcreg_u32("ENT_SELF",    LC_ENT_SELF_V);
    LC_ENT_GUID_V    =lcreg_u32("ENT_GUID",    LC_ENT_GUID_V);
    LC_ENT_H_V       =lcreg_u32("ENT_H",       LC_ENT_H_V);
    LC_ENT_SPECIES_V =lcreg_u32("ENT_SPECIES", LC_ENT_SPECIES_V);
    LC_ENT_ITEM_FLAG_V=lcreg_u32("ENT_ITEM_FLAG",LC_ENT_ITEM_FLAG_V);
    LC_H_AC_OFF_V    =lcreg_u32("H_AC_OFF",    LC_H_AC_OFF_V);
    LC_H_NAME_OFF_V  =lcreg_u32("NAME_H",      LC_H_NAME_OFF_V);
    LC_NAME_BYTES_V  =lcreg_u32("NAME_BYTES",  LC_NAME_BYTES_V);
    LC_NAME_LEN_V    =lcreg_u32("NAME_LEN",    LC_NAME_LEN_V);
    LC_CELL_NEXT_V   =lcreg_u32("CELL_NEXT",   LC_CELL_NEXT_V);
    LC_CELL_VEC_BEG_V=lcreg_u32("CELL_VEC_BEG",LC_CELL_VEC_BEG_V);
    LC_CELL_VEC_END_V=lcreg_u32("CELL_VEC_END",LC_CELL_VEC_END_V);
    LC_HEADS[0]      =lcreg_u32("CELL_MAP_OFF1", LC_HEADS[0]);
    LC_HEADS[1]      =lcreg_u32("CELL_MAP_OFF2", LC_HEADS[1]);
    LC_ACTOR_VEC_V     =lcreg_u32("ACTOR_VEC_OFF", LC_ACTOR_VEC_V);
    LC_ACTOR_VEC_END_V =lcreg_u32("ACTOR_VEC_END", LC_ACTOR_VEC_END_V);
    LC_PRESB_BASE_V  =lcreg_u32("PRESB_BATCH_BASE", LC_PRESB_BASE_V);
    LC_PRESB_A_OFF_V =lcreg_u32("PRESB_A_OFF", LC_PRESB_A_OFF_V);
    LC_PRESB_B_OFF_V =lcreg_u32("PRESB_B_OFF", LC_PRESB_B_OFF_V);
    LC_PRESB_SCAN_V  =lcreg_u32("PRESB_SCAN_LEN", LC_PRESB_SCAN_V);
    LC_PRESB_CELL_OFF_V=lcreg_u32("PRESB_CELL_OFF", LC_PRESB_CELL_OFF_V);
    LC_PRESB_CELL_DY_V =lcreg_u32("PRESB_CELL_DY",  LC_PRESB_CELL_DY_V);
    LC_STR_SSO_MAX_V   =lcreg_u32("STR_SSO_MAX",    LC_STR_SSO_MAX_V);
    LC_HEAP_LO         =lcreg_u64("HEAP_LO",        LC_HEAP_LO);
    LC_HEAP_HI         =lcreg_u64("HEAP_HI",        LC_HEAP_HI);
    LC_ACT_ATK_OWNER_V=lcreg_u32("ACT_ATK_OWNER", LC_ACT_ATK_OWNER_V);
    LC_ACT_ATK_TARGET_V=lcreg_u32("ACT_ATK_TARGET", LC_ACT_ATK_TARGET_V);
    LC_AC_SCAN_V     =lcreg_u32("AC_SCAN_LEN", LC_AC_SCAN_V);
    LC_AC_ACTION_OFF =lcreg_u32("AC_ACTION_OFF", LC_AC_ACTION_OFF);
    LC_SELF_REVAL_TICKS = (int)lcreg_u32("POLL_BODYACT_REVAL_TICKS", (uint32_t)LC_SELF_REVAL_TICKS);
    LC_AC_ACTION_WIN =lcreg_u32("AC_ACTION_WIN", LC_AC_ACTION_WIN);
    LC_ITEM_OWN_BEG_V=lcreg_u32("ITEM_OWN_SCAN_BEG", LC_ITEM_OWN_BEG_V);
    LC_ITEM_OWN_END_V=lcreg_u32("ITEM_OWN_SCAN_END", LC_ITEM_OWN_END_V);
    /* [2026-10-19] Door 개폐 상태 */
    { const char *dn = lcreg_str("DOOR_NAME", LC_DOOR_NAME);
      if (dn && dn[0]){ strncpy(LC_DOOR_NAME, dn, sizeof(LC_DOOR_NAME) - 1);
                        LC_DOOR_NAME[sizeof(LC_DOOR_NAME) - 1] = 0; } }
    LC_DOOR_SP_V      = lcreg_u32("DOOR_SP", LC_DOOR_SP_V);
    LC_DOOR_STATE_OFF_V = lcreg_u32("DOOR_STATE_OFF", LC_DOOR_STATE_OFF_V);
    LC_DOOR_STATE_OPEN  = lcreg_u32("DOOR_STATE_OPEN", LC_DOOR_STATE_OPEN);
    LC_DOOR_STATE_CLOSED= lcreg_u32("DOOR_STATE_CLOSED", LC_DOOR_STATE_CLOSED);
    LC_DOOR_GFX_OFF_V = lcreg_u32("DOOR_GFX_OFF", LC_DOOR_GFX_OFF_V);
    LC_DOOR_GFX_NORMAL= lcreg_u32("DOOR_GFX_NORMAL", LC_DOOR_GFX_NORMAL);
    LC_DOOR_GFX_LOCKED= lcreg_u32("DOOR_GFX_LOCKED", LC_DOOR_GFX_LOCKED);
    LC_DOOR_AC_FLAG_V = lcreg_u32("DOOR_AC_FLAG_OFF", LC_DOOR_AC_FLAG_V);
    /* [2026-10-14.6] 플레이 과정 (Actor 기준) */
    LC_ENT_SEL_FLAG_A_V =lcreg_u32("ENT_SEL_FLAG_A",   LC_ENT_SEL_FLAG_A_V);
    LC_ENT_SEL_FLAG_B_V =lcreg_u32("ENT_SEL_FLAG_B",   LC_ENT_SEL_FLAG_B_V);
    LC_ENT_ATKRANGE_V   =lcreg_u32("ENT_ATK_RANGE",    LC_ENT_ATKRANGE_V);
    LC_ENT_BUFF_BEG_V   =lcreg_u32("ENT_BUFF_BEG",     LC_ENT_BUFF_BEG_V);
    LC_ENT_BUFF_END_V   =lcreg_u32("ENT_BUFF_END",     LC_ENT_BUFF_END_V);
    LC_ENT_BUFF_ID_V    =lcreg_u32("ENT_BUFF_ID_OFF",  LC_ENT_BUFF_ID_V);
    LC_ENT_X_V          =lcreg_u32("ENT_ACT_X",        LC_ENT_X_V);
    LC_ENT_Y_V          =lcreg_u32("ENT_ACT_Y",        LC_ENT_Y_V);
    LC_ENT_ACTLIST_BEG_V=lcreg_u32("ENT_ACTLIST_BEG",  LC_ENT_ACTLIST_BEG_V);
    LC_ENT_ACTLIST_END_V=lcreg_u32("ENT_ACTLIST_END",  LC_ENT_ACTLIST_END_V);
    LC_ITEM_CONTRIB  =lcreg_u32("OFF_ITEM_CONTRIB",  LC_ITEM_CONTRIB);
    LC_LH_DELTA      =lcreg_u32("LH_DELTA_MAX",      LC_LH_DELTA);
    LC_SUB_STRIDE_V  =lcreg_u32("SUB_STRIDE",  LC_SUB_STRIDE_V);
    LC_SUBCOUNT_V    =lcreg_u32("SUBCOUNT",    LC_SUBCOUNT_V);
    LC_MAP_CHILD_V   =lcreg_u32("MAP_CHILD_OFF", LC_MAP_CHILD_V);
    LC_MAP_RECT_SCAN_V=lcreg_u32("MAP_RECT_SCAN_LEN", LC_MAP_RECT_SCAN_V);
    LC_MAP_SCAN_V    =lcreg_u32("MAP_SCAN_LEN", LC_MAP_SCAN_V);
    LC_SWEEP_EVERY   =(int)lcreg_u32("ENT_SWEEP_EVERY", (uint32_t)LC_SWEEP_EVERY); if(LC_SWEEP_EVERY<1) LC_SWEEP_EVERY=1;
    LC_READ_INTERVAL_MS = lcreg_u32("ENT_READ_INTERVAL_MS", LC_READ_INTERVAL_MS);
    LC_READ_JITTER_MS   = lcreg_u32("ENT_READ_JITTER_MS",   LC_READ_JITTER_MS);
    LC_READ_COMBAT_MS   = lcreg_u32("ENT_READ_INTERVAL_COMBAT_MS", LC_READ_COMBAT_MS);
    LC_COMBAT_CELLS     = lcreg_u32("ENT_COMBAT_CELLS",     LC_COMBAT_CELLS);
    LC_COMBAT_HOLD_MS   = lcreg_u32("ENT_COMBAT_HOLD_MS",   LC_COMBAT_HOLD_MS);
    LC_SWEEP_MS         = lcreg_u32("ENT_SWEEP_MS",         LC_SWEEP_MS);
    LC_STEP_MS = (float)lcreg_f("CTRL_STEP_MS", LC_STEP_MS);
    LC_REF_H   = (float)lcreg_f("REF_H", LC_REF_H);
    LC_U_SCALE = (float)lcreg_f("ISO_U_SCALE", LC_U_SCALE);
    LC_U_BIAS  = (float)lcreg_f("ISO_U_BIAS",  LC_U_BIAS);
    LC_V_SCALE = (float)lcreg_f("ISO_V_SCALE", LC_V_SCALE);
    LC_PPS   = (float)lcreg_f("PPS", LC_PPS);
    LC_VP_DX = (float)lcreg_f("VP_DX", LC_VP_DX);
    LC_VP_DY = (float)lcreg_f("VP_DY", LC_VP_DY);
}
#endif

static const char *clsOf(uint32_t v)
{
    if (v == LC_VFT_SELF)    return "MyPlayer";
    if (v == LC_VFT_PLAYER)  return "Player";
    if (v == LC_VFT_MONSTER) return "Monster";
    if (v == LC_VFT_SUMMON)  return "Summon";
    if (v == LC_VFT_ITEM)    return "Item";
    if (v == LC_VFT_NPC)     return "NPC";
    if (v == LC_VFT_SEGPROP) return "SegmentProp";
    if (v == LC_VFT_ACTOR)   return "Actor";
    if (v == LC_VFT_SHIP)    return "Ship";
    return "?";
}
static int isEntVft(uint32_t v)
{
    return v == LC_VFT_SELF || v == LC_VFT_PLAYER || v == LC_VFT_MONSTER || v == LC_VFT_SUMMON ||
           v == LC_VFT_ITEM || v == LC_VFT_NPC || v == LC_VFT_SEGPROP || v == LC_VFT_ACTOR;
}
static int isActorish(uint32_t v)
{
    return v == LC_VFT_SELF || v == LC_VFT_PLAYER || v == LC_VFT_MONSTER || v == LC_VFT_SUMMON || v == LC_VFT_ACTOR;
}

/* ── 3. entity record: raw A/B + interpolated iso (enttrack model) ───────── */
typedef struct {
    uint64_t e, guid, presB, ac;
    uint32_t vft;
    uint32_t sp;            /* species: d32(e+ENT_SPECIES) */
    int      cellx, celly;
    float    aU, aV;        /* PRES_B +0x50 / +0x54  (A = committed) */
    float    bU, bV;        /* PRES_B +0x78 / +0x7C  (B = next target) */
    float    iU, iV;        /* interpolated (A + (B-A) * t), t = dt/516ms */
    DWORD    aTime;         /* when A last changed */
    int      aInit, hasIso;
    int      dead;
    int      bait;          /* AC+0x40 dword == 0x78 => bait/dormant (not shown) */
    uint64_t atkOwner, atkTgt; int hasAtk;
    /* [ATS 10_8] 읽기 전용 확장: 공격유효성/장애물/사망출처.
     * 기존 필드/양식은 그대로. 아래는 추가 출력용. */
    int      atkValid;      /* 1=attackable 0=no -1=unknown (targetinfo flags) */
    int      atkBlocked;    /* 1=LOS blocked (targetinfo flag B) */
    uint8_t  tgtFlagA;      /* targetinfo +0x46 */
    uint8_t  tgtFlagB;      /* targetinfo +0x47 */
    uint8_t  actorFlag59a;  /* actor +0x59A */
    int      deadSrc;       /* 1=AC+0x49  2=Death/DeadBody vft  0=alive */
    uint32_t itemType, itemQty;
    uint64_t itemOwner;      /* ground-item owner GUID (0 = free/no owner)   */
    int      itemOwnerSeen;  /* 1 = ownership slot scanned this frame        */
    uint32_t itemFlag;       /* +0x48 ownership/lock-state flag (0=free)     */
    uint32_t itemContrib;    /* +OFF_ITEM_CONTRIB : 내 데미지 기여율(0~100)   */
    int      itemOwn;        /* 0=n/a 1=MINE 2=OTHER 3=FREE                  */
    uint32_t bodyAct;        /* ActionComponent+AC_ACTION_OFF object vft (RVA) */
    uint32_t cmdVft;         /* ActorController+CTL_CMD_OFF command vft (RVA) */
    char     nm[80];
    int      spawnMs;       /* GetTickCount() when first seen */
    /* ���� ?? ?? (self ??, lc_derive ? ???) ���� */
    float    distIso;       /* self?? ??? ??(??, ????) */
    float    distTile;      /* self?? ??(?) ?? (????) */
    int      dCellX, dCellY;/* self ?? ? ?? */
    int      worldTx, worldTy; /* ?? ?? ?? (cellx,celly ??) */
    /* ????: A=??(aU/aV ??), I=??(iU/iV ??) */
    int      scrAX, scrAY;  /* ?? ???? */
    int      scrIX, scrIY;  /* ?? ???? */
    int      scrDX, scrDY;  /* ?? ???? ??(self=0,0) */
    /* [2026-10-19] Door(문) 전용 — 스냅샷에서 1회만 읽어 채운다(추가 IOCTL 0 목표) */
    int      doorState;     /* 0=닫힘 1=열림 2=미상 -1=문 아님 */
    uint32_t doorFrame;     /* AC+DOOR_STATE_OFF  (0x1C=열림/0x1D=닫힘) */
    uint32_t doorGfx;       /* PRES+DOOR_GFX_OFF  (문 종류: 0x800A/0x8009) */
    int      doorLocked;    /* 1 = 열 수 없는(고정) 문(종류=DOOR_GFX_LOCKED) */
    int      doorSeen;      /* 1 = 이번 스냅샷에서 문 판독을 수행함 */
} LC_E;

#define LC_MAXE 512
static uint32_t LC_ATK_RANGE_TILES = 10u;  /* registry ATK_RANGE_TILES */
static LC_E *lc_findCur(uint64_t guid);    /* fwd decl (defined below) */
static LC_E lc_cur[LC_MAXE]; static int lc_nc = 0;
static LC_E lc_prev[LC_MAXE]; static int lc_npc = 0;
static uint64_t lc_meGuid = 0, lc_meE = 0;
static uint64_t lc_actor = 0;
static int lc_dbg = 0;

/* slow-sweep ledger cache: keyed by entity pointer, avoids re-reading
 * names / component pointers on every fast poll (enttrack slow sweep). */
typedef struct {
    uint64_t e, guid, presB, ac;
    uint32_t vft;
    int      hasName, hasAc, seenGen;
    char     nm[80];
    /* A/B interpolation state: MUST persist across fast polls (lc_cur is rebuilt
     * every poll, so storing this in LC_E would reset it and kill interpolation) */
    float    aU, aV, bU, bV;
    DWORD    aTime;
    int      aInit;
    /* 10_8 AC 변경감지 캐시: 슬롯 구성 지문이 같으면 vft 재스캔 생략 */
    uint64_t acFp; int hasAcFp;
    uint8_t  cDead, cHasAtk; uint64_t cAtkOwner, cAtkTgt;
    uint32_t cBodyAct, cCmdVft;
} LC_LED;
#define LC_MAXLED 1024
static LC_LED lc_led[LC_MAXLED];
static int lc_ledN = 0, lc_gen = 0;
static unsigned long long lc_sweepCount = 0;

/* Subsystem lookup.
 *
 * The 9.30 patch reordered the subsystem array, so sub[22]/sub[23] no longer
 * carry ActorSubsystem/MapSubsystem (verified live: sub[22] vft = 0x11BF2D8).
 * Subsystems must therefore be identified by their RTTI vtable, never by
 * index. LC_SUBIDX is kept only as a hint for diagnostics.
 */
#define LC_SUBIDX 64
static uint64_t lc_subs = 0;      /* subsystem array base (16-byte stride)  */
static uint32_t lc_subsCacheV[256]; static uint64_t lc_subsCacheP[256]; static int lc_subsCacheN = 0;
static int lc_subsCursor = 0;
static void lc_subsCacheAdd(uint32_t v, uint64_t s)
{
    if (!v || lc_subsCacheN >= 256) return;
    for (int i = 0; i < lc_subsCacheN; i++) if (lc_subsCacheV[i] == v) return;
    lc_subsCacheV[lc_subsCacheN] = v; lc_subsCacheP[lc_subsCacheN] = s; lc_subsCacheN++;
}
static uint64_t lc_subsGet(uint32_t wantVft)
{
    /* 10_8: vft→포인터 캐시 + 스캔 커서. 지나온 서브시스템을 전부 캐시하므로
     * 앵커가 ACTORSUBS(idx≈22)까지 스캔하면 그 이하 인덱스(예 CHARDATA 13)는 무료. */
    for (int c = 0; c < lc_subsCacheN; c++)
        if (lc_subsCacheV[c] == wantVft && isHeap(lc_subsCacheP[c])) return lc_subsCacheP[c];
    if (!lc_subs) return 0;
    while (lc_subsCursor < (int)LC_SUBCOUNT_V) {
        int i = lc_subsCursor++;
        uint64_t s = q64(lc_subs + (uint64_t)LC_SUB_STRIDE_V * i);
        if (!isHeap(s)) continue;
        uint32_t v1 = vrva(s), v2 = vrva(s + 8);
        lc_subsCacheAdd(v1, s); if (v2 != v1) lc_subsCacheAdd(v2, s);
        if (v1 == wantVft || v2 == wantVft) return s;
    }
    return 0;
}
static int lc_anchor(void)
{
    uint64_t mgr = q64(g_base + LC_MGR_V);
    if (!isHeap(mgr)) return 0;
    uint64_t holder = q64(mgr + LC_HOLDER_V);
    if (!isHeap(holder)) return 0;
    uint64_t subs = q64(holder + LC_SUBB_V);
    if (!isHeap(subs)) return 0;
    lc_subs = subs;
    lc_subsCacheN = 0; lc_subsCursor = 0;     /* 10_8: 앵커 재해석 시 캐시/커서 무효화 */
    uint64_t actor = lc_subsGet(LC_VFT_ACTORSUBS);
    if (!actor) return 0;
    lc_actor = actor;
    return 1;
}

static LC_LED *lc_ledFind(uint64_t e, int create)
{
    for (int i = 0; i < lc_ledN; i++) if (lc_led[i].e == e) return &lc_led[i];
    if (!create || lc_ledN >= LC_MAXLED) return NULL;
    LC_LED *L = &lc_led[lc_ledN++];
    memset(L, 0, sizeof(*L));
    L->e = e;
    return L;
}

static int lc_name(uint64_t e, char *out, int cap)
{
    out[0] = 0;
    uint64_t H = q64(e + LC_ENT_H_V);          if (!isHeap(H))  return 0;
    uint64_t no = q64(H + LC_H_NAME_OFF_V);    if (!isHeap(no)) return 0;
    uint64_t len = q64(no + LC_NAME_LEN_V);
    if (len == 0 || len > (uint64_t)cap - 1 || len > 200) return 0;
    uint64_t src = (len >= LC_STR_SSO_MAX_V) ? q64(no + LC_NAME_BYTES_V) : (no + LC_NAME_BYTES_V);
    if (!rm(src, out, (uint32_t)len)) { out[0] = 0; return 0; }
    out[len] = 0; return 1;
}
static uint64_t lc_findPresB(uint64_t e)
{
    uint64_t H = q64(e + LC_ENT_H_V);
    if (!isHeap(H)) return 0;
    for (uint32_t o = 0; o < LC_PRESB_SCAN_V; o += 8) {
        uint64_t c = q64(H + o);
        if (isHeap(c) && (vrva(c) == LC_VFT_PRESB)) return c;
    }
    return 0;
}

/* 10_8: 엔티티 후보 1개 처리(중복제거 -> 헤더 검증 -> 원장 갱신 -> ptrs 추가). */
static void lc_addEnt(uint64_t e, uint64_t *ptrs, int *np, int maxP)
{
    if (*np >= maxP || !isHeap(e)) return;
    for (int k = 0; k < *np; k++) if (ptrs[k] == e) return;
    uint8_t hb[0x50];
    gst_cur=&gst_hdrS; int _okh=lc_pgRead(e, hb, sizeof hb); gst_cur=0; if (!_okh) return;
    if (*(uint64_t *)(hb + LC_ENT_SELF_V) != e) return;
    uint64_t vftp = *(uint64_t *)hb;
    uint32_t v = isMod(vftp) ? (uint32_t)(vftp - g_base) : 0;
    if (!isEntVft(v)) return;
    LC_LED *L = lc_ledFind(e, 1);
    if (L) {
        L->seenGen = lc_gen;
        if (!L->vft)          L->vft = v;
        if (!L->hasName)      { if (lc_name(e, L->nm, sizeof(L->nm))) L->hasName = 1; }
        if (!L->guid)         L->guid = *(uint64_t *)(hb + LC_ENT_GUID_V);
        if (!L->presB)        L->presB = lc_findPresB(e);
        if (!L->hasAc) {
            uint64_t H = *(uint64_t *)(hb + LC_ENT_H_V);
            uint64_t ac = isHeap(H) ? q64(H + LC_H_AC_OFF_V) : 0;
            if (isHeap(ac) && vrva(ac) == LC_VFT_AC) { L->ac = ac; L->hasAc = 1; }
        }
    }
    ptrs[(*np)++] = e;
}

static uint8_t lc_vbuf[4096]; static uint64_t lc_vbase = ~0ull;   /* 10_8: 노드 벡터 배치 캐시 */
/* walk the cellmap once: refresh the ledger for every entity present.
 * returns the number of entities; fills e-list of pointers into ptrs[]. */
static int lc_sweepSlow(uint64_t *ptrs, int maxP)
{
    lc_gen++;
    lc_vbase = ~0ull;                       /* 10_8: 벡터 배치 캐시 리셋 */
    int n = 0;

    /* 경로 A: 평면 액터 벡터(ActorSubsystem +ACTOR_VEC_OFF). 짝수 슬롯=Actor*.
     * 성공하면 셀맵 워크를 생략(열거 O(1)콜). 실패 시 경로 B 폴백. */
    int viavec = 0;
    {   /* [DEV] LC_NOVEC=1 이면 벡터 경로 비활성(A/B 측정용) */
        static int _novec = -1; if (_novec < 0) _novec = getenv("LC_NOVEC") ? 1 : 0;
        uint64_t beg = _novec ? 0 : q64(lc_actor + LC_ACTOR_VEC_V);
        uint64_t end = _novec ? 0 : q64(lc_actor + LC_ACTOR_VEC_END_V);
        if (isHeap(beg) && isHeap(end) && end >= beg && ((end - beg) % 8 == 0) && (end - beg) <= (16ull<<20)) {
            uint64_t slots = (end - beg) / 8;
            static uint64_t vbuf2[4096];
            int ok = 1;
            for (uint64_t i = 0; i < slots && n < maxP; ) {
                int cc = (slots - i > 4096) ? 4096 : (int)(slots - i);
                if (!rm(beg + (uint64_t)i*8, vbuf2, (uint32_t)(cc*8))) { ok = 0; break; }
                for (int j = 0; j < cc; j += 2) lc_addEnt(vbuf2[j], ptrs, &n, maxP);
                i += cc;
            }
            if (ok && !(slots >= 2 && n == 0)) viavec = 1;   /* 구조 이상 시 폴백 */
        }
    }

    /* 경로 B: 셀맵 워크(폴백) */
    static uint64_t ndseen[8192]; static uint64_t ndnext[8192]; int nnd = 0;   /* 10_8: 두 head 중복 노드 재방문 억제 */
    for (int hi = 0; !viavec && hi < 2 && n < maxP; hi++) {
        /* head slot -> sentinel container S; S+0x08 -> first node; a node's
         * +0x00 links back to S, and the last node's +0x08 closes the ring.
         * The entity vector is the node's [ +0x18, +0x20 ). */
        uint64_t sent = q64(lc_actor + LC_HEADS[hi]);
        if (!isHeap(sent)) continue;
        uint64_t c = q64(sent + 8);
        for (int g = 0; isHeap(c) && c != sent && g < 4000 && n < maxP; g++) {
            uint64_t cnext;
            {   /* 10_8: 이미 걸은 노드는 cb 재읽기 없이 저장된 next 로 넘어감 */
                int seen = 0;
                for (int k = 0; k < nnd; k++) if (ndseen[k] == c) { seen = 1; cnext = ndnext[k]; break; }
                if (seen) { c = cnext; continue; }
            }
            uint8_t cb[0x28];                        /* 셀 노드 1회 배치: next(+8), vecbeg(+0x18), vecend(+0x20) */
            gst_cur=&gst_node; int _ok=rm(c, cb, sizeof cb); gst_cur=0; if (!_ok) break;
            uint64_t vb = *(uint64_t *)(cb + LC_CELL_VEC_BEG_V), ve = *(uint64_t *)(cb + LC_CELL_VEC_END_V);
            cnext = *(uint64_t *)(cb + LC_CELL_NEXT_V);
            if (nnd < 8192) { ndseen[nnd] = c; ndnext[nnd] = cnext; nnd++; }
            if (isHeap(vb) && isHeap(ve) && ve >= vb) {
                int cnt = (int)((ve - vb) / 8);
                if (cnt > 0 && cnt < 6000) {
                    for (int i = 0; i < cnt && n < maxP; i++) {
                        /* 10_8 노드 벡터 배치: 포인터 배열을 청크(≤512)로 1콜 읽기 */
                        uint64_t cstart = vb + (((uint64_t)i) & ~511ull) * 8;
                        if (cstart != lc_vbase) {
                            int c2 = (cnt - i > 512) ? 512 : (cnt - i);
                            gst_cur=&gst_vec; int _okv=rm(cstart, lc_vbuf, (uint32_t)(c2 * 8)); gst_cur=0; if (!_okv) break;
                            lc_vbase = cstart;
                        }
                        lc_addEnt(*(uint64_t *)(lc_vbuf + (((uint64_t)i) & 511ull) * 8), ptrs, &n, maxP);
                    }
                }
            }
            c = cnext;
        }
    }
    /* drop stale ledger rows so a recycled pointer is re-resolved */
    for (int i = 0; i < lc_ledN; ) {
        if (lc_led[i].seenGen != lc_gen) lc_led[i] = lc_led[--lc_ledN];
        else i++;
    }
    lc_sweepCount++;
    return n;
}

/* A/B pipeline interpolation, isolated so it can be unit-tested without memory.
 * enttrack model: A(+0x50) is the committed cell, B(+0x78) the next target,
 * one commit per LC_STEP_MS; t = elapsed since A changed, clamped to [0,1]. */
static void lc_interpIso(LC_E *X, DWORD now)
{
    if (!X->hasIso) { X->iU = X->iV = 0.f; return; }
    float t = (float)(now - X->aTime) / LC_STEP_MS;
    if (t < 0.f) t = 0.f;
    if (t > 1.f) t = 1.f;
    X->iU = X->aU + (X->bU - X->aU) * t;
    X->iV = X->aV + (X->bV - X->aV) * t;
}


/* fast poll: 1 batched IOCTL per entity (PRES_B batch) + action scan */
static uint8_t lc_presBuf[0x48];
static int lc_pgRead(uint64_t addr, void* out, uint32_t len);   /* fwd decl (정의는 바로 아래) */
static int lc_isDoor(const LC_E *X);                            /* fwd decl */
/* 10_8 region(커밋 구간) 기반 bulk read: region 전체를 1콜(SignedReadSpan)로 읽고 오프셋 파싱.
 * (드라이버는 Size 임의 지원, region 경계만 안 넘으면 1콜 성공) */
#define LC_PGC_MAX 512
static uint64_t lc_pgc_key[LC_PGC_MAX];
static uint8_t  lc_pgc_buf[LC_PGC_MAX][0x1000];
static int      lc_pgc_n = 0;
static void lc_pgc_reset(void){ lc_pgc_n = 0; }
static uint8_t* lc_pgc_get(uint64_t pg)
{
    for (int i = 0; i < lc_pgc_n; i++) if (lc_pgc_key[i] == pg) return lc_pgc_buf[i];
    if (lc_pgc_n >= LC_PGC_MAX) return 0;
    uint32_t got = 0;
    uint64_t _b = (uint64_t)g_ioctl;
    int okf = SignedReadFast(g_pid, pg, lc_pgc_buf[lc_pgc_n], 0x1000, &got) && got != 0;
    if (gst_cur) *gst_cur += (unsigned long long)((uint64_t)g_ioctl - _b);
    if (!okf) return 0;
    lc_pgc_key[lc_pgc_n] = pg;
    return lc_pgc_buf[lc_pgc_n++];
}
static int lc_pgRead(uint64_t addr, void* out, uint32_t len)
{
    uint64_t pg = addr & ~(uint64_t)0xFFF; uint32_t off = (uint32_t)(addr & 0xFFF);
    if (off + len <= 0x1000) { uint8_t* b = lc_pgc_get(pg); if (b) { memcpy(out, b + off, len); return 1; } }
    return rm(addr, out, len);   /* 페이지 경계 걸침/캐시 만원 → 직접 읽기 */
}

/* ── 3b. Door(문) 개폐 판독 (2026-10-19 확정) ────────────────────────────
 *  Door = InteractiveNPC 중 종(SPECIES)=DOOR_SP(8) 이거나 이름="Door".
 *  [상태] ActionComponent + DOOR_STATE_OFF(0xD8) dword: 0x1C=열림 / 0x1D=닫힘
 *  [종류] Presentation  + DOOR_GFX_OFF(0x38)  dword: 0x800A=여닫이 / 0x8009=고정(열 수 없음)
 *  IOCTL: 페이지 캐시 사용(스냅샷이 이미 같은 페이지를 적재 → 추가 IOCTL 0).
 *  문서: docs/DOOR_STATE.md */
static int lc_isDoor(const LC_E *X)
{
    if (!X) return 0;
    if (X->vft != LC_VFT_NPC) return 0;
    if (X->sp == LC_DOOR_SP_V) return 1;
    if (LC_DOOR_NAME[0] && X->nm[0] && !strcmp(X->nm, LC_DOOR_NAME)) return 1;
    return 0;
}
/* 문 종류 그래픽 ID (Presentation + DOOR_GFX_OFF) — 상태 아님 */
static int lc_doorGfx(const LC_E *X, uint32_t *out)
{
    if (!X || !isHeap(X->presB)) return 0;
    uint32_t v = 0;
    if (!lc_pgRead(X->presB + LC_DOOR_GFX_OFF_V, &v, 4)) return 0;
    if (out) *out = v;
    return 1;
}
/* 개폐 상태 dword (ActionComponent + DOOR_STATE_OFF) */
static int lc_doorFrame(const LC_E *X, uint32_t *out)
{
    if (!X || !isHeap(X->ac)) return 0;
    uint32_t v = 0;
    if (!lc_pgRead(X->ac + LC_DOOR_STATE_OFF_V, &v, 4)) return 0;
    if (out) *out = v;
    return 1;
}
/* 0=닫힘 1=열림 2=미상 -1=문 아님 (스냅샷이 채운 값을 그대로 사용) */
static int lc_doorStateOfFrame(uint32_t f)
{
    if (f == LC_DOOR_STATE_OPEN)   return 1;
    if (f == LC_DOOR_STATE_CLOSED) return 0;
    return 2;
}
static int lc_doorState(const LC_E *X)
{
    if (!X) return -1;
    if (X->doorSeen) return X->doorState;      /* 스냅샷 캐시(추가 IOCTL 없음) */
    if (!lc_isDoor(X)) return -1;              /* 스냅샷 이후 삽입된 개체 방어 */
    uint32_t f = 0;
    if (!lc_doorFrame(X, &f)) return 2;
    return lc_doorStateOfFrame(f);
}
/* 1 = 열 수 없는(고정) 문 — 종류 그래픽이 DOOR_GFX_LOCKED (사용자 확인 근거) */
static int lc_doorLocked(const LC_E *X)
{
    if (!X) return 0;
    if (X->doorSeen) return X->doorLocked;
    if (!lc_isDoor(X)) return 0;
    uint32_t g = 0;
    if (!lc_doorGfx(X, &g)) return 0;
    return g == LC_DOOR_GFX_LOCKED;
}
static const char *lc_doorStateStr(const LC_E *X)
{
    int s = lc_doorState(X);
    return s == 0 ? "closed" : s == 1 ? "open" : s == 2 ? "unknown" : "";
}
/* 현시용 3상태 토큰 (etview/JSON 공통): open / close / not_permitted
 *   not_permitted = 열 수 없는(고정) 문 — 종류 그래픽이 DOOR_GFX_LOCKED.
 *   (닫힘은 close — 사용자 요청 표기) */
static const char *lc_doorToken(const LC_E *X)
{
    if (!X || !X->doorSeen) return "";
    if (X->doorLocked) return "not_permitted";
    if (X->doorState == 1) return "open";
    if (X->doorState == 0) return "close";
    return "unknown";
}
/* 스냅샷에서 문 개체만 1회 판독해 LC_E 에 채운다(문 수만큼, 캐시 히트 시 IOCTL 0). */
static void lc_fillDoor(void)
{
    for (int i = 0; i < lc_nc; i++){
        LC_E *X = &lc_cur[i];
        X->doorSeen = 0; X->doorState = -1; X->doorFrame = 0; X->doorGfx = 0; X->doorLocked = 0;
        if (!lc_isDoor(X)) continue;
        uint32_t g = 0, f = 0;
        int hg = lc_doorGfx(X, &g), hf = lc_doorFrame(X, &f);
        X->doorGfx   = hg ? g : 0;
        X->doorFrame = hf ? f : 0;
        X->doorLocked= (hg && g == LC_DOOR_GFX_LOCKED) ? 1 : 0;
        X->doorState = hf ? lc_doorStateOfFrame(f) : 2;
        X->doorSeen  = 1;
    }
}
/* ── 10_15 bodyact: ActionComponent+AC_ACTION_OFF / ActorController+CTL_CMD_OFF ── */
static const char *lc_bodyOf(uint32_t v)
{
    if (!v) return "none";
    if (v == LC_VFT_BREATHACT)   return "stand";
    if (v == LC_VFT_MOVINGACT)   return "walk";
    if (v == LC_VFT_MOVINGBACK)  return "walkback";
    if (v == LC_VFT_ATTACKACT)   return "attack";
    if (v == LC_VFT_ACTIONBASE)  return "pickup";
    if (v == LC_VFT_SPELLACT)    return "spell";
    if (v == LC_VFT_DAMAGEDACTION || v == LC_VFT_DAMAGEDREACTION) return "damaged";
    if (v == LC_VFT_DEATH || v == LC_VFT_DEADBODY) return "death";
    if (v == LC_VFT_CHANGEDIR)   return "turn";
    if (v == LC_VFT_EFFECTACTION) return "effect";
    return "other";
}
static const char *lc_cmdOf(uint32_t v)
{
    if (!v) return "none";
    if (v == LC_VFT_CMDMOVE)     return "move";
    if (v == LC_VFT_CMDATTACK)   return "attack";
    if (v == LC_VFT_CMDINTERACT) return "interact";
    return "other";
}
/* Read command vft at ActorController+CTL_CMD_OFF. Uses page cache (1–3 IOCTL). */
static uint32_t lc_readCmdVft(uint64_t e)
{
    uint64_t H = 0;
    { uint8_t hb[0x98];
      if (!lc_pgRead(e + LC_ENT_H_V, &H, 8) || !isHeap(H)) return 0;
      if (!lc_pgRead(H, hb, sizeof hb)) return 0;
      uint64_t ctl = *(uint64_t *)(hb + LC_H_CTL_OFF_V);
      if (!isHeap(ctl)) return 0;
      uint32_t cv = vrva(ctl);
      if (cv && cv != LC_VFT_CTLCOMP) return 0;
      uint8_t cb[0x60];
      if (!lc_pgRead(ctl, cb, sizeof cb)) return 0;
      uint64_t cmd = *(uint64_t *)(cb + LC_CTL_CMD_OFF_V);
      if (!isHeap(cmd)) return 0;
      uint64_t wv = 0;
      if (!lc_pgRead(cmd, &wv, 8)) return 0;
      return isMod(wv) ? (uint32_t)(wv - g_base) : 0;
    }
}
/* MyPlayer-only body+cmd. Fixed anchor (lc_anchor) + actor vector; no cellmap.
 * Returns 1 on success. Writes lc_selfBodyAct / lc_selfCmdVft / lc_selfDispAct.
 * Prefer lc_pollSelfBodyFast for low-latency viewers (sticky AC/CTL + cmd fuse). */
static uint32_t lc_selfBodyAct = 0, lc_selfCmdVft = 0, lc_selfDispAct = 0;
static uint64_t lc_selfBodyE = 0;
static uint64_t lc_selfAc = 0, lc_selfCtl = 0;
static int lc_selfFastAge = 0;

/* cmd updates before AC+0xC0 body (action_timeline). Map intent onto display body. */
static uint32_t lc_fuseBodyCmd(uint32_t body, uint32_t cmd)
{
    if (!cmd) return body;
    if (cmd == LC_VFT_CMDATTACK) {
        if (!body || body == LC_VFT_BREATHACT || body == LC_VFT_MOVINGACT ||
            body == LC_VFT_MOVINGBACK || body == LC_VFT_CHANGEDIR)
            return LC_VFT_ATTACKACT;
    } else if (cmd == LC_VFT_CMDMOVE) {
        if (!body || body == LC_VFT_BREATHACT)
            return LC_VFT_MOVINGACT;
    } else if (cmd == LC_VFT_CMDINTERACT) {
        if (!body || body == LC_VFT_BREATHACT || body == LC_VFT_MOVINGACT ||
            body == LC_VFT_MOVINGBACK || body == LC_VFT_CHANGEDIR)
            return LC_VFT_ACTIONBASE;
    }
    return body;
}

static int lc_pollSelfBody(void)
{
    if (!lc_actor && !lc_anchor()) return 0;
    uint64_t e = lc_selfBodyE;
    if (!e || vrva(e) != LC_VFT_SELF) {
        e = 0;
        uint64_t beg = q64(lc_actor + LC_ACTOR_VEC_V);
        uint64_t end = q64(lc_actor + LC_ACTOR_VEC_END_V);
        if (!isHeap(beg) || !isHeap(end) || end < beg || ((end - beg) % 8) || (end - beg) > (16ull << 20))
            return 0;
        uint64_t slots = (end - beg) / 8;
        static uint64_t vbuf[4096];
        for (uint64_t i = 0; i < slots; ) {
            int cc = (slots - i > 4096) ? 4096 : (int)(slots - i);
            if (!rm(beg + i * 8, vbuf, (uint32_t)(cc * 8))) break;
            for (int j = 0; j < cc; j += 2) {
                uint64_t cand = vbuf[j];
                if (!isHeap(cand)) continue;
                if (vrva(cand) == LC_VFT_SELF) { e = cand; break; }
            }
            if (e) break;
            i += cc;
        }
        if (!e) return 0;
        lc_selfBodyE = e;
    }
    /* H page → AC + CTL in one page read when possible */
    uint64_t H = 0;
    if (!lc_pgRead(e + LC_ENT_H_V, &H, 8) || !isHeap(H)) return 0;
    uint8_t hb[0x98];
    if (!lc_pgRead(H, hb, sizeof hb)) return 0;
    uint64_t ac = *(uint64_t *)(hb + LC_H_AC_OFF_V);
    uint64_t ctl = *(uint64_t *)(hb + LC_H_CTL_OFF_V);
    uint32_t body = 0, cmd = 0;
    if (isHeap(ac) && vrva(ac) == LC_VFT_AC) {
        uint8_t ab[0xE0];
        uint32_t need = LC_AC_ACTION_OFF + 8; if (need > sizeof ab) need = sizeof ab;
        if (lc_pgRead(ac, ab, need) && LC_AC_ACTION_OFF + 8 <= need) {
            uint64_t ap = *(uint64_t *)(ab + LC_AC_ACTION_OFF);
            if (isHeap(ap)) {
                uint64_t wv = 0;
                if (lc_pgRead(ap, &wv, 8) && isMod(wv)) body = (uint32_t)(wv - g_base);
            }
        }
    }
    if (isHeap(ctl)) {
        uint32_t cv = vrva(ctl);
        if (!cv || cv == LC_VFT_CTLCOMP) {
            uint8_t cb[0x60];
            if (lc_pgRead(ctl, cb, sizeof cb)) {
                uint64_t cp = *(uint64_t *)(cb + LC_CTL_CMD_OFF_V);
                if (isHeap(cp)) {
                    uint64_t wv = 0;
                    if (lc_pgRead(cp, &wv, 8) && isMod(wv)) cmd = (uint32_t)(wv - g_base);
                }
            }
        }
    }
    lc_selfBodyAct = body;
    lc_selfCmdVft = cmd;
    lc_selfAc = isHeap(ac) ? ac : 0;
    lc_selfCtl = isHeap(ctl) ? ctl : 0;
    lc_selfDispAct = lc_fuseBodyCmd(body, cmd);
    return 1;
}

/* Sticky AC/CTL leaf poll: ~4 IOCTL/tick when warm; periodic full resolve.
 * Raw body stays in lc_selfBodyAct; fused early display in lc_selfDispAct. */
static int lc_selfResolvePtrs(void)
{
    if (!lc_actor && !lc_anchor()) return 0;
    uint64_t e = lc_selfBodyE;
    if (!e || vrva(e) != LC_VFT_SELF) {
        e = 0;
        uint64_t beg = q64(lc_actor + LC_ACTOR_VEC_V);
        uint64_t end = q64(lc_actor + LC_ACTOR_VEC_END_V);
        if (!isHeap(beg) || !isHeap(end) || end < beg || ((end - beg) % 8) || (end - beg) > (16ull << 20))
            return 0;
        uint64_t slots = (end - beg) / 8;
        static uint64_t vbuf[4096];
        for (uint64_t i = 0; i < slots; ) {
            int cc = (slots - i > 4096) ? 4096 : (int)(slots - i);
            if (!rm(beg + i * 8, vbuf, (uint32_t)(cc * 8))) break;
            for (int j = 0; j < cc; j += 2) {
                uint64_t cand = vbuf[j];
                if (!isHeap(cand)) continue;
                if (vrva(cand) == LC_VFT_SELF) { e = cand; break; }
            }
            if (e) break;
            i += (uint64_t)cc;
        }
        if (!e) return 0;
        lc_selfBodyE = e;
    }
    uint64_t H = q64(e + LC_ENT_H_V);
    if (!isHeap(H)) return 0;
    uint64_t ac = q64(H + LC_H_AC_OFF_V);
    uint64_t ctl = q64(H + LC_H_CTL_OFF_V);
    if (isHeap(ac)) {
        uint32_t av = vrva(ac);
        if (av && av != LC_VFT_AC) ac = 0;
    } else ac = 0;
    if (isHeap(ctl)) {
        uint32_t cv = vrva(ctl);
        if (cv && cv != LC_VFT_CTLCOMP) ctl = 0;
    } else ctl = 0;
    if (!ac && !ctl) return 0;
    lc_selfAc = ac;
    lc_selfCtl = ctl;
    return 1;
}

static int lc_selfLeafRead(void)
{
    uint32_t body = 0, cmd = 0;
    if (isHeap(lc_selfAc)) {
        uint64_t ap = q64(lc_selfAc + LC_AC_ACTION_OFF);
        if (isHeap(ap)) body = vrva(ap);
    }
    if (isHeap(lc_selfCtl)) {
        uint64_t cp = q64(lc_selfCtl + LC_CTL_CMD_OFF_V);
        if (isHeap(cp)) cmd = vrva(cp);
    }
    lc_selfBodyAct = body;
    lc_selfCmdVft = cmd;
    lc_selfDispAct = lc_fuseBodyCmd(body, cmd);
    return (body || cmd) ? 1 : 0;
}

static int lc_pollSelfBodyFast(void)
{
    if (!lc_selfAc || !lc_selfCtl || lc_selfFastAge >= LC_SELF_REVAL_TICKS) {
        if (!lc_selfResolvePtrs()) {
            lc_selfAc = lc_selfCtl = 0;
            lc_selfBodyAct = lc_selfCmdVft = lc_selfDispAct = 0;
            return 0;
        }
        lc_selfFastAge = 0;
    }
    lc_selfFastAge++;
    if (lc_selfLeafRead()) return 1;
    lc_selfAc = lc_selfCtl = 0;
    if (!lc_selfResolvePtrs()) return 0;
    lc_selfFastAge = 0;
    return lc_selfLeafRead();
}

static void lc_pollFast(uint64_t *ptrs, int n, DWORD now)
{
    lc_nc = 0;
    uint32_t pbase = LC_PRESB_BASE_V;
    int aOff = (int)LC_PRESB_A_OFF_V - (int)pbase;   /* A(+0x50) rel to batch base */
    int bOff = (int)LC_PRESB_B_OFF_V - (int)pbase;   /* B(+0x78) */
    for (int i = 0; i < n && lc_nc < LC_MAXE; i++) {
        uint64_t e = ptrs[i];
        LC_LED *L = lc_ledFind(e, 0);
        LC_E *X = &lc_cur[lc_nc];
        memset(X, 0, sizeof(*X));
        X->e = e;
        uint8_t hb[0x50];                    /* 엔티티 헤더 1회 배치: vft/self/guid/species/flag */
        gst_cur=&gst_hdrP; int _okp=lc_pgRead(e, hb, sizeof hb); gst_cur=0; if (!_okp) continue;
        if (*(uint64_t *)(hb + LC_ENT_SELF_V) != e) continue;   /* 소멸/재사용 → 스킵(스윕 사이 프레임 안전) */
        X->vft = L ? L->vft : (isMod(*(uint64_t *)hb) ? (uint32_t)(*(uint64_t *)hb - g_base) : 0);
        X->guid = L && L->guid ? L->guid : *(uint64_t *)(hb + LC_ENT_GUID_V);
        X->presB = L ? L->presB : 0;
        X->ac = L ? L->ac : 0;
        X->sp = *(uint32_t *)(hb + LC_ENT_SPECIES_V);   /* ENT_SPECIES */
        if (L && L->hasName) { strncpy(X->nm, L->nm, sizeof(X->nm) - 1); X->nm[sizeof(X->nm)-1] = 0; }
        else lc_name(e, X->nm, sizeof(X->nm));
        X->cellx = -1; X->celly = -1;
        X->spawnMs = now;

        /* --- batched PRES_B read: cx,cy | A | B --- */
        gst_cur=&gst_pres; int _okpb = (X->presB && lc_pgRead(X->presB + pbase, lc_presBuf, sizeof(lc_presBuf))); gst_cur=0;
        if (_okpb) {
            int32_t cx, cy; float aU, aV, bU, bV;
            memcpy(&cx, lc_presBuf + LC_PRESB_CELL_OFF_V, 4);
            memcpy(&cy, lc_presBuf + LC_PRESB_CELL_OFF_V + LC_PRESB_CELL_DY_V, 4);
            memcpy(&aU, lc_presBuf + aOff, 4);
            memcpy(&aV, lc_presBuf + aOff + 4, 4);
            memcpy(&bU, lc_presBuf + bOff, 4);
            memcpy(&bV, lc_presBuf + bOff + 4, 4);
            if (cx > -100000 && cx < 100000 && cy > -100000 && cy < 100000) {
                X->cellx = cx; X->celly = cy; X->hasIso = 1;
            }
            if (aU > -1e7f && aU < 1e7f && aV > -1e7f && aV < 1e7f) {
                float nB = (bU > -1e7f && bU < 1e7f) ? bU : aU;
                float nBv = (bV > -1e7f && bV < 1e7f) ? bV : aV;
                if (L) {
                    /* persistent A/B pipeline in the ledger -> real interpolation */
                    if (!L->aInit) { L->aU = aU; L->aV = aV; L->aTime = now; L->aInit = 1; }
                    else if (L->aU != aU || L->aV != aV) { L->aU = aU; L->aV = aV; L->aTime = now; }
                    L->bU = nB; L->bV = nBv;
                    X->aU = L->aU; X->aV = L->aV; X->aTime = L->aTime; X->aInit = 1;
                    X->bU = L->bU; X->bV = L->bV;
                } else {
                    if (!X->aInit) { X->aTime = now; X->aInit = 1; }
                    else if (X->aU != aU || X->aV != aV) X->aTime = now;
                    X->aU = aU; X->aV = aV;
                    X->bU = nB; X->bV = nBv;
                }
                X->hasIso = 1;
            }
        }
        /* --- attack / death (ActionComponent @ H + H_AC_OFF) --- */
        if (!X->ac) {
            uint64_t H = q64(e + LC_ENT_H_V);
            uint64_t ac = isHeap(H) ? q64(H + LC_H_AC_OFF_V) : 0;
            if (isHeap(ac) && vrva(ac) == LC_VFT_AC) X->ac = ac;
        }
        if (X->ac) {
            /* AC: bait/dead 바이트 + 행동 슬롯 vft 확인.
             * §20.2 정본 규칙: 시체 판정 = AC[0..0x140] 어디든
             *   DeathAction/AppearDeadBody 참조  OR  AC+0x49==1.
             * 과거엔 ATTACKACT/DEATH 를 +AC_ACTION_OFF(0xC0) 윈도우만 스캔해
             * 시체 액션 신호를 놓치고, 더 늦은 +0x49(despawn 단계)로만 dead 가
             * 켜지는 지연이 있었다. → 사망 vft 는 AC 전체에서 찾는다.
             * (후보 vft 는 ab 안의 절대주소이므로 g_base+vw 직접비교 = 추가 IOCTL 0)
             * ATTACKACT 는 실측 고정 슬롯(윈도우)에서만 인정해 오검을 줄인다. */
            static uint8_t ab[0x200];
            uint32_t acn = LC_AC_SCAN_V; if (acn > sizeof(ab)) acn = sizeof(ab);
            gst_cur=&gst_acblk; int _okab=lc_pgRead(X->ac, ab, acn); gst_cur=0;
            if (_okab) {
                /* standard bait/dormant state (AC+0x40 dword == 0x78; SPEC entity.monster.bait) */
                X->bait = (LC_AC_BAIT_OFF + 4 <= acn && *(uint32_t *)(ab + LC_AC_BAIT_OFF) == LC_AC_BAIT_VAL) ? 1 : 0;
                /* completed corpse rule: ActionComponent dead byte (AC+0x49==1) */
                if (LC_AC_DEAD_OFF < acn && ab[LC_AC_DEAD_OFF] == (uint8_t)LC_AC_DEAD_VAL) { X->dead = 1; X->deadSrc = 1; }
                /* 10_8: 슬롯 구성 지문 — 같으면 vft 재스캔 생략(액션 객체는 잘 안 변함) */
                uint64_t fp = 1469598103934665603ull; int nheap = 0;
                for (uint32_t o = 0; o + 8 <= acn; o += 8) { uint64_t w=*(uint64_t*)(ab+o); if(isHeap(w)){ fp ^= w*1099511628211ull; nheap++; } }
                LC_LED *LL = lc_ledFind(e, 0);
                if (nheap > 0 && LL && LL->hasAcFp && LL->acFp == fp) {
                    /* 10_8: 지문 히트 시 라이브 dead 바이트를 캐시가 '덮지' 못하게 OR 만.
                     * (정본 규칙: dead = 죽음 vft OR AC+0x49==1 → 바이트 단독 사망도 보존) */
                    if (LL->cDead) X->dead = 1;
                    X->hasAtk = LL->cHasAtk; X->atkOwner = LL->cAtkOwner; X->atkTgt = LL->cAtkTgt;
                    X->bodyAct = LL->cBodyAct;
                } else {
                uint32_t aw0 = LC_AC_ACTION_OFF, aw1 = aw0 + LC_AC_ACTION_WIN; if (aw1 > acn) aw1 = acn;
                for (uint32_t o = 0; o + 8 <= acn; o += 8) {
                    uint64_t w = *(uint64_t *)(ab + o);   /* AC 슬롯 = 액션 '객체 포인터'(힙) */
                    if (!isHeap(w)) continue;
                    uint64_t wv=0; gst_cur=&gst_slot; int _oksl=lc_pgRead(w,&wv,8); gst_cur=0; if(!_oksl) continue;   /* 액션 객체 vft: 페이지그룹 */
                    uint32_t v = isMod(wv) ? (uint32_t)(wv - g_base) : 0;   /* 객체의 vft */
                    if (v == LC_VFT_DEATH || v == LC_VFT_DEADBODY) { X->dead = 1; X->deadSrc = 2; }   /* AC 전체: 시체 액션 */
                    else if (v == LC_VFT_ATTACKACT && o >= aw0 && o < aw1) {      /* 공격은 고정 슬롯만 */
                        X->hasAtk = 1; X->atkOwner = q64(w + LC_ACT_ATK_OWNER_V); X->atkTgt = q64(w + LC_ACT_ATK_TARGET_V);
                    }
                    /* 10_15: primary body slot = AC_ACTION_OFF (fixed chain) */
                    if (o == LC_AC_ACTION_OFF) X->bodyAct = v;
                }
                if (LL) { LL->acFp = fp; LL->hasAcFp = 1; LL->cDead = (uint8_t)X->dead; LL->cHasAtk = (uint8_t)X->hasAtk; LL->cAtkOwner = X->atkOwner; LL->cAtkTgt = X->atkTgt; LL->cBodyAct = X->bodyAct; }
                }
                /* 10_15: command only for MyPlayer (IOCTL 최소화) */
                if (X->vft == LC_VFT_SELF) {
                    X->cmdVft = lc_readCmdVft(e);
                    if (LL) LL->cCmdVft = X->cmdVft;
                } else if (LL) {
                    X->cmdVft = LL->cCmdVft;
                }
            }
        }
        /* [ATS 10_8] read-side extension: init + derive */
        X->atkValid = -1; X->atkBlocked = 0;
        X->atkBlocked   = 0;   /* LOS block: judged from map data */
        X->tgtFlagA     = 0;   /* targetinfo +0x46 (unread here) */
        X->tgtFlagB     = 0;   /* targetinfo +0x47 (unread here) */
        X->actorFlag59a = 0;   /* actor +0x59A   (unread here) */
        if (!X->dead) X->deadSrc = 0;

        /* --- ground item: type/qty (owner resolved in post-pass below) ---
         * 9.30 live-verified layout:
         *   e+0x18 = GUID (u64).  e+0x38 = u32 QUANTITY (previously misread
         *   as e+0x18, which overlaps the guid low dword).
         *   EfficiencyInventory count names show "??? (N)" and N==e+0x38. */
        if (X->vft == LC_VFT_ITEM) {
            X->itemType = X->sp;                        /* same offset as species (+0x38) → 중복 read 제거 */
            X->itemQty  = X->sp;
            X->itemFlag = *(uint32_t *)(hb + LC_ENT_ITEM_FLAG_V); /* ownership/lock state (0=free) */
        }
        lc_nc++;
    }
    /* interpolate every entity with the A/B pipeline */
    for (int i = 0; i < lc_nc; i++) lc_interpIso(&lc_cur[i], now);

    /* post-pass: ground-item ownership.  Only values equal to a live actor
     * GUID count as an owner; everything else (asian aDate free stacks)
     * stays 0 => free.  Runs after lc_cur is complete so all actors are
     * known. */
    /* post-pass: attack validity.  MUST run after lc_cur is complete;
     * inside lc_collect it was order-dependent (target not yet listed). */
    for (int i = 0; i < lc_nc; i++) {
        LC_E *X = &lc_cur[i];
        X->atkValid = -1; X->atkBlocked = 0;
        if (!X->hasAtk || !X->atkTgt) continue;
        const LC_E *T = lc_findCur(X->atkTgt);
        if (!T) X->atkValid = -1;   /* target not collected -> unknown */
        else if (T->dead) X->atkValid = 0;
        else {
            int dx = T->cellx - X->cellx, dy = T->celly - X->celly;
            int adx = dx < 0 ? -dx : dx, ady = dy < 0 ? -dy : dy;
            int cheb = adx > ady ? adx : ady;
            X->atkValid = (cheb <= (int)LC_ATK_RANGE_TILES) ? 1 : 0;
        }
    }
    static uint8_t ownbuf[0x200];
    for (int i = 0; i < lc_nc; i++) {
        LC_E *X = &lc_cur[i];
        if (X->vft != LC_VFT_ITEM) continue;
        X->itemOwner = 0; X->itemOwnerSeen = 1;
        /* 데미지 기여(내 것 판정) + 소유 분류 */
        X->itemContrib = d32(X->e + LC_ITEM_CONTRIB);
        if (X->itemContrib) X->itemOwn = 1;                 /* MINE */
        else { int found = 0;
            for (int k = 0; k < lc_nc; k++) {
                if (!isActorish(lc_cur[k].vft)) continue;
                uint64_t g = lc_cur[k].guid; if (!g) continue;
                if (X->guid > g && (X->guid - g) <= LC_LH_DELTA) { found = 1; break; }
            }
            X->itemOwn = found ? 2 : 3;                     /* OTHER : FREE */
        }
        uint32_t beg = LC_ITEM_OWN_BEG_V, end = LC_ITEM_OWN_END_V;
        uint32_t len = (end > beg) ? (end - beg) : 0; if (len > sizeof(ownbuf)) len = sizeof(ownbuf);
        gst_cur=&gst_item; int _okow = (len && lc_pgRead(X->e + beg, ownbuf, len)); gst_cur=0;
        if (_okow) {          /* 소유 필드 1회 배치 */
            for (uint32_t o = 0; o + 8 <= len && !X->itemOwner; o += 8) {
                uint64_t w = *(uint64_t *)(ownbuf + o);
                if (!w || isHeap(w) || isMod(w)) continue;
                if (w == lc_meGuid) { X->itemOwner = w; break; }
                for (int k = 0; k < lc_nc; k++) {
                    if (isActorish(lc_cur[k].vft) && lc_cur[k].guid == w) { X->itemOwner = w; break; }
                }
            }
        }
    }
}

/* ── 10_8: 저주기 스냅샷 스케줄러 ──────────────────────────────────────────
 * 스냅샷(읽기) 주기를 소비(렌더/출력) 루프에서 분리한다.
 * 소비 루프가 아무리 자주 lc_collect()를 불러도, ENT_READ_INTERVAL_MS 이내
 * 재호출은 드라이버를 건드리지 않고 보간만 갱신한다.
 * (도구·파일명·출력양식 불변. 진단 라인 '# ioctl=' 은 캐시 프레임에서 0.) */
static void lc_refreshInterp(void)
{
    DWORD now = GetTickCount();
    for (int i = 0; i < lc_nc; i++) lc_interpIso(&lc_cur[i], now);
}

/* 10_8: 근접 몬스터 존재 시 전투 모드(폴링 3배). self 셀 기준 Chebyshev 반경. */
static void lc_combatUpdate(DWORD now)
{
    int scx = -1000000, scy = -1000000;
    for (int i = 0; i < lc_nc; i++) {
        uint32_t v = lc_cur[i].vft;
        if (v == LC_VFT_SELF || v == LC_VFT_PLAYER) { scx = lc_cur[i].cellx; scy = lc_cur[i].celly; break; }
    }
    int ncombat = 0;
    if (scx > -100000) {
        int R = (int)LC_COMBAT_CELLS;
        for (int i = 0; i < lc_nc; i++) {
            uint32_t v = lc_cur[i].vft;
            if (v != LC_VFT_MONSTER && v != LC_VFT_SUMMON) continue;
            if (lc_cur[i].cellx < 0) continue;
            int dx = lc_cur[i].cellx - scx; if (dx < 0) dx = -dx;
            int dy = lc_cur[i].celly - scy; if (dy < 0) dy = -dy;
            if (dx <= R && dy <= R) { ncombat = 1; break; }
        }
    }
    if (ncombat) lc_combatUntil = now + LC_COMBAT_HOLD_MS;
    lc_combatOn = (lc_combatUntil && (int32_t)(now - lc_combatUntil) < 0) ? 1 : 0;
}

static uint64_t lc_ptrs[LC_MAXE];          /* 마지막 스윕의 엔티티 포인터 목록 */
static int      lc_ptrN = 0;
static DWORD    lc_lastSweepMs = 0;        /* API 모드: 구조 스윕 시각 */

static void lc_collect(void)
{
    static DWORD lastReadMs = 0;
    DWORD now = GetTickCount();

    /* 전투 중이면 주기 단축(3배), 아니면 기본 주기. 지터는 주기에 '가산'. */
    uint32_t iv = LC_READ_INTERVAL_MS;
    if (lc_combatUntil && (int32_t)(now - lc_combatUntil) < 0 && LC_READ_COMBAT_MS) iv = LC_READ_COMBAT_MS;
    if (LC_READ_JITTER_MS) iv += (GetTickCount() % LC_READ_JITTER_MS);

    /* 읽기 주기 미도래 → 스냅샷 유지 + 보간만 (드라이버 호출 0) */
    if (lastReadMs && (uint32_t)(now - lastReadMs) < iv) {
        lc_refreshInterp();
        return;
    }
    lastReadMs = now;

    lc_pgc_reset();   /* 10_8: region 캐시 리셋(사이클당) */
    gst_io0 = (unsigned long long)g_ioctl;
    gst_hdrS=gst_node=gst_vec=gst_hdrP=gst_pres=gst_acblk=gst_slot=gst_item=gst_n0=gst_n1=0;
    /* 10_8: 매 읽기 사이클 전체 재스윕 + region bulk read.
     * → 엔티티 집합 항상 최신(정확도 향상), 구조 서명/변경감지 불필요.
     * 10_16(API): 호출자가 스윕주기(ENT_SWEEP_MS)를 지정하면, 구조 스윕은 그
     * 주기로만 수행하고 값 읽기/보간은 ENT_READ_INTERVAL_MS 주기로 갱신한다.
     * EXE 모드(lcapi_on()==0)에서는 기존과 동일하게 매 사이클 스윕(동작 불변). */
    {
        int doSweep = 1;
        if (lcapi_on() && LC_SWEEP_MS) {
            if (lc_lastSweepMs && (uint32_t)(now - lc_lastSweepMs) < LC_SWEEP_MS) doSweep = 0;
            else lc_lastSweepMs = now;
        }
        if (doSweep) lc_ptrN = lc_sweepSlow(lc_ptrs, LC_MAXE);
    }
    lc_pollFast(lc_ptrs, lc_ptrN, now);
    lc_fillDoor();            /* Door 상태/종류 1회 판독(페이지 캐시 → 추가 IOCTL 0) */
    lc_combatUpdate(now);
    {
        static int _on=-1; if(_on<0) _on=getenv("LC_STATS")?1:0;
        if(_on){
            unsigned long long s=gst_hdrS+gst_node+gst_vec+gst_hdrP+gst_pres+gst_acblk+gst_slot+gst_item;
            fprintf(stderr,"[stats] cyc=%d n=%d combat=%d n0=%llu n1=%llu hdrS=%llu node=%llu vec=%llu hdrP=%llu pres=%llu acblk=%llu slot=%llu item=%llu sum=%llu tot=%llu\n",
                lc_sweepCount, lc_nc, lc_combatOn, gst_n0,gst_n1, gst_hdrS,gst_node,gst_vec,gst_hdrP,gst_pres,gst_acblk,gst_slot,gst_item,s,(unsigned long long)g_ioctl-gst_io0);
        }
    }
}

static void lc_pick_self(void)
{
    lc_meGuid = 0; lc_meE = 0;
    for (int i = 0; i < lc_nc; i++)
        if (lc_cur[i].vft == LC_VFT_SELF) { lc_meGuid = lc_cur[i].guid; lc_meE = lc_cur[i].e; return; }
    for (int i = 0; i < lc_nc; i++)
        if (lc_cur[i].vft == LC_VFT_PLAYER) { lc_meGuid = lc_cur[i].guid; lc_meE = lc_cur[i].e; return; }
}
static LC_E *lc_findCur(uint64_t guid)
{
    for (int i = 0; i < lc_nc; i++) if (lc_cur[i].guid == guid) return &lc_cur[i];
    return NULL;
}
static LC_E *lc_findPrev(uint64_t guid)
{
    for (int i = 0; i < lc_npc; i++) if (lc_prev[i].guid == guid) return &lc_prev[i];
    return NULL;
}
static LC_E *lc_findMe(void) { return lc_meGuid ? lc_findCur(lc_meGuid) : NULL; }
static const char *lc_nameOfGuid(uint64_t guid)
{
    LC_E *X = lc_findCur(guid);
    return X ? (X->nm[0] ? X->nm : "?") : "?";
}

/* ── 4. current map rect ─────────────────────────────────────────────────── */
/* The quad is NOT in MapSubsystem itself: MapSubsystem -> +0x768 child -> +0x3C.
 * Auto-located once (self-validating), then cached; re-located if it changes. */
static int lc_mx0 = 0, lc_my0 = 0, lc_mx1 = 0, lc_my1 = 0, lc_mapValid = 0;
static uint64_t lc_mapSrc = 0; static int lc_mapOff = -1;

static int lc_rectOK(int x0, int y0, int x1, int y1, int px, int py)
{
    if (x1 <= x0 || y1 <= y0) return 0;
    if ((x1 - x0) > 8192 || (y1 - y0) > 8192) return 0;
    if ((x1 - x0) < 64  || (y1 - y0) < 64)   return 0;
    if (x0 % 32 || y0 % 32) return 0;                 /* 32 = one world tile */
    if (px >= 0 && !(x0 <= px && px <= x1 && y0 <= py && py <= y1)) return 0;
    return 1;
}
static int lc_trySrc(uint64_t src, int px, int py)
{
    if (!isHeap(src)) return 0;
    for (int o = 0; o + 16 <= (int)LC_MAP_RECT_SCAN_V; o += 4) {
        int x0 = (int)d32(src + o),     y0 = (int)d32(src + o + 4);
        int x1 = (int)d32(src + o + 8), y1 = (int)d32(src + o + 12);
        if (lc_rectOK(x0, y0, x1, y1, px, py)) {
            lc_mapSrc = src; lc_mapOff = o;
            lc_mx0 = x0; lc_my0 = y0; lc_mx1 = x1; lc_my1 = y1; lc_mapValid = 1;
            return 1;
        }
    }
    return 0;
}
static int lc_readMapRect(int px, int py)
{
    /* MapSubsystem is located by vtable: the subsystem array order is not
     * stable across builds (see lc_subsGet). */
    uint64_t msub = lc_subsGet(LC_VFT_MAPSUBSYS);
    if (!isHeap(msub)) { if (lc_dbg) fprintf(stderr, "[dbg] MapSubsystem not found by vft\n"); return 0; }
    if (lc_mapSrc) {
        int o = lc_mapOff;
        int x0 = (int)d32(lc_mapSrc + o),     y0 = (int)d32(lc_mapSrc + o + 4);
        int x1 = (int)d32(lc_mapSrc + o + 8), y1 = (int)d32(lc_mapSrc + o + 12);
        if (lc_rectOK(x0, y0, x1, y1, px, py)) {
            lc_mx0 = x0; lc_my0 = y0; lc_mx1 = x1; lc_my1 = y1; lc_mapValid = 1;
            return 1;
        }
        lc_mapSrc = 0; lc_mapOff = -1;
    }
    if (lc_trySrc(q64(msub + LC_MAP_CHILD_V), px, py)) return 1;
    if (lc_trySrc(msub, px, py)) return 1;
    for (int o = 0; o + 8 <= (int)LC_MAP_SCAN_V; o += 8) {
        uint64_t w = q64(msub + o);
        if (isHeap(w) && w != msub && !vrva(w)) if (lc_trySrc(w, px, py)) return 1;
    }
    lc_mapValid = 0;
    if (lc_dbg) fprintf(stderr, "[dbg] map rect not found (cell %d,%d)\n", px, py);
    return 0;
}

/* ── 5. static assets ────────────────────────────────────────────────────── */
#define LC_MAXMAP 512
#define LC_MAXENT 64
#define LC_MAXPT  8192

typedef struct { int id, x0, y0, x1, y1, tx, ty; char name[64]; } LC_MAP;
typedef struct { int x, y; char key[64]; } LC_ENTR;
typedef struct { int map, x, y, rank; char type[8]; } LC_EXIT;

typedef struct {
    LC_MAP  maps[LC_MAXMAP];   int nmap;
    LC_ENTR entr[LC_MAXENT];   int nentr;
    LC_EXIT exit_[2048];       int nexit;
    struct { int map, x, y; } gate[LC_MAXPT]; int ngate;
    unsigned char *grid;       int gridMid, gridTx, gridTy;
} LC_ASSETS;

static LC_ASSETS gA;

static void lc_split(char *s, char **f, int maxf)
{
    int n = 0; f[n++] = s;
    for (char *p = s; *p; p++) if (*p == '\t') { *p = 0; if (n < maxf) f[n++] = p + 1; }
}
static int lc_int(const char *s) { return (int)strtol(s, NULL, 10); }

static void lc_loadAssets(const char *root)
{
    char path[512], line[1024];
    memset(&gA, 0, sizeof(gA));

    snprintf(path, sizeof(path), "%s/T3_maps/registry/dossier.tsv", root);
    FILE *f = fopen(path, "r");
    if (f) {
        int first = 1;
        while (fgets(line, sizeof(line), f)) {
            char *p = strchr(line, '\n'); if (p) *p = 0;
            if (first) { first = 0; continue; }
            char *fl[16];
            lc_split(line, fl, 16);
            if (gA.nmap >= LC_MAXMAP) break;
            LC_MAP *m = &gA.maps[gA.nmap++];
            m->id = lc_int(fl[0]);
            snprintf(m->name, sizeof(m->name), "%s", fl[1]);
            m->x0 = lc_int(fl[2]); m->y0 = lc_int(fl[3]);
            m->x1 = lc_int(fl[4]); m->y1 = lc_int(fl[5]);
            m->tx = lc_int(fl[6]); m->ty = lc_int(fl[7]);
        }
        fclose(f);
    }

    snprintf(path, sizeof(path), "%s/T3_maps/registry/dungeon_entrances.tsv", root);
    f = fopen(path, "r");
    if (f) {
        int first = 1;
        while (fgets(line, sizeof(line), f)) {
            char *p = strchr(line, '\n'); if (p) *p = 0;
            if (first) { first = 0; continue; }
            char *fl[8];
            lc_split(line, fl, 8);
            if (gA.nentr >= LC_MAXENT) break;
            snprintf(gA.entr[gA.nentr].key, 64, "%s", fl[0]);
            gA.entr[gA.nentr].x = lc_int(fl[1]);
            gA.entr[gA.nentr].y = lc_int(fl[2]);
            gA.nentr++;
        }
        fclose(f);
    }

    snprintf(path, sizeof(path), "%s/T3_maps/registry/exit_candidates.tsv", root);
    f = fopen(path, "r");
    if (f) {
        int first = 1;
        while (fgets(line, sizeof(line), f)) {
            char *p = strchr(line, '\n'); if (p) *p = 0;
            if (first) { first = 0; continue; }
            char *fl[10];
            lc_split(line, fl, 10);
            if (gA.nexit >= (int)(sizeof(gA.exit_) / sizeof(gA.exit_[0]))) break;
            LC_EXIT *e = &gA.exit_[gA.nexit++];
            e->map = lc_int(fl[0]); e->x = lc_int(fl[2]); e->y = lc_int(fl[3]);
            snprintf(e->type, sizeof(e->type), "%s", fl[4]);
            e->rank = lc_int(fl[7]);
        }
        fclose(f);
    }

    snprintf(path, sizeof(path), "%s/T3_maps/registry/gate_tiles.tsv", root);
    f = fopen(path, "r");
    if (f) {
        int first = 1;
        while (fgets(line, sizeof(line), f)) {
            char *p = strchr(line, '\n'); if (p) *p = 0;
            if (first) { first = 0; continue; }
            char *fl[8];
            lc_split(line, fl, 8);
            if (gA.ngate >= LC_MAXPT) break;
            gA.gate[gA.ngate].map = lc_int(fl[0]);
            gA.gate[gA.ngate].x   = lc_int(fl[2]);
            gA.gate[gA.ngate].y   = lc_int(fl[3]);
            gA.ngate++;
        }
        fclose(f);
    }
}

static const LC_MAP *lc_mapByRect(int x0, int y0, int x1, int y1)
{
    for (int i = 0; i < gA.nmap; i++)
        if (gA.maps[i].x0 == x0 && gA.maps[i].y0 == y0 &&
            gA.maps[i].x1 == x1 && gA.maps[i].y1 == y1) return &gA.maps[i];
    return NULL;
}
static const LC_MAP *lc_mapById(int id)
{
    for (int i = 0; i < gA.nmap; i++) if (gA.maps[i].id == id) return &gA.maps[i];
    return NULL;
}
static const LC_MAP *lc_mapAt(int x, int y)
{
    const LC_MAP *best = NULL;
    for (int i = 0; i < gA.nmap; i++) {
        const LC_MAP *m = &gA.maps[i];
        if (m->x0 <= x && x <= m->x1 && m->y0 <= y && y <= m->y1) {
            if (!best || (long)m->tx * m->ty < (long)best->tx * best->ty) best = m;
        }
    }
    return best;
}

/* obstacle grid, 1 byte per tile, 1 = blocked (L3.attr0&1). cached for one map */
static const unsigned char *lc_grid(const LC_MAP *m)
{
    if (!m) return NULL;
    if (gA.grid && gA.gridMid == m->id) return gA.grid;
    char path[512];
    snprintf(path, sizeof(path), "T3_maps/obstacle_tiles_raw/map_%d.bin", m->id);
    FILE *f = fopen(path, "rb");
    if (!f) return NULL;
    size_t need = (size_t)m->tx * m->ty;
    unsigned char *buf = (unsigned char *)malloc(need);
    if (!buf) { fclose(f); return NULL; }
    size_t got = fread(buf, 1, need, f);
    fclose(f);
    if (got != need) { free(buf); return NULL; }
    free(gA.grid);
    gA.grid = buf; gA.gridMid = m->id; gA.gridTx = m->tx; gA.gridTy = m->ty;
    return gA.grid;
}
static int lc_blockedAt(const LC_MAP *m, int x, int y)
{
    const unsigned char *g = lc_grid(m);
    if (!g) return -1;
    int ix = x - m->x0, iy = y - m->y0;
    if (ix < 0 || iy < 0 || ix >= m->tx || iy >= m->ty) return -1;
    return g[iy * m->tx + ix] ? 1 : 0;
}

/* ── 6. game window + iso->screen projection (etview model) ─────────────── */
struct LC_WFIND { DWORD pid; HWND best; long long area; };
static BOOL CALLBACK lc_wproc(HWND h, LPARAM lp)
{
    struct LC_WFIND *e = (struct LC_WFIND *)lp;
    DWORD p = 0; GetWindowThreadProcessId(h, &p);
    if (p != e->pid || !IsWindowVisible(h)) return TRUE;
    RECT r; if (!GetClientRect(h, &r)) return TRUE;
    long long a = (long long)(r.right - r.left) * (r.bottom - r.top);
    if (a > e->area) { e->area = a; e->best = h; }
    return TRUE;
}
static HWND lc_findGameWnd(DWORD pid)
{
    struct LC_WFIND e; memset(&e, 0, sizeof(e));
    e.pid = pid; e.area = 0;
    EnumWindows(lc_wproc, (LPARAM)&e);
    return e.best;
}

/* etview projection: du/dv in iso units, self is the battlefield centre. */
typedef struct { float sx, sy, pxp, pyp, sc; } LC_VIEW;
static void lc_viewCalc(LC_VIEW *v, int bw, int bh)
{
    float sc = (float)bh / LC_REF_H;
    if (sc < 0.2f || sc > 4.f) sc = 1.f;
    v->sc  = sc;
    v->sx  = (float)bw * 0.5f + LC_VP_DX * sc;
    v->sy  = (float)bh * 0.5f - LC_VP_DY * sc;
    v->pxp = LC_PPS * sc;
    v->pyp = LC_PPS * sc;
}
static void lc_project(LC_E *X, LC_E *self, const LC_VIEW *v, int *rx, int *ry)
{
    float du = X->iU - self->iU, dv = X->iV - self->iV;
    *rx = (int)(v->sx + du * v->pxp);
    *ry = (int)(v->sy - dv * v->pyp);
}
/* fallback self iso from the global player tile when no entity matches */
static void lc_selfIsoFromTile(int cx, int cy, float *u, float *v)
{
    *u = LC_U_SCALE * ((float)cx + (float)cy) - LC_U_BIAS;
    *v = LC_V_SCALE * ((float)cx - (float)cy);
}

static void lc_derive(const LC_VIEW *v)
{
    LC_E *self = lc_meGuid ? lc_findMe() : 0;
    float sU = self ? self->iU : 0.0f, sV = self ? self->iV : 0.0f;
    int   sCX = self ? self->cellx : 0, sCY = self ? self->celly : 0;
    for (int i = 0; i < lc_nc; i++) {
        LC_E *X = &lc_cur[i];
        X->worldTx = X->cellx;
        X->worldTy = X->celly;
        X->dCellX  = X->cellx - sCX;
        X->dCellY  = X->celly - sCY;
        float dtx = (float)X->dCellX, dty = (float)X->dCellY;
        X->distTile = sqrtf(dtx*dtx + dty*dty);
        float du = X->iU - sU, dv = X->iV - sV;
        X->distIso  = sqrtf(du*du + dv*dv);
        if (self && v) {
            /* ??(I) ???? */
            int rx, ry; lc_project(X, self, v, &rx, &ry);
            X->scrIX = rx; X->scrIY = ry;
            X->scrDX = rx - (int)v->sx;
            X->scrDY = ry - (int)v->sy;
            /* ??(A) ???? */
            float dUA = X->aU - self->aU, dVA = X->aV - self->aV;
            X->scrAX = (int)(v->sx + dUA * v->pxp);
            X->scrAY = (int)(v->sy - dVA * v->pyp);
        } else { X->scrDX = X->scrDY = 0; X->scrIX = X->scrIY = X->scrAX = X->scrAY = 0; }
    }
}

/* ── 6b. 공용 엔티티 JSON 스키마 (어댑터 공통) ────────────────────────────
 * enttrack / etview 등 모든 어댑터가 "동일 스키마"를 쓰도록 여기서 한 번만 정의.
 * 필드명(통일): guid, cls, vft, sp, name, tile, world, dcell,
 *               scrA(확정 투영), scrI(보간 투영), dscr(보간-중심),
 *               isoA(확정 iso), isoI(보간 iso), distTile, distIso, qty,
 *               alive, dead, bait, atk, owner, tgt, on, self
 * 값 로직은 lcore(엔티티/보간/공격사건) 단일. 프레임 헤더는 lc_jsonHead/Foot.
 */
static void lc_jsonHead(FILE *f, DWORD t0, int cw, int ch, const LC_VIEW *v,
                        int sCX, int sCY, float sScr, float sScrY, int n)
{
    fprintf(f, "{\"t\":%u,\"res\":[%d,%d],\"scale\":%.4f,"
               "\"self\":{\"cell\":[%d,%d],\"scr\":[%.1f,%.1f]},\"n\":%d,\"ents\":[",
            (unsigned)(GetTickCount() - t0), cw, ch, v->sc, sCX, sCY, sScr, sScrY, n);
}
static void lc_jsonEnt(FILE *f, const LC_E *X, int cw, int ch, int first)
{
    int onScr = (X->scrIX >= -40 && X->scrIX <= cw + 40 &&
                 X->scrIY >= -40 && X->scrIY <= ch + 40);
    int qty = (X->vft == LC_VFT_ITEM || X->vft == LC_VFT_SEGPROP) ? (int)X->itemQty : -1;
    int contrib = (X->vft == LC_VFT_ITEM) ? (int)X->itemContrib : -1;
    const char *own = (X->vft == LC_VFT_ITEM)
        ? (X->itemOwn == 1 ? "MINE" : X->itemOwn == 2 ? "OTHER" : X->itemOwn == 3 ? "FREE" : "-") : "-";
    /* [2026-10-19] Door 이면 개폐 상태 추가(문 아닌 개체는 스키마 불변).
     * 값은 스냅샷(lc_fillDoor)이 채운 LC_E 캐시 사용 → JSON 방출 시 IOCTL 0. */
    char doorBuf[80]; doorBuf[0] = 0;
    if (X->doorSeen){
        snprintf(doorBuf, sizeof doorBuf,
                 ",\"door\":\"%s\",\"doorType\":\"0x%X\",\"doorFrame\":\"0x%X\",\"doorLocked\":%d",
                 lc_doorToken(X), X->doorGfx, X->doorFrame, X->doorLocked);
    }
    fprintf(f, "%s{\"guid\":\"0x%llX\",\"cls\":\"%s\",\"vft\":\"0x%X\",\"sp\":%u,\"name\":\"%s\","
               "\"tile\":[%d,%d],\"world\":[%d,%d],\"dcell\":[%d,%d],"
               "\"scr\":[%d,%d],\"iscr\":[%d,%d],\"dscr\":[%d,%d],"
               "\"iso\":[%.1f,%.1f],\"iiso\":[%.1f,%.1f],"
               "\"distTile\":%.2f,\"distIso\":%.1f,\"qty\":%d,\"contrib\":%d,\"own\":\"%s\","
               "\"alive\":%d,\"dead\":%d,\"bait\":%d,\"atk\":%d,\"owner\":\"0x%llX\",\"tgt\":\"0x%llX\","
               "\"atkValid\":%d,\"blk\":%d,\"tgtFA\":%u,\"tgtFB\":%u,\"a59a\":%u,\"deadSrc\":%d,"
               "\"on\":%d%s%s}",
        first ? "" : ",",
        (unsigned long long)X->guid, clsOf(X->vft), X->vft, X->sp, X->nm,
        X->cellx, X->celly, X->worldTx, X->worldTy, X->dCellX, X->dCellY,
        X->scrAX, X->scrAY, X->scrIX, X->scrIY, X->scrDX, X->scrDY,
        X->aU, X->aV, X->iU, X->iV,
        X->distTile, X->distIso, qty, contrib, own,
        X->dead ? 0 : 1, X->dead, X->bait, X->hasAtk,
        (unsigned long long)X->atkOwner, (unsigned long long)X->atkTgt,
        X->atkValid, X->atkBlocked, (unsigned)X->tgtFlagA, (unsigned)X->tgtFlagB,
        (unsigned)X->actorFlag59a, X->deadSrc,
        onScr, doorBuf, (X->guid == lc_meGuid) ? ",\"self\":1" : "");
}
static void lc_jsonFoot(FILE *f) { fprintf(f, "]}\n"); }

/* ── 7. event queue (worker -> UI) ──────────────────────────────────────── */
typedef struct {
    DWORD    t;
    char     kind[24];
    uint64_t g1, g2;
    int      i1, i2, i3, i4;
    char     a[80], b[80];
} LC_EV;
#define LC_EVQ 2048
static LC_EV   g_evq[LC_EVQ];
static int     g_evh = 0, g_evt = 0;
static CRITICAL_SECTION g_cs;
static int g_csInit = 0;
static void lc_csInit(void) { if (!g_csInit) { InitializeCriticalSection(&g_cs); g_csInit = 1; } }
static void lc_pushEv(const char *kind, uint64_t g1, uint64_t g2,
                      int i1, int i2, int i3, int i4, const char *a, const char *b)
{
    EnterCriticalSection(&g_cs);
    LC_EV *e = &g_evq[g_evt % LC_EVQ];
    memset(e, 0, sizeof(*e));
    e->t = GetTickCount();
    snprintf(e->kind, sizeof(e->kind), "%s", kind);
    e->g1 = g1; e->g2 = g2;
    e->i1 = i1; e->i2 = i2; e->i3 = i3; e->i4 = i4;
    if (a) snprintf(e->a, sizeof(e->a), "%s", a);
    if (b) snprintf(e->b, sizeof(e->b), "%s", b);
    g_evt++;
    LeaveCriticalSection(&g_cs);
}
static int lc_popEv(LC_EV *out)
{
    int got = 0;
    EnterCriticalSection(&g_cs);
    if (g_evh < g_evt) { *out = g_evq[g_evh % LC_EVQ]; g_evh++; got = 1; }
    else if (g_evt - g_evh > LC_EVQ) g_evh = g_evt;
    LeaveCriticalSection(&g_cs);
    return got;
}

#ifdef __cplusplus
}
#endif
#endif /* LCORE_H */
