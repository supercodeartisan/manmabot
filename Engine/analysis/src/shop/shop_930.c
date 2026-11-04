/* shop_930.c — 상점 리스트 읽기 정본 모듈 (10_5 규격)
 * ---------------------------------------------------------------------------
 *  대원칙:
 *    1) 고정앵커  : ShopSubsystem = lc_subsGet(VFT_SHOP)
 *    2) 고정체인  : Buy  = q64(sub+SHOP_BUY_BEGIN) .. SHOP_BUY_END, stride BUY_STRIDE
 *                   item: vft==BUYLISTITEM_VFT, +BLI_ORDER/+BLI_ITEMID/+BLI_TEMPLATE/+BLI_PRICE
 *                   Sell = q64(sub+0x58)..+0x60 (stride 0x20), +0x18 id, +0x1C unit price
 *    3) 이름해석  : mid → 메시지 테이블(FNV 앵커) → string.csv 폴백
 *    4) MmCopy단일, 상수 registry 단일출처, 읽기규격 POLL_SHOP_*.
 *  usage: shop_930.exe [registry] [secs] [out.txt]
 *  출력: <EXE>\out\shop_out.txt  (상점창 열려 있어야 Buy 행 존재)
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

static uint32_t RG_SHOPVFT, RG_STATE, RG_BBEG, RG_BEND, RG_BCAP, RG_BSTRIDE;
static uint32_t RG_BUYVFT, RG_BLI_KEY, RG_BLI_KEYBACK, RG_BLI_ORDER, RG_BLI_ID, RG_BLI_TMPL, RG_BLI_PRICE;
static uint32_t RG_SBEG, RG_SEND, RG_SSTRIDE, RG_SVFT, RG_S_ID, RG_S_UNIT;
static uint32_t RG_INVVFT, RG_IVB, RG_IVE, RG_ITEMVFT, RG_ITEM_ID, RG_ITEM_TMPL, RG_ITEM_CNT, RG_ITEM_FMT;
static uint32_t RG_ARVA,RG_MASK,RG_STRIDE,RG_NEXT,RG_RECNAME,RG_NAMEKR,RG_NODETEXT,RG_RECHDR,RG_STRLEN,RG_STRCAP,RG_SSOMAX,RG_MIDFB;
static uint64_t RG_FNVOFF,RG_FNVPRIME;
static char RG_STRCSV[256];
static int  s_id[40000]; static char s_kr[40000][160]; static int s_n=0;
static int  RG_PREFKR=1;   /* 1=한글 사전(STRINGS) 우선, 0=메모리 이름 우선 */
static const char* strName(int id){
    for(int i=0;i<s_n;i++) if(s_id[i]==id){
        const char* v=s_kr[i];
        if(!v[0] || !strncmp(v,"desc",4) || !strncmp(v,"string",6)) return 0;
        return v;
    }
    return 0;
}
static void loadStrings(const char*p){ FILE*g=fopen(p,"rb"); if(!g)return; char*raw=(char*)malloc(2<<20); if(!raw){fclose(g);return;}
    int n=(int)fread(raw,1,2<<20,g); fclose(g); raw[n]=0; char*s=raw;
    if((unsigned char)s[0]==0xEF&&(unsigned char)s[1]==0xBB&&(unsigned char)s[2]==0xBF)s+=3;
    while(*s){ char*e=strchr(s,'\n'); if(e)*e=0; char*cm=strchr(s,','); if(cm){ int id=atoi(s);
        if(id>0){ char*p1=strchr(cm+1,','),*p2=p1?strchr(p1+1,','):0;
            if(p2){ char*kr=p2+1,*buf=s_kr[s_n]; int bi=0,inq=0; if(*kr=='"'){inq=1;kr++;}
                while(*kr&&bi<159){ if(inq){if(*kr=='"')break;} else {if(*kr==',')break;} buf[bi++]=*kr++; }
                buf[bi]=0; s_id[s_n]=id; s_n++; if(s_n>=40000)break; } } }
        if(!e)break; s=e+1; } free(raw); }
static int readSso(uint64_t a,char*out,int cap){ uint8_t h[0x20]; out[0]=0; if(cap<=1||!rm(a,h,sizeof(h)))return 0;
    uint64_t sz=*(uint64_t*)(h+RG_STRLEN),cp=*(uint64_t*)(h+RG_STRCAP); if(!sz||sz>0x400||cp>0x100000)return 0;
    if((int)sz>=cap)sz=cap-1; if(cp<RG_SSOMAX)memcpy(out,h,(size_t)sz); else { uint64_t p=*(uint64_t*)h; if(!isHeap(p)||!rm(p,out,(uint32_t)sz))return 0; }
    out[sz]=0; return (int)sz; }
