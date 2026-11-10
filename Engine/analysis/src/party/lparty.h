/* lparty.h — 파티 읽기 공용 엔진 (header-only, 10_9)
 *  party / realtime_party 어댑터가 공유. 상수는 registry(SEC-17), 읽기는 MmCopy 단일.
 *  앵커 PartySubsystem(vft) → 고정체인 → Party → vector<shared_ptr<PartyPlayer>>.
 *  액터 조인(GUID→엔티티)으로 레벨/사망/공격대상 취득(로드된 멤버만).
 */
#ifndef LPARTY_H
#define LPARTY_H
#include <string.h>
#include "lcreg.h"
#include "lcore.h"

/* ── registry 상수 (런타임 로드) ─────────────────────────────────────── */
static uint32_t P_VFT_SUBS, P_VFT_RC, P_VFT_RCP;
static uint32_t P_REF, P_HOP1, P_HOP2, P_HOPCTRL;
static uint32_t P_LNAME, P_LLVL, P_VBEG, P_VEND, P_VCAP, P_MCNT;
static uint32_t M_SELF, M_NAME, M_NLEN, M_NCAP, M_GUID;
static uint32_t M_NAME2, M_N2LEN, M_N2CAP, M_LVL, M_CLS, M_F5C, M_HP, M_MP, M_X, M_Y, M_LVL2;
static uint32_t P_SSO, P_MAXMEM, P_BFSMAX, P_RESCAN, P_ENTLVL;
static uint32_t M_MAPID, M_F54, M_F60;

static void load_cfg(void){
    P_VFT_SUBS=lcreg_u32("PARTY_VFT_SUBS",0x12293B8u);
    P_VFT_RC  =lcreg_u32("PARTY_VFT_RC",0x1229350u);
    P_VFT_RCP =lcreg_u32("PARTY_VFT_RC_PLAYER",0x1229328u);
    P_REF     =lcreg_u32("PARTY_REF_OFF",0x4A0);
    P_HOP1    =lcreg_u32("PARTY_HOP1_OFF",0x00);
    P_HOP2    =lcreg_u32("PARTY_HOP2_OFF",0x28);
    P_HOPCTRL =lcreg_u32("PARTY_HOP_CTRL",0x10);
    P_LNAME   =lcreg_u32("PARTY_LEADER_NAME",0x08);
    P_LLVL    =lcreg_u32("PARTY_LEADER_LVL",0x28);
    P_VBEG    =lcreg_u32("PARTY_VEC_BEG",0x30);
    P_VEND    =lcreg_u32("PARTY_VEC_END",0x38);
    P_VCAP    =lcreg_u32("PARTY_VEC_CAP",0x40);
    P_MCNT    =lcreg_u32("PARTY_MEMBER_COUNT",0x48);
    M_SELF    =lcreg_u32("PM_SELF",0x00);
    M_NAME    =lcreg_u32("PM_NAME",0x08);
    M_NLEN    =lcreg_u32("PM_NAME_LEN",0x18);
    M_NCAP    =lcreg_u32("PM_NAME_CAP",0x20);
    M_GUID    =lcreg_u32("PM_GUID",0x28);
    M_NAME2   =lcreg_u32("PM_NAME2",0x30);
    M_N2LEN   =lcreg_u32("PM_NAME2_LEN",0x40);
    M_N2CAP   =lcreg_u32("PM_NAME2_CAP",0x48);
    M_LVL     =lcreg_u32("PM_LEVEL",0x50);
    M_CLS     =lcreg_u32("PM_CLASS",0x58);
    M_F5C     =lcreg_u32("PM_F5C",0x5C);
    M_HP      =lcreg_u32("PM_HP",0x64);
    M_MP      =lcreg_u32("PM_MP",0x68);
    M_X       =lcreg_u32("PM_X",0x70);
    M_Y       =lcreg_u32("PM_Y",0x74);
    M_LVL2    =lcreg_u32("PM_LEVEL2",0x90);
    P_SSO     =lcreg_u32("PARTY_STR_SSO",0x10);
    P_MAXMEM  =lcreg_u32("PARTY_MAX_MEMBERS",8);
    P_BFSMAX  =lcreg_u32("PARTY_BFS_MAXNODE",250000);
    P_RESCAN  =lcreg_u32("PARTY_RESCAN_MS",5000);
    P_ENTLVL  =lcreg_u32("ENT_LEVEL_OFF",0x120);   /* 액터 조인 레벨(검증 self=13) */
    M_MAPID   =lcreg_u32("PM_MAPID",0x6C);         /* 멤버 맵ID(검증 self=4=아덴) */
    M_F54     =lcreg_u32("PM_F54",0x54);           /* 관찰필드(리더만 != 0xFFFFFFFF) */
    M_F60     =lcreg_u32("PM_F60",0x60);           /* 관찰필드(미규명) */
}

