/* uimsg_1021.c — UIMessage(차단 통보문) 리더  [11-4 규약 / registry 상수 / IOCTL 최소]
 *
 *  11-4 규약:
 *   - 모든 게임 상수는 registry(LC930_REGISTRY.txt)에서 lcreg_u32 로 읽는다.
 *   - 드라이버 IOCTL 도 registry(SD_IOCTL_IMAGE_BASE)에서 읽어 Ex 함수로 전달.
 *   - 출력은 stdout + <EXE>\out\uimsg_out.txt.
 *
 *  시작(고정앵커·고정체인, 약 6 IOCTL):
 *   1) SD_IOCTL_IMAGE_BASE → LC.exe base                      (1)
 *   2) MGR    = *(BASE + MGR)                                 (1)
 *   3) holder = *(MGR + HOLDER_OFF)                           (1)
 *   4) subs   = *(holder + SUBB)                              (1)
 *   5) cms    = *(subs + CMS_SUB_INDEX * SUB_STRIDE)          (1)
 *   6) validate *(cms) == BASE + CMS_VFT                      (1)
 *
 *  샘플(1~2 IOCTL):
 *   - cms 페이지(CMS_PAGE_SIZE) 1회 읽기 → CMS_FLAG1_OFF / CMS_MSG_OFF /
 *     CMS_FLAG2_OFF 를 동시 파싱.
 *   - std::string 헤더(ptr/len/cap) 변경 시에만 데이터 +1.
 *
 *  usage: uimsg_1021.exe [seconds] [-a|-h]
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <string.h>
#include <stdlib.h>
#include "lcreg.h"
#include "lcore.h"

/* ── registry 상수 (main 에서 로드) ─────────────────────────── */
static uint32_t RG_CMS_VFT, RG_CMS_IDX, RG_CMS_MSG, RG_CMS_F1, RG_CMS_F2;
static uint32_t RG_STR_PTR, RG_STR_LEN, RG_STR_CAP, RG_PAGE;
static uint32_t RG_SD_IMG, RG_POLL_MS;

static uint64_t g_cms=0;
static uint64_t g_lastPtr=0,g_lastSize=0,g_lastCap=0;
static char     g_lastText[512];
static int      g_forceData=0,g_headerOnly=0;
static FILE    *g_out=0;

static void loadRegistryConstants(void)
{
    RG_CMS_VFT = lcreg_u32("CMS_VFT",        0x11E26A8);
    RG_CMS_IDX = lcreg_u32("CMS_SUB_INDEX",  6);
    RG_CMS_MSG = lcreg_u32("CMS_MSG_OFF",    0x28);
    RG_CMS_F1  = lcreg_u32("CMS_FLAG1_OFF",  0x18);
    RG_CMS_F2  = lcreg_u32("CMS_FLAG2_OFF",  0xC8);
    RG_STR_PTR = lcreg_u32("CMS_STR_PTR_OFF",0x00);
    RG_STR_LEN = lcreg_u32("CMS_STR_LEN_OFF",0x10);
    RG_STR_CAP = lcreg_u32("CMS_STR_CAP_OFF",0x18);
    RG_PAGE    = lcreg_u32("CMS_PAGE_SIZE",  0x1000);
    RG_SD_IMG  = lcreg_u32("SD_IOCTL_IMAGE_BASE", 0x222048);
    RG_POLL_MS = lcreg_u32("UIMSG_POLL_MS", 250);
}

/* ── 고정체인 시작 ───────────────────────────────────────────── */
static int attachFast(void)
{
    HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0);
    PROCESSENTRY32W pe; pe.dwSize=sizeof(pe);
    DWORD pid=0;
    if (Process32FirstW(snap,&pe))
        do { if(_wcsicmp(pe.szExeFile,L"LC.exe")==0){ pid=pe.th32ProcessID; break; } }
        while (Process32NextW(snap,&pe));
    CloseHandle(snap);
    if(!pid) return 1;
    if(!SignedOpen()) return 2;
    SignedSetTarget(pid); g_pid=pid;

    uint64_t base=0;
    if (SignedGetImageBaseEx(pid, RG_SD_IMG, &base) && base) {   /* 1 IOCTL */
        g_base=base;
        g_modSize=lcreg_u32("MODULE_SIZE",0x3F6E000);
        return 0;
    }
    if (!getModule(&g_base,&g_modSize)) return 3;                /* 폴백 */
    return 0;
}

