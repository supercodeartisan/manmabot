/* invsync.c — T7 통합 자동 재발견 도구 (인벤토리 + 이름 테이블)
 *
 * 단일 실행으로 T7 의 모든 가변 오프셋을 재발견·검증·registry 기록한다.
 * 각 단계는 서명(signature) 기반이며 검증 게이트를 통과할 때만 기록한다.
 * 실패 단계는 기존 값을 보존하고 OK/REDISCOVERED/FAIL-KEPT 를 보고한다.
 *
 * 데이터 판독 = SignedReadMemory 만. region 열거만 VirtualQueryEx.
 * registry = inventories/inventory_offsets.txt (봇 DLL이 읽는 같은 파일).
 *
 * usage: invsync.exe
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../entities/signeddrv_client.h"

static uint64_t g_pid=0,g_base=0; static uint32_t g_modSize=0,g_br=0;
static int rm(uint64_t a,void*b,uint32_t s){return SignedReadMemory(g_pid,a,b,s,&g_br)&&g_br==s;}
static uint64_t q64(uint64_t a){uint64_t v=0;rm(a,&v,8);return v;}
static uint32_t d32(uint64_t a){uint32_t v=0;rm(a,&v,4);return v;}
static int isHeap(uint64_t a){return a>=0x10000000000ULL&&a<0x70000000000ULL;}
static int isMod(uint64_t a){return a>=g_base&&a<g_base+g_modSize;}
static uint32_t vrva(uint64_t o){uint64_t v=q64(o);return isMod(v)?(uint32_t)(v-g_base):0;}

static int getModule(uint64_t*base,uint32_t*size){
    uint64_t peb=0,ldr=0,head=0,cur=0;
    if(!SignedGetPeb(g_pid,&peb)||!peb) return 0;
    if(!rm(peb+0x18,&ldr,8)||!ldr) return 0;
    if(!rm(ldr+0x20,&head,8)||!head) return 0;
    cur=head;
    for(int g=0;g<5000&&cur&&cur!=(ldr+0x20);g++){
        uint64_t e=cur-0x10,db=0;uint32_t ds=0;
        if(rm(e+0x30,&db,8)&&db&&rm(e+0x40,&ds,4)&&ds){*base=db;*size=ds;return 1;}
        if(!rm(cur,&cur,8))break;
    }
    return 0;
}

/* ---------- registry (키 보존형) ---------- */
#define MAXL 512
static char g_lines[MAXL][256]; static int g_nl=0;
static void loadReg(const char* path){
    FILE* f=fopen(path,"r"); if(!f) return; char line[256];
    while(fgets(line,sizeof(line),f) && g_nl<MAXL){
        char* p; if((p=strchr(line,'\n')))*p=0; if((p=strchr(line,'\r')))*p=0;
        strncpy(g_lines[g_nl],line,255); g_nl++;
    }
    fclose(f);
}
static void setKV(const char* key,const char* val){
    char pat[64]; snprintf(pat,sizeof(pat),"%s=",key);
    for(int i=0;i<g_nl;i++) if(!strncmp(g_lines[i],pat,strlen(pat))){
        /* 기존 코멘트(값 뒤 # 포함줄) 는 값만 교체 */
        char rest[256]; strncpy(rest,g_lines[i]+strlen(pat),255); rest[255]=0;
        char* hash=strchr(rest,'#'); char tail[256]; tail[0]=0;
        if(hash) strncpy(tail,hash,255);
        snprintf(g_lines[i],256,"%s%s%s%s",pat,val,(tail[0]?" ":""),tail);
        return;
    }
    if(g_nl<MAXL) snprintf(g_lines[g_nl++],256,"%s%s",pat,val);
}
static uint32_t getKV(const char* key,uint32_t def){
    char pat[64]; snprintf(pat,sizeof(pat),"%s=",key);
    for(int i=0;i<g_nl;i++) if(!strncmp(g_lines[i],pat,strlen(pat)))
        return (uint32_t)strtoul(g_lines[i]+strlen(pat),0,0);
    return def;
}
static uint64_t getKV64(const char* key,uint64_t def){
    char pat[64]; snprintf(pat,sizeof(pat),"%s=",key);
    for(int i=0;i<g_nl;i++) if(!strncmp(g_lines[i],pat,strlen(pat)))
        return (uint64_t)strtoull(g_lines[i]+strlen(pat),0,16);
    return def;
}
static void saveReg(const char* path){
    FILE* f=fopen(path,"w"); if(!f) return;
    for(int i=0;i<g_nl;i++) fprintf(f,"%s\n",g_lines[i]);
    fclose(f);
}

