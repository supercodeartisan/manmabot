/* chatmon_930.c — 채팅창 실시간 모니터 (독립 모듈)
 * ===========================================================================
 *  목적: 채팅창이 들고 있는 메시지를 실시간으로 읽어 "발신자 + 채널 + 본문"을
 *        콘솔에 스트리밍한다(파일에도 동일 내용 + TSV 이벤트 로그).
 *
 *  왜 별도 모듈인가
 *    · `chat_930`(정본·파일출력)은 창 + CHAT_LINES_OFF(0xF8) 의 **UI 배열**만 읽는다.
 *      이 배열은 **트랜지언트**(시간이 지나면 비워짐)라 느린 주기에서 라인을 놓치고
 *      **발신자 문자열이 없다**.
 *    · 메시지의 영속 정본 = 창 +0x10 → resource + CHAT_POOL_RES_OFF(0x4E8) 의 **라인 풀**.
 *      슬롯마다 std::string 3개(본문/전체/발신자)를 갖는다(2026-10-17 chatdump 실측).
 *
 *  고정앵커 + 고정체인 (registry 단일 진실 공급처 · 하드코딩 없음)
 *    anchor : UISubsystem = lc_subsGet(VFT_UISUBSYSTEM)
 *    창     : 컨테이너 walk(UIDLG_CONT head:next → UIDLG_CONT_VAL) → RTTI 단명 == CHAT_LAYOUT_CLASS
 *    resource = *(창 + CHAT_RESOURCE_OFF)
 *    pool     = *(resource + CHAT_POOL_RES_OFF)
 *    slot i   = pool + CHAT_POOL_ENTRY + i*CHAT_POOL_STRIDE        (i < CHAT_POOL_SLOTS)
 *       + CHAT_LINE_MSG(본문) / CHAT_LINE_FULL(전체) / CHAT_LINE_SENDER(발신자)
 *       각 std::string = {data@+0, size@OFF_STR_LEN, cap@OFF_STR_CAP}, cap<STR_SSO_MAX → SSO
 *    (보조) UI 배열 = *(창 + CHAT_LINES_OFF), stride CHAT_LINE_STRIDE, NULL 종료
 *       → **순서(오래된→최신)** 확인 + 입력중(끝이 CHAT_INPUT_CURSOR) 판별
 *    (보조) 입력필드 텍스트 = 창 + CHAT_INPUT_FIELD (디코드 가능한 경우만)
 *
 *  인코딩: CHAT_ENC(UTF-8) 우선, 실패 시 CHAT_ENC_FALLBACK(CP949) → UTF-8 로 출력.
 *
 *  IOCTL: 페이지 캐시(lc_pgRead)로 슬롯 3중 문자열 헤더를 슬롯당 0x60B 배치 읽기 →
 *         같은 페이지 내 슬롯들은 1콜로 커버된다. 변화 없는 슬롯은 디코드도 생략.
 *
 *  usage: chatmon_930.exe [secs] [-clear] [-all] [-v] [-raw] [registry] [out.txt]
 *    -clear : 매 사이클 콘솔을 지우고 다시 그림(라이브 뷰)
 *    -all   : 새 메시지 외에 현재 풀 전체도 매 사이클 표시
 *    -v     : 근거 모드 — 슬롯 index/hash/길이 + UI 배열 순서 + 입력필드
 *    -raw   : 원시 바이트(hex)도 표시(인코딩 판정용)
 *  출력: <EXE>\out\chatmon_out.txt
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

#define SLOT_CAP   128      /* 슬롯 배열 상한(안전) */
#define STR_CAP    0x400    /* 문자열 버퍼 */
#define EVENT_CAP  4096     /* 이벤트 링(중복 판정) */
#define UI_LINE_CAP 320     /* 채팅 히스토리/UI 라인 최대 보관 수(히스토리 상한 300) */
#define HIST_TAIL   2       /* 사이클당 읽는 최근 히스토리 개수(비용 제한, 중복은 캐시로 제거) */

/* ── registry ───────────────────────────────────────────────────────────── */
static uint32_t RG_UVFT, RG_CVAL, RG_TDNAME, RG_COLTD, RG_RESO;
static uint32_t RG_POOLOFF, RG_ENTRY, RG_STRIDE, RG_SLOTS;
static uint32_t RG_O_MSG, RG_O_FULL, RG_O_SEND;
static uint32_t RG_STRLEN, RG_STRCAP, RG_SSOMAX, RG_STRMAX;
static uint32_t RG_LINESOFF, RG_LINESTRIDE, RG_LINEMAX;
static uint32_t RG_INPFIELD;
static uint32_t RG_NOTICE, RG_POPVIS, RG_POPMSG, RG_RENDER, RG_LABEL, RG_LABEL2;
static uint32_t RG_CF_PANEL, RG_CF_VIS, RG_CF_MSG;   /* 확인 패널(chat+0x150) */
static uint32_t g_askType = 0;   /* ASK 종류 코드(구조) */
static char     g_myName[80];                        /* 내 캐릭터 이름(송/수신 판정) */
static int      g_myNameTried = 0;
static int      g_dump = 0;                          /* -dump : 확인패널/팝업 필드 진단 */
static int      g_delta = 0;                         /* -delta : 변화분만(기본=매 사이클 전체 현황) */
static int      g_learn = 0;                         /* -learn : 확인 팝업 표본 TSV 기록 */
static FILE    *g_lf = 0;
/* 채팅 유형 라벨(registry: CHAT_TYPE_LABELS="a/b:라벨,...") — 검증된 값만 */
#define CTL_CAP 16
static char g_ctlKey[CTL_CAP][16]; static char g_ctlName[CTL_CAP][32]; static int g_ctlN = 0;
static void parseTypeLabels(const char *s)
{
    const char *p = s ? s : "";
    while (*p && g_ctlN < CTL_CAP){
        char k[16] = "", nm[32] = "";
        if (sscanf(p, "%15[^:]:%31[^,]", k, nm) >= 1 && k[0]){
            snprintf(g_ctlKey[g_ctlN], sizeof g_ctlKey[0], "%s", k);
            snprintf(g_ctlName[g_ctlN], sizeof g_ctlName[0], "%s", nm);
            g_ctlN++;
        }
        p = strchr(p, ',');
        if (p) p++; else break;
    }
}
static const char *typeLabel(int a, int b)
{
    char key[16]; snprintf(key, sizeof key, "%d/%d", a, b);
    for (int i = 0; i < g_ctlN; i++) if (!strcmp(g_ctlKey[i], key)) return g_ctlName[i];
    return 0;
}
static void learnChatType(int chan, int a, int b, const char *lang, const char *msg)
{
    if (!g_learn) return;
    if (!g_lf){ const char *lp = lcreg_outpath("chatmon_learn.tsv");
                lcreg_mkdir_for(lp); g_lf = fopen(lp, "a");
                if (g_lf){ fprintf(g_lf, "# kind\tchan\ta/b\tlang\tsample\n"); fflush(g_lf); } }
    if (!g_lf) return;
    static char seen[64][24]; static int sn = 0;
    char key[24]; snprintf(key, sizeof key, "%d:%d/%d:%s", chan, a, b, lang);
    for (int i = 0; i < sn; i++) if (!strcmp(seen[i], key)) return;
    if (sn < 64) snprintf(seen[sn++], sizeof seen[0], "%s", key);
    fprintf(g_lf, "CHAT\t%d\t%d/%d\t%s\t%s\n", chan, a, b, lang, msg);
    fflush(g_lf);
}
/* 이름 대조(언어 비의존): 팝업/채팅 문자열에서 '실제 엔티티 이름'을 찾아 발신자를 판정 */
#define NAME_CAP 96
static char     g_names[NAME_CAP][80]; static int g_namesN = 0;
static unsigned g_namesMs = 0; static uint32_t RG_NAMESMS = 5000;
static int      RG_LATINFB = 0;   /* CHATMON_LATIN_FALLBACK: 텍스트 선두 라틴 토큰 폴백(기본 0=끔) */
static uint32_t RG_PINV_VFT = 0x122C720;  /* PartyInviteData vft (초대 대기 신호) */
/* ── 채팅 히스토리 (모듈 해석 확정 2026-10-20) ─────────────────────────
 *  sub+0x3F8 = std::map<int 채널, HIST>   (FUN_00484890 조회 / FUN_00488EB0 삽입)
 *  HIST = { array@0x08, mask@0x10, head@0x18, count@0x20 } (cap 300)
 *  bucket[idx] -> shared_ptr 블록 { ptr, rep } , ChatData = rep (vft 0x121BA90)
 *  ChatData: int @+0x08/+0x0C, msg@+0x18, full@+0x38, sender@+0x58, lang@+0x78 */
static uint32_t RG_HISTMAP = 0x3F8, RG_CD_VFT = 0x121BA90;
static uint32_t RG_CD_OFF[4] = { 0x18, 0x38, 0x58, 0x78 };  /* msg/full/sender/lang */
static uint32_t RG_H_ARR=0x08, RG_H_MASK=0x10, RG_H_HEAD=0x18, RG_H_CNT=0x20;
static uint32_t RG_HML_TEXT = 0x1E0;   /* HudMessageLayout 시스템 통보 텍스트 */
/* 확인 팝업 종류 = ASK 코드(panel+0x1C0 캡처 상위32) 로 식별(언어 비의존). registry: CHATMON_ASK_TYPES */
#define CTYPE_CAP 16
static uint32_t g_ctypeVft[CTYPE_CAP]; static char g_ctypeName[CTYPE_CAP][32]; static int g_ctypeN = 0;
static void parseCtypes(const char *s)
{
    const char *p = s ? s : "";
    while (*p && g_ctypeN < CTYPE_CAP){
        unsigned v = 0; char nm[32] = "";
        if (sscanf(p, "%x:%31[^,]", &v, nm) >= 1 && v){
            g_ctypeVft[g_ctypeN] = (uint32_t)v;
            snprintf(g_ctypeName[g_ctypeN], sizeof g_ctypeName[0], "%s", nm);
            g_ctypeN++;
        }
        p = strchr(p, ',');
        if (p) p++; else break;
    }
}
static const char *ctypeOf(uint32_t vftRva)
{
    for (int i = 0; i < g_ctypeN; i++) if (g_ctypeVft[i] == vftRva) return g_ctypeName[i];
    return 0;
}
static char     RG_POPUPS[256] = "CommonMessagePopup,CommonBigMessagePopup,ChatConfirmPanel";
static uint32_t RG_POPWALKMS = 2000;
static uint32_t RG_ENC, RG_ENCFB, RG_DEDUPN, RG_STOPEMPTY, RG_SCANLEN, RG_SCANRETRYMS, RG_SCANTRIES;
static uint32_t g_encTry[8]; static int g_encN = 0;   /* 인코딩 폴백 체인(언어 무관) */
static uint32_t g_poolOff = 0;     /* 사용 중인 pool 오프셋(자동탐색 시 갱신) */
static char     RG_CLASS[96], RG_CURCHAR[8];
static uint32_t g_chead[8], g_cnext[8]; static int g_ncont = 0;
static int      g_clear = 0, g_all = 0, g_verbose = 0, g_raw = 0;
static uint64_t g_winCache = 0;   /* 마지막으로 찾은 채팅창 인스턴스(유효성 재확인 후 재사용) */
static int      g_poolScanned = 0; /* 풀 자동탐색 성공 여부 */
static int      g_poolTries = 0;   /* 풀 자동탐색 시도 횟수 */
static int      g_emptyRuns = 0;   /* 줄 0개 연속 사이클(→ 창 재선택) */
static unsigned g_lastScanMs = 0;  /* 마지막 시도 시각 */
static int      g_statusSec = 0;   /* -status N : 변화가 없어도 N초마다 생존줄 출력(0=끔) */
static unsigned g_nextStatusMs = 0;  /* 다음 생존줄 시각(ms) */
/* 통보문(팝업) 캐시: 컨테이너 전수 walk 는 비싸므로 인스턴스만 캐시하고 주기적으로 재탐색 */
#define POPUP_CAP 8
static uint64_t g_pop[POPUP_CAP]; static int g_popN = 0;
static unsigned g_popWalkMs = 0;
/* 채팅창 UI 배열(현재 화면에 보이는 줄들, 오래된→최신) + 직전 사이클 사본(변화분 계산) */
static char     g_ui[UI_LINE_CAP][STR_CAP];
static char     g_uiPrev[UI_LINE_CAP][STR_CAP];
static int      g_uinPrev = 0;
static char     g_cur[UI_LINE_CAP][STR_CAP];     /* 이번 사이클 통합 항목(태그 포함) */
static int      g_curN = 0;

