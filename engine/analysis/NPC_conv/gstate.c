/* gstate.c - unified realtime game-screen state (JSONL): open windows + player +
 * shop buy/sell + NPC dialog options (script, count, click rects). single process.
 * usage: gstate.exe [seconds]
 */
#define _CRT_SECURE_NO_WARNINGS
#include <windows.h>
#include <tlhelp32.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include "signeddrv_client.h"
static uint64_t g_pid=0,g_base=0; static uint32_t g_modSize=0;
static int rm(uint64_t a,void*b,uint32_t s){ uint32_t br=0; return SignedReadMemory(g_pid,a,b,s,&br)&&br==s; }
static uint64_t q64(uint64_t a){ uint64_t v=0; rm(a,&v,8); return v; }
static uint32_t d32(uint64_t a){ uint32_t v=0; rm(a,&v,4); return v; }
static float ff(uint64_t a){ float v=0; rm(a,&v,4); return v; }
static int inMod(uint64_t a){ return a>=g_base && a<g_base+(uint64_t)g_modSize; }
static int isHeap(uint64_t a){ return a>=0x10000000000ULL && a<0x80000000000ULL; }
static int getModule(uint64_t*base,uint32_t*size){
    uint64_t peb=0,ldr=0,head=0,cur=0;
    if(!SignedGetPeb(g_pid,&peb)||!peb)return 0;
    if(!rm(peb+0x18,&ldr,8)||!ldr)return 0;
    if(!rm(ldr+0x20,&head,8)||!head)return 0; cur=head;
    for(int g=0;g<5000&&cur&&cur!=(ldr+0x20);g++){
        uint64_t e=cur-0x10,db=0; uint32_t ds=0;
        if(rm(e+0x30,&db,8)&&db&&rm(e+0x40,&ds,4)&&ds){*base=db;*size=ds;return 1;}
        if(!rm(cur,&cur,8))break;
    } return 0;
}
static int classOfVft(uint64_t vft_va,char*out,int cap){
    out[0]=0; if(!inMod(vft_va)) return 0;
    uint64_t col=q64(vft_va-8);
    if(!inMod(col)){ if(col>0 && col<g_modSize) col=g_base+col; else return 0; }
    uint32_t td_rva=0; rm(col+0xC,&td_rva,4);
    uint64_t td=g_base+td_rva; if(!inMod(td)) return 0;
    char raw[512]; memset(raw,0,sizeof(raw)); if(!rm(td+0x10,raw,sizeof(raw)-1)) return 0;
    const char*p=raw; if(strncmp(p,".?AV",4)==0) p+=4;
    int n=0; while(*p && n<cap-1){ if(p[0]=='@'&&p[1]=='@') break; if(p[0]=='@'){ if(n<cap-2){out[n++]=':';out[n++]=':';} p++; } else out[n++]=*p++; }
    out[n]=0; return n>0;
}
static int readstr(uint64_t obj,char*out,int maxout){
    uint8_t b[0x20]; if(!rm(obj+0x1A8,b,0x20)){ out[0]=0; return 0; }
    uint64_t len=*(uint64_t*)(b+0x10);
    if(len==0||len>200){ out[0]=0; return 0; }
    if(len<=15){ int n=(int)len<maxout-1?(int)len:maxout-1; memcpy(out,b,n); out[n]=0; }
    else { uint64_t p=*(uint64_t*)b; if(!isHeap(p)){out[0]=0;return 0;} int n=(int)len<maxout-1?(int)len:maxout-1; if(!rm(p,out,n)){out[0]=0;return 0;} out[n]=0; }
    return 1;
}
#define HS 131072
static uint64_t h_k[HS]; static signed char h_r[HS];
static int isUiLayoutVft(uint64_t v){
    uint32_t i=(uint32_t)((v>>4)&(HS-1));
    for(int pr=0; pr<16; pr++){
        uint32_t j=(i+pr)&(HS-1);
        if(h_k[j]==0){ char nm[256]; int r=0;
            if(classOfVft(v,nm,sizeof(nm))){ int t=0; while(nm[t]&&nm[t]!=':'&&t<200) t++; int e=t;
                if(e>=12 && strncmp(nm+e-12,"LayoutPCImpl",12)==0 && strstr(nm,"ui::lineage")) r=1; }
            h_k[j]=v; h_r[j]=(signed char)(r?1:-1); return r; }
        if(h_k[j]==v) return h_r[j]>0;
    }
    return 0;
}
#define MAXW 256
static uint64_t w_obj[MAXW]; static uint32_t w_vft[MAXW]; static char w_cls[MAXW][96]; static int w_n=0;
static void discover(void){
    HANDLE hp=OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,FALSE,(DWORD)g_pid);
    if(!hp) return;
    MEMORY_BASIC_INFORMATION mbi; uint64_t a=0x10000000000ULL; uint8_t buf[0x1000];
    while(a<0x80000000000ULL){
        if(!VirtualQueryEx(hp,(LPCVOID)a,&mbi,sizeof(mbi))){ a+=0x100000; continue; }
        uint64_t base=(uint64_t)mbi.BaseAddress, sz=(uint64_t)mbi.RegionSize;
        if(mbi.State==MEM_COMMIT && sz>=0x1000 && sz<=0x10000000 && !(mbi.Protect&(PAGE_NOACCESS|PAGE_GUARD|PAGE_EXECUTE))){
            for(uint64_t off=0; off+8<=sz; off+=0x1000){
                if(!rm(base+off,buf,0x1000)) continue;
                for(int i=0;i<=0x1000-8;i+=8){
                    uint64_t q=*(uint64_t*)(buf+i);
                    if(!inMod(q)||!isUiLayoutVft(q)) continue;
                    uint32_t rva=(uint32_t)(q-g_base);
                    int seen=0; for(int k=0;k<w_n;k++) if(w_vft[k]==rva){ seen=1; break; }
                    if(seen) continue;
                    if(w_n<MAXW){ char nm[256]; classOfVft(q,nm,sizeof(nm));
                        char sh[96]; int t=0; while(nm[t]&&nm[t]!=':'&&t<95){ sh[t]=nm[t]; t++; } sh[t]=0;
                        int dup=0; for(int k=0;k<w_n;k++) if(strcmp(w_cls[k],sh)==0){ dup=1; break; }
                        if(dup) continue;
                        w_obj[w_n]=base+off+i; w_vft[w_n]=rva; strcpy(w_cls[w_n],sh); w_n++; }
                }
            }
        }
        a=base+sz; if(sz==0) a+=0x1000;
    }
    CloseHandle(hp);
}
static uint64_t findNode(uint64_t root,uint32_t tar,const char* want){
    static uint64_t q[20000]; int qh=0,qt=0; q[qt++]=root; int cnt=0;
    while(qh<qt && cnt<8000){
        uint64_t n=q[qh++]; cnt++;
        if(!inMod(q64(n))) continue;
        if((uint32_t)(q64(n)-g_base)==tar){ char nm[64]; if(readstr(n,nm,sizeof(nm))&&(!want||strcmp(nm,want)==0)) return n; }
        uint8_t ob[0x300]; if(!rm(n,ob,0x300)) continue;
        for(int o=0;o<0x300-8;o+=8){ uint64_t p=*(uint64_t*)(ob+o);
            if(!isHeap(p)||!inMod(q64(p))||p==n) continue;
            int dup=0; for(int i=0;i<qt;i++) if(q[i]==p){dup=1;break;}
            if(!dup && qt<20000) q[qt++]=p; }
    }
    return 0;
}
int main(int argc,char**argv){
    SetConsoleOutputCP(CP_UTF8);
    int seconds=argc>1?atoi(argv[1]):0;
    HANDLE snap=CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS,0); PROCESSENTRY32W pe; pe.dwSize=sizeof(pe); DWORD pid=0;
    if(Process32FirstW(snap,&pe)) do{ if(_wcsicmp(pe.szExeFile,L"LC.exe")==0){pid=pe.th32ProcessID;break;} }while(Process32NextW(snap,&pe));
    CloseHandle(snap); if(!pid){ printf("no LC.exe\n"); return 1; }
    if(!SignedOpen()){ printf("driver fail\n"); return 1; }
    SignedSetTarget(pid); g_pid=pid;
    if(!getModule(&g_base,&g_modSize)){ printf("module fail\n"); return 1; }
    fprintf(stderr,"gstate: discovering UI...\n"); fflush(stderr);
    discover();
    fprintf(stderr,"gstate: %d windows. JSONL on stdout.\n",w_n); fflush(stderr);
    DWORD t0=GetTickCount();
    for(;;){
        char js[8192]; int p=0;
        uint32_t px=0,py=0; rm(g_base+0x1668710,&px,4); rm(g_base+0x1668714,&py,4);
        p+=snprintf(js+p,sizeof(js)-p,"{\"t\":%u,\"player\":[%u,%u],\"open\":[",(unsigned)(GetTickCount()-t0),px,py);
        int first=1;
        for(int i=0;i<w_n;i++){ uint64_t o=w_obj[i]; if(!o) continue; if(!inMod(q64(o))||(uint32_t)(q64(o)-g_base)!=w_vft[i]){ w_obj[i]=0; continue;} if((d32(o+0x70)&0xFF)==1){ p+=snprintf(js+p,sizeof(js)-p,"%s\"%s\"",first?"":",",w_cls[i]); first=0; } }
        uint64_t mgr=q64(g_base+0x1668860), holder=q64(mgr+0xD0), subs=q64(holder+0x180), shop=q64(subs+16*36);
        uint64_t vb=q64(shop+0x40),ve=q64(shop+0x48),sb=q64(shop+0x58),se=q64(shop+0x60);
        long long bn=(vb&&ve&&ve>=vb)?(long long)((ve-vb)/0x90):0;
        long long sn=(sb&&se&&se>=sb)?(long long)((se-sb)/0x20):0;
        p+=snprintf(js+p,sizeof(js)-p,"],\"shop\":{\"buy\":%lld,\"sell\":%lld}",bn,sn);
        uint64_t dlg=0; for(int i=0;i<w_n;i++) if(strstr(w_cls[i],"NPCDialog")){ dlg=w_obj[i]; break; }
        int dv=dlg?(d32(dlg+0x70)&0xFF):0;
        p+=snprintf(js+p,sizeof(js)-p,",\"dialog\":{\"open\":%d,\"script\":%u,\"opts\":[",dv,dlg?d32(dlg+0xD8):0);
        int f2=1;
        if(dv){ uint64_t lv=findNode(dlg,0x12438F8u,"ListView");
            if(lv){ uint64_t vecb=q64(lv+0x340); uint64_t inner=isHeap(vecb)?q64(vecb):0;
                if(isHeap(inner)){ uint64_t rb=q64(inner+0x178),re=q64(inner+0x180);
                    int n=(isHeap(rb)&&isHeap(re)&&re>=rb)?(int)((re-rb)/8):0; if(n>64)n=64;
                    for(int i=0;i<n;i++){ uint64_t row=q64(rb+i*8); if(!isHeap(row)) continue;
                        float wx=ff(row+0xB0),wy=ff(row+0xB4),w=ff(row+0x6C),h=ff(row+0x70);
                        float x0=wx*0.625f,x1=(wx+w)*0.625f,y0=(960.0f-(wy+h))*0.625f,y1=(960.0f-wy)*0.625f;
                        p+=snprintf(js+p,sizeof(js)-p,"%s{\"i\":%d,\"click\":[%.1f,%.1f],\"rect\":[%.1f,%.1f,%.1f,%.1f]}",f2?"":",",i,(x0+x1)/2,(y0+y1)/2,x0,y0,x1,y1); f2=0; } } } }
        p+=snprintf(js+p,sizeof(js)-p,"]}}");
        printf("%s\n",js); fflush(stdout);
        if(seconds>0 && (int)(GetTickCount()-t0)>=seconds*1000) break;
        Sleep(500);
    }
    SignedClose(); return 0;
}