/* module image (RTTI) */
static uint8_t* g_mod=0; static uint32_t g_modRead=0;
static void loadModule(void){
    g_mod=(uint8_t*)malloc(g_modSize); if(!g_mod)return;
    for(uint32_t o=0;o<g_modSize;o+=0x10000){
        uint32_t w=(g_modSize-o<0x10000)?(g_modSize-o):0x10000;
        if(!rm(g_base+o,g_mod+o,w)) memset(g_mod+o,0,w); else g_modRead+=w;
    }
}
static uint32_t findVftByName(const char* name){
    if(!g_mod) return 0; size_t ln=strlen(name); int hits=0;
    for(uint32_t i=0;i+ln<g_modRead && hits<2;i++){
        if(memcmp(g_mod+i,name,ln)!=0) continue; hits++;
        if(i<0x10) continue; uint32_t td=i-0x10;
        for(uint32_t j=0;j+4<=g_modRead;j++){
            uint32_t u; memcpy(&u,g_mod+j,4); if(u!=td) continue;
            if(j<0xC) continue; uint32_t col=j-0xC; uint64_t colva=g_base+col;
            for(uint32_t k=0;k+8<=g_modRead;k++){
                uint64_t q; memcpy(&q,g_mod+k,8); if(q!=colva) continue;
                return k+8;
            }
        }
    }
    return 0;
}

static int readSso(uint64_t a,char* out,int outSz){
    uint8_t h[0x20]; if(outSz<2||!rm(a,h,sizeof(h))) return -1;
    uint64_t size=*(uint64_t*)(h+0x10), cap=*(uint64_t*)(h+0x18);
    if(size==0||size>0x400||cap>0x100000) return -1;
    if((int)size>=outSz) size=outSz-1;
    if(cap<=0xF) memcpy(out,h,(size_t)size);
    else { uint64_t p=*(uint64_t*)h; if(!isHeap(p)||!rm(p,out,(uint32_t)size)) return -1; }
    out[size]=0; return (int)size;
}
static uint64_t fnv1aKey(uint32_t mid,uint64_t off,uint64_t prime){
    char s[24]; int n=snprintf(s,sizeof(s),"1_%u",mid);
    uint64_t h=off; for(int i=0;i<n;i++){ h^=(unsigned char)s[i]; h*=prime; } return h;
}
static uint32_t recMidOf(uint64_t rec){
    uint8_t h[0x20]; if(!rm(rec+0x10,h,sizeof(h))) return 0;
    if(h[0]!='1'||h[1]!='_') return 0;
    uint64_t size=*(uint64_t*)(h+0x10);
    if(size<3||size>12) return 0;
    uint32_t m=0; for(uint64_t i=2;i<size;i++){ if(h[i]<'0'||h[i]>'9') return 0; m=m*10+(h[i]-'0'); }
    return m;
}
/* count "1_<digits>" SSO keys in obj(0x400) + 1-hop children */
static int keyDensity(uint64_t obj,int depth){
    if(!isHeap(obj)||depth>1) return 0;
    uint8_t b[0x400]; if(!rm(obj,b,sizeof(b))) return 0;
    int c=0;
    for(uint32_t i=0;i+0x40<=sizeof(b);i++){
        if(b[i]!='1'||b[i+1]!='_') continue;
        uint32_t k=i+2,m=0; while(k<i+16&&b[k]>='0'&&b[k]<='9'){m=m*10+(b[k]-'0');k++;}
        if(m&&k>i+2&&*(uint64_t*)(b+i+0x10)==(uint64_t)(k-i)&&*(uint64_t*)(b+i+0x18)==0xF) c++;
    }
    if(depth<1) for(uint32_t o=0;o<0x40;o+=8){ uint64_t ch=q64(obj+o); if(isHeap(ch)) c+=keyDensity(ch,depth+1); }
    return c;
}

/* ---------- stage helpers ---------- */
static const char* RES="";   /* per-stage result */
static int g_redis=0;        /* rediscovered count */