/* ── RTTI ───────────────────────────────────────────────────────────────── */
static int classOf(uint64_t vft, char *out, int cap)
{
    out[0] = 0;
    if (!isMod(vft)) return 0;
    uint64_t col = q64(vft - 8);
    if (!isMod(col)){ if (col > 0 && col < (uint64_t)g_modSize) col = g_base + col; else return 0; }
    uint32_t td_rva = 0; if (!lc_pgRead(col + RG_COLTD, &td_rva, 4)) return 0;
    uint64_t td = g_base + td_rva; if (!isMod(td)) return 0;
    char raw[512]; memset(raw, 0, sizeof raw);
    if (!lc_pgRead(td + RG_TDNAME, raw, sizeof raw - 1)) return 0;
    const char *p = raw; if (!strncmp(p, ".?AV", 4)) p += 4;
    int n = 0;
    while (*p && n < cap - 1){
        if (p[0] == '@' && p[1] == '@') break;
        if (p[0] == '@'){ if (n < cap - 2){ out[n++] = ':'; out[n++] = ':'; } p++; }
        else out[n++] = *p++;
    }
    out[n] = 0; return n > 0;
}
static void shortName(const char *nm, char *out, int cap)
{ int t = 0; while (nm[t] && nm[t] != ':' && t < cap - 1){ out[t] = nm[t]; t++; } out[t] = 0; }

/* vft → 짧은 클래스명 캐시 (노드 순회 시 RTTI 재읽기 제거 → IOCTL 대폭 감소) */
#define CC_MAX 1024
static uint64_t CC_vft[CC_MAX]; static char CC_nm[CC_MAX][96]; static int CC_n = 0;
static int classOfC(uint64_t vft, char *out, int cap)
{
    for (int i = 0; i < CC_n; i++) if (CC_vft[i] == vft){ snprintf(out, (size_t)cap, "%s", CC_nm[i]); return 1; }
    char nm[128];
    if (!classOf(vft, nm, sizeof nm)) return 0;
    shortName(nm, out, cap);
    if (CC_n < CC_MAX){ CC_vft[CC_n] = vft; snprintf(CC_nm[CC_n], sizeof CC_nm[0], "%s", out); CC_n++; }
    return 1;
}

/* 인코딩 이름 → 코드페이지 (registry 값이 "UTF-8" 같은 문자열이므로) */
static uint32_t encId(const char *e)
{
    if (!e || !e[0]) return CP_UTF8;
    if (!_stricmp(e, "UTF-8") || !_stricmp(e, "UTF8") || !_stricmp(e, "65001")) return CP_UTF8;
    if (!_stricmp(e, "CP949") || !_stricmp(e, "EUC-KR") || !_stricmp(e, "949")) return 949;
    if (!_stricmp(e, "CP932") || !_stricmp(e, "SHIFT-JIS") || !_stricmp(e, "932")) return 932;
    if (!_stricmp(e, "CP936") || !_stricmp(e, "GBK") || !_stricmp(e, "936")) return 936;
    return CP_ACP;
}

/* ── std::string 파서 (헤더는 이미 읽힌 버퍼에서, 데이터는 필요 시 읽기) ── */
/*   hdr  = std::string 시작 주소의 0x20 바이트 버퍼
 *   base = hdr 가 속한 슬롯 시작 주소(hdr - base = 필드 오프셋) */
static int strFromHdr(const uint8_t *hdr, int cap, uint8_t *out, int verbose_note)
{
    (void)verbose_note;
    out[0] = 0;
    uint64_t sz = *(const uint64_t *)(hdr + RG_STRLEN);
    uint64_t cp = *(const uint64_t *)(hdr + RG_STRCAP);
    if (!(sz > 0 && sz < RG_STRMAX && cp >= sz)) return 0;
    if (sz > (uint64_t)cap - 1) sz = (uint64_t)cap - 1;
    if (cp < RG_SSOMAX){ memcpy(out, hdr, (size_t)sz); out[sz] = 0; return (int)sz; }
    uint64_t q = *(const uint64_t *)hdr;
    if (!isHeap(q)) return 0;
    if (!lc_pgRead(q, out, (uint32_t)sz)) return 0;
    out[sz] = 0; return (int)sz;
}
/* 인코딩 폴백 체인: UTF-8 → CP949 → CP936(중국 간체) → CP950(대만 번체) …
 *   registry CHAT_ENC_TRY 로 순서/구성을 바꿀 수 있다. (로케일 비의존 디코드) */
static void decodeStr(const uint8_t *b, int n, char *out, int cap)
{
    out[0] = 0;
    if (n <= 0) return;
    wchar_t wb[0x800];
    int wn = 0;
    for (int i = 0; i < g_encN && wn <= 0; i++)
        wn = MultiByteToWideChar(g_encTry[i], MB_ERR_INVALID_CHARS, (const char *)b, n, wb, 0x800);
    for (int i = 0; i < g_encN && wn <= 0; i++)          /* 엄격 판정 실패 → 관용 판정 */
        wn = MultiByteToWideChar(g_encTry[i], 0, (const char *)b, n, wb, 0x800);
    if (wn <= 0){ snprintf(out, (size_t)cap, "%s", "(decode-fail)"); return; }
    int un = WideCharToMultiByte(CP_UTF8, 0, wb, wn, out, cap - 1, 0, 0);
    if (un < 0) un = 0;
    out[un] = 0;
}
/* std::string (절대주소) → 원시 바이트 */
static int strFromHdr2(uint64_t addr, uint8_t *out, int cap)
{
    uint8_t h[0x20];
    if (!lc_pgRead(addr, h, sizeof h)) return 0;
    return strFromHdr(h, cap, out, 0);
}
static void hexOf(const uint8_t *b, int n, char *out, int cap, int maxb)
{
    int o = 0; out[0] = 0;
    if (n > maxb) n = maxb;
    for (int i = 0; i < n && o < cap - 4; i++) o += snprintf(out + o, (size_t)(cap - o), "%02X ", b[i]);
}

/* ── 이벤트 중복 링 ─────────────────────────────────────────────────────── */
static uint64_t g_ev[EVENT_CAP]; static int g_ev_n = 0, g_ev_i = 0;
static uint64_t fnv1a_n(const void *p, size_t n, uint64_t h)
{
    const uint8_t *b = (const uint8_t *)p;
    while (n--){ h ^= *b++; h *= 1099511628211ULL; }
    return h;
}
static uint64_t fnv1a(const void *p, size_t n)
{ return fnv1a_n(p, n, 1469598103934665603ULL); }
static int evSeen(uint64_t h, int remember)
{
    int lim = g_ev_n < EVENT_CAP ? g_ev_n : EVENT_CAP;
    for (int i = 0; i < lim; i++) if (g_ev[i] == h) return 1;
    if (remember){
        g_ev[g_ev_i] = h;
        g_ev_i = (g_ev_i + 1) % (RG_DEDUPN && RG_DEDUPN <= EVENT_CAP ? (int)RG_DEDUPN : EVENT_CAP);
        if (g_ev_n < (RG_DEDUPN && RG_DEDUPN <= EVENT_CAP ? (int)RG_DEDUPN : EVENT_CAP)) g_ev_n++;
    }
    return 0;
}

/* ── 채팅창 탐색 ────────────────────────────────────────────────────────── */
static uint64_t findChatWindow(uint64_t ui)
{
    for (int c = 0; c < g_ncont && isHeap(ui); c++){
        uint64_t node = q64(ui + g_chead[c]);
        for (int n = 0; isHeap(node) && n < 4096; n++){
            uint64_t x = q64(node + RG_CVAL);
            if (isHeap(x)){
                char sh[96];
                if (classOfC(q64(x), sh, sizeof sh) && !strcmp(sh, RG_CLASS)) return x;
            }
            uint64_t nx = q64(node + g_cnext[c]); if (nx == node) break; node = nx;
        }
    }
    return 0;
}

/* 풀 포인터 정합성: 힙 + 8정렬 + 실제 판독 가능 (isHeap 단독은 너무 느슨) */
static int poolOk(uint64_t p)
{
    if (!isHeap(p) || (p & 7)) return 0;
    uint8_t h[0x40];
    return lc_pgRead(p, h, sizeof h) != 0;
}

/* 등록 오프셋이 무효할 때: resource 필드(0..CHAT_POOL_SCAN_LEN, 8B 간격)를 훑어 *   "엔트리 배열"처럼 보이는 힙 포인터를 1회 탐색한다(슬롯 16개 중 3개 이상 문자열).
 *   반환 = pool, foundOff 에 발견 오프셋. (IOCTL: 페이지 캐시로 제한적) */
static uint64_t poolScan(uint64_t res, uint32_t scanlen, uint32_t *foundOff)
{
    if (!isHeap(res)) return 0;
    for (uint32_t off = 0; off + 8 <= scanlen; off += 8){
        uint64_t p = q64(res + off);
        if (!poolOk(p)) continue;
        /* 후보 검사: 슬롯 3개만 확인(첫 슬롯 1콜 위주 → IOCTL 최소) */
        int hits = 0;
        for (uint32_t s = 0; s < 3; s++){
            uint8_t blk[0x60];
            if (!lc_pgRead(p + RG_ENTRY + (uint64_t)s * RG_STRIDE, blk, sizeof blk)) break;
            uint8_t rb[STR_CAP];
            if (strFromHdr(blk + RG_O_MSG, sizeof rb, rb, 0) > 0) hits++;
            else if (strFromHdr(blk + RG_O_FULL, sizeof rb, rb, 0) > 0) hits++;
            else if (strFromHdr(blk + RG_O_SEND, sizeof rb, rb, 0) > 0) hits++;
        }
        if (hits >= 2){ if (foundOff) *foundOff = off; return p; }
    }
    return 0;
}

/* 창의 줄 수(0xF8 배열에서 NULL 전까지의 유효 포인터 개수) — 후보 채점용 */
/* ── 슬롯 ───────────────────────────────────────────────────────────────── */
static int countLines(uint64_t win)
{
    if (!isHeap(win)) return 0;
    uint64_t lines = q64(win + RG_LINESOFF);
    if (!isHeap(lines)) return 0;
    uint32_t want = RG_LINEMAX * 8; if (want > 0x400) want = 0x400;
    uint8_t ptrbuf[0x400];
    if (!lc_pgRead(lines, ptrbuf, want)) return 0;
    int cnt = 0;
    for (uint32_t i = 0; i * 8 + 8 <= want; i++){
        uint64_t p; memcpy(&p, ptrbuf + i * 8, 8);
        if (!isHeap(p)) break;
        cnt++;
    }
    return cnt;
}

/* 같은 클래스(HudChatLayoutPCImpl) 창이 여러 개일 수 있다 → 줄이 가장 많은 것을 고른다.
 *   (탭/팝업 채팅창이 동시에 존재하는 경우 오선택 방지) */