static uint64_t fnvKey(uint32_t mid){ char s[24]; int n=snprintf(s,sizeof(s),"1_%u",mid); uint64_t h=RG_FNVOFF;
    for(int i=0;i<n;i++){h^=(unsigned char)s[i];h*=RG_FNVPRIME;} return h; }
static uint32_t recMid(uint64_t rec){ uint8_t h[0x20]; if(!rm(rec+RG_RECHDR,h,sizeof(h)))return 0; if(h[0]!='1'||h[1]!='_')return 0;
    uint64_t sz=*(uint64_t*)(h+RG_STRLEN); if(sz<3||sz>12)return 0; uint32_t m=0; for(uint64_t i=2;i<sz;i++){ if(h[i]<'0'||h[i]>'9')return 0; m=m*10+(h[i]-'0'); } return m; }
static int msgName(uint32_t mid,char*out,int cap){ out[0]=0; if(!mid||!RG_ARVA)return 0; uint64_t A=q64(g_base+RG_ARVA); if(!isHeap(A))return 0;
    uint64_t rec=q64(A+(fnvKey(mid)&RG_MASK)*RG_STRIDE);
    for(int st=0;isHeap(rec)&&st<64;st++){ if(recMid(rec)==mid){ uint64_t nn=q64(rec+RG_RECNAME); if(!isHeap(nn))return 0;
        uint64_t kr=q64(nn+RG_NAMEKR); if(!isHeap(kr))return 0; return readSso(kr+RG_NODETEXT,out,cap)>0; }
        uint64_t nx=q64(rec+RG_NEXT); if(nx==rec)break; rec=nx; } return 0; }
static int resolve(uint32_t mid,char*out,int cap){
    const char* s = RG_PREFKR ? strName(mid) : 0;       /* 한글 사전 우선 */
    if(s){ snprintf(out,cap,"%s",s); return 1; }
    if(msgName(mid,out,cap)) return 1;
    s = strName(mid); if(s){ snprintf(out,cap,"%s",s); return 1; }
    snprintf(out,cap,"(?)"); return 0;
}
/* 10_8: mid→이름 캐시(같은 mid 반복 제거) */
static uint32_t rc_mid[512]; static char rc_nm[512][128]; static int rc_n=0;
static void resolveC(uint32_t mid,char*out,int cap){
    for(int i=0;i<rc_n;i++) if(rc_mid[i]==mid){ snprintf(out,cap,"%s",rc_nm[i]); return; }
    resolve(mid,out,cap);
    if(rc_n<512){ rc_mid[rc_n]=mid; snprintf(rc_nm[rc_n],128,"%s",out); rc_n++; }
}
/* +0x30 이 가리키는 표시문자열(std::string) → "$NNN" mid. 실패 시 0.
 * 실측: 문자열 객체는 (포인터 - BLI_KEY_BACK) 에 위치. 내용 예) "$1075", "+0 $61 (10)". */
static uint32_t midFromKey(uint64_t keyPtr){ if(!isHeap(keyPtr))return 0; char s[64]="";
    if(readSso(keyPtr-RG_BLI_KEYBACK,s,sizeof(s))<=0)return 0;
    const char*d=strchr(s,'$'); if(!d)return 0; return (uint32_t)strtoul(d+1,0,10); }