/* std::string (MSVC x64): 버퍼@off, _Mysize@lenOff, _Myres@capOff. len<SSO → 인라인. */
static void read_sso(uint64_t base, uint32_t off, uint32_t lenOff, uint32_t capOff, char *out, int cap){
    out[0]=0;
    uint64_t len=q64(base+lenOff);
    if(len==0 || len>(uint64_t)(cap-1) || len>200) return;
    uint64_t src = (len < (uint64_t)P_SSO) ? (base+off) : q64(base+off);
    if(!rm(src,out,(uint32_t)len)){ out[0]=0; return; }
    out[len]=0; (void)capOff;
}

/* 고정체인: PartySubsystem→(REF)→(HOP1)→(HOP2)=Party. 서명검증. 0=실패. */
static uint64_t resolve_fixed(uint64_t psub){    if(!isHeap(psub)) return 0;
    uint64_t a=q64(psub+P_REF);      if(!isHeap(a)) return 0;
    uint64_t b=q64(a+P_HOP1);        if(!isHeap(b)) return 0;
    uint64_t p=q64(b+P_HOP2);        if(!isHeap(p)) return 0;
    uint64_t ctrl=q64(p-P_HOPCTRL);
    if(!isMod(ctrl) || (uint32_t)(ctrl-g_base)!=P_VFT_RC) return 0;
    return p;
}

/* 서명 BFS 폴백: psub 그래프에서 _Ref_count_obj2<Party>(vft P_VFT_RC) 탐색. */
#define PBFS_VISB 19
static uint64_t pvis[1u<<PBFS_VISB];
static uint64_t pqn[1<<18];
static int pmark(uint64_t v){ uint64_t h=(v>>3)*0x9E3779B97F4A7C15ull; h>>=(64-PBFS_VISB);
    for(uint64_t i=0;i<(1u<<PBFS_VISB);i++){ uint64_t idx=(h+i)&((1u<<PBFS_VISB)-1);
        if(pvis[idx]==0){ pvis[idx]=v|1; return 1; } if((pvis[idx]&~1ull)==v) return 0; } return 0; }
static uint64_t resolve_bfs(uint64_t psub){
    if(!isHeap(psub)) return 0;
    memset(pvis,0,sizeof pvis);
    int head=0,tail=0; pqn[tail++]=psub; pmark(psub);
    static uint8_t buf[0x100];
    while(head<tail){
        if((uint32_t)(head) > P_BFSMAX) break;
        uint64_t o=pqn[head++]; if(!isHeap(o)) continue;
        if(!rm(o,buf,0x80)) continue;
        uint64_t v0=*(uint64_t*)buf;
        if(isMod(v0) && (uint32_t)(v0-g_base)==P_VFT_RC) return o+P_HOPCTRL;
        for(int j=0;j<0x80;j+=8){ uint64_t c=*(uint64_t*)(buf+j);
            if(isHeap(c) && tail<(1<<18) && pmark(c)) pqn[tail++]=c; }
    }
    return 0;
}

typedef struct { char name[128]; char name2[128]; uint64_t guid; int32_t x,y; int mapId;
                 uint32_t lvl,cls,f5c,hp,mp,lvl2; int repok;
                 int lvlJoin; int dead; int hasAtk; uint64_t atkTgt; char tgtName[80];
                 int isLeader; uint32_t f54, f60; } PMem;