static uint64_t pickChatWindow(uint64_t ui, int *pScore)
{
    uint64_t best = 0; int bestN = -1;
    for (int c = 0; c < g_ncont && isHeap(ui); c++){
        uint64_t node = q64(ui + g_chead[c]);
        for (int n = 0; isHeap(node) && n < 4096; n++){
            uint64_t x = q64(node + RG_CVAL);
            if (isHeap(x)){
                char sh[96];
                if (classOfC(q64(x), sh, sizeof sh) && !strcmp(sh, RG_CLASS)){
                    int cnt = countLines(x);
                    if (cnt > bestN){ bestN = cnt; best = x; }
                }
            }
            uint64_t nx = q64(node + g_cnext[c]); if (nx == node) break; node = nx;
        }
    }
    if (pScore) *pScore = bestN;
    return best;
}
typedef struct { uint64_t hash; int ok; char chan[24]; char sender[0x100], msg[STR_CAP], full[STR_CAP]; char rawhex[3 * 48 * 3 + 8]; } Slot;
static Slot g_slot[SLOT_CAP];
static int  g_nslot = 0;

/* UI 배열의 한 줄을 풀 정보(채널·발신자)로 보강한다. 풀에 없으면 원문 그대로. */
static void enrichLine(const char *line, char *out, int cap)
{
    for (int i = 0; i < g_nslot; i++){
        if (!strcmp(g_slot[i].msg, line) || (g_slot[i].full[0] && !strcmp(g_slot[i].full, line))){
            if (g_slot[i].sender[0])
                snprintf(out, (size_t)cap, "%s %s : %s", g_slot[i].chan, g_slot[i].sender, line);
            else
                snprintf(out, (size_t)cap, "%s %s", g_slot[i].chan, line);
            return;
        }
    }
    snprintf(out, (size_t)cap, "%s", line);
}

/* 채널 라벨: 전체문자열이 "[X] ..." / 본문이 "[X] ..." 형태면 X, 아니면 "-" */
static void chanOf(const char *full, const char *msg, char *out, int cap)
{
    const char *s = (full && full[0]) ? full : msg;
    out[0] = 0;
    if (s && s[0] == '['){
        const char *e = strchr(s, ']');
        if (e && e - s > 1 && e - s < cap - 1){ int n = (int)(e - s + 1); memcpy(out, s, (size_t)n); out[n] = 0; return; }
    }
    snprintf(out, (size_t)cap, "-");
}

/* 두 라인 리스트의 변화분 계산(시프트 정렬).
 *   배열은 "앞에서 오래된 줄이 빠지고 뒤에 새 줄이 붙는" 형태이므로
 *   prev 의 접미부 == cur 의 접두부 인 시프트 s 를 찾아
 *     · 빠진 줄 = prev[0..s)
 *     · 새 줄   = cur[lim..curN)   (lim = min(prevN - s, curN))
 *   로 분해한다. 정렬 실패(완전 교체) 시 s=prevN, lim=0. */
static void diffLines(char cur[][STR_CAP], int curN, char prev[][STR_CAP], int prevN, int *pShift, int *pLim)
{
    int shift = -1, lim = 0;
    for (int s = 0; s <= prevN; s++){
        int ok = 1, l = prevN - s;
        if (l > curN) l = curN;
        for (int i = 0; i < l; i++) if (strcmp(cur[i], prev[s + i])){ ok = 0; break; }
        if (ok){ shift = s; lim = l; break; }
    }
    if (shift < 0){ shift = prevN; lim = 0; }
    *pShift = shift; *pLim = lim;
}

static int selftest(void)
{
    static char cur[UI_LINE_CAP][STR_CAP], prev[UI_LINE_CAP][STR_CAP];
    int cn, pn, sh, lm, step;
    printf("chatmon deltarule selftest\n");
    /* 1) 최초: 3줄 */
    const char *s1[] = { "ㅎㅇ", "어디야", "ㅋㅋ" };
    cn = 3; for (int i = 0; i < cn; i++) snprintf(cur[i], STR_CAP, "%s", s1[i]);
    pn = 0; diffLines(cur, cn, prev, pn, &sh, &lm);
    printf("  step1: 빠짐=%d 새줄=%d (기대 0/3)\n", sh, cn - lm);
    memcpy(prev, cur, sizeof cur); pn = cn;
    /* 2) 새 줄 1개 추가 → 새줄 1 */
    const char *s2[] = { "ㅎㅇ", "어디야", "ㅋㅋ", "집합!" };
    cn = 4; for (int i = 0; i < cn; i++) snprintf(cur[i], STR_CAP, "%s", s2[i]);
    diffLines(cur, cn, prev, pn, &sh, &lm);
    printf("  step2: 빠짐=%d 새줄=%d (기대 0/1)\n", sh, cn - lm);
    memcpy(prev, cur, sizeof cur); pn = cn;
    /* 3) 2줄 추가 + 1줄 밀려남 → 빠짐 1 / 새줄 3 */
    const char *s3[] = { "ㅋㅋ", "집합!", "가자", "출발" };
    cn = 4; for (int i = 0; i < cn; i++) snprintf(cur[i], STR_CAP, "%s", s3[i]);
    diffLines(cur, cn, prev, pn, &sh, &lm);
    printf("  step3: 빠짐=%d 새줄=%d (기대 2/2: 앞 2줄 밀려남, 새 줄 2개)\n", sh, cn - lm);
    /* 4) 완전 교체 */
    const char *s4[] = { "전혀", "다른", "내용" };
    cn = 3; for (int i = 0; i < cn; i++) snprintf(cur[i], STR_CAP, "%s", s4[i]);
    diffLines(cur, cn, prev, pn, &sh, &lm);
    printf("  step4: 빠짐=%d 새줄=%d (기대 4/3)\n", sh, cn - lm);
    (void)step;
    return 0;
}

/* std::string(절대주소) → UTF-8 */
static int strAtAddr(uint64_t addr, char *out, int cap)
{
    uint8_t rb[STR_CAP];
    int n = strFromHdr2(addr, rb, sizeof rb);
    if (n <= 0){ out[0] = 0; return 0; }
    decodeStr(rb, n, out, cap);
    return out[0] != 0;
}
/* 위젯 → 렌더러(+WIDGET_RENDERER) → 라벨 std::string(+LABEL_TEXT_OFF, 대체 WIN_LABEL_TEXT2) */
static int widgetText(uint64_t w, char *out, int cap)
{
    out[0] = 0;
    if (!isHeap(w)) return 0;
    uint64_t r = q64(w + RG_RENDER);
    if (!isHeap(r)) return 0;
    if (strAtAddr(r + RG_LABEL, out, cap)) return 1;
    if (strAtAddr(r + RG_LABEL2, out, cap)) return 1;
    return 0;
}
static int popupMatch(const char *cls)
{
    char buf[256]; snprintf(buf, sizeof buf, "%s", RG_POPUPS);
    for (char *t = strtok(buf, ","); t; t = strtok(0, ","))
        if (!strcmp(cls, t)) return 1;
    return 0;
}
/* 팝업(통보문) 창 인스턴스 캐시 갱신 — walk 는 CHATMON_POPUP_WALK_MS 주기로만 */
static void walkPopups(uint64_t ui, unsigned now)
{
    if (now - g_popWalkMs < RG_POPWALKMS && g_popN > 0) return;
    g_popWalkMs = now; g_popN = 0;
    for (int c = 0; c < g_ncont && isHeap(ui); c++){
        uint64_t node = q64(ui + g_chead[c]);
        for (int n = 0; isHeap(node) && n < 4096; n++){
            uint64_t x = q64(node + RG_CVAL);
            if (isHeap(x)){
                char sh[96];
                if (classOfC(q64(x), sh, sizeof sh) && popupMatch(sh) && g_popN < POPUP_CAP)
                    g_pop[g_popN++] = x;
            }
            uint64_t nx = q64(node + g_cnext[c]); if (nx == node) break; node = nx;
        }
    }
}
static const char *nameInText(const char *s, int startIfPrefix);   /* fwd decl */

/* 파티 초대 대기 신호: PartyInviteData(vft) 인스턴스가 그래프에 존재하는가.
 *   언어와 무관한 '구조' 신호다. 확인 패널이 떠 있을 때만 호출(비용 제한). */
static int partyInvitePresent(uint64_t win)
{
    uint64_t psub = lc_subsGet(lcreg_u32("PARTY_VFT_SUBS", 0x1228B10));
    uint64_t roots[2] = { psub, isHeap(win) ? q64(win + RG_RESO) : 0 };
    uint32_t lens[2] = { 0x800, 0x1000 };
    for (int r = 0; r < 2; r++){
        uint64_t base = roots[r];
        if (!isHeap(base)) continue;
        for (uint32_t o = 0; o + 8 <= lens[r]; o += 8){
            uint64_t p = q64(base + o);
            if (!isHeap(p) || (p & 7)) continue;
            uint64_t v = q64(p);
            if (isMod(v) && (uint32_t)(v - g_base) == RG_PINV_VFT) return 1;
        }
    }
    return 0;
}

/* 표시중인 통보문 텍스트를 g_cur 에 추가 */
static void collectPopups(int *cn)
{
    for (int i = 0; i < g_popN; i++){
        uint64_t x = g_pop[i];
        if (!isHeap(x)) continue;
        if (!q64(x + RG_POPVIS)) continue;                 /* +0x78 == 0 → 표시중 아님 */
        char t[STR_CAP] = "";
        if (!strAtAddr(x + RG_POPMSG, t, sizeof t)){        /* +0xC8 우선 */
            for (uint32_t o = 0; o + 8 <= 0x200; o += 8){   /* 없으면 필드 스캔 */
                uint64_t p = q64(x + o);
                if (!isHeap(p)) continue;
                if (strAtAddr(p, t, sizeof t) && strlen(t) > 3) break;
                t[0] = 0;
                if (widgetText(p, t, sizeof t) && t[0]) break;
            }
        }
        if (t[0] && *cn < UI_LINE_CAP)
            snprintf(g_cur[(*cn)++], STR_CAP, "[통보] %s", t);
    }
}

/* vft 로 인스턴스 찾기(그래프 1단계 스캔) — 언어 비의존 구조 신호 */
static uint64_t instanceByVft(uint64_t base, uint32_t len, uint32_t vftRva)
{
    if (!isHeap(base)) return 0;
    for (uint32_t o = 0; o + 8 <= len; o += 8){
        uint64_t p = q64(base + o);
        if (!isHeap(p) || (p & 7)) continue;
        uint64_t v = q64(p);
        if (isMod(v) && (uint32_t)(v - g_base) == vftRva) return p;
    }
    return 0;
}
/* 인스턴스 내부에서 이름(std::string) 후보를 하나 고른다(가장 긴 것, 메시지 본문 제외) */
static int firstStringIn(uint64_t obj, uint32_t len, const char *exclude, char *out, int cap)
{
    out[0] = 0;
    if (!isHeap(obj)) return 0;
    size_t best = 0;
    for (uint32_t o = 0; o + 8 <= len; o += 8){
        char s[256];
        if (!strAtAddr(obj + o, s, sizeof s) || !s[0]) continue;
        if (exclude && exclude[0] && strstr(exclude, s)) continue;   /* 본문 일부 제외 */
        size_t L = strlen(s);
        if (L < 2 || L > 24) continue;
        if (L > best){ best = L; snprintf(out, (size_t)cap, "%s", s); }
    }
    return out[0] != 0;
}

