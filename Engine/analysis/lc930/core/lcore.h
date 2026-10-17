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
static unsigned long long g_ioctl = 0;

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
#include "../../pgcache.h"
static int rm(uint64_t a, void *b, uint32_t s)
{
    int drv = 0;
    int ok = pg_read((uint64_t)g_pid, a, b, s, &drv);
    g_ioctl += (unsigned)drv;
    return ok;
}
static uint64_t q64(uint64_t a) { uint64_t v = 0; rm(a, &v, 8); return v; }
static uint32_t d32(uint64_t a) { uint32_t v = 0; rm(a, &v, 4); return v; }
static float    f32(uint64_t a) { float    v = 0; rm(a, &v, 4); return v; }
static int isHeap(uint64_t a) { return a >= 0x10000000000ULL && a < 0x80000000000ULL; }
static int isMod(uint64_t a)  { return a >= g_base && a < g_base + (uint64_t)g_modSize; }
static uint32_t vrva(uint64_t o) { uint64_t v = q64(o); return isMod(v) ? (uint32_t)(v - g_base) : 0; }

static void lc_dropAnchor(void);

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
    SignedSetTarget(pid);
    /* Same process: the image base does not move. Skip the PEB walk. */
    if (g_pid == (uint64_t)pid && g_base && g_modSize) return 0;
    g_pid = pid;
    g_base = 0;
    g_modSize = 0;
    lc_dropAnchor();
    if (!getModule(&g_base, &g_modSize)) { fprintf(stderr, "module base fail\n"); return 3; }
    return 0;
}

/* ── 2. constants (vft RVAs refreshed 2026-09-30 via RTTI) ──────────────── */
#define VFT_SELF      0x11819F0u
#define VFT_PLAYER    0x11819B8u
#define VFT_MONSTER   0x11818A8u
#define VFT_SUMMON    0x1181E58u
#define VFT_ITEM      0x1181838u
#define VFT_NPC       0x1181800u
#define VFT_SEGPROP   0x1181D58u
#define VFT_ACTOR     0x117DDF8u
#define VFT_PRES_B    0x1181738u   /* TransformComponent (PRES_B)          */
#define VFT_AC        0x1180DF0u   /* ActionComponent                      */
/* ActionComponent state fields (RESULTS_T2 sec14 / 9.30 entity.c isDead) */
#define AC_DEAD_OFF   0x49u        /* byte  : 1 = dead/corpse              */
#define AC_DEAD_VAL   1
#define AC_BAIT_OFF   0x40u        /* dword : 0x78 = bait(dormant, not shown) */
#define AC_BAIT_VAL   0x78u
#define VFT_ATTACKACT 0x1180B78u   /* AttackAction  +0x80 owner +0x88 target */
#define VFT_DEATH     0x1180AE8u
#define VFT_DEADBODY  0x11808A8u
#define VFT_BREATHACT 0x1180A10u
#define VFT_MAPSUBSYS 0x11C7DF0u   /* MapSubsystem   (live-verified)        */
#define VFT_ACTORSUBS 0x117EAD8u   /* ActorSubsystem (live-verified)        */
#define VFT_BEHAVIORS 0x1183140u   /* BehaviorSubsystem                    */
#define VFT_CTLCOMP   0x1181010u   /* ActorControllerComponent             */
#define VFT_SHIP      0x1181CB0u   /* Ship   (RTTI-indexed, +0x30)          */

/* ---- subsystems resolved OFFLINE by class-name lookup (delta_930.py) ----
 * These sit in the sub[64] array and are found by lc_subsGet(vft).  They are
 * RTTI-indexed in the 9.30 build (62 subsystems total), so the deltas below
 * are exact and were NOT guessed.  Regenerate on the next build with
 * T3_maps/delta_930.py -- game access is not required.                */