/* 리더 판정: 파티 리더 이름(Party+PARTY_LEADER_NAME)과 멤버 이름 비교.
 *  - 리더 이름은 클라이언트가 직접 보유한 '검증된' 변수다(SEC-17).
 *  - Lineage 캐릭터 이름은 전역 유일 → 이름 동일 = 동일 멤버.
 *  - 리더 이름을 못 읽었을 때를 대비해 관찰필드 f54(리더만 0xFFFFFFFF 아님)를 함께 노출한다. */
static int lp_isLeader(const PMem*m, const char*leader){
    if(leader && leader[0] && m->name[0] && !strcmp(m->name,leader)) return 1;
    return 0;
}

/* std::string(SSO 또는 힙) 읽기 — leader 이름 등에 사용 */
static void lp_read_str_cstr(const uint8_t*hb, uint32_t off, uint32_t lenOff, char*out, int cap){
    out[0]=0;
    uint64_t len=*(const uint64_t*)(hb+lenOff);
    if(len==0 || len>(uint64_t)(cap-1)) return;
    if(len<P_SSO){ memcpy(out,hb+off,(size_t)len); out[len]=0; }
    else { uint64_t src=*(const uint64_t*)(hb+off); if(rm(src,out,(uint32_t)len)) out[len]=0; else out[0]=0; }
}

/* 1 = live PartyPlayer, 0 = this slot is not a member, -1 = this slot could not be read.
 * A stored _Ptr is not enough. _Rep's vft has to be PARTY_VFT_RC_PLAYER on this read.
 * A failed read is -1 so the caller keeps the sample unknown instead of "no party". */
static int lp_slot_live(uint64_t slot, uint64_t *ptr_out){
    uint64_t ptr=0, rep=0, vft=0;
    *ptr_out=0;
    if(!rm(slot,&ptr,8) || !rm(slot+8,&rep,8)) return -1;
    if(!isHeap(ptr) || !isHeap(rep)) return 0;
    if(!rm(rep,&vft,8)) return -1;
    if(!isMod(vft) || (uint32_t)(vft-g_base)!=P_VFT_RCP) return 0;
    *ptr_out=ptr;
    return 1;
}

static int read_members(uint64_t party, PMem *out, int cap){
    int n=0, unread=0;
    uint64_t vb=q64(party+P_VBEG), ve=q64(party+P_VEND);
    if(!isHeap(vb) || !isHeap(ve) || ve<vb) return 0;
    uint64_t cnt=(ve-vb)/16; if(cnt>(uint64_t)cap) cnt=cap;
    for(uint64_t i=0;i<cnt;i++){
        uint64_t ptr=0;
        int live=lp_slot_live(vb+i*16,&ptr);
        if(live<0){ unread=1; continue; }
        if(!live) continue;
        PMem *m=&out[n]; memset(m,0,sizeof(*m)); m->lvlJoin=-1; m->dead=-1;
        read_sso(ptr,M_NAME,M_NLEN,M_NCAP,m->name,sizeof m->name);
        read_sso(ptr,M_NAME2,M_N2LEN,M_N2CAP,m->name2,sizeof m->name2);
        m->guid=q64(ptr+M_GUID);
        rm(ptr+M_X,&m->x,4); rm(ptr+M_Y,&m->y,4);
        rm(ptr+M_LVL,&m->lvl,4); rm(ptr+M_CLS,&m->cls,4); rm(ptr+M_F5C,&m->f5c,4);
        rm(ptr+M_HP,&m->hp,4); rm(ptr+M_MP,&m->mp,4); rm(ptr+M_LVL2,&m->lvl2,4);
        { int32_t mi=0; rm(ptr+M_MAPID,&mi,4); m->mapId=mi; }
        m->repok = 1;
        rm(ptr+M_F54,&m->f54,4); rm(ptr+M_F60,&m->f60,4);
        n++;
    }
    return unread ? -1 : n;
}
/* 배치/개별 읽기 결과에 리더 표시를 채운다. */
static void lp_mark_leaders(PMem*out,int n,const char*leader){
    for(int i=0;i<n;i++) out[i].isLeader = lp_isLeader(&out[i],leader);
}