static uint64_t resolveCmsFixed(void)
{
    uint64_t mgr=q64(g_base + LC_MGR_V);                  /* 1 */
    if(!isHeap(mgr)) return 0;
    uint64_t holder=q64(mgr + LC_HOLDER_V);               /* 1 */
    if(!isHeap(holder)) return 0;
    uint64_t subs=q64(holder + LC_SUBB_V);                /* 1 */
    if(!isHeap(subs)) return 0;
    lc_subs=subs;

    uint64_t cms=q64(subs + (uint64_t)RG_CMS_IDX*LC_SUB_STRIDE_V); /* 1 */
    if(!isHeap(cms)) return 0;
    uint64_t vf=q64(cms);                                  /* 1 */
    if(isMod(vf) && (uint32_t)(vf-g_base)==RG_CMS_VFT) return cms;
    return 0;
}

/* ── 샘플 ───────────────────────────────────────────────────── */
static void sample(int t)
{
    if(!isHeap(g_cms)){ printf("t=%d CommonMessageSubsystem not resolved\n",t); return; }
    unsigned long long io0=g_ioctl;

    uint64_t page=g_cms & ~(uint64_t)(RG_PAGE-1);
    uint32_t off =(uint32_t)(g_cms-page);
    static uint8_t pg[0x10000];
    if(RG_PAGE>sizeof pg){ printf("t=%d CMS_PAGE_SIZE too big\n",t); return; }
    if(!rm(page,pg,RG_PAGE)){ printf("t=%d page read fail\n",t); return; }  /* 1 */

    uint64_t f1,ptr,size,cap,f2;
    memcpy(&f1, pg+off+RG_CMS_F1, 8);
    memcpy(&ptr,pg+off+RG_CMS_MSG+RG_STR_PTR, 8);
    memcpy(&size,pg+off+RG_CMS_MSG+RG_STR_LEN, 8);
    memcpy(&cap, pg+off+RG_CMS_MSG+RG_STR_CAP, 8);
    memcpy(&f2, pg+off+RG_CMS_F2, 8);

    char text[512]; text[0]=0; int have=0;
    if(size>0 && size<=0x400 && size<=cap && cap<=0x100000){
        int n=(int)size; if(n>=(int)sizeof text) n=(int)sizeof text-1;
        if(cap<=0x10){ memcpy(text,pg+off+RG_CMS_MSG+RG_STR_PTR,(size_t)n); text[n]=0; have=1; }
        else if(!g_headerOnly){
            int changed=(ptr!=g_lastPtr||size!=g_lastSize||cap!=g_lastCap);
            if(changed||g_forceData||g_lastText[0]==0){
                if(isHeap(ptr)&&rm(ptr,text,(uint32_t)n)){ text[n]=0; have=1; } /* +1 */
            } else { snprintf(text,sizeof text,"%s",g_lastText); have=1; }
        }
    }

    if(!have){
        if(g_lastText[0]){
            printf("t=%d UIMessage cleared (size=%llu) ioctl=%llu\n",
                t,(unsigned long long)size,(unsigned long long)(g_ioctl-io0));
            if(g_out){
                fprintf(g_out,"%d\tCLEARED\tsize=%llu\n",t,(unsigned long long)size);
                fflush(g_out);
                lcapi_sample(g_out);
            }
            g_lastText[0]=0;
        } else if(g_out && (t==0 || lcapi_on())){
            /* API one-shot / idle: always emit a sample so sink gets a beat. */
            fprintf(g_out,"%d\tEMPTY\tsize=0\n",t);
            fflush(g_out);
            lcapi_sample(g_out);
        }
        return;
    }
    if(strcmp(text,g_lastText)!=0 || t==0 || lcapi_on()){
        printf("t=%d UIMessage size=%llu cap=%llu flags[+0x%X]=0x%llX [+0x%X]=0x%llX ioctl=%llu\n",
            t,(unsigned long long)size,(unsigned long long)cap,
            RG_CMS_F1,(unsigned long long)f1,RG_CMS_F2,(unsigned long long)f2,
            (unsigned long long)(g_ioctl-io0));
        printf("     text=\"%s\"\n",text);
        if(g_out){
            fprintf(g_out,"%d\tUIMSG\tsize=%llu\tcap=%llu\tf1=0x%llX\tf2=0x%llX\t%s\n",
                t,(unsigned long long)size,(unsigned long long)cap,
                (unsigned long long)f1,(unsigned long long)f2,text);
            fflush(g_out);
            lcapi_sample(g_out);
        }
        snprintf(g_lastText,sizeof g_lastText,"%s",text);
        g_lastPtr=ptr; g_lastSize=size; g_lastCap=cap;
    }
}

