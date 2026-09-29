/* nametable.c — LC.exe 정적 이름 테이블 공유 리더 (구현)
 * 데이터 판독은 signeddrv(SignedReadMemory)만 사용. */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "../entities/signeddrv_client.h"
#include "nametable.h"

static NtCtx g_def = {
    0,0,0,
    0x1668888, 0x10, 0xFFFF,
    0xcbf29ce484222325ULL, 0x100000001b3ULL,
    0x00, 0x38, 0x10,
    0x00, 0x08, 0x10, 0x30
};

static int rm_(uint64_t pid,uint64_t a,void*b,uint32_t s){ uint32_t br=0; return SignedReadMemory(pid,a,b,s,&br)&&br==s; }
static uint64_t q64_(uint64_t pid,uint64_t a){ uint64_t v=0; rm_(pid,a,&v,8); return v; }
static int isHeap_(uint64_t a){ return a>=0x10000000000ULL && a<0x70000000000ULL; }
static int isMod_(const NtCtx* c,uint64_t a){ return a>=c->base && a<c->base+c->modSize; }

static int readSso_(uint64_t pid,uint64_t a,char* out,int outSz){
    uint8_t h[0x20]; if(outSz<2||!rm_(pid,a,h,sizeof(h))) return -1;
    uint64_t size=*(uint64_t*)(h+0x10), cap=*(uint64_t*)(h+0x18);
    if(size==0||size>0x400||cap>0x100000) return -1;
    if((int)size>=outSz) size=outSz-1;
    if(cap<=0xF) memcpy(out,h,(size_t)size);
    else { uint64_t p=*(uint64_t*)h; if(!isHeap_(p)||!rm_(pid,p,out,(uint32_t)size)) return -1; }
    out[size]=0; return (int)size;
}
static uint64_t fnv1aKey(uint32_t mid,uint64_t off,uint64_t prime){
    char s[24]; int n=snprintf(s,sizeof(s),"1_%u",mid);
    uint64_t h=off; for(int i=0;i<n;i++){ h^=(unsigned char)s[i]; h*=prime; } return h;
}
static uint32_t recMidOf(uint64_t pid,const NtCtx* c,uint64_t rec){
    uint8_t h[0x20]; if(!rm_(pid,rec+c->recKey,h,sizeof(h))) return 0;
    if(h[0]!='1'||h[1]!='_') return 0;
    uint64_t size=*(uint64_t*)(h+0x10);
    if(size<3||size>12) return 0;
    uint32_t m=0; for(uint64_t i=2;i<size;i++){ if(h[i]<'0'||h[i]>'9') return 0; m=m*10+(h[i]-'0'); }
    return m;
}

void ntLoadRegistry(NtCtx* c, const char* path){
    *c=g_def;
    FILE* f=fopen(path,"r"); if(!f) return; char line[256];
    while(fgets(line,sizeof(line),f)){
        char* p=strchr(line,'='); if(!p) continue; *p=0;
        char* k=line; for(char* t=k;*t;t++) if(*t==' '||*t=='\t'){*t=0;break;}
        const char* v=p+1;
        #define HEX(kk,field) if(!strcmp(k,kk)){ c->field=(uint32_t)strtoul(v,0,16); continue; }
        #define DEK(kk,field) if(!strcmp(k,kk)){ c->field=(uint32_t)strtoul(v,0,10); continue; }
        if(!strcmp(k,"MSG_ANCHOR_RVA")){ c->anchorRva=(uint32_t)strtoul(v,0,16); continue; }
        if(!strcmp(k,"MSG_BUCKET_STRIDE")){ c->bucketStride=(uint32_t)strtoul(v,0,16); continue; }
        if(!strcmp(k,"MSG_BUCKET_MASK")){ c->bucketMask=(uint32_t)strtoul(v,0,16); continue; }
        if(!strcmp(k,"MSG_FNV_OFFSET")){ c->fnvOffset=strtoull(v,0,16); continue; }
        if(!strcmp(k,"MSG_FNV_PRIME")){ c->fnvPrime=strtoull(v,0,16); continue; }
        if(!strcmp(k,"MSG_REC_NEXT")){ c->recNext=(uint32_t)strtoul(v,0,16); continue; }
        if(!strcmp(k,"MSG_REC_NAME")){ c->recName=(uint32_t)strtoul(v,0,16); continue; }
        if(!strcmp(k,"MSG_NAME_KR")){ c->nameKR=(uint32_t)strtoul(v,0,16); continue; }
        if(!strcmp(k,"MSG_NAME_TW")){ c->nameTW=(uint32_t)strtoul(v,0,16); continue; }
        if(!strcmp(k,"MSG_NODE_LANG")){ c->nodeLang=(uint32_t)strtoul(v,0,16); continue; }
        if(!strcmp(k,"MSG_NODE_TEXT")){ c->nodeText=(uint32_t)strtoul(v,0,16); continue; }
    }
    fclose(f);
}