/* S1: MGR 재발견 (서명: guard==1, holder, 40~120 subsys, 다수 module vft) */
static int findMgr(uint32_t* outOff, uint64_t* outMgr, uint64_t* outHolder){
    int best=-1; uint32_t bo=0; uint64_t bv=0,bh=0; int bcnt=0, bok=0;
    if(!g_mod) return 0;
    for(uint32_t off=0; off+8<=g_modSize; off+=8){
        uint64_t v; memcpy(&v,g_mod+off,8);
        if(!isHeap(v)||(v&0xF)) continue;
        unsigned char g=0; if(!rm(v+0xD8,&g,1)||g!=1) continue;
        uint64_t holder=0; if(!rm(v+0xD0,&holder,8)||!isHeap(holder)) continue;
        uint64_t bgn=0,end=0;
        if(!rm(holder+0x180,&bgn,8)||!rm(holder+0x188,&end,8)) continue;
        if(!isHeap(bgn)||end<=bgn||((end-bgn)%16)) continue;
        int cnt=(int)((end-bgn)/16); if(cnt<40||cnt>120) continue;
        int okv=0,n=0;
        for(int i=0;i<cnt&&n<24;i++){ uint64_t s=0; if(!rm(bgn+16ull*i,&s,8)) break; if(!isHeap(s)) continue; n++;
            uint64_t vf=0; if(rm(s,&vf,8)&&isMod(vf)) okv++; }
        if(okv<5) continue;
        int score = okv*10 - (cnt>62?cnt-62:62-cnt);   /* cnt≈62, okv 최대 */
        if(score>best){ best=score; bo=off; bv=v; bh=holder; bcnt=cnt; bok=okv; }
    }
    if(best<0) return 0;
    *outOff=bo; *outMgr=bv; *outHolder=bh;
    fprintf(stderr,"  [S1] MGR candidate off=0x%X mgr=0x%llX holder=0x%llX cnt=%d okv=%d\n",
        bo,(unsigned long long)bv,(unsigned long long)bh,bcnt,bok);
    return 1;
}