int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char*reg=lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    const char*outp=lcreg_outpath("shop_out.txt");
    int secs=0; { int seen=0;
      for(int i=1;i<argc;i++){ if(strstr(argv[i],".txt")||strstr(argv[i],".out")){ if(!seen&&strstr(argv[i],"REGISTRY")){reg=argv[i];seen=1;} else outp=argv[i]; }
        else if(atoi(argv[i])>0&&!strstr(argv[i],".")) secs=atoi(argv[i]); } }
    lcreg_load(reg); lc_reg_apply();
    RG_SHOPVFT=lcreg_u32("VFT_SHOP",0x120AE68); RG_STATE=lcreg_u32("SHOP_STATE",0x28);
    RG_BBEG=lcreg_u32("SHOP_BUY_BEGIN",0x40); RG_BEND=lcreg_u32("SHOP_BUY_END",0x48); RG_BCAP=lcreg_u32("SHOP_BUY_CAP",0x50);
    RG_BUYVFT=lcreg_u32("BUYLISTITEM_VFT",0x121F740);
    RG_BLI_KEY=lcreg_u32("BLI_KEY",0x30);
    RG_BLI_KEYBACK=lcreg_u32("BLI_KEY_BACK",2);
    RG_BLI_ORDER=lcreg_u32("BLI_ORDER",0x38); RG_BLI_ID=lcreg_u32("BLI_ITEMID",0x3C);
    RG_BLI_TMPL=lcreg_u32("BLI_TEMPLATE",0x40); RG_BLI_PRICE=lcreg_u32("BLI_PRICE",0x44);
    RG_BSTRIDE=lcreg_u32("BUY_STRIDE",0x90);
    RG_SBEG=lcreg_u32("SHOP_SELL_BEGIN",0x58); RG_SEND=lcreg_u32("SHOP_SELL_END",0x60); RG_SSTRIDE=lcreg_u32("SELL_STRIDE",0x20);
    RG_SVFT=lcreg_u32("SELLLISTITEM_VFT",0x121F7A8); RG_S_ID=lcreg_u32("SLI_ID",0x18); RG_S_UNIT=lcreg_u32("SLI_UNIT",0x1C);
    RG_INVVFT=lcreg_u32("INV_VFT",0x12079A0); RG_IVB=lcreg_u32("INV_VEC_BEG",0x3D8); RG_IVE=lcreg_u32("INV_VEC_END",0x3E0);
    RG_ITEMVFT=lcreg_u32("ITEM_VFT",0x1207430); RG_ITEM_ID=lcreg_u32("ITEM_ID",0x18); RG_ITEM_TMPL=lcreg_u32("ITEM_TEMPLATE",0x20);
    RG_ITEM_CNT=lcreg_u32("ITEM_COUNT",0x38); RG_ITEM_FMT=lcreg_u32("ITEM_FMT",0x68);
    RG_ARVA=lcreg_u32("MSG_ANCHOR_RVA",0x16687B8); RG_MASK=lcreg_u32("MSG_BUCKET_MASK",0xFFFF);
    RG_STRIDE=lcreg_u32("MSG_BUCKET_STRIDE",0x10); RG_NEXT=lcreg_u32("MSG_REC_NEXT",0x00);
    RG_RECNAME=lcreg_u32("MSG_REC_NAME",0x38); RG_NAMEKR=lcreg_u32("MSG_NAME_KR",0x00); RG_NODETEXT=lcreg_u32("MSG_NODE_TEXT",0x30);
    RG_RECHDR=lcreg_u32("OFF_REC_HDR",0x10);
    RG_STRLEN=lcreg_u32("OFF_STR_LEN",0x10); RG_STRCAP=lcreg_u32("OFF_STR_CAP",0x18);
    RG_SSOMAX=lcreg_u32("STR_SSO_MAX",0x10); RG_MIDFB=lcreg_u32("SHOP_MID_FALLBACK",1);
    RG_PREFKR=(int)lcreg_u32("NAME_PREFER_KR",1);
    RG_FNVOFF=lcreg_u64("MSG_FNV_OFFSET",0xcbf29ce484222325ULL); RG_FNVPRIME=lcreg_u64("MSG_FNV_PRIME",0x100000001b3ULL);
    snprintf(RG_STRCSV,sizeof(RG_STRCSV),"%s",lcreg_resolve(lcreg_str("ITEM_NAME_CSV","data/item_name_kr.csv"),
        lcreg_str("ITEM_NAME_DIST","data/item_name_kr.csv")));
    lcreg_poll P=lcreg_poll_load("SHOP");

    if(lc_attach())return 1; loadStrings(RG_STRCSV); if(!lc_anchor())return 2;
    lcreg_mkdir_for(outp);
    FILE*f=fopen(outp,"w"); if(!f){ fprintf(stderr,"cannot open %s\n",outp); return 4; }
    fprintf(f,"# registry=%s SHOP_VFT=%X\n",reg,RG_SHOPVFT);

    DWORD t0=GetTickCount();
    do{
        LARGE_INTEGER fr,q0,q1; QueryPerformanceFrequency(&fr); QueryPerformanceCounter(&q0);
        g_ioctl=0;
        uint64_t shop=lc_subsGet(RG_SHOPVFT); int nb=0,ns=0;
        if(isHeap(shop)){
            uint32_t state=d32(shop+RG_STATE);
            fprintf(f,"t=%ums shop=0x%llX state=0x%X\n",(unsigned)(GetTickCount()-t0),(unsigned long long)shop,state);
            uint64_t vb=q64(shop+RG_BBEG), ve=q64(shop+RG_BEND);
            int bn=(isHeap(vb)&&isHeap(ve)&&ve>=vb)?(int)((ve-vb)/RG_BSTRIDE):0; if(bn>512)bn=512;
            for(int k=0;k<bn;k++){ uint64_t b=vb+(uint64_t)k*RG_BSTRIDE;
                    uint8_t bh[0x48]; if(!rm(b,bh,sizeof bh)) continue;        /* 행 헤더 1콜 */
                    uint64_t vfp; memcpy(&vfp,bh,8); if(!isMod(vfp)||(uint32_t)(vfp-g_base)!=RG_BUYVFT)continue;
                    uint64_t key; memcpy(&key,bh+RG_BLI_KEY,8);
                    uint32_t order,id,tmpl,price;
                    memcpy(&order,bh+RG_BLI_ORDER,4); memcpy(&id,bh+RG_BLI_ID,4);
                    memcpy(&tmpl,bh+RG_BLI_TMPL,4);   memcpy(&price,bh+RG_BLI_PRICE,4);
                    uint32_t mid=midFromKey(key); if(!mid && RG_MIDFB) mid=id;
                    char nm[128]; resolveC(mid,nm,sizeof(nm));
                    fprintf(f,"  BUY [%2d] order=%-4u id=%-7u tmpl=%-6u price=%-7u %s\n",k,order,id,tmpl,price,nm); nb++; }
            uint64_t sb=q64(shop+RG_SBEG), se=q64(shop+RG_SEND);
            int sn=(isHeap(sb)&&isHeap(se)&&se>=sb)?(int)((se-sb)/RG_SSTRIDE):0; if(sn>512)sn=512;
            uint64_t inv=lc_subsGet(RG_INVVFT);
            for(int k=0;k<sn;k++){ uint64_t s=sb+(uint64_t)k*RG_SSTRIDE;
                    uint8_t sh[0x20]; if(!rm(s,sh,sizeof sh)) continue;         /* sell 행 헤더 1콜 */
                    uint64_t svf; memcpy(&svf,sh,8); if(!isMod(svf)||(uint32_t)(svf-g_base)!=RG_SVFT)continue;
                    uint32_t id,unit; memcpy(&id,sh+RG_S_ID,4); memcpy(&unit,sh+RG_S_UNIT,4);
                    uint32_t mid=0,tmpl=0,cnt=0; char nm[128]="(?)";
                    if(isHeap(inv)){ uint64_t ivb=q64(inv+RG_IVB),ive=q64(inv+RG_IVE); int in=(isHeap(ivb)&&isHeap(ive)&&ive>=ivb)?(int)((ive-ivb)/8):0;
                        static uint8_t ibf[4096]; int found=0;
                        for(int ib=0; ib<in && !found; ){ int c=((in-ib)>512)?512:(in-ib); if(!rm(ivb+(uint64_t)ib*8,ibf,c*8)) break;
                            for(int kk=0;kk<c && !found;kk++){ uint64_t it; memcpy(&it,ibf+(uint64_t)kk*8,8); if(!isHeap(it))continue;
                                uint8_t ih[0x50]; if(!rm(it,ih,sizeof ih))continue;
                                uint64_t vfp; memcpy(&vfp,ih,8); if(!isMod(vfp)||(uint32_t)(vfp-g_base)!=RG_ITEMVFT)continue;
                                uint32_t iid; memcpy(&iid,ih+RG_ITEM_ID,4); if(iid!=id)continue;
                                memcpy(&tmpl,ih+RG_ITEM_TMPL,4); memcpy(&cnt,ih+RG_ITEM_CNT,4);
                                char fmt[80]=""; readSso(it+RG_ITEM_FMT,fmt,sizeof(fmt));
                                const char*d=strchr(fmt,'$'); if(d)mid=(uint32_t)strtoul(d+1,0,10); resolveC(mid,nm,sizeof(nm)); found=1; }
                            ib+=c;
                        }
                    }
                fprintf(f,"  SELL[%2d] id=%-9u tmpl=%-6u invCnt=%-5u unit=%-7u %s\n",k,id,tmpl,cnt,unit,nm); ns++; }
        } else fprintf(f,"t=%ums ShopSubsystem not found\n",(unsigned)(GetTickCount()-t0));
        QueryPerformanceCounter(&q1);
        fprintf(f,"# buy=%d sell=%d ioctl=%llu time=%.4fms\n",nb,ns,g_ioctl,(q1.QuadPart-q0.QuadPart)*1000.0/fr.QuadPart);
        fflush(f);
        lcapi_sample(f);
        if(secs) Sleep(lcreg_poll_sleep_ms(&P));
    } while(!lcapi_done() && secs && (int)(GetTickCount()-t0)<secs*1000);
    fclose(f); SignedClose(); printf("done -> %s\n",outp); return 0;
}
