/* lasthit_930.c - 지상 아이템 획득 귀속 판정 (guid-adjacency + last-hitter)
 * ===========================================================================
 *  이론 (2026-10-06, 라이브 검증):
 *    ① 지상 아이템의 GUID = 소스 몬스터 GUID + delta (실측 delta ∈ 1..6).
 *       → 사망전이/시체 타이밍에 의존하지 않고, 아이템이 나타나는 순간
 *         "guid 가 아이템보다 작은, 최근에 본 액터"로 소스를 특정한다.
 *    ② 소스의 last-attacker (AttackAction vft 0x11C12F8: owner@+0x80) 가
 *       서버 규칙상 드랍 소유자다.
 *
 *  판정 라벨:
 *    MINE    소스 last-attacker == 나
 *    OTHER   소스 last-attacker != 0, != 나
 *    UNKNOWN 소스 미특정 또는 공격자 미관측(화면 밖 등)
 *
 *  ground-truth(교차검증):
 *    아무 키 -> MARK (가장 가까운 아이템에 "시도" 표시)
 *    아이템 소멸 -> GONE (픽업 성공/만료) + 그때 label
 *
 *  상수(단일출처): registry/LC930_REGISTRY.txt
 *    [SEC-14] LH_DELTA_MAX / LH_SEEN_WIN_MS / LH_OWN_WIN_MS / LH_CELL_WIN
 *    [SEC-13] POLL_ITEMLAST_INTERVAL_MS / _JITTER_MS
 *  읽기: signeddrv.sys MmCopy ONLY. 고정앵커+vft(인덱스 금지). 힙 전역스캔 금지.
 *
 *  usage: lasthit_930.exe [secs]   (프로젝트 루트 -> <exe>\out\lasthit_out.txt)
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <conio.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

#define MAXM 1024
#define MAXA 1024
#define MAXI 512

typedef struct { uint64_t guid; int cx, cy; DWORD lastMs; } MON;
typedef struct { uint64_t victim, owner; DWORD t; } ATK;
typedef struct { uint64_t guid; int cx, cy; const char*label; uint64_t src, owner; DWORD first; int gone; } OI;

static MON mons[MAXM]; static int nmons = 0;
static ATK atks[MAXA]; static int natks = 0;
static OI  items[MAXI]; static int nitems = 0;
static uint64_t deadG[512]; static int ndead = 0;

/* registry-loaded tuning (SEC-14) */
static int LH_DELTA_MAX, LH_SEEN_WIN, LH_OWN_WIN, LH_CELL_WIN;

static MON* monGet(uint64_t g, int create){
    for(int i=0;i<nmons;i++) if(mons[i].guid==g) return &mons[i];
    if(!create || nmons>=MAXM) return 0;
    MON*m=&mons[nmons++]; memset(m,0,sizeof *m); m->guid=g; return m;
}
static void atkSet(uint64_t v, uint64_t o, DWORD t){
    for(int i=0;i<natks;i++) if(atks[i].victim==v){ atks[i].owner=o; atks[i].t=t; return; }
    if(natks<MAXA){ atks[natks].victim=v; atks[natks].owner=o; atks[natks].t=t; natks++; }
}
static uint64_t atkGet(uint64_t v, DWORD now){
    for(int i=0;i<natks;i++) if(atks[i].victim==v && (int)(now-atks[i].t)<=LH_OWN_WIN) return atks[i].owner;
    return 0;
}
/* 소스 특정: guid 가 item 보다 작고 delta<=LH_DELTA_MAX, 최근목격, 셀근접.
 * 최소 delta(가장 가까운) 우선, 동률이면 셀거리. */
static int findSrc(uint64_t gi, int cx, int cy, DWORD now, uint64_t*outG){
    uint64_t best=0, bd=0; int bdist=1<<30;
    for(int i=0;i<nmons;i++){ MON*m=&mons[i];
        if(gi<=m->guid) continue;
        uint64_t d=gi-m->guid; if(d>(uint64_t)LH_DELTA_MAX) continue;
        if((int)(now-m->lastMs)>LH_SEEN_WIN) continue;
        int cdist=abs(m->cx-cx)+abs(m->cy-cy);
        if(cdist>LH_CELL_WIN*2) continue;
        if(!best || d<bd || (d==bd && cdist<bdist)){ best=m->guid; bd=d; bdist=cdist; }
    }
    if(best){ *outG=best; return (int)bd; }
    return 0;
}