int main(void){
    SetConsoleOutputCP(CP_UTF8);
    FILE* rep=fopen("invsync_report.txt","w");
    #define RPT(...) do{ printf(__VA_ARGS__); if(rep) fprintf(rep,__VA_ARGS__); }while(0)

    loadReg("inventory_offsets.txt");
    /* 기존 값 */
    uint32_t MGR=getKV("MGR",0x1668860), GUARD_OFF=getKV("GUARD_OFF",0xD8), GUARD_VAL=getKV("GUARD_VAL",1);
    uint32_t HOLDER_OFF=getKV("HOLDER_OFF",0xD0), SUB_BEG=getKV("SUBLIST_BEG",0x180), SUB_END=getKV("SUBLIST_END",0x188);
    uint32_t INV_SUB_IDX=getKV("INV_SUB_IDX",26), INV_VFT=getKV("INV_VFT",0x11C6BE8);
    uint32_t INV_VEC_BEG=getKV("INV_VEC_BEG",0x3D8), INV_VEC_END=getKV("INV_VEC_END",0x3E0);
    uint32_t ITEM_VFT=getKV("ITEM_VFT",0x11C6640), ITEM_FMT=getKV("ITEM_FMT",0x68);
    uint32_t ANCHOR_RVA=getKV("MSG_ANCHOR_RVA",0x1668888);
    uint64_t FNV_OFF=getKV64("MSG_FNV_OFFSET",0xcbf29ce484222325ULL);
    uint64_t FNV_PRIME=getKV64("MSG_FNV_PRIME",0x100000001b3ULL);
    uint32_t BUCKET_STRIDE=getKV("MSG_BUCKET_STRIDE",0x10), BUCKET_MASK=getKV("MSG_BUCKET_MASK",0xFFFF);
    uint32_t REC_NAME=getKV("MSG_REC_NAME",0x38), NAME_KR=getKV("MSG_NAME_KR",0x00), NODE_TEXT=getKV("MSG_NODE_TEXT",0x30);

    HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0); PROCESSENTRY32W pe; pe.dwSize=sizeof(pe); DWORD pid=0;
    if(Process32FirstW(snap,&pe)) do{ if(_wcsicmp(pe.szExeFile,L"LC.exe")==0){pid=pe.th32ProcessID;break;} }while(Process32NextW(snap,&pe));
    CloseHandle(snap);
    if(!pid){ RPT("no LC.exe\n"); if(rep)fclose(rep); return 1; }
    if(!SignedOpen()){ RPT("driver open fail\n"); if(rep)fclose(rep); return 1; }
    SignedSetTarget(pid); g_pid=pid;
    if(!getModule(&g_base,&g_modSize)){ RPT("module base fail\n"); if(rep)fclose(rep); return 1; }
    loadModule();
    RPT("== invsync : module base=0x%llX size=0x%X ==\n",(unsigned long long)g_base,g_modSize);

    /* ---- S1: MGR ---- */
    uint32_t mgrOff=0; uint64_t mgr=0, holder=0;
    if(findMgr(&mgrOff,&mgr,&holder)){
        if(mgrOff!=MGR){ MGR=mgrOff; char hv[16]; snprintf(hv,sizeof(hv),"0x%X",MGR); setKV("MGR",hv); g_redis++;
            RPT("  [S1] REDISCOVERED MGR 0x%X\n",MGR); }
        else RPT("  [S1] OK MGR=0x%X\n",MGR);
    } else RPT("  [S1] FAIL-KEPT MGR=0x%X (수동 재탐색 필요)\n",MGR);

    /* ---- S2: sub list ---- */
    mgr=q64(g_base+MGR);
    holder=q64(mgr+HOLDER_OFF);
    uint64_t bgn=q64(holder+SUB_BEG), end=q64(holder+SUB_END);
    int subs=(int)((end-bgn)/16);
    RPT("  [S2] holder=0x%llX subsystems=%d %s\n",(unsigned long long)holder,subs,(subs>=40?"OK":"FAIL-KEPT"));

    /* ---- S3: INV vft (RTTI) ---- */
    uint32_t v=findVftByName(".?AVInventorySubsystem@lineage@@");
    if(v){ if(v!=INV_VFT){ INV_VFT=v; char hv[16]; snprintf(hv,sizeof(hv),"0x%X",INV_VFT); setKV("INV_VFT",hv); g_redis++;
            RPT("  [S3] REDISCOVERED INV_VFT=0x%X\n",INV_VFT); } else RPT("  [S3] OK INV_VFT=0x%X\n",INV_VFT); }
    else RPT("  [S3] FAIL-KEPT INV_VFT=0x%X\n",INV_VFT);

    /* ---- S4: INV idx/vec (vft 매칭 + 벡터 서명 재검증) ---- */
    uint64_t inv=0; int idx=-1;
    for(int i=0;i<subs;i++){ uint64_t s=q64(bgn+16ull*i); if(vrva(s)==INV_VFT){ inv=s; idx=i; break; } }
    if(inv){
        /* INV_VEC_BEG 검증: 포인터 배열(begin<end<=0x20000) 이고 원소 '여럿'이 module vft.
           약한 검증(1개)은 손상값을 통과시키므로, 최소 3개 또는 절반 이상 요구. */
        int vok=0;
        { uint64_t vb=q64(inv+INV_VEC_BEG), ve=q64(inv+INV_VEC_END);
          if(isHeap(vb)&&ve>vb&&(ve-vb)<=0x20000&&((ve-vb)%8)==0){
            uint64_t n=(ve-vb)/8; int kn=(n>8?8:(int)n), ok=0;
            for(int j=0;j<kn;j++){ uint64_t e=q64(vb+j*8); if(isHeap(e)&&vrva(e)) ok++; }
            if(kn>=3 && ok>=3 && ok*2>=kn) vok=1;
          } }
        if(!vok){
            for(uint32_t o=0x200;o<0x800;o+=8){ uint64_t vb=q64(inv+o),ve=q64(inv+o+8);
                if(!isHeap(vb)||ve<=vb||(ve-vb)>0x20000||((ve-vb)%8)) continue;
                uint64_t n=(ve-vb)/8; int kn=(n>8?8:(int)n); if(kn<3) continue;
                int ok=0; for(int j=0;j<kn;j++){ uint64_t e=q64(vb+j*8); if(isHeap(e)&&vrva(e)) ok++; }
                if(ok>=3 && ok*2>=kn){ INV_VEC_BEG=o; INV_VEC_END=o+8;
                    char ov[16],ev[16]; snprintf(ov,sizeof(ov),"0x%X",o); snprintf(ev,sizeof(ev),"0x%X",o+8);
                    setKV("INV_VEC_BEG",ov); setKV("INV_VEC_END",ev); g_redis++;
                    RPT("  [S4] REDISCOVERED vec=+0x%X (vector signature, ok=%d/%d)\n",o,ok,kn); break; } }
        }
        if(vok) RPT("  [S4] vec=+0x%X OK\n",INV_VEC_BEG);
    }
    if(!inv){ /* INV_VFT 실패 시 벡터 서명 폴백 */
        for(int i=0;i<subs&&!inv;i++){ uint64_t s=q64(bgn+16ull*i); if(!isHeap(s)) continue;
            for(uint32_t o=0x200;o<0x800;o+=8){ uint64_t vb=q64(s+o),ve=q64(s+o+8);
                if(!isHeap(vb)||ve<=vb||(ve-vb)>0x20000||((ve-vb)%8)) continue;
                uint64_t first=q64(vb); if(!isHeap(first)) continue;
                if(!vrva(first)) continue;
                int ok=0,kn=((ve-vb)/8>4?4:(int)((ve-vb)/8));
                for(int j=0;j<kn;j++){ uint64_t e=q64(vb+j*8); if(isHeap(e)&&vrva(e)) ok++; }
                if(ok<kn-1) continue;
                inv=s; idx=i; INV_VEC_BEG=o; INV_VEC_END=o+8; g_redis++;
                char ov[16],ev[16]; snprintf(ov,sizeof(ov),"0x%X",o); snprintf(ev,sizeof(ev),"0x%X",o+8);
                setKV("INV_VEC_BEG",ov); setKV("INV_VEC_END",ev);
                RPT("  [S4] REDISCOVERED (vec-signature) vec=+0x%X\n",o); break; } } }
    if(inv){ char hv[16]; snprintf(hv,sizeof(hv),"%d",idx); setKV("INV_SUB_IDX",hv);
        RPT("  [S4] idx=%d inv=0x%llX vec=+0x%X\n",idx,(unsigned long long)inv,INV_VEC_BEG);
        if(idx!=INV_SUB_IDX){ INV_SUB_IDX=idx; g_redis++; } }
    else RPT("  [S4] FAIL-KEPT: InventorySubsystem 미발견\n");

    /* ---- S5: ITEM vft/fmt (벡터 원소 다수결로 vft 확정, fmt 재검증) ---- */
    int nItem=0;
    if(inv){ uint64_t vb=q64(inv+INV_VEC_BEG), ve=q64(inv+INV_VEC_END);
        if(isHeap(vb)&&ve>vb&&(ve-vb)<=0x20000){
            uint64_t nn=(ve-vb)/8, seen[400]; int ns=0;
            /* 1) 벡터 원소 vft 빈도 집계 → 최빈 module vft = ITEM_VFT */
            uint32_t vfts[16]; int vc[16]; int nv=0;
            for(uint64_t k=0;k<nn;k++){ uint64_t e=q64(vb+k*8); if(!isHeap(e)) continue; uint32_t vv=vrva(e); if(!vv) continue;
                int f=0; for(int j=0;j<nv;j++) if(vfts[j]==vv){vc[j]++;f=1;break;}
                if(!f&&nv<16){vfts[nv]=vv;vc[nv]=1;nv++;} }
            int bi=-1; for(int j=0;j<nv;j++) if(bi<0||vc[j]>vc[bi]) bi=j;
            if(bi>=0){
                if(vfts[bi]!=ITEM_VFT){ ITEM_VFT=vfts[bi]; char hv[16]; snprintf(hv,sizeof(hv),"0x%X",ITEM_VFT); setKV("ITEM_VFT",hv); g_redis++;
                    RPT("  [S5] REDISCOVERED ITEM_VFT=0x%X (majority %d/%d)\n",ITEM_VFT,vc[bi],(int)nn); }
                else RPT("  [S5] OK ITEM_VFT=0x%X (majority %d)\n",ITEM_VFT,vc[bi]);
                for(uint64_t k=0;k<nn&&ns<400;k++){ uint64_t e=q64(vb+k*8); if(!isHeap(e)||vrva(e)!=ITEM_VFT) continue;
                    int d=0; for(int z=0;z<ns;z++) if(seen[z]==e){d=1;break;} if(d)continue; seen[ns++]=e; }
                nItem=ns;
                /* 2) ITEM_FMT 재검증: 두 아이템이 같은 오프셋에서 '$' 여야 */
                if(ns>0){ uint64_t e=seen[0]; char fmt[128]={0}; uint32_t cur=ITEM_FMT;
                    int ok=(readSso(e+cur,fmt,sizeof(fmt))>0&&fmt[0]=='$');
                    if(ok && ns>1){ char f2[128]={0}; if(!(readSso(seen[1]+cur,f2,sizeof(f2))>0&&f2[0]=='$')) ok=0; }
                    if(!ok){ for(uint32_t o=0x40;o<0xA0;o+=8){ if(readSso(e+o,fmt,sizeof(fmt))>0&&fmt[0]=='$'){
                            if(ns>1){ char f2[128]={0}; if(!(readSso(seen[1]+o,f2,sizeof(f2))>0&&f2[0]=='$')) continue; }
                            ITEM_FMT=o; char ov[16]; snprintf(ov,sizeof(ov),"0x%X",o); setKV("ITEM_FMT",ov); g_redis++;
                            RPT("  [S5] REDISCOVERED ITEM_FMT=0x%X ('%s')\n",o,fmt); break; } } }
                    else RPT("  [S5] OK ITEM_FMT=0x%X\n",ITEM_FMT); }
            }
        } }
    RPT("  [S5] items listed=%d\n",nItem);

    /* ---- S6: 이름 앵커 재발견 (모듈 전역 슬롯, '1_<mid>' 키 밀도) ---- */
    if(g_mod){
        int best=0; uint32_t boff=0; uint64_t bval=0;
        for(uint32_t off=0; off+8<=g_modSize; off+=8){
            uint64_t vv; memcpy(&vv,g_mod+off,8);
            if(!isHeap(vv)) continue;
            int c=keyDensity(vv,0);
            if(c>best){ best=c; boff=off; bval=vv; }
        }
        if(best>=5){
            if(boff!=ANCHOR_RVA){ ANCHOR_RVA=boff; char hv[16]; snprintf(hv,sizeof(hv),"0x%X",boff); setKV("MSG_ANCHOR_RVA",hv); g_redis++;
                RPT("  [S6] REDISCOVERED MSG_ANCHOR_RVA=0x%X (keys=%d)\n",boff,best); }
            else RPT("  [S6] OK MSG_ANCHOR_RVA=0x%X (keys=%d)\n",ANCHOR_RVA,best);
        } else RPT("  [S6] FAIL-KEPT MSG_ANCHOR_RVA=0x%X (density=%d)\n",ANCHOR_RVA,best);
    }

    /* ---- S7: 해시/버킷/이름 검증 게이트 (양성 대조: mid 목록) ---- */
    {
        uint64_t anchor=q64(g_base+ANCHOR_RVA);
        int okCount=0, tried=0;
        uint32_t probeMids[]={67,4,70,167,517,7,36,264,2,66,23,35,127,332,10068};
        char nm[128];
        for(int i=0;i<(int)(sizeof(probeMids)/sizeof(probeMids[0]));i++){
            uint32_t mid=probeMids[i]; tried++;
            uint64_t rec=q64(anchor+(fnv1aKey(mid,FNV_OFF,FNV_PRIME)&BUCKET_MASK)*BUCKET_STRIDE);
            for(int st=0; isHeap(rec)&&st<64; st++){
                if(recMidOf(rec)==mid){
                    uint64_t nn=q64(rec+REC_NAME); if(isHeap(nn)){
                        uint64_t kr=q64(nn+NAME_KR);
                        if(isHeap(kr)&&readSso(kr+NODE_TEXT,nm,sizeof(nm))>0) okCount++;
                    }
                    break;
                }
                uint64_t nx=q64(rec); if(nx==rec) break; rec=nx;
            }
        }
        RPT("  [S7] name resolve %d/%d %s\n",okCount,tried,(okCount*2>=tried?"OK":"FAIL-KEPT"));
    }

    saveReg("inventory_offsets.txt");
    RPT("== invsync done: rediscovered=%d, registry=inventory_offsets.txt ==\n",g_redis);
    if(rep) fclose(rep);
    SignedClose();
    return 0;
}