#define VFT_CHARDATA  0x1185340u   /* CharacterDataSubsystem sub[12]  (+0xA0) */
#define VFT_INVENTORY 0x11C6878u   /* InventorySubsystem   sub[26]  (-0x370) */
#define VFT_HUDSLOT   0x1182FC0u   /* HudSlotDataSubsystem sub[30]  (+0x78)  */
#define VFT_ITEMENT   0x11C66E8u   /* ItemEntity    (live-verified, no RTTI)  */
#define VFT_SHOP      0x11C9D28u   /* ShopSubsystem             sub[36] (+0x88)  */
#define VFT_PLAYERSHOP 0x11C96F8u  /* PlayerShopSubsystem               (+0x? ) */
#define VFT_BUYITEM   0x11DE710u   /* BuyListItem record           (+0x558)  */
#define VFT_SELLITEM  0x11DE778u   /* SellListItem record          (+0x558)  */
#define VFT_EQUIPINFO 0x11C6450u   /* EquipmentInfoSubsystem  (UI foothold)   */
#define VFT_DUNGEON   0x11C5A28u   /* DungeonSubsystem   (portal/dungeon)     */
#define VFT_SPELL     0x11CABF8u   /* SpellSubsystem                            */
#define VFT_STORAGE   0x11CB0B0u   /* StorageSubsystem                           */
#define VFT_BUFF      0x11BB770u   /* BuffSubsystem                              */
#define VFT_MAIL      0x1183290u   /* MailSubsystem                              */
#define VFT_CAMERA    0x118B540u   /* CameraSubsystem                            */
#define VFT_INPUT     0x1182D40u   /* InputSubsystem                             */
#define VFT_GAMESTATE 0x1182E30u   /* GameStateSubsystem                         */
#define VFT_NETWORK   0x1199D18u   /* NetworkSubsystem                           */
#define VFT_CHAT      0x11BBEC0u   /* ChatSubsystem                              */
#define VFT_PORTALACT 0x1189140u   /* PortalInteraction (portal track)           */

/* enttrack / etview geometry */
#define LC_MGR    0x1668790u
#define LC_HOLDER 0xD0u
#define LC_SUBB   0x180u
#define LC_PLAYER_X 0x1668640u    /* was 0x1668710 (moved this build) */
#define LC_PLAYER_Y 0x1668644u
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
static uint32_t LC_SUB_STRIDE    = 16u, LC_SUBCOUNT = 64u;
static uint32_t LC_MAP_CHILD     = 0x768u, LC_MAP_RECT_SCAN = 0x400u, LC_MAP_SCAN = 0x800u;
/* ActorSubsystem 셀맵 head 슬롯 (registry CELL_MAP_OFF1/2 로 갱신) */
static uint32_t LC_HEADS[2] = { 0x7A0u, 0x7E0u };

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
                LC_PRESB_B_OFF_V=0x78u, LC_PRESB_SCAN_V=0x200u;
static uint32_t LC_ACT_ATK_OWNER_V=0x80u, LC_ACT_ATK_TARGET_V=0x88u,
                LC_AC_SCAN_V=0x140u;
static uint32_t LC_ITEM_OWN_BEG_V=0x10u, LC_ITEM_OWN_END_V=0xC0u;
static uint32_t LC_SUB_STRIDE_V=16u, LC_SUBCOUNT_V=64u;
static uint32_t LC_MAP_CHILD_V=0x768u, LC_MAP_RECT_SCAN_V=0x400u,
                LC_MAP_SCAN_V=0x800u;

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
    LC_PRESB_BASE_V  =lcreg_u32("PRESB_BATCH_BASE", LC_PRESB_BASE_V);
    LC_PRESB_A_OFF_V =lcreg_u32("PRESB_A_OFF", LC_PRESB_A_OFF_V);
    LC_PRESB_B_OFF_V =lcreg_u32("PRESB_B_OFF", LC_PRESB_B_OFF_V);
    LC_PRESB_SCAN_V  =lcreg_u32("PRESB_SCAN_LEN", LC_PRESB_SCAN_V);
    LC_ACT_ATK_OWNER_V=lcreg_u32("ACT_ATK_OWNER", LC_ACT_ATK_OWNER_V);
    LC_ACT_ATK_TARGET_V=lcreg_u32("ACT_ATK_TARGET", LC_ACT_ATK_TARGET_V);
    LC_AC_SCAN_V     =lcreg_u32("AC_SCAN_LEN", LC_AC_SCAN_V);
    LC_ITEM_OWN_BEG_V=lcreg_u32("ITEM_OWN_SCAN_BEG", LC_ITEM_OWN_BEG_V);
    LC_ITEM_OWN_END_V=lcreg_u32("ITEM_OWN_SCAN_END", LC_ITEM_OWN_END_V);
    LC_SUB_STRIDE_V  =lcreg_u32("SUB_STRIDE",  LC_SUB_STRIDE_V);
    LC_SUBCOUNT_V    =lcreg_u32("SUBCOUNT",    LC_SUBCOUNT_V);
    LC_MAP_CHILD_V   =lcreg_u32("MAP_CHILD_OFF", LC_MAP_CHILD_V);
    LC_MAP_RECT_SCAN_V=lcreg_u32("MAP_RECT_SCAN_LEN", LC_MAP_RECT_SCAN_V);
    LC_MAP_SCAN_V    =lcreg_u32("MAP_SCAN_LEN", LC_MAP_SCAN_V);
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
    uint32_t itemType, itemQty;
    uint64_t itemOwner;      /* ground-item owner GUID (0 = free/no owner)   */
    int      itemOwnerSeen;  /* 1 = ownership slot scanned this frame        */
    uint32_t itemFlag;       /* +0x48 ownership/lock-state flag (0=free)     */
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
} LC_E;