/* GUID → 액터(엔티티) 조인: 레벨/사망/공격대상(로드된 멤버만). lc_collect 선행 필요. */
static void join_actors(PMem *out, int n){
    for(int i=0;i<n;i++){ PMem *m=&out[i];
        for(int k=0;k<lc_nc;k++){ if(lc_cur[k].guid!=m->guid) continue; LC_E*A=&lc_cur[k];
            uint32_t lv=0; rm(A->e+P_ENTLVL,&lv,4); m->lvlJoin=(lv>=1&&lv<=150)?(int)lv:-1;
            m->dead=A->dead; m->hasAtk=A->hasAtk; m->atkTgt=A->atkTgt;
            for(int j=0;j<lc_nc;j++) if(lc_cur[j].guid==A->atkTgt){ strncpy(m->tgtName,lc_cur[j].nm,sizeof m->tgtName-1); break; }
            break; }
    }
}

/* ── 저호출(캐시+배치): 전역/BFS 금지, 갱신 1회 <10콜 ─────────────────── */
/* 캐시 파일: "BASE PSUB PARTY" (hex). 별도 버퍼 사용(lcreg_outpath 정적버퍼 오염 방지). */
static const char* lp_cache_path(void){
    static char b[1024]; snprintf(b,sizeof b,"%s\\out\\party_cache.txt", lcreg_base()); return b;
}
static void lp_cache_load(uint64_t*base,uint64_t*psub_out,uint64_t*party_out){
    *base=*psub_out=*party_out=0;
    FILE*g=fopen(lp_cache_path(),"r"); if(!g) return;
    unsigned long long b=0,p=0,pt=0;
    if(fscanf(g,"%llX %llX %llX",&b,&p,&pt)==3){ *base=b; *psub_out=p; *party_out=pt; }
    fclose(g);
}
static void lp_cache_save(uint64_t base,uint64_t psub,uint64_t party){
    FILE*g=fopen(lp_cache_path(),"w"); if(!g) return;
    fprintf(g,"%llX %llX %llX\n",(unsigned long long)base,(unsigned long long)psub,(unsigned long long)party);
    fclose(g);
}
static int lp_verify_subs(uint64_t psub){ uint64_t v=0; return isHeap(psub)&&rm(psub,&v,8)&&(uint32_t)(v-g_base)==P_VFT_SUBS; }
static int lp_verify(uint64_t party){      uint64_t v=0; return isHeap(party)&&rm(party-P_HOPCTRL,&v,8)&&(uint32_t)(v-g_base)==P_VFT_RC; }
/* 앵커 발견(캐시 miss 1회): mgr→holder→sub[] 배치 → vft 로 psub 식별. */
static uint64_t lp_discover_subs(void){
    uint64_t mgr=q64(g_base+lcreg_u32("MGR",0x16EB6F0));
    if(!isHeap(mgr)) return 0;
    uint64_t holder=q64(mgr+lcreg_u32("HOLDER_OFF",0xD0));
    if(!isHeap(holder)) return 0;
    uint64_t subsbase=q64(holder+lcreg_u32("SUBB",0x180));
    if(!isHeap(subsbase)) return 0;
    static uint8_t sb[64*16]; if(!rm(subsbase,sb,sizeof sb)) return 0;
    for(int i=0;i<64;i++){ uint64_t s=*(uint64_t*)(sb+i*16); if(!isHeap(s)) continue;
        uint64_t v=0; if(rm(s,&v,8) && (uint32_t)(v-g_base)==P_VFT_SUBS) return s; }
    return 0;
}
/* 캐시 miss 시 고정체인으로 Party 해석. */
static uint64_t lp_resolve_from(uint64_t psub){
    uint64_t objA=0,objB=0,party=0;
    if(!isHeap(psub)) return 0;
    rm(psub+P_REF,&objA,8); if(!isHeap(objA)) return 0;
    { uint8_t b[0x40]; if(!rm(objA,b,sizeof b)) return 0; objB=*(uint64_t*)(b+P_HOP1); }
    if(!isHeap(objB)) return 0;
    { uint8_t b[0x40]; if(!rm(objB,b,sizeof b)) return 0; party=*(uint64_t*)(b+P_HOP2); }
    return lp_verify(party)?party:0;
}
/* 멤버 배치 읽기: 헤더 1콜 + 칸의 _Rep 확인 + 멤버별 1콜.
 * 반환 n = 이번 읽기에서 vft가 확인된 멤버 수. -1 = 헤더나 칸을 읽지 못함(미확인). */