int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char* reg = lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    lcreg_load(reg); lc_reg_apply();
    LH_DELTA_MAX = (int)lcreg_u32("LH_DELTA_MAX", 16);
    LH_SEEN_WIN  = (int)lcreg_u32("LH_SEEN_WIN_MS", 8000);
    LH_OWN_WIN   = (int)lcreg_u32("LH_OWN_WIN_MS", 8000);
    LH_CELL_WIN  = (int)lcreg_u32("LH_CELL_WIN", 6);
    int secs=(argc>1)?atoi(argv[1]):0;
    if(lc_attach())return 1; if(!lc_anchor())return 2;
    const char*outp=lcreg_outpath("lasthit_out.txt"); lcreg_mkdir_for(outp);
    FILE*f=fopen(outp,"w"); if(!f)return 4;

    lcreg_poll poll = lcreg_poll_load("ITEMLAST");
    DWORD t0=GetTickCount(); int markn=0;
    LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr);
    DWORD lastRep=t0; unsigned long long rRep=g_ioctl; double msAcc=0;
    fprintf(f,"# lasthit v1 (guid-adjacency + last-hitter) delta<=%d seen<=%dms own<=%dms cell<=%d poll=%u+%ums reg=%s\n",
            LH_DELTA_MAX,LH_SEEN_WIN,LH_OWN_WIN,LH_CELL_WIN,poll.interval_ms,poll.jitter_ms,reg);
    fprintf(f,"# any key => MARK (nearest item recorded)\n");

    int nItem=0,nMine=0,nOther=0,nUnk=0; int dhist[64]; memset(dhist,0,sizeof dhist);
    for(;;){
        QueryPerformanceCounter(&q0);
        lc_collect(); lc_pick_self();
        DWORD now=GetTickCount();

        if(_kbhit()){ _getch();
            int bi=-1; float bd=1e18f;
            for(int i=0;i<lc_nc;i++) if(lc_cur[i].vft==LC_VFT_ITEM && lc_cur[i].distIso<bd){ bd=lc_cur[i].distIso; bi=i; }
            markn++;
            if(bi>=0) fprintf(f,"t=%-7u MARK #%d near guid=%016llX \"%s\" cell=(%d,%d) dist=%.1f\n",
                (unsigned)(now-t0),markn,(unsigned long long)lc_cur[bi].guid,lc_cur[bi].nm,
                lc_cur[bi].cellx,lc_cur[bi].celly,lc_cur[bi].distIso);
            else fprintf(f,"t=%-7u MARK #%d near=none\n",(unsigned)(now-t0),markn);
            fflush(f);
        }

        /* 1) AttackAction 수집 -> victim->last owner */
        for(int i=0;i<lc_nc;i++){ LC_E*X=&lc_cur[i];
            if(X->hasAtk && X->atkTgt && X->atkOwner) atkSet(X->atkTgt, X->atkOwner, now);
        }
        /* 2) 액터 위치/생존 최신화(소스 후보) */
        for(int i=0;i<lc_nc;i++){ LC_E*X=&lc_cur[i];
            if(X->vft==LC_VFT_MONSTER || X->vft==LC_VFT_SUMMON || X->vft==LC_VFT_NPC || X->vft==LC_VFT_PLAYER){
                MON*m=monGet(X->guid,1); if(m){ m->cx=X->cellx; m->cy=X->celly; m->lastMs=now; }
            }
        }
        /* 3) 사망 전이(교차검증) */
        for(int i=0;i<lc_nc;i++){ LC_E*X=&lc_cur[i]; if(!X->dead) continue;
            int seen=0; for(int k=0;k<ndead;k++) if(deadG[k]==X->guid){seen=1;break;}
            if(!seen){ if(ndead<512) deadG[ndead++]=X->guid;
                uint64_t ow=atkGet(X->guid,now);
                fprintf(f,"t=%-7u DEATH guid=%016llX owner=%016llX %s cell=(%d,%d)\n",
                    (unsigned)(now-t0),(unsigned long long)X->guid,(unsigned long long)ow,
                    ow==lc_meGuid&&ow?"ME":(ow?"OTHER":"?"),X->cellx,X->celly); }
        }
        /* 4) 신규 아이템 -> 소스특정 + 귀속 */
        for(int i=0;i<lc_nc;i++){ LC_E*X=&lc_cur[i];
            if(X->vft!=LC_VFT_ITEM || !X->guid) continue;
            int seen=0; for(int k=0;k<nitems;k++) if(items[k].guid==X->guid){seen=1;break;}
            if(seen || nitems>=MAXI) continue;
            uint64_t sg=0; int d=findSrc(X->guid,X->cellx,X->celly,now,&sg);
            uint64_t ow = d ? atkGet(sg,now) : 0;
            const char*lab = !d ? "UNKNOWN" : (ow==lc_meGuid&&ow ? "MINE" : (ow ? "OTHER" : "UNKNOWN"));
            if(!d) nUnk++; else if(ow==lc_meGuid&&ow) nMine++; else if(ow) nOther++; else nUnk++;
            if(d>=0 && d<64) dhist[d]++;
            OI*o=&items[nitems++]; o->guid=X->guid; o->cx=X->cellx; o->cy=X->celly;
            o->label=lab; o->src=sg; o->owner=ow; o->first=now;
            fprintf(f,"t=%-7u ITEM guid=%016llX \"%s\" cell=(%d,%d) q=%u -> SRC=%016llX d=%d owner=%016llX %s\n",
                (unsigned)(now-t0),(unsigned long long)X->guid,X->nm,X->cellx,X->celly,X->itemQty,
                (unsigned long long)sg,d,(unsigned long long)ow,lab);
            nItem++; fflush(f);
        }
        /* 5) GONE(픽업/만료) */
        for(int i=0;i<nitems;i++){ if(items[i].gone) continue;
            uint64_t g=items[i].guid; int seen=0;
            for(int k=0;k<lc_nc;k++) if(lc_cur[k].vft==LC_VFT_ITEM && lc_cur[k].guid==g){seen=1;break;}
            if(!seen){ fprintf(f,"t=%-7u GONE guid=%016llX label=%s age=%ums\n",
                    (unsigned)(now-t0),(unsigned long long)g,items[i].label,(unsigned)(now-items[i].first));
                items[i].gone=1; fflush(f); }
        }
        /* 5b) 살아있는 동안 last-attacker 변동 반영: 킬 블로우(마지막 타격)는 아이템
         *     생성 직후에 기록될 수 있어, 생성 시점 라벨은 stale 할 수 있다.
         *     서버 규칙=마지막 타격자 → 소스 ATK가 갱신되면 라벨을 재확정한다. */
        for(int i=0;i<nitems;i++){ if(items[i].gone || !items[i].label || !items[i].src) continue;
            uint64_t ow=atkGet(items[i].src, now); if(!ow) continue;
            const char*nl = (ow==lc_meGuid)?"MINE":"OTHER";
            if(ow!=items[i].owner || nl!=items[i].label){
                fprintf(f,"t=%-7u RELABEL guid=%016llX %s->%s owner=%016llX\n",
                    (unsigned)(now-t0),(unsigned long long)items[i].guid,items[i].label,nl,(unsigned long long)ow);
                items[i].owner=ow; items[i].label=nl; fflush(f);
            }
        }
        QueryPerformanceCounter(&q1); msAcc+=(double)(q1.QuadPart-q0.QuadPart)*1000.0/(double)fr.QuadPart;
        if(now-lastRep>=1000){ fprintf(f,"# reads=%llu time=%.3fms/1s\n",g_ioctl-rRep,msAcc); rRep=g_ioctl; lastRep=now; msAcc=0; fflush(f); }
        lcapi_sample(f);
        if(lcapi_done() || (secs && (int)(now-t0)>=secs*1000)) break;
        lcreg_poll_sleep_ms(&poll);
    }
    nMine=nOther=nUnk=0;
    for(int i=0;i<nitems;i++){ if(!strcmp(items[i].label,"MINE"))nMine++; else if(!strcmp(items[i].label,"OTHER"))nOther++; else nUnk++; }
    fprintf(f,"\n# items=%d MINE=%d OTHER=%d UNKNOWN=%d marks=%d\n",nItem,nMine,nOther,nUnk,markn);
    fprintf(f,"# delta histogram:"); for(int d=0;d<64;d++) if(dhist[d]) fprintf(f," d%d=%d",d,dhist[d]);
    fprintf(f,"\n");
    fclose(f); SignedClose();
    printf("done -> %s  items=%d mine=%d other=%d unk=%d\n",outp,nItem,nMine,nOther,nUnk);
    return 0;
}