/* functor(콜백) 덤프: vft RVA + 캡처 필드 — 팝업 '종류'의 구조 키 후보 */
static void dumpFunctor(FILE *f, uint64_t o, const char *tag)
{
    if (!isHeap(o)) return;
    uint64_t v = q64(o);
    fprintf(f, "   [%s] obj=0x%llX vft=0x%X\n", tag, (unsigned long long)o,
            isMod(v) ? (uint32_t)(v - g_base) : 0);
    for (uint32_t k = 0x08; k + 8 <= 0x70; k += 8){
        uint64_t x = q64(o + k);
        if (!x) continue;
        char s[128];
        if (strAtAddr(o + k, s, sizeof s) && s[0])
            fprintf(f, "      +0x%02X STR \"%s\"\n", k, s);
        else if (x < 0x1000000)
            fprintf(f, "      +0x%02X INT 0x%llX\n", k, (unsigned long long)x);
        else if (isHeap(x)){
            char c2[96] = "-";
            if (classOfC(q64(x), c2, sizeof c2)) fprintf(f, "      +0x%02X OBJ 0x%llX cls=%s\n", k, (unsigned long long)x, c2);
            else fprintf(f, "      +0x%02X PTR 0x%llX\n", k, (unsigned long long)x);
        }
    }
    /* +0x08 캡처 포인터(패킷/메시지) 내부 덤프 — ASK 종류/발신자 구조 확인용 */
    uint64_t pl = q64(o + 0x08);
    if (isHeap(pl)){
        uint64_t pv = q64(pl);
        fprintf(f, "      [payload] 0x%llX vft=0x%X\n", (unsigned long long)pl,
                isMod(pv) ? (uint32_t)(pv - g_base) : 0);
        for (uint32_t k2 = 0; k2 + 8 <= 0x200; k2 += 8){
            uint64_t y = q64(pl + k2);
            if (!y) continue;
            char s2[256], c3[96] = "-";
            if (strAtAddr(pl + k2, s2, sizeof s2) && s2[0]) fprintf(f, "         +0x%03X STR \"%s\"\n", k2, s2);
            else if (y < 0x1000000) fprintf(f, "         +0x%03X INT 0x%llX (%llu)\n", k2, (unsigned long long)y, (unsigned long long)y);
            else if (isHeap(y) && classOfC(q64(y), c3, sizeof c3)) fprintf(f, "         +0x%03X OBJ cls=%s\n", k2, c3);
        }
    }
}

/* 확인(Confirm) 패널: HudChatLayoutPCImpl + CHATCONFIRM_PANEL_OFF(0x150) *   +0x78 != 0 → 표시중,  +0xC8 = 메시지(std::string).   (winmon 실측 확정)
 *   ※ 'ChatConfirmPanel' 은 창 클래스가 아니라 이 패널이다(오해 정정). */
static void collectConfirm(FILE *f, uint64_t win, unsigned el, int *cn)
{
    if (!isHeap(win)) return;
    uint64_t panel = q64(win + RG_CF_PANEL);
    if (!isHeap(panel)) return;
    if (!q64(panel + RG_CF_VIS)) return;                   /* 표시중 아님 */
    char t[STR_CAP] = "";
    if (!strAtAddr(panel + RG_CF_MSG, t, sizeof t)) return;
    if (!t[0]) return;
    /* ── 발신/수신/종류 판정 ──────────────────────────────────────────────
     *  언어 비의존: ① PartyInviteData 인스턴스(구조) ② 이름 대조 ③ 본문 내 이름
     *  비용: 메시지가 바뀔 때만 스캔(해시 캐시). */
    static uint64_t cfHash = 0; static char cfSender[80] = "", cfType[32] = "-";
    uint64_t h = fnv1a(t, strlen(t));
    if (h != cfHash){
        cfHash = h; cfSender[0] = 0; snprintf(cfType, sizeof cfType, "%s", "-");
        /* ① 종류 = 콜백 functor vft (구조 키, 언어 비의존) */
        uint64_t cb1 = q64(panel + 0x78), cb2 = q64(panel + 0xB8);
        uint32_t v1 = 0, v2 = 0;
        if (isHeap(cb1)){ uint64_t v = q64(cb1); if (isMod(v)) v1 = (uint32_t)(v - g_base); }
        if (isHeap(cb2)){ uint64_t v = q64(cb2); if (isMod(v)) v2 = (uint32_t)(v - g_base); }
        /* 종류: 콜백 람다 vft 는 '범용'(lambda_3/4) → 종류 키로 쓰지 않는다.
         *   호출자 콜백(+0x1C0)에 캡처된 ASK 값의 상위 32bit 를 종류 코드로 본다(검증 진행 중). */
        g_askType = 0;
        { uint64_t cb3 = q64(panel + 0x1C0);
          if (isHeap(cb3)){
              uint64_t cap = q64(cb3 + 0x10);
              g_askType = (uint32_t)(cap >> 32);
          } }
        { const char *tn = ctypeOf(g_askType);
          snprintf(cfType, sizeof cfType, "%s", tn ? tn : ""); }   /* 매핑 없으면 라벨 생략(추정 금지) */
        /* ② 발신자: 구조(초대 데이터) 우선 → 이름 대조 순 */
        uint64_t psub = lc_subsGet(lcreg_u32("PARTY_VFT_SUBS", 0x1228B10));
        uint64_t inv = instanceByVft(psub, 0x800, RG_PINV_VFT);
        if (!inv && isHeap(win)) inv = instanceByVft(q64(win + RG_RESO), 0x1000, RG_PINV_VFT);
        if (inv) firstStringIn(inv, 0x200, t, cfSender, sizeof cfSender);
        if (!cfSender[0]){
            const char *nm = nameInText(t, 0);
            if (nm) snprintf(cfSender, sizeof cfSender, "%s", nm);
        }
        if (!cfSender[0] && RG_LATINFB) leadingLatinName(t, cfSender, sizeof cfSender); /* 옵션: 라틴 토큰 폴백 */
        if (g_learn){
            if (!g_lf){ const char *lp = lcreg_outpath("chatmon_learn.tsv");
                        lcreg_mkdir_for(lp); g_lf = fopen(lp, "a");
                        if (g_lf){ fprintf(g_lf, "# t\ttype\task\tsender\treceiver\ttext\n"); fflush(g_lf); } }
            if (g_lf){
                fprintf(g_lf, "%u\t%u\t%u\t%s\t%s\t%s\n",
                        el, (uint32_t)q64(panel + 0xC0), g_askType,
                        cfSender[0] ? cfSender : "-", g_myName[0] ? g_myName : "(나)", t);
                fflush(g_lf);
            }
        }
        if (g_dump)
            fprintf(f, "[DUMP-TYPE] t=%ums msgHash=%016llX type=%s cb1vft=0x%X cb2vft=0x%X sender=\"%s\" inv=0x%llX psub=0x%llX\n",
                    el, (unsigned long long)h, cfType, v1, v2, cfSender,
                    (unsigned long long)inv, (unsigned long long)psub);
    }
    /* 확인 패널은 '나에게' 오는 것이 기본 → 수신자 = 나 */
    const char *rcv = g_myName[0] ? g_myName : "(나)";
    char sender[80]; snprintf(sender, sizeof sender, "%s", cfSender[0] ? cfSender : "-");
    uint32_t ptype = (uint32_t)q64(panel + 0xC0);      /* ConfirmPanelParam.type (구조 값) */
    const char *grp = (g_askType >= 0x3B7 && g_askType <= 0x3BA) ? " [grp 0x3B7-0x3BA]" : "";
    if (*cn < UI_LINE_CAP)
        snprintf(g_cur[(*cn)++], STR_CAP, "[통보%s type=%u ask=%u%s] 발신=%s 수신=%s \"%s\"",
                 cfType[0] ? cfType : "", ptype, g_askType, grp, sender, rcv, t);
    if (g_dump){
        fprintf(f, "[DUMP-CONFIRM] t=%ums panel=0x%llX (문자열/정수 후보)\n",
                el, (unsigned long long)panel);
        for (uint32_t o = 0; o + 8 <= 0x200; o += 8){
            uint64_t v = q64(panel + o);
            if (!v) continue;
            char s[256];
            if (strAtAddr(panel + o, s, sizeof s) && s[0])
                fprintf(f, "   +0x%03X STR  \"%s\"\n", o, s);
            else if (v < 0x100000)
                fprintf(f, "   +0x%03X INT  0x%llX (%llu)\n", o,
                        (unsigned long long)v, (unsigned long long)v);
            else if (isHeap(v)){
                char c2[96];
                if (classOfC(q64(v), c2, sizeof c2)){
                    uint64_t vv = q64(v);
                    fprintf(f, "   +0x%03X OBJ  0x%llX cls=%s vft=0x%X\n", o, (unsigned long long)v, c2,
                            isMod(vv) ? (uint32_t)(vv - g_base) : 0);
                    if (strstr(c2, "_Func_impl")) dumpFunctor(f, v, "functor");
                }
            }
        }
        /* 메시지 렌더러(ChatRichText) 내부 — 발신자/세그먼트 구조 확인용 */
        { uint64_t rt = q64(panel + 0x20);
          if (isHeap(rt)){
              fprintf(f, "   [rich] obj=0x%llX\n", (unsigned long long)rt);
              for (uint32_t k = 0; k + 8 <= 0x180; k += 8){
                  uint64_t x = q64(rt + k);
                  if (!x) continue;
                  char s[256]; char c2[96] = "-";
                  if (strAtAddr(rt + k, s, sizeof s) && s[0]) fprintf(f, "      +0x%03X STR \"%s\"\n", k, s);
                  else if (x < 0x100000) fprintf(f, "      +0x%03X INT 0x%llX\n", k, (unsigned long long)x);
                  else if (isHeap(x) && classOfC(q64(x), c2, sizeof c2)) fprintf(f, "      +0x%03X OBJ cls=%s\n", k, c2);
              }
          } }
        /* 콜백(functor) 2개 = 확인 동작(예/아니오). vft 가 종류 식별 키 후보. */
        dumpFunctor(f, q64(panel + 0x78), "cb+0x78");
        dumpFunctor(f, q64(panel + 0xB8), "cb+0xB8");
        /* 버튼 2개 라벨(로컬라이즈 문자열 — 참고용) */
        for (uint32_t bo = 0x10; bo <= 0x18; bo += 8){
            uint64_t bt = q64(panel + bo);
            if (!isHeap(bt)) continue;
            char lb[256];
            if (widgetText(bt, lb, sizeof lb) && lb[0])
                fprintf(f, "   btn+0x%02X text=\"%s\"\n", bo, lb);
        }
    }
}

/* ── 이름 캐시: 엔티티 스냅샷에서 실제 이름을 모은다(언어 비의존 판정의 기준) ── */
static void refreshNames(unsigned now)
{
    if (g_namesN && (unsigned)(now - g_namesMs) < RG_NAMESMS) return;
    g_namesMs = now;
    lc_collect(); lc_pick_self();
    LC_E *me = lc_findMe();
    if (me && me->nm[0]) snprintf(g_myName, sizeof g_myName, "%s", me->nm);
    g_namesN = 0;
    for (int i = 0; i < lc_nc && g_namesN < NAME_CAP; i++){
        LC_E *X = &lc_cur[i];
        if (!X->nm[0]) continue;
        if (X->vft == LC_VFT_ITEM) continue;              /* 아이템 이름 제외 */
        if (strlen(X->nm) < 2) continue;                  /* 1글자 이름은 오탐 위험 */
        snprintf(g_names[g_namesN++], sizeof g_names[0], "%s", X->nm);
    }
}
/* 발신자 이름 풀 — 일반 채팅 ChatData.sender / 귓속말 라인 이름에서 학습.
 *   파티 라인은 발신자를 포함하지 않으므로(실측), '선두 = 알려진 이름' 일 때만 수신으로 확정한다. */