static int lp_read_batch(uint64_t party, PMem*out, int cap, char*leader, int lcap, uint32_t*cnt_out){
    int n=0, unread=0; *cnt_out=0; leader[0]=0;
    uint8_t hb[0x50]; if(!rm(party,hb,sizeof hb)) return -1;
    lp_read_str_cstr(hb,P_LNAME,P_LNAME+0x10,leader,lcap);
    *cnt_out=*(uint32_t*)(hb+P_MCNT);
    uint64_t vb=*(uint64_t*)(hb+P_VBEG), ve=*(uint64_t*)(hb+P_VEND);
    if(!isHeap(vb)||!isHeap(ve)||ve<vb) return 0;
    uint64_t cnt=(ve-vb)/16; if(cnt>(uint64_t)cap) cnt=cap;
    for(uint64_t i=0;i<cnt;i++){
        uint64_t ptr=0;
        int live=lp_slot_live(vb+i*16,&ptr);
        if(live<0){ unread=1; continue; }
        if(!live) continue;
        uint8_t mb[0x80]; if(!rm(ptr,mb,sizeof mb)){ unread=1; continue; }
        PMem*m=&out[n]; memset(m,0,sizeof(*m)); m->lvlJoin=-1; m->dead=-1;
        uint64_t len=*(uint64_t*)(mb+M_NLEN);
        if(len< P_SSO && len<sizeof m->name){ memcpy(m->name,mb+M_NAME,len); m->name[len]=0; }
        else { uint64_t src=*(uint64_t*)(mb+M_NAME); if(rm(src,m->name,(uint32_t)(len<sizeof m->name?len:sizeof m->name-1))) m->name[len]=0; }
        m->guid=*(uint64_t*)(mb+M_GUID);
        m->x=*(int32_t*)(mb+M_X); m->y=*(int32_t*)(mb+M_Y);
        m->lvl=*(uint32_t*)(mb+M_LVL); m->cls=*(uint32_t*)(mb+M_CLS); m->f5c=*(uint32_t*)(mb+M_F5C);
        m->hp=*(uint32_t*)(mb+M_HP); m->mp=*(uint32_t*)(mb+M_MP);
        m->mapId=*(int32_t*)(mb+M_MAPID);
        m->f54=*(uint32_t*)(mb+M_F54); m->f60=*(uint32_t*)(mb+M_F60);
        m->isLeader = lp_isLeader(m,leader);
        m->repok = 1;
        n++;
    }
    return unread ? -1 : n;
}
/* 헤더(리더/멤버수) 1콜. (선택 사용) */
static void lp_read_header(uint64_t party, char*leader,int lcap, uint32_t*cnt){
    leader[0]=0; *cnt=0;
    uint8_t hb[0x50]; if(!rm(party,hb,sizeof hb)) return;
    lp_read_str_cstr(hb,P_LNAME,P_LNAME+0x10,leader,lcap);
    *cnt=*(uint32_t*)(hb+P_MCNT);
}

/* 클래스 코드(0..3) → 이름. Lineage 표준: 0=군주,1=기사,2=요정,3=마법사 (tarak=마법사=3 확인). */
static const char* lp_className(uint32_t c){
    static const char* n[4]={"군주","기사","요정","마법사"};
    return c<4?n[c]:"?";
}