#define LC_MAXE 512
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
} LC_LED;
#define LC_MAXLED 1024
static LC_LED lc_led[LC_MAXLED];
static int lc_ledN = 0, lc_gen = 0;
static unsigned long long lc_sweepCount = 0;

/* Subsystem lookup.
 *
 * The 9.30 patch reordered the subsystem array, so sub[22]/sub[23] no longer
 * carry ActorSubsystem/MapSubsystem (verified live: sub[22] vft = 0x117EAD8).
 * Subsystems must therefore be identified by their RTTI vtable, never by
 * index. LC_SUBIDX is kept only as a hint for diagnostics.
 */
#define LC_SUBIDX 64
static uint64_t lc_subs = 0;      /* subsystem array base (16-byte stride)  */
static uint32_t lc_subsCacheV[256];
static uint64_t lc_subsCacheP[256];
static int lc_subsCacheN = 0;
static int lc_subsCursor = 0;

static void lc_dropAnchor(void)
{
    lc_subs = 0;
    lc_actor = 0;
    lc_subsCacheN = 0;
    lc_subsCursor = 0;
}

static void lc_subsCacheAdd(uint32_t v, uint64_t s)
{
    int i;
    if (!v || lc_subsCacheN >= 256) return;
    for (i = 0; i < lc_subsCacheN; i++) if (lc_subsCacheV[i] == v) return;
    lc_subsCacheV[lc_subsCacheN] = v;
    lc_subsCacheP[lc_subsCacheN] = s;
    lc_subsCacheN++;
}

/* vft→pointer cache. A later lookup of a subsystem already walked is one
 * cache hit, not another pass over sub[]. Identification stays by vft. */