#define SND_CAP 64
static char g_sndName[SND_CAP][40]; static int g_sndN = 0;
static void addSndName(const char *nm)
{
    if (!nm || strlen(nm) < 2) return;
    if (g_myName[0] && !strcmp(nm, g_myName)) return;
    for (int i = 0; i < g_sndN; i++) if (!strcmp(g_sndName[i], nm)) return;
    if (g_sndN >= SND_CAP){ memmove(g_sndName[0], g_sndName[1], sizeof g_sndName[0] * (SND_CAP - 1)); g_sndN = SND_CAP - 1; }
    snprintf(g_sndName[g_sndN++], sizeof g_sndName[0], "%s", nm);
}
/* 선두가 **알려진 이름 + 공백**인가(구조 대조). 맞으면 그 이름 포인터, 아니면 0. */
static const char *prefixKnownName(const char *s, int *lenOut)
{
    if (lenOut) *lenOut = 0;
    if (!s || !s[0]) return 0;
    const char *best = 0; size_t bl = 0;
    for (int i = 0; i < g_namesN; i++){
        size_t L = strlen(g_names[i]);
        if (L > bl && !strncmp(s, g_names[i], L) && s[L] == ' '){ best = g_names[i]; bl = L; }
    }
    for (int i = 0; i < g_sndN; i++){
        size_t L = strlen(g_sndName[i]);
        if (L > bl && !strncmp(s, g_sndName[i], L) && s[L] == ' '){ best = g_sndName[i]; bl = L; }
    }
    if (g_myName[0]){
        size_t L = strlen(g_myName);
        if (L > bl && !strncmp(s, g_myName, L) && s[L] == ' '){ best = g_myName; bl = L; }
    }
    if (best && lenOut) *lenOut = (int)bl;
    return best;
}
/* 문자열에서 이름을 찾는다: startIfPrefix=1 이면 선두 근처만 검사(채팅 라인 발신자용) */
static const char *nameInText(const char *s, int startIfPrefix)
{
    if (!s || !s[0]) return 0;
    const char *best = 0; size_t bestPos = (size_t)-1;
    for (int i = 0; i < g_namesN; i++){
        const char *p = strstr(s, g_names[i]);
        if (!p) continue;
        size_t pos = (size_t)(p - s);
        if (startIfPrefix && pos > 24) continue;           /* 선두 발신자 후보만 */
        if (pos < bestPos || (pos == bestPos && strlen(g_names[i]) > strlen(best ? best : ""))){
            best = g_names[i]; bestPos = pos;
        }
    }
    return best;
}
/* 선두 라틴/숫자 토큰 = 이름 후보(예: "poorboy이(가) …"). CJK 이름은 엔티티 대조에 의존. */
static int leadingLatinName(const char *s, char *out, int cap)
{
    out[0] = 0;
    if (!s) return 0;
    int i = 0;
    while (s[i] == ' ' || s[i] == '\t') i++;
    int st = i;
    while ((s[i] >= 'A' && s[i] <= 'Z') || (s[i] >= 'a' && s[i] <= 'z') ||
           (s[i] >= '0' && s[i] <= '9') || s[i] == '_') i++;
    int n = i - st;
    if (n < 2 || n >= cap) return 0;
    memcpy(out, s + st, (size_t)n); out[n] = 0;
    return 1;
}

/* 발신/수신 방향: 이름이 '나'면 송신, 아니면 수신, 이름 미검출이면 '?' */
static char dirOf(const char *sender)
{
    if (!sender || !sender[0]) return '?';
    if (g_myName[0] && !strcmp(sender, g_myName)) return 'T';   /* TX */
    return 'R';                                                  /* RX */
}

/* 표시용 정리: 게임 색상 마커(\f<char>) 제거 + 앞뒤 공백 제거 */
static void cleanText(const char *in, char *out, int cap)
{
    int o = 0;
    for (int i = 0; in && in[i] && o < cap - 1; i++){
        if (in[i] == '\\' && in[i+1] == 'f' && in[i+2]){ i += 2; continue; }
        out[o++] = in[i];
    }
    out[o] = 0;
    while (o > 0 && (out[o-1] == ' ' || out[o-1] == '\r' || out[o-1] == '\n')) out[--o] = 0;
    int st = 0; while (out[st] == ' ') st++;
    if (st) memmove(out, out + st, strlen(out + st) + 1);
}

/* ── 채팅 히스토리: 최근 HIST_TAIL 개만 읽고 **링 캐시**로 중복 제거 ──────
 *   (모듈 해석 체인: sub+0x3F8 std::map<int,HIST> → bucket → shared_ptr.rep=ChatData) */
static int      g_histN = 0;                        /* 링 캐시 항목 수 */
static uint64_t g_histHash[256];                    /* 항목 해시(중복 판정) */
static char     g_histItem[256][STR_CAP];
/* 채팅 라인 접두(마커) → 유형 (구조 신호, 언어 비의존). registry: CHAT_LINE_MARKERS
 *   실측(2026-10-20): `"brgxfc 안녕` = 마커 + **발신자 이름** + ' ' + 본문.
 *   같은 포맷이 파티/혈맹/거래/월드에도 적용된다 → 마커 뒤 첫 토큰 = 발신자.
 *   따라서 발신자 이름은 패킷이 아니라 **클라이언트 라인 문자열 자체**에 있다. */
#define MARK_CAP 8
static uint8_t g_markCh[MARK_CAP]; static char g_markName[MARK_CAP][32]; static int g_markN = 0;
static void parseMarkers(const char *s)
{
    g_markN = 0;
    const char *p = s ? s : "";
    while (*p && g_markN < MARK_CAP){
        char k[8] = "", nm[32] = "";
        if (sscanf(p, "%7[^:]:%31[^,]", k, nm) >= 1 && k[0]){
            g_markCh[g_markN] = (uint8_t)strtoul(k, 0, 16);
            snprintf(g_markName[g_markN], sizeof g_markName[0], "%s", nm[0] ? nm : "?");
            g_markN++;
        }
        p = strchr(p, ',');
        if (p) p++; else break;
    }
}
/* 토큰이 이름처럼 보이는가(문장부호/공백 없음). 언어 비의존: 바이트 종류만 본다. */
static int isNameToken(const char *t)
{
    if (!t || !t[0]) return 0;
    size_t L = strlen(t);
    if (L < 1 || L > 24) return 0;
    for (size_t i = 0; i < L; i++){
        unsigned char c = (unsigned char)t[i];
        if (c >= 0x80) continue;                     /* UTF-8 멀티바이트 이름 */
        if (strchr("?!.,:;'\"()[]{}<>/\\", c)) return 0;
    }
    return 1;
}
static const char *lineTag(const char *line, char *senderOut, int cap)
{
    if (senderOut && cap > 0) senderOut[0] = 0;
    uint8_t c = (uint8_t)line[0];
    const char *tag = 0;
    for (int i = 0; i < g_markN; i++) if (g_markCh[i] == c){ tag = g_markName[i]; break; }
    if (!tag) return "일반";
    /* 실측(2026-10-20): `#팔계야 뭘하니?` 는 **본문만**(sender 없음).
     *   같은 메시지의 ChatData = {sender:"번개공격", msg:"팔계야 뭘하니?", full:"(번개공격) …"}.
     *   ⇒ 파티/혈맹 등은 첫 토큰이 발신자가 아니다(본문의 일부).
     *   ⇒ 귓속말(0x22)만 `"이름 본문` 실측 근거가 있어 이름을 취한다. */
    if (senderOut && cap > 0 && c == 0x22){
        const char *p = line + 1; int i = 0;
        while (*p == ' ') p++;
        while (*p && *p != ' ' && i < cap - 1) senderOut[i++] = *p++;
        senderOut[i] = 0;
        if (!isNameToken(senderOut)) senderOut[0] = 0;
        else if (*p != ' ') senderOut[0] = 0;
    }
    return tag;
}

/* 내가 보낸 메시지 본문 링 — 파티/기타 라인의 방향(송신) 판정 교차 신호 */
static char     g_myMsg[16][STR_CAP]; static int g_myMsgN = 0;
static void myMsgPush(const char *s)
{
    if (!s || !s[0]) return;
    for (int i = 0; i < g_myMsgN; i++) if (!strcmp(g_myMsg[i], s)) return;
    if (g_myMsgN >= 16){ memmove(g_myMsg[0], g_myMsg[1], sizeof g_myMsg[0] * 15); g_myMsgN = 15; }
    snprintf(g_myMsg[g_myMsgN++], STR_CAP, "%s", s);
}
static int myMsgHas(const char *s)
{
    if (!s || !s[0]) return 0;
    for (int i = 0; i < g_myMsgN; i++){
        if (!strcmp(g_myMsg[i], s)) return 1;
        if (strlen(s) >= 2 && strstr(g_myMsg[i], s)) return 1;
    }
    return 0;
}

/* 내가 입력한 텍스트 이력(입력필드 +0xC0) — 파티/기타 라인의 방향(송신) 판정 */
static char     g_inpHist[16][STR_CAP]; static unsigned g_inpMs[16]; static int g_inpN = 0;
static void noteInput(const char *s, unsigned now)
{
    if (!s || strlen(s) < 2) return;
    for (int i = 0; i < g_inpN; i++) if (!strcmp(g_inpHist[i], s)){ g_inpMs[i] = now; return; }
    if (g_inpN >= 16){ memmove(g_inpHist[0], g_inpHist[1], sizeof g_inpHist[0] * 15);
                       memmove(g_inpMs, g_inpMs + 1, sizeof(unsigned) * 15); g_inpN = 15; }
    snprintf(g_inpHist[g_inpN], STR_CAP, "%s", s); g_inpMs[g_inpN] = now; g_inpN++;
}
static int inpHas(const char *s, unsigned now, unsigned win)
{
    if (!s || !s[0]) return 0;
    for (int i = 0; i < g_inpN; i++){
        if ((unsigned)(now - g_inpMs[i]) > win) continue;
        if (!strcmp(g_inpHist[i], s)) return 1;
        if (strlen(s) >= 2 && strstr(g_inpHist[i], s)) return 1;
    }
    return 0;
}

static void histPush(const char *item)
{
    uint64_t h = fnv1a(item, strlen(item));
    for (int i = 0; i < g_histN; i++) if (g_histHash[i] == h) return;   /* 중복 */
    if (g_histN >= 256){                                 /* 가득 → 가장 오래된 것 제거 */
        memmove(g_histItem[0], g_histItem[1], sizeof g_histItem[0] * 255);
        memmove(g_histHash, g_histHash + 1, sizeof(uint64_t) * 255);
        g_histN = 255;
    }
    snprintf(g_histItem[g_histN], STR_CAP, "%s", item);
    g_histHash[g_histN] = h; g_histN++;
}
/* 이미 판독한 ChatData → 표시 문자열 캐시(최근 64개).
 *   같은 항목은 문자열 4개를 다시 읽지 않고 캐시로 재사용한다(IOCTL 절감). */