/* ── 지역 테이블(region_table.tsv): mapId+cell → 지역/하위지역 ── */
typedef struct { int id,nameId,mapId,x0,y0,x1,y1,isDungeon; char name[96]; } LPRegion;
static LPRegion *lp_reg=0; static int lp_nreg=0;
static void lp_regions_load(void){
    if(lp_reg) return;
    const char*p=lcreg_resolve(lcreg_str("REGIONS_CSV","10_5/registry/region_table.tsv"),
                               lcreg_str("REGIONS_DIST","registry/region_table.tsv"));
    FILE*f=fopen(p,"rb"); if(!f) return;
    lp_reg=(LPRegion*)calloc(1024,sizeof(LPRegion)); if(!lp_reg){ fclose(f); return; }
    char line[1024]; int first=1;
    while(fgets(line,sizeof line,f)){
        if(first){ first=0; continue; }
        char*nl=strchr(line,'\n'); if(nl)*nl=0; if(!line[0]) continue;
        if(lp_nreg>=1024) break;
        LPRegion*r=&lp_reg[lp_nreg]; char*fld[9]; int n=0; fld[n++]=line;
        for(char*c=line;*c&&n<9;c++) if(*c=='\t'){ *c=0; fld[n++]=c+1; }
        if(n<9) continue;
        r->id=atoi(fld[0]); r->nameId=atoi(fld[1]); r->mapId=atoi(fld[2]);
        snprintf(r->name,sizeof r->name,"%s",fld[3]);
        r->x0=atoi(fld[4]); r->y0=atoi(fld[5]); r->x1=atoi(fld[6]); r->y1=atoi(fld[7]); r->isDungeon=atoi(fld[8]);
        lp_nreg++;
    }
    fclose(f);
}
static long lp_areaOf(const LPRegion*r){ return (long)(r->x1-r->x0)*(long)(r->y1-r->y0); }
static int lp_pickRegion(int mapId,int cx,int cy,const LPRegion**sub,const LPRegion**reg){
    const LPRegion*best=0,*big=0,*mapLevel=0; long bestA=0,bigA=0;
    for(int i=0;i<lp_nreg;i++){ const LPRegion*r=&lp_reg[i]; if(r->mapId!=mapId) continue;
        if(r->x1<=r->x0||r->y1<=r->y0){ if(!mapLevel) mapLevel=r; continue; }
        if(!(r->x0<=cx&&cx<=r->x1&&r->y0<=cy&&cy<=r->y1)) continue;
        long a=lp_areaOf(r); if(!best||a<bestA){best=r;bestA=a;} if(!big||a>bigA){big=r;bigA=a;} }
    if(!best&&mapLevel){ *sub=mapLevel; *reg=mapLevel; return 1; }
    if(sub)*sub=best; if(reg)*reg=big; return best?1:0;
}
/* 멤버 mapId+cell → 지역/하위지역 문자열. */
static void lp_regionOf(int mapId,int cx,int cy,char*out,int cap){
    out[0]=0; const LPRegion*sub=0,*reg=0;
    if(lp_nreg && lp_pickRegion(mapId,cx,cy,&sub,&reg) && sub){
        if(reg && reg!=sub) snprintf(out,cap,"%s/%s",reg->name,sub->name);
        else snprintf(out,cap,"%s",sub->name);
    } else snprintf(out,cap,"(?)");
}

/* 멤버 mapId+cell → 지역명(reg)·부분지역명(sub) 각각. */
static void lp_regionTwo(int mapId,int cx,int cy,char*reg,int rcap,char*sub,int scap){
    reg[0]=0; sub[0]=0; const LPRegion*b=0,*g=0;
    if(lp_nreg && lp_pickRegion(mapId,cx,cy,&b,&g)){
        snprintf(sub,scap,"%s", b?b->name:"(?)");
        snprintf(reg,rcap,"%s", g?g->name:(b?b->name:"(?)"));
    } else { snprintf(reg,rcap,"(?)"); snprintf(sub,scap,"(?)"); }
}

#endif /* LPARTY_H */