static uint64_t lc_subsGet(uint32_t wantVft)
{
    int c;
    for (c = 0; c < lc_subsCacheN; c++)
        if (lc_subsCacheV[c] == wantVft && isHeap(lc_subsCacheP[c])) return lc_subsCacheP[c];
    if (!lc_subs) return 0;
    while (lc_subsCursor < (int)LC_SUBCOUNT_V) {
        int i = lc_subsCursor++;
        uint64_t s = q64(lc_subs + (uint64_t)LC_SUB_STRIDE_V * i);
        uint32_t v1, v2;
        if (!isHeap(s)) continue;
        v1 = vrva(s);
        lc_subsCacheAdd(v1, s);
        if (v1 == wantVft) return s;
        v2 = vrva(s + 8);
        if (v2 != v1) lc_subsCacheAdd(v2, s);
        if (v2 == wantVft) return s;
    }
    return 0;
}
static int lc_anchor(void)
{
    uint64_t mgr, holder, subs, actor;
    /* Held actor still has its vft: the chain has not moved. One check. */
    if (lc_actor && lc_subs && vrva(lc_actor) == LC_VFT_ACTORSUBS) return 1;
    lc_dropAnchor();
    mgr = q64(g_base + LC_MGR_V);
    if (!isHeap(mgr)) return 0;
    holder = q64(mgr + LC_HOLDER_V);
    if (!isHeap(holder)) return 0;
    subs = q64(holder + LC_SUBB_V);
    if (!isHeap(subs)) return 0;
    lc_subs = subs;
    lc_subsCursor = 0;
    lc_subsCacheN = 0;
    actor = lc_subsGet(LC_VFT_ACTORSUBS);
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
    uint64_t src = (len >= 16) ? q64(no + LC_NAME_BYTES_V) : (no + LC_NAME_BYTES_V);
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

/* walk the cellmap once: refresh the ledger for every entity present.
 * returns the number of entities; fills e-list of pointers into ptrs[]. */
static int lc_sweepSlow(uint64_t *ptrs, int maxP)
{
    lc_gen++;
    int n = 0;
    for (int hi = 0; hi < 2 && n < maxP; hi++) {
        /* head slot -> sentinel container S; S+0x08 -> first node; a node's
         * +0x00 links back to S, and the last node's +0x08 closes the ring.
         * The entity vector is the node's [ +0x18, +0x20 ). */
        uint64_t sent = q64(lc_actor + LC_HEADS[hi]);
        if (!isHeap(sent)) continue;
        uint64_t c = q64(sent + 8);
        for (int g = 0; isHeap(c) && c != sent && g < 4000 && n < maxP; g++) {
            uint64_t vb = q64(c + LC_CELL_VEC_BEG_V), ve = q64(c + LC_CELL_VEC_END_V);
            if (isHeap(vb) && isHeap(ve) && ve >= vb) {
                int cnt = (int)((ve - vb) / 8);
                if (cnt > 0 && cnt < 6000) {
                    for (int i = 0; i < cnt && n < maxP; i++) {
                        uint64_t e = q64(vb + i * 8);
                        if (!isHeap(e) || q64(e + LC_ENT_SELF_V) != e) continue;
                        uint32_t v = vrva(e);
                        if (!isEntVft(v)) continue;
                        int dup = 0;
                        for (int k = 0; k < n; k++) if (ptrs[k] == e) { dup = 1; break; }
                        if (dup) continue;
                        LC_LED *L = lc_ledFind(e, 1);
                        if (L) {
                            L->seenGen = lc_gen;
                            if (!L->vft)          L->vft = v;
                            if (!L->hasName)      { if (lc_name(e, L->nm, sizeof(L->nm))) L->hasName = 1; }
                            if (!L->guid)         L->guid = q64(e + LC_ENT_GUID_V);
                            if (!L->presB)        L->presB = lc_findPresB(e);
                            if (!L->hasAc) {
                                uint64_t H = q64(e + LC_ENT_H_V);
                                uint64_t ac = isHeap(H) ? q64(H + LC_H_AC_OFF_V) : 0;
                                if (isHeap(ac) && vrva(ac) == LC_VFT_AC) { L->ac = ac; L->hasAc = 1; }
                            }
                        }
                        ptrs[n++] = e;
                    }
                }
            }
            c = q64(c + LC_CELL_NEXT_V);
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
        X->vft = L ? L->vft : vrva(e);
        X->guid = L && L->guid ? L->guid : q64(e + LC_ENT_GUID_V);
        X->presB = L ? L->presB : 0;
        X->ac = L ? L->ac : 0;
        X->sp = d32(e + LC_ENT_SPECIES_V);   /* ENT_SPECIES */
        if (L && L->hasName) { strncpy(X->nm, L->nm, sizeof(X->nm) - 1); X->nm[sizeof(X->nm)-1] = 0; }
        else lc_name(e, X->nm, sizeof(X->nm));
        X->cellx = -1; X->celly = -1;
        X->spawnMs = now;

        /* --- batched PRES_B read: cx,cy | A | B --- */
        if (X->presB && rm(X->presB + pbase, lc_presBuf, sizeof(lc_presBuf))) {
            int32_t cx, cy; float aU, aV, bU, bV;
            memcpy(&cx, lc_presBuf + 0x00, 4);
            memcpy(&cy, lc_presBuf + 0x04, 4);
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
            /* standard bait/dormant state (AC+0x40 dword == 0x78; SPEC entity.monster.bait) */
            X->bait = (d32(X->ac + LC_AC_BAIT_OFF) == LC_AC_BAIT_VAL) ? 1 : 0;
            for (uint32_t o = 0; o < LC_AC_SCAN_V; o += 8) {
                uint64_t w = q64(X->ac + o);
                if (!isHeap(w)) continue;
                uint32_t v = vrva(w);
                if (v == LC_VFT_ATTACKACT) {
                    X->hasAtk = 1; X->atkOwner = q64(w + LC_ACT_ATK_OWNER_V); X->atkTgt = q64(w + LC_ACT_ATK_TARGET_V);
                } else if (v == LC_VFT_DEATH || v == LC_VFT_DEADBODY) {
                    X->dead = 1;
                }
            }
            /* completed corpse rule also checks the ActionComponent dead byte (AC+0x49==1) */
            { uint8_t db = 0; if (rm(X->ac + LC_AC_DEAD_OFF, &db, 1) && db == (uint8_t)LC_AC_DEAD_VAL) X->dead = 1; }
        }
        /* --- ground item: type/qty (owner resolved in post-pass below) ---
         * 9.30 live-verified layout:
         *   e+0x18 = GUID (u64).  e+0x38 = u32 QUANTITY (previously misread
         *   as e+0x18, which overlaps the guid low dword).
         *   EfficiencyInventory count names show "??? (N)" and N==e+0x38. */
        if (X->vft == LC_VFT_ITEM) {
            X->itemType = d32(e + LC_ENT_SPECIES_V);
            X->itemQty  = d32(e + LC_ENT_SPECIES_V);   /* corrected: quantity == +0x38 */
            X->itemFlag = d32(e + LC_ENT_ITEM_FLAG_V); /* ownership/lock state (0=free)  */
        }
        lc_nc++;
    }
    /* interpolate every entity with the A/B pipeline */
    for (int i = 0; i < lc_nc; i++) lc_interpIso(&lc_cur[i], now);

    /* post-pass: ground-item ownership.  Only values equal to a live actor
     * GUID count as an owner; everything else (asian aDate free stacks)
     * stays 0 => free.  Runs after lc_cur is complete so all actors are
     * known. */
    for (int i = 0; i < lc_nc; i++) {
        LC_E *X = &lc_cur[i];
        if (X->vft != LC_VFT_ITEM) continue;
        X->itemOwner = 0; X->itemOwnerSeen = 1;
        for (uint32_t o = LC_ITEM_OWN_BEG_V; o < LC_ITEM_OWN_END_V && !X->itemOwner; o += 8) {
            uint64_t w = q64(X->e + o);
            if (!w || isHeap(w) || isMod(w)) continue;
            if (w == lc_meGuid) { X->itemOwner = w; break; }
            for (int k = 0; k < lc_nc; k++) {
                if (isActorish(lc_cur[k].vft) && lc_cur[k].guid == w) { X->itemOwner = w; break; }
            }
        }
    }
}

/* one-shot: sweep + poll, no separate 2-speed scheduling (livetrack / tests) */
static void lc_collect(void)
{
    static uint64_t ptrs[LC_MAXE];
    int n = lc_sweepSlow(ptrs, LC_MAXE);
    lc_pollFast(ptrs, n, GetTickCount());
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

/* ���� ?? ??: self ?? ??/??/???? ??? ��������������������������������������������
 *   lc_collect() + lc_pick_self() ?? ??. self? ??? cellx/celly ??. */
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
    fprintf(f, "%s{\"guid\":\"0x%llX\",\"cls\":\"%s\",\"vft\":\"0x%X\",\"sp\":%u,\"name\":\"%s\","
               "\"tile\":[%d,%d],\"world\":[%d,%d],\"dcell\":[%d,%d],"
               "\"scr\":[%d,%d],\"iscr\":[%d,%d],\"dscr\":[%d,%d],"
               "\"iso\":[%.1f,%.1f],\"iiso\":[%.1f,%.1f],"
               "\"distTile\":%.2f,\"distIso\":%.1f,\"qty\":%d,"
               "\"alive\":%d,\"dead\":%d,\"bait\":%d,\"atk\":%d,\"owner\":\"0x%llX\",\"tgt\":\"0x%llX\","
               "\"on\":%d%s}",
        first ? "" : ",",
        (unsigned long long)X->guid, clsOf(X->vft), X->vft, X->sp, X->nm,
        X->cellx, X->celly, X->worldTx, X->worldTy, X->dCellX, X->dCellY,
        X->scrAX, X->scrAY, X->scrIX, X->scrIY, X->scrDX, X->scrDY,
        X->aU, X->aV, X->iU, X->iV,
        X->distTile, X->distIso, qty,
        X->dead ? 0 : 1, X->dead, X->bait, X->hasAtk,
        (unsigned long long)X->atkOwner, (unsigned long long)X->atkTgt,
        onScr, (X->guid == lc_meGuid) ? ",\"self\":1" : "");
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