#define CDCAP 64
static struct { uint64_t cd; char item[STR_CAP]; } g_cdCache[CDCAP];
static int g_cdCacheN = 0;
static const char *cdCacheGet(uint64_t cd)
{
    for (int i = 0; i < g_cdCacheN; i++) if (g_cdCache[i].cd == cd) return g_cdCache[i].item;
    return 0;
}
static void cdCachePut(uint64_t cd, const char *item)
{
    if (g_cdCacheN >= CDCAP){
        memmove(g_cdCache, g_cdCache + 1, sizeof(g_cdCache[0]) * (CDCAP - 1)); g_cdCacheN = CDCAP - 1;
    }
    g_cdCache[g_cdCacheN].cd = cd;
    snprintf(g_cdCache[g_cdCacheN].item, STR_CAP, "%s", item);
    g_cdCacheN++;
}
static void addHistItems(uint64_t node, uint64_t head, int depth)
{
    if (!isHeap(node) || node == head || depth > 64) return;
    uint8_t nb[0x30];
    if (!lc_pgRead(node, nb, sizeof nb)) return;
    uint64_t L, R, nil;
    memcpy(&L, nb + 0x00, 8); memcpy(&R, nb + 0x10, 8); memcpy(&nil, nb + 0x18, 8);
    if (!nil || L != head) addHistItems(L, head, depth + 1);

    int chan = (int)*(int *)(nb + 0x20);
    uint8_t hb[0x30];
    if (lc_pgRead(node + 0x28, hb, sizeof hb)){
        uint64_t arr = 0, mask = 0, headi = 0, cnt = 0;
        memcpy(&arr,   hb + RG_H_ARR, 8);
        memcpy(&mask,  hb + RG_H_MASK, 8);
        memcpy(&headi, hb + RG_H_HEAD, 8);
        memcpy(&cnt,   hb + RG_H_CNT, 8);
        if (isHeap(arr) && cnt > 0 && mask > 1){
            uint64_t lim = cnt > 300 ? 300 : cnt;
            uint64_t start = (lim > HIST_TAIL) ? (lim - HIST_TAIL) : 0;   /* 최근 것만 */
            for (uint64_t i = start; i < lim; i++){
                uint64_t idx = (headi + i) & (mask - 1);
                uint64_t sp = 0;
                if (!lc_pgRead(arr + idx * 8, &sp, 8)) break;
                if (!isHeap(sp) || (sp & 7)) continue;
                uint64_t cd = q64(sp + 8);
                if (!isHeap(cd) || (cd & 7)) continue;
                uint64_t v = q64(cd);
                if (!isMod(v) || (uint32_t)(v - g_base) != RG_CD_VFT) continue;
                /* 이미 읽은 ChatData 는 캐시된 표시 문자열을 그대로 사용(재판독 생략) */
                const char *cached = cdCacheGet(cd);
                if (cached){ histPush(cached); continue; }
                char f4[4][512];
                for (int k = 0; k < 4; k++)
                    if (!strAtAddr(cd + RG_CD_OFF[k], f4[k], sizeof f4[0])) f4[k][0] = 0;
                if (!f4[0][0]) continue;
                addSndName(f4[2]);                       /* 일반 채팅 sender = 실제 플레이어 이름(학습) */
                int a = (int)d32(cd + 0x08), b = (int)d32(cd + 0x0C);
                const char *dir = (g_myName[0] && f4[2][0] && !strcmp(f4[2], g_myName)) ? "송신"
                                : (f4[2][0] ? "수신" : "?");
                char cm[STR_CAP]; cleanText(f4[0], cm, sizeof cm);
                char item[STR_CAP];
                const char *tl = typeLabel(a, b);
                snprintf(item, STR_CAP, "[%s ch=%d a=%d b=%d%s lang=%s] %s : %s",
                         dir, chan, a, b, tl ? tl : "", f4[3][0] ? f4[3] : "-",
                         f4[2][0] ? f4[2] : "(?)", cm);
                cdCachePut(cd, item);
                histPush(item);
                { char d0[4]; snprintf(d0, sizeof d0, "%s", dir);
                  if (d0[0] == '송') myMsgPush(cm); }
                learnChatType(chan, a, b, f4[3][0] ? f4[3] : "-", cm);
            }
        }
    }
    if (!nil || R != head) addHistItems(R, head, depth + 1);
}

/* ── 시스템 통보(HudMessageLayout+0x1E0, NUL 종료 UTF-8) ────────────────── */
static uint64_t g_hmlCache = 0;
static uint64_t findWindowByClass(uint64_t ui, const char *want)
{
    for (int c = 0; c < g_ncont && isHeap(ui); c++){
        uint64_t node = q64(ui + g_chead[c]);
        for (int n = 0; isHeap(node) && n < 4096; n++){
            uint64_t x = q64(node + RG_CVAL);
            if (isHeap(x)){
                char sh[96];
                if (classOfC(q64(x), sh, sizeof sh) && !strcmp(sh, want)) return x;
            }
            uint64_t nx = q64(node + g_cnext[c]); if (nx == node) break; node = nx;
        }
    }
    return 0;
}
static void collectSysNotice(uint64_t ui)
{
    uint64_t w = 0;
    if (isHeap(g_hmlCache)){
        char sh[96];
        if (classOfC(q64(g_hmlCache), sh, sizeof sh) && !strcmp(sh, "HudMessageLayout")) w = g_hmlCache;
    }
    if (!w && isHeap(ui)){ w = findWindowByClass(ui, "HudMessageLayout"); g_hmlCache = w; }
    if (!isHeap(w)) return;
    uint8_t buf[1024];
    if (!lc_pgRead(w + RG_HML_TEXT, buf, sizeof buf - 1)) return;
    buf[sizeof buf - 1] = 0;
    size_t n = 0; while (n < sizeof buf - 1 && buf[n]) n++;
    if (n < 4) return;
    /* 쓰레기 배제: 제어문자(개행/탭 제외) 포함 시 무시 */
    for (size_t i = 0; i < n; i++){
        unsigned char c = buf[i];
        if (c < 0x20 && c != '\n' && c != '\t') return;
    }
    char u8[2048];
    decodeStr(buf, (int)n, u8, sizeof u8);
    if (!u8[0]) return;
    char item[STR_CAP];
    snprintf(item, sizeof item, "[시스템] %s", u8);
    histPush(item);
}

