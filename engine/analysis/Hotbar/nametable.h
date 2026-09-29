/* nametable.c/.h — LC.exe 정적 이름 테이블(메시지 테이블) 공유 리더
 *
 * T7 인벤토리에서 확정한 정적 이름 경로를 독립 모듈로 추출.
 * 핫바(T4) 아이템 슬롯의 "$NNN" 토큰 → 이름 해석에 재사용한다.
 *
 * 경로(힙 스캔 없음):
 *   anchor = *(BASE + MSG_ANCHOR_RVA)                 # 모듈 전역 슬롯
 *   idx    = FNV1a("1_<mid>") & MSG_BUCKET_MASK       # FNV-1a
 *   rec    = *(anchor + idx*MSG_BUCKET_STRIDE)
 *   while recMid(rec)!=mid: rec = *(rec+MSG_REC_NEXT)  # 버킷 체인
 *   name   = readSSO( *( *(rec+MSG_REC_NAME) + MSG_NAME_KR ) + MSG_NODE_TEXT )
 *
 * 모든 판독은 SignedReadMemory(호출측 제공). registry(inventory_offsets.txt)로 파라미터 로드.
 */
#ifndef NAMETABLE_H
#define NAMETABLE_H
#include <stdint.h>

typedef struct {
    uint64_t pid;
    uint64_t base;
    uint32_t modSize;
    /* registry 파라미터 */
    uint32_t anchorRva;
    uint32_t bucketStride, bucketMask;
    uint64_t fnvOffset, fnvPrime;
    uint32_t recNext, recName, recKey;
    uint32_t nameKR, nameTW, nodeLang, nodeText;
} NtCtx;

/* registry(inventory_offsets.txt)에서 파라미터 로드. 없으면 기본값 유지. */
void ntLoadRegistry(NtCtx* c, const char* path);

/* "1_<mid>" 이름 해석. 성공 1. out=KR(UTF-8), twOut(옵션)=TW. */
int  ntResolve(const NtCtx* c, uint32_t mid, char* out, int outSz, char* twOut, int twSz);

/* fmt 문자열("$NNN ...")에서 첫 토큰 mid 추출. 없으면 0. */
uint32_t ntTokenMid(const char* fmt);

/* fmt 전체를 이름으로 치환(토큰들을 이름으로 join). 예: "$189 ($117)" -> "우럭하이 방패 (오크의 망토)" */
void ntResolveFmt(const NtCtx* c, const char* fmt, char* out, int outSz);

#endif