int main(int argc,char**argv)
{
    SetConsoleOutputCP(CP_UTF8);
    int secs=0;
    for(int i=1;i<argc;i++){
        if(!strcmp(argv[i],"-a")) g_forceData=1;
        else if(!strcmp(argv[i],"-h")) g_headerOnly=1;
        else secs=atoi(argv[i]);
    }
    lcreg_find_root("10_5/registry/LC930_REGISTRY.txt");
    const char *reg=lcreg_resolve("10_5/registry/LC930_REGISTRY.txt","registry/LC930_REGISTRY.txt");
    lcreg_load(reg); lc_reg_apply();
    loadRegistryConstants();

    unsigned long long io0=g_ioctl;
    int ar=attachFast();
    if(ar){ printf("# attach failed rc=%d\n",ar); SignedClose(); return ar; }
    g_cms=resolveCmsFixed();
    unsigned long long startup=g_ioctl-io0;

    if(!isHeap(g_cms)){
        if(lc_anchor()) g_cms=lc_subsGet(RG_CMS_VFT);
        startup=g_ioctl-io0;
    }

    const char *outp=lcreg_outpath("uimsg_out.txt"); lcreg_mkdir_for(outp);
    g_out=fopen(outp,"w");
    if(g_out){ fprintf(g_out,"# registry=%s cms=0x%llX\n",reg,(unsigned long long)g_cms); fflush(g_out); }

    printf("# LC pid=%llu base=0x%llX cms=0x%llX startup_ioctl=%llu (total=%llu)\n",
        (unsigned long long)g_pid,(unsigned long long)g_base,(unsigned long long)g_cms,
        (unsigned long long)startup,(unsigned long long)g_ioctl);

    if(lcapi_on()){
        /* DLL/API: emit until adapter count/stop (host sets interval). */
        if(RG_POLL_MS<50) RG_POLL_MS=50;
        int i=0;
        do {
            sample(i++);
            if(!lcapi_done()) Sleep(RG_POLL_MS);
        } while(!lcapi_done());
    } else if(secs<=0){
        sample(0);
    } else {
        if(RG_POLL_MS<50) RG_POLL_MS=50;
        int steps=(int)((long long)secs*1000/RG_POLL_MS);
        if(steps<1) steps=1;
        for(int i=0;i<steps;i++){ sample(i); if(i+1<steps) Sleep(RG_POLL_MS); }
    }

    printf("# done total_ioctl=%llu\n",(unsigned long long)g_ioctl);
    if(g_out){ fprintf(g_out,"# done total_ioctl=%llu\n",(unsigned long long)g_ioctl); fclose(g_out); }
    SignedClose();
    return 0;
}