int main(int argc, char **argv)
{
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg  = lcreg_resolve("10_5/registry/LC930_REGISTRY.txt", "registry/LC930_REGISTRY.txt");
    const char *outp = lcreg_outpath("chatmon_out.txt");
    int secs = 0;
    for (int i = 1; i < argc; i++){
        if (!strcmp(argv[i], "-clear")){ g_clear = 1; continue; }
        if (!strcmp(argv[i], "-all")){ g_all = 1; continue; }
        if (!strcmp(argv[i], "-v")){ g_verbose = 1; continue; }
        if (!strcmp(argv[i], "-raw")){ g_raw = 1; continue; }
        if (!strcmp(argv[i], "-selftest")){ return selftest(); }
        if (!strcmp(argv[i], "-dump")){ g_dump = 1; continue; }
        if (!strcmp(argv[i], "-delta")){ g_delta = 1; continue; }
        if (!strcmp(argv[i], "-learn")){ g_learn = 1; continue; }
        if (!strcmp(argv[i], "-status")){ g_statusSec = (i + 1 < argc && atoi(argv[i+1]) > 0) ? atoi(argv[++i]) : 5; continue; }
        if (strstr(argv[i], ".txt") || strstr(argv[i], ".out")){
            if (strstr(argv[i], "REGISTRY")) reg = argv[i]; else outp = argv[i];
        } else if (atoi(argv[i]) > 0 && !strchr(argv[i], '.')) secs = atoi(argv[i]);
    }
    lcreg_load(reg); lc_reg_apply();

    RG_UVFT      = lcreg_u32("VFT_UISUBSYSTEM", 0x11E2710);
    RG_CVAL      = lcreg_u32("UIDLG_CONT_VAL", 0x38);
    RG_TDNAME    = lcreg_u32("RTTI_TD_NAME_OFF", 0x10);
    RG_COLTD     = lcreg_u32("RTTI_COL_TD_OFF", 0xC);
    RG_RESO      = lcreg_u32("CHAT_RESOURCE_OFF", 0x10);
    RG_POOLOFF   = lcreg_u32("CHAT_POOL_RES_OFF", 0x4E8);
    RG_ENTRY     = lcreg_u32("CHAT_POOL_ENTRY", 0x18);
    RG_STRIDE    = lcreg_u32("CHAT_POOL_STRIDE", 0xC0);
    RG_SLOTS     = lcreg_u32("CHAT_POOL_SLOTS", 64);
    RG_O_MSG     = lcreg_u32("CHAT_LINE_MSG", 0x00);
    RG_O_FULL    = lcreg_u32("CHAT_LINE_FULL", 0x20);
    RG_O_SEND    = lcreg_u32("CHAT_LINE_SENDER", 0x40);
    RG_STRLEN    = lcreg_u32("OFF_STR_LEN", 0x10);
    RG_STRCAP    = lcreg_u32("OFF_STR_CAP", 0x18);
    RG_SSOMAX    = lcreg_u32("STR_SSO_MAX", 0x10);
    RG_STRMAX    = lcreg_u32("CHAT_POOL_STR_MAX", 0x800);
    RG_LINESOFF  = lcreg_u32("CHAT_LINES_OFF", 0xF8);
    RG_LINESTRIDE= lcreg_u32("CHAT_LINE_STRIDE", 0x8);
    RG_LINEMAX   = lcreg_u32("CHAT_LINE_MAX", 64);
    RG_INPFIELD  = lcreg_u32("CHAT_INPUT_FIELD", 0xC0);
    RG_NOTICE    = lcreg_u32("CHAT_NOTICE_OFF", 0x140);
    RG_POPVIS    = lcreg_u32("POPUP_VIS_OFF", 0x78);
    RG_POPMSG    = lcreg_u32("POPUP_MSG_OFF", 0xC8);
    RG_RENDER    = lcreg_u32("WIDGET_RENDERER", 0x740);
    RG_LABEL     = lcreg_u32("LABEL_TEXT_OFF", 0x378);
    RG_LABEL2    = lcreg_u32("WIN_LABEL_TEXT2", 0x358);
    snprintf(RG_POPUPS, sizeof RG_POPUPS, "%s",
             lcreg_str("CHATMON_POPUP_CLASSES", "CommonMessagePopup,CommonBigMessagePopup,ChatConfirmPanel"));
    RG_POPWALKMS = lcreg_u32("CHATMON_POPUP_WALK_MS", 2000);
    RG_CF_PANEL  = lcreg_u32("CHATCONFIRM_PANEL_OFF", 0x150);
    RG_CF_VIS    = lcreg_u32("CHATCONFIRM_FN_OFF", 0x78);
    RG_CF_MSG    = lcreg_u32("CHATCONFIRM_MSG_OFF", 0xC8);
    RG_NAMESMS   = lcreg_u32("CHATMON_NAMES_MS", 5000);
    { const char *mk = lcreg_str("CHAT_LINE_MARKERS", "22:귓속말,23:파티,40:혈맹,24:거래,25:월드");
      parseMarkers(mk);
      if (g_verbose) printf("# markers raw=\"%s\" n=%d\n", mk ? mk : "(null)", g_markN); }
    RG_PINV_VFT  = lcreg_u32("PARTYINVITE_VFT", 0x122C720);
    { const char *ct = lcreg_str("CHATMON_ASK_TYPES", "");
      parseCtypes(ct);
      if (g_verbose) printf("# ask-types raw=\"%s\" n=%d first=0x%X:%s\n", ct ? ct : "(null)", g_ctypeN,
              g_ctypeN ? g_ctypeVft[0] : 0, g_ctypeN ? g_ctypeName[0] : "-"); }
    RG_ENC       = encId(lcreg_str("CHAT_ENC", "UTF-8"));
    { const char *tr = lcreg_str("CHAT_ENC_TRY", "UTF-8,CP949,CP936,CP950");
      char tb[128]; snprintf(tb, sizeof tb, "%s", tr ? tr : "");
      for (char *tk = strtok(tb, ","); tk && g_encN < 8; tk = strtok(0, ",")){
          uint32_t cp = encId(tk);
          if (cp) g_encTry[g_encN++] = cp;
      }
      if (!g_encN) g_encTry[g_encN++] = CP_UTF8; }
    RG_ENCFB     = encId(lcreg_str("CHAT_ENC_FALLBACK", "CP949"));
    RG_DEDUPN    = lcreg_u32("CHAT_DEDUP_N", 256);
    RG_STOPEMPTY = lcreg_u32("CHAT_POOL_STOP_EMPTY", 8);
    RG_SCANLEN   = lcreg_u32("CHAT_POOL_SCAN_LEN", 0x800);
    RG_SCANRETRYMS = lcreg_u32("CHAT_POOL_SCAN_RETRY_MS", 5000);
    RG_SCANTRIES   = lcreg_u32("CHAT_POOL_SCAN_TRIES", 3);
    RG_LATINFB     = (int)lcreg_u32("CHATMON_LATIN_FALLBACK", 0);
    parseTypeLabels(lcreg_str("CHAT_TYPE_LABELS", ""));
    RG_HISTMAP     = lcreg_u32("CHAT_HIST_MAP_OFF", 0x3F8);
    RG_CD_VFT      = lcreg_u32("CHATDATA_VFT", 0x121BA90);
    RG_CD_OFF[0]   = lcreg_u32("CHATDATA_MSG_OFF", 0x18);
    RG_CD_OFF[1]   = lcreg_u32("CHATDATA_FULL_OFF", 0x38);
    RG_CD_OFF[2]   = lcreg_u32("CHATDATA_SENDER_OFF", 0x58);
    RG_CD_OFF[3]   = lcreg_u32("CHATDATA_LANG_OFF", 0x78);
    RG_H_ARR       = lcreg_u32("CHAT_HIST_ARR_OFF", 0x08);
    RG_H_MASK      = lcreg_u32("CHAT_HIST_MASK_OFF", 0x10);
    RG_H_HEAD      = lcreg_u32("CHAT_HIST_HEAD_OFF", 0x18);
    RG_H_CNT       = lcreg_u32("CHAT_HIST_COUNT_OFF", 0x20);
    RG_HML_TEXT    = lcreg_u32("HUDMSG_TEXT_OFF", 0x1E0);
    g_poolOff    = RG_POOLOFF;
    snprintf(RG_CLASS, sizeof RG_CLASS, "%s", lcreg_str("CHAT_LAYOUT_CLASS", "HudChatLayoutPCImpl"));
    snprintf(RG_CURCHAR, sizeof RG_CURCHAR, "%s", lcreg_str("CHAT_INPUT_CURSOR", "\\"));
    { const char *v = lcreg_str("UIDLG_CONT", "0x38:0x18,0x28:0x28"); char buf[128];
      snprintf(buf, sizeof buf, "%s", v);
      char *tok = strtok(buf, ",");
      while (tok && g_ncont < 8){ char *c = strchr(tok, ':');
        if (c){ *c = 0; g_chead[g_ncont] = (uint32_t)strtoul(tok, 0, 0);
                g_cnext[g_ncont] = (uint32_t)strtoul(c + 1, 0, 0); g_ncont++; }
        tok = strtok(0, ","); } }
    if (RG_SLOTS > SLOT_CAP) RG_SLOTS = SLOT_CAP;

    if (lc_attach()) return 1;
    if (!lc_anchor()) return 2;
    lcreg_mkdir_for(outp);
    FILE *f = fopen(outp, "w"); if (!f) return 4;
    fprintf(f, "# chatmon — 채팅창 실시간 모니터  (registry=%s)\n", reg);
    fprintf(f, "# build=2026-10-20(13차) opt=io-cache+idle  poll=%u/%ums\n",
            lcreg_u32("CHATMON_POLL_MS", 150), lcreg_u32("CHATMON_POLL_IDLE_MS", 350));
    fprintf(f, "# anchor=UISubsystem class=%s res+0x%X pool+0x%X entry=0x%X stride=0x%X slots=%u\n",
            RG_CLASS, RG_RESO, RG_POOLOFF, RG_ENTRY, RG_STRIDE, RG_SLOTS);
    fprintf(f, "# slot fields: msg+0x%X full+0x%X sender+0x%X   enc=%u/fb=%u\n",
            RG_O_MSG, RG_O_FULL, RG_O_SEND, RG_ENC, RG_ENCFB);
    fflush(f);

    DWORD t0 = GetTickCount();
    long seq = 0; int first = 1;
    do {
        LARGE_INTEGER fr, q0, q1; QueryPerformanceFrequency(&fr); QueryPerformanceCounter(&q0);
        lc_pgc_reset();
        g_ioctl = 0;                       /* 사이클별 IOCTL 계측 */
        uint64_t ui = lc_subsGet(RG_UVFT);
        /* 창 인스턴스 캐시: 매 사이클 컨테이너 전수 탐색(≈120콜)을 피한다.
         *   캐시된 인스턴스의 vft(클래스명)만 재확인 → 불일치/소멸 시에만 재탐색. */
        uint64_t win = 0; int winScore = -1;
        if (isHeap(g_winCache)){
            char sh[96];
            if (classOfC(q64(g_winCache), sh, sizeof sh) && !strcmp(sh, RG_CLASS)) win = g_winCache;
        }
        if (!win && isHeap(ui)){ win = pickChatWindow(ui, &winScore); g_winCache = win; g_emptyRuns = 0; }
#define IOMARK(tag) do{ if(g_verbose){ printf("   [io] %-7s %llu\n", tag, (unsigned long long)g_ioctl); } }while(0)
        IOMARK("win");

        /* 풀 해석: 등록 오프셋 우선. 무효하면 (채팅이 보이고 예산이 남았을 때만) 자동 탐색.
         *   - 후보 검사는 첫 슬롯 1개만 본다(IOCTL 최소)
         *   - 시도 간격 CHAT_POOL_SCAN_RETRY_MS(기본 5000), 최대 CHAT_POOL_SCAN_TRIES(기본 3)회 */
        uint64_t res = isHeap(win) ? q64(win + RG_RESO) : 0;
        uint64_t pool = isHeap(res) ? q64(res + g_poolOff) : 0;
        if (!poolOk(pool) && isHeap(res) &&
            (g_poolTries < (int)RG_SCANTRIES) &&
            (g_lastScanMs == 0 || (unsigned)(GetTickCount() - g_lastScanMs) >= RG_SCANRETRYMS)){
            uint32_t found = 0;
            uint64_t p2 = poolScan(res, RG_SCANLEN, &found);
            g_poolTries++; g_lastScanMs = GetTickCount();
            if (p2){
                g_poolOff = found; pool = p2; g_poolScanned = 1;
                fprintf(f, "# pool 자동탐색 성공: res+0x%X -> 0x%llX (등록 0x%X 무효)\n",
                        found, (unsigned long long)p2, RG_POOLOFF);
                printf("  (pool 자동탐색 성공: res+0x%X — 발신자 사용 가능)\n", found); fflush(stdout);
            } else if (g_poolTries == (int)RG_SCANTRIES){
                fprintf(f, "# pool 자동탐색 %d회 실패 → UI 배열만 사용(발신자 없음)\n", g_poolTries);
                printf("  (pool 자동탐색 %d회 실패 — UI 배열만 사용)\n", g_poolTries); fflush(stdout);
            }
        }

        IOMARK("pool");
        int nslot = 0, nnew = 0;
        char evbuf[512]; int evn = 0; evbuf[0] = 0;

        if (poolOk(pool)){
            int empty_run = 0;
            for (uint32_t i = 0; i < RG_SLOTS; i++){
                uint64_t e = pool + RG_ENTRY + (uint64_t)i * RG_STRIDE;
                uint8_t blk[0x60];
                if (!lc_pgRead(e, blk, sizeof blk)) break;
                uint8_t rb[STR_CAP]; int n;
                n = strFromHdr(blk + RG_O_MSG, sizeof rb, rb, 0);
                char msg[STR_CAP]; if (n > 0) decodeStr(rb, n, msg, sizeof msg); else msg[0] = 0;
                n = strFromHdr(blk + RG_O_FULL, sizeof rb, rb, 0);
                char full[STR_CAP]; if (n > 0) decodeStr(rb, n, full, sizeof full); else full[0] = 0;
                n = strFromHdr(blk + RG_O_SEND, sizeof rb, rb, 0);
                char sender[0x100]; if (n > 0) decodeStr(rb, n, sender, sizeof sender); else sender[0] = 0;
                if (!msg[0] && !full[0] && !sender[0]){          /* 빈 슬롯 */
                    if (++empty_run >= (int)RG_STOPEMPTY) break; /* 연속 빈 슬롯 → 조기 종료(IOCTL 절약) */
                    continue;
                }
                empty_run = 0;

                Slot *S = &g_slot[nslot];
                snprintf(S->sender, sizeof S->sender, "%s", sender);
                snprintf(S->msg,    sizeof S->msg,    "%s", msg);
                snprintf(S->full,   sizeof S->full,   "%s", full);
                chanOf(full, msg, S->chan, sizeof S->chan);
                S->ok = 1;

                uint64_t h = fnv1a_n(S->sender, strlen(S->sender), 1469598103934665603ULL);
                h = fnv1a_n(S->msg, strlen(S->msg), h);
                S->hash = h;

                int isnew = 0;
                if (!evSeen(h, 0)){ isnew = !first; evSeen(h, 1); }  /* 첫 사이클=기준선(과거분 NEW 금지) */
                if (isnew){
                    nnew++;
                    fprintf(f, "[MSG] t=%ums seq=%ld slot=%u chan=%s sender=\"%s\" msg=\"%s\" full=\"%s\"\n",
                            (unsigned)(GetTickCount()-t0), ++seq, i, S->chan, S->sender, S->msg, S->full);
                    if (evn < (int)sizeof evbuf - 1)
                        evn += snprintf(evbuf + evn, sizeof evbuf - (size_t)evn, "  [NEW] #%ld %s %s : %s\n",
                                        seq, S->chan, S->sender[0] ? S->sender : "(?)", S->msg);
                }
                if (g_raw){
                    char hx[64];
                    hexOf(blk + RG_O_SEND, 16, hx, sizeof hx, 16);
                    snprintf(S->rawhex, sizeof S->rawhex, "%s", hx);
                } else S->rawhex[0] = 0;
                nslot++;
                if (nslot >= (int)RG_SLOTS) break;
            }
        }
        g_nslot = nslot;

        /* ── 주 소스: UI 배열(창 + CHAT_LINES_OFF) — 순서(오래된→최신)가 보존된다 ──
         *   배열은 트랜지언트이므로 "매 사이클 전체"를 읽고 **변화분만** 출력한다. */
        UI_LINE_CAP_UNUSED:
        int ui_n = 0, ui_input = 0;
        uint64_t lines = isHeap(win) ? q64(win + RG_LINESOFF) : 0;

        if (isHeap(lines)){
            uint32_t want = RG_LINEMAX * 8; if (want > 0x400) want = 0x400;
            uint8_t ptrbuf[0x400];
            if (lc_pgRead(lines, ptrbuf, want)){
                /* 문자열 캐시: (포인터,길이) 동일 → 재판독 생략(IOCTL 절감).
                 *   배열이 밀려도 같은 줄은 같은 문자열 객체를 가리키는 것을 실측 확인. */
                static uint64_t ucPtr[UI_LINE_CAP]; static uint32_t ucLen[UI_LINE_CAP];
                static char ucTxt[UI_LINE_CAP][STR_CAP]; static int ucN = 0;
                static unsigned ucFullMs = 0;
                int full = (unsigned)(GetTickCount() - ucFullMs) > 2000;   /* 2s마다 전체 재판독 */
                if (full) ucFullMs = (unsigned)GetTickCount();
                for (uint32_t i = 0; i * 8 + 8 <= want && ui_n < UI_LINE_CAP; i++){
                    uint64_t p; memcpy(&p, ptrbuf + i * 8, 8);
                    if (!isHeap(p)) break;                       /* NULL/무효 → 배열 끝 */
                    int idx = (int)i;
                    if (!full && idx < ucN && p == ucPtr[idx] && ucTxt[idx][0]){
                        snprintf(g_ui[ui_n], STR_CAP, "%s", ucTxt[idx]);
                        ui_n++; continue;
                    }
                    uint8_t rb[STR_CAP]; int n = strFromHdr2(p, rb, sizeof rb);
                    if (n <= 0) continue;
                    decodeStr(rb, n, g_ui[ui_n], STR_CAP);
                    if (g_ui[ui_n][0]){
                        if (idx < UI_LINE_CAP){
                            ucPtr[idx] = p; ucLen[idx] = (uint32_t)n;
                            snprintf(ucTxt[idx], STR_CAP, "%s", g_ui[ui_n]);
                            if (idx + 1 > ucN) ucN = idx + 1;
                        }
                        ui_n++;
                    }
                }
            }
            if (ui_n > 0 && RG_CURCHAR[0]){
                size_t L = strlen(g_ui[ui_n - 1]), C = strlen(RG_CURCHAR);
                if (L >= C && !strcmp(g_ui[ui_n - 1] + L - C, RG_CURCHAR)) ui_input = 1;
            }
        }
        /* 0줄이 오래 지속될 때만 창 재선택(재선택은 ~170콜) — 기본 20사이클(≈4s) */
        if (ui_n == 0 && isHeap(g_winCache) && ++g_emptyRuns >= 20){ g_winCache = 0; g_emptyRuns = 0; }
        else if (ui_n > 0) g_emptyRuns = 0;
        IOMARK("uiline");
        char inp[STR_CAP] = "";
        if (isHeap(win)){
            uint8_t rb[STR_CAP]; int n = strFromHdr2(win + RG_INPFIELD, rb, sizeof rb);
            if (n > 0) decodeStr(rb, n, inp, sizeof inp);
        }
        noteInput(inp, (unsigned)(GetTickCount() - t0));

        /* ── 통합 항목 구성 ────────────────────────────────────────────────
         *  [CHAT] 채팅 라인(UI 배열) + [공지] 캠페인/공지 위젯(+0x140)
         *  + [통보] 팝업 창(현재 표시중인 것만).  ← 예전에 못 잡던 부분
         *  ※ +0xF8 배열은 트랜지언트라 비어 있을 때가 많다. 그래서 공지/통보를 별도 소스로 합친다. */
        int cn = 0;
        /* 이름 대조는 **필요할 때만**(특수 라인이 있을 때) + 내 이름 갱신은 10s 주기.
         *   lc_collect 는 액터 그래프를 훑어 호출이 크므로 매 2s 갱신을 피한다. */
        { int saw = 0;
          for (int i = 0; i < ui_n; i++){
              char c = g_ui[i][0];
              if (c == '"' || c == '#' || c == '@' || c == '$' || c == '%'){ saw = 1; break; }
          }
          static unsigned lastNamesMs = 0; unsigned nowMs = (unsigned)GetTickCount();
          if ((unsigned)(nowMs - lastNamesMs) >= 10000){ refreshNames(nowMs); lastNamesMs = nowMs; }
          (void)saw;
        }
        g_histN = 0;
        { /* ① 영속 히스토리(ChatData 체인): 최근 HIST_TAIL 개만 읽고 링 캐시로 중복 제거 */
          uint64_t csub = lc_subsGet(lcreg_u32("VFT_CHAT", 0x121BE00));
          if (isHeap(csub)){
              uint64_t hhead = q64(csub + RG_HISTMAP);
              if (isHeap(hhead)) addHistItems(q64(hhead + 0x08), hhead, 0);
              collectSysNotice(ui);
          }
        }
        IOMARK("hist");
        {                                             /* ② 창 UI 배열: 귓속말/파티 등 접두 유형 보강 */
            for (int i = 0; i < ui_n; i++){
                char c0 = g_ui[i][0];
                char snd[80]; const char *tg = lineTag(g_ui[i], snd, sizeof snd);
                int special = strcmp(tg, "일반") != 0;      /* 마커가 있으면 특수 라인 */
                if (!special && g_histN > 0) continue;      /* 일반 대화는 히스토리 사용(중복 방지) */
                char cm[STR_CAP]; cleanText(g_ui[i], cm, sizeof cm);
                /* 마커 제거 → 남은 전체 문자열(이름 포함) = 방향 판정용 원문 */
                const char *after = special ? cm + 1 : cm;
                while (*after == ' ') after++;
                unsigned now = (unsigned)(GetTickCount() - t0);
                /* 내가 보낸 것: 원문 전체가 입력 이력/내 메시지와 일치하면 송신(구조 신호) */
                int mine = myMsgHas(after) || inpHas(after, now, 10000);
                const char *body = after;
                if (mine){
                    if (g_myName[0]) snprintf(snd, sizeof snd, "%s", g_myName);
                } else {
                    /* 파티/혈맹 등 — 실측 포맷(2026-10-20):
                     *   받은 라인 = `#발신자 본문`  (예: `#poorboy 팔계씨 뭘하나`)
                     *   보낸 라인 = `#본문`         (예: `#팔계야 뭘하니?`, `#모두 모여라`)
                     *   ⇒ 선두가 **알려진 이름**이면 수신, 아니면 내가 보낸 것(송신). */
                    if (special && c0 != '"'){
                        const char *nm = prefixKnownName(after, 0);
                        if (nm) snprintf(snd, sizeof snd, "%s", nm);
                        else if (g_myName[0]) snprintf(snd, sizeof snd, "%s", g_myName);
                    }
                    if (snd[0]){
                        size_t L = strlen(snd);
                        if (!strncmp(body, snd, L)){ body += L; while (*body == ' ') body++; }
                    }
                    if (!snd[0]){ const char *n = nameInText(g_ui[i], 1); if (n) snprintf(snd, sizeof snd, "%s", n); }
                }
                if (c0 == '"' && snd[0]) addSndName(snd);      /* 귓속말 이름 = 실제 플레이어 이름 */
                const char *dir = mine ? "송신"
                                : (snd[0] ? ((g_myName[0] && !strcmp(snd, g_myName)) ? "송신" : "수신") : "?");
                char item[STR_CAP];
                snprintf(item, sizeof item, "[%s %s] %s : %s", tg, dir,
                         snd[0] ? snd : "(?)", body);
                histPush(item);
            }
        }
        if (g_histN > 0){                              /* 링 캐시(히스토리 + UI 보강) 반영 */
            for (int k = 0; k < g_histN && cn < UI_LINE_CAP; k++)
                snprintf(g_cur[cn++], STR_CAP, "%s", g_histItem[k]);
        }
        {
            uint64_t nw = isHeap(win) ? q64(win + RG_NOTICE) : 0;
            char nt[STR_CAP];
            if (widgetText(nw, nt, sizeof nt) && nt[0] && cn < UI_LINE_CAP)
                snprintf(g_cur[cn++], STR_CAP, "[공지] %s", nt);
        }
        if (isHeap(ui)){ walkPopups(ui, GetTickCount()); collectPopups(&cn); }
        collectConfirm(f, win, (unsigned)(GetTickCount() - t0), &cn);
        IOMARK("confirm");
        g_curN = cn;

        /* ── 변화분(delta) 계산: prev 리스트와 정렬(시프트)을 맞춘다 ──
         *   배열은 "오래된 줄이 앞에서 빠지고 새 줄이 뒤에 붙는" 형태이므로
         *   prev 의 접미부와 cur 의 접두부가 일치하는 시프트 s 를 찾는다. */
        int shift = -1, lim = 0;
        for (int s = 0; s <= g_uinPrev; s++){
            int ok = 1, l = g_uinPrev - s;
            if (l > cn) l = cn;
            for (int i = 0; i < l; i++) if (strcmp(g_cur[i], g_uiPrev[s + i])){ ok = 0; break; }
            if (ok){ shift = s; lim = l; break; }
        }
        if (shift < 0){ shift = g_uinPrev; lim = 0; }            /* 완전 교체 */
        int nadd = cn - lim;                                     /* 새로 붙은 줄 수 */
        if (nadd < 0) nadd = 0;

        unsigned el = (unsigned)(GetTickCount() - t0);
        int changed = first || nnew || shift > 0 || nadd > 0;
        /* 초당 드라이버 호출(최적화 지표) */
        static unsigned long long ioSec = 0; static unsigned lastSecMs = 0, ioRate = 0;
        ioSec += g_ioctl;
        if (el - lastSecMs >= 1000){ ioRate = (unsigned)(ioSec * 1000ull / (unsigned long long)(el - lastSecMs)); ioSec = 0; lastSecMs = el; }

        /* ── 콘솔: 상태줄은 "변화가 있을 때만"(또는 -v / -status 주기) ── */
        if (g_clear) fputs("\x1b[2J\x1b[1;1H", stdout);
        if (!g_delta){
            /* 기본: 매 사이클 '최신 상황' 전체를 콘솔에 출력(실시간 현황) */
            if (g_clear) printf("\x1b[H");
            printf("=== chatmon  t=%ums  항목=%d(히스토리 %d)%s  변화=%d  ioctl=%llu io/s=%u ===\n",
                   el, cn, g_histN, ui_input ? "(입력중)" : "", nadd + shift, g_ioctl, ioRate);
            for (int i = 0; i < cn; i++) printf("  [%2d] %s\n", i, g_cur[i]);
        } else {
            if (changed || g_verbose || (g_statusSec && el >= g_nextStatusMs)){
                printf("=== chatmon  t=%ums  항목=%d(채팅 %d)%s  새줄=%d  빠진줄=%d  ioctl=%llu io/s=%u%s ===\n",
                       el, cn, ui_n, ui_input ? "(입력중)" : "", nadd, shift, g_ioctl, ioRate,
                       changed ? "" : "  (변화 없음)");
                if (!changed) g_nextStatusMs = el + (unsigned)g_statusSec * 1000u;
            }
            if (first){
                for (int i = 0; i < cn; i++) printf("  [%2d] %s\n", i, g_cur[i]);
            } else if (changed){
                for (int i = 0; i < shift; i++) printf("  [-] %s\n", g_uiPrev[i]);
                for (int i = lim; i < cn; i++) printf("  [+] %s\n", g_cur[i]);
            }
        }
        if (evn) fputs(evbuf, stdout);
        if (g_all){
            printf("  [전체] %d항목\n", cn);
            for (int i = 0; i < cn; i++) printf("    [%2d] %s\n", i, g_cur[i]);
            for (int i = 0; i < g_nslot; i++)
                printf("  (pool %2d) %-6s %-14s : %s\n", i, g_slot[i].chan,
                       g_slot[i].sender[0] ? g_slot[i].sender : "(?)", g_slot[i].msg);
        }
        if (g_verbose){
            printf("  (UI n=%d input=\"%s\" pool=%s slots=%d)\n", ui_n, inp,
                   poolOk(pool) ? "ok" : "invalid", nslot);
            for (int i = 0; i < g_nslot; i++)
                printf("   slot %2d h=%016llX msg(%zu) full(%zu) send=\"%s\"%s\n",
                       i, (unsigned long long)g_slot[i].hash, strlen(g_slot[i].msg),
                       strlen(g_slot[i].full), g_slot[i].sender, g_slot[i].rawhex);
        }
        fflush(stdout);

        /* ── 파일 ── */
        if (changed){
            fprintf(f, "\n## t=%ums 항목=%d(채팅 %d) 새줄=%d 빠진줄=%d input=%d ioctl=%llu\n",
                    el, cn, ui_n, nadd, shift, ui_input, g_ioctl);
            if (first){
                for (int i = 0; i < cn; i++) fprintf(f, "  [%2d] %s\n", i, g_cur[i]);
            } else {
                for (int i = 0; i < shift; i++) fprintf(f, "  [-] %s\n", g_uiPrev[i]);
                for (int i = lim; i < cn; i++) fprintf(f, "  [+] %s\n", g_cur[i]);
            }
        }
        if (g_verbose){
            fprintf(f, "  (UI n=%d input=\"%s\" pool=%s slots=%d win=0x%llX res=0x%llX)\n",
                    ui_n, inp, poolOk(pool) ? "ok" : "invalid", nslot,
                    (unsigned long long)win, (unsigned long long)res);
            for (int i = 0; i < g_nslot; i++)
                fprintf(f, "   slot %2d %-6s %-14s : %s\n", i, g_slot[i].chan,
                        g_slot[i].sender[0] ? g_slot[i].sender : "(?)", g_slot[i].msg);
        }
        fflush(f);
        /* prev ← cur */
        memcpy(g_uiPrev, g_cur, sizeof g_cur); g_uinPrev = cn;

        QueryPerformanceCounter(&q1);
        lcapi_sample(f);
        first = 0;
        if (secs){
            /* 실시간: 변화가 있던 사이클은 짧게, 유휴는 길게 (호출 절감) */
            uint32_t pAct  = lcreg_u32("CHATMON_POLL_MS", 200);
            uint32_t pIdle = lcreg_u32("CHATMON_POLL_IDLE_MS", 350);
            Sleep(changed ? pAct : pIdle);
        }
        (void)fr; (void)q0; (void)q1;
    } while (!lcapi_done() && secs && (int)(GetTickCount() - t0) < secs * 1000);

    fclose(f); SignedClose();
    printf("\ndone -> %s\n", outp);
    return 0;
}