uint32_t ntTokenMid(const char* fmt){
    for(const char* p=fmt; *p; p++)
        if(*p=='$'&&p[1]>='0'&&p[1]<='9') return (uint32_t)atoi(p+1);
    return 0;
}

int ntResolve(const NtCtx* c, uint32_t mid, char* out, int outSz, char* twOut, int twSz){
    if(out&&outSz>0) out[0]=0;
    if(!mid||!c->pid||!c->base) return 0;
    uint64_t anchor=q64_(c->pid,c->base+c->anchorRva);
    if(!isHeap_(anchor)) return 0;
    uint64_t rec=q64_(c->pid,anchor+(fnv1aKey(mid,c->fnvOffset,c->fnvPrime)&c->bucketMask)*c->bucketStride);
    for(int st=0; isHeap_(rec)&&st<64; st++){
        if(recMidOf(c->pid,c,rec)==mid){
            uint64_t nn=q64_(c->pid,rec+c->recName);
            if(!isHeap_(nn)) return 0;
            uint64_t kr=q64_(c->pid,nn+c->nameKR);
            uint64_t tw=q64_(c->pid,nn+c->nameTW);
            int ok=0;
            if(isHeap_(kr)){ char lang[8];
                if(readSso_(c->pid,kr+c->nodeLang,lang,sizeof(lang))>0 && readSso_(c->pid,kr+c->nodeText,out,outSz)>0) ok=1; }
            if(twOut&&twSz>0&&isHeap_(tw)) readSso_(c->pid,tw+c->nodeText,twOut,twSz);
            return ok;
        }
        uint64_t nx=q64_(c->pid,rec+c->recNext); if(nx==rec) break; rec=nx;
    }
    return 0;
}

void ntResolveFmt(const NtCtx* c, const char* fmt, char* out, int outSz){
    /* "$NNN" 토큰을 각각 이름으로 치환(위치 보존). 예:
       "$4 (2,675)" -> "아데나 (2,675)"
       "+0 $5 ($9)" -> "+0 장검 (대검)"  (인챈트 접두/괄호는 원문 유지) */
    int o=0; out[0]=0; const char* p=fmt;
    while(*p && o+1<outSz){
        if(*p=='$' && p[1]>='0' && p[1]<='9'){
            uint32_t mid=0; p++;
            while(*p>='0'&&*p<='9'){ mid=mid*10+(*p-'0'); p++; }
            char nm[160]={0};
            if(ntResolve(c,mid,nm,sizeof(nm),0,0)){
                const char* q=nm; while(*q && o+1<outSz) out[o++]=*q++;
            } else {
                char tok[16]; snprintf(tok,sizeof(tok),"$%u",mid);
                const char* q=tok; while(*q && o+1<outSz) out[o++]=*q++;
            }
            continue;
        }
        out[o++]=*p++;
    }
    out[o]=0;
}
