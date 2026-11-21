# 차단 UIMessage 감지 설계 (Chat과 엄격 구분)

## 0. 결론
- 현재 화면의 차단 통보문은 **Chat이 아니라 UIMessage**.
- 저장 위치: **`CommonMessageSubsystem`** (subs[6], RTTI `CommonMessageSubsystem@ui@lineage`, live vft RVA `0x11E26A8`) **+0x28** 의 `std::string` (UTF-8).
- 현시 모듈: **`CommonMessagePopup`** (단일 ok 버튼 + ChatRichText), 긴 메시지는 `CommonBigMessagePopup`.

## 1. 앵커 / 구조 (이미 아는 것)
- **모든 상수는 registry `[SEC-20]`에 등록** (single source of truth):
  `CMS_VFT`, `CMS_SUB_INDEX`, `CMS_MSG_OFF`, `CMS_FLAG1_OFF`, `CMS_FLAG2_OFF`,
  `CMS_STR_PTR_OFF`, `CMS_STR_LEN_OFF`, `CMS_STR_CAP_OFF`, `CMS_PAGE_SIZE`,
  `CMS_POPUP_VFT`, `CMS_POPUP_BIG_VFT`, `CMS_POPUP_TEXT_OFF`,
  `SD_IOCTL_IMAGE_BASE`, `SD_IOCTL_READ`.
- `MGR=*(BASE+0x16EB6F0)` → `holder=*(mgr+0xD0)` → `subs=*(holder+0x180)`, stride `0x10`, 64개.
- `CommonMessageSubsystem` = subs[`CMS_SUB_INDEX`=6] (RTTI 클래스명으로도 검증).
- 메시지 std::string (MSVC):
  - `+0x28` = data ptr (SSO면 inline)
  - `+0x38` = size
  - `+0x40` = capacity
- 부가 필드(후보): `+0x18` = 1, `+0xC8` = `0x0000000100010101`.

## 2. Chat vs UIMessage — 엄격 구분
| 구분 | 저장소/모듈 | 오프셋 | 실제 예 |
|---|---|---|---|
| **Chat** | `ChatSubsystem`(vft `0x121C470`) / `HudChatLayoutPCImpl` / `ChatData` | `CHATDATA_MSG_OFF=0x18` | `***** 캐릭터는 또 다른 나입니다. *****` |
| **UIMessage** | `CommonMessageSubsystem`(vft `0x11E26A8`) | **`+0x28`** | **`운영자의 요청 또는 정책에 의해 게임 접속이 종료되었습니다.`** |

→ 차단 알림은 ChatData/HudChat 경로가 아니라 CommonMessage 경로에 있다.

## 3. 감지 루프 (핵심)
1. `subs[64]`에서 RTTI `CommonMessageSubsystem` 인스턴스 탐색 (또는 `lc_subsGet(0x11E26A8)`).
2. `+0x28` std::string 읽기:
   - `size = q64(obj+0x38)`, `cap = q64(obj+0x40)`, `ptr = q64(obj+0x28)`
   - `0 < size <= 0x400 && size <= cap <= 0x100000` 검증
   - `cap <= 0x10` → SSO(inline), 아니면 `ptr`에서 UTF-8 읽기
3. 텍스트 패턴 매칭: `운영자`, `정책`, `종료`, `차단`, `이용` 등.
4. 텍스트 변경/소거 시각 로그 + `+0x18`, `+0xC8` 변화 기록.
5. (선택) `UISubsystem` window list에서 `CommonMessagePopup` 존재/가시성 확인.

## 4. 현시 모듈 후보 (VFT/RTTI)
| 클래스 | live vft | 구성 | 용도 |
|---|---|---|---|
| `CommonMessagePopup` | `0x12779B0` | Button 1(+0xC8) + ChatRichText(+0xD0) | **단일 ok 모달 = 차단 통보문과 일치** |
| `CommonBigMessagePopup` | `0x1277760` | Button 3(+0xB8/0xC0/0xC8) + ChatRichText(+0xD0) | 긴/다중 버튼 메시지 |
| `NoticeLayout` | (미인스턴스) | - | 서버 공지 (UIDLG_WIN_Notice) |
| `ChatConfirmPanel` | - | HudChatLayoutPCImpl+0x150 | 채팅 확인 패널 |

## 5. 패킷 폴백 (가장 확실한 원문)
- `SC_MESSAGE_BOX` (vft `0x1227238`), `SC_MESSAGE_BOX_ALRAM_NOTI` (`0x12291E8`).
- `prsmsg`로 수신 opcode를 캡처해 차단 시점 opcode/payload 확보.

## 7. IOCTL 최소화 (적용 완료)
- **앵커 1회 확정 후 주소 캐시**: `lc_anchor()`가 subs[]를 캐시하므로 `lc_subsGet(0x11E26A8)`는 보통 **0 IOCTL**. 캐시 미스 시 subs 배열 1회 통읽기.
- **페이지 단위 벌크 읽기**: 샘플마다 서브시스템이 속한 `0x1000` 페이지를 **1 IOCTL**로 읽어 `+0x18/+0x28/+0x38/+0x40/+0xC8`을 동시 파싱.
- **변경 감지**: 문자열 헤더(ptr/size/cap)가 바뀔 때만 데이터 **+1 IOCTL**.
- 측정:
  | 모드 | IOCTL/샘플 |
  |---|---|
  | 기본(변경 감지) | **1** (변경 시 2) |
  | `-a` (매번 데이터) | 2 |
  | `-h` (헤더만) | 1 |
- 이전 버전(샘플마다 subs[64] RTTI 재스캔) 대비 **약 130~260배 감소**.
- **시작 비용 6 IOCTL** (고정앵커·고정체인):
  1. `0x222048 GET_IMAGE_BASE` → LC.exe base (1)
  2. `MGR = *(BASE+0x16EB6F0)` (1)
  3. `holder = *(MGR+0xD0)` (1)
  4. `subs = *(holder+0x180)` (1)
  5. `cms = *(subs+6*0x10)` (1)
  6. validate `*(cms) == BASE+0x11E26A8` (1)
  - 검증 실패 시에만 기존 subs[64] 스캔으로 폴백.
- 측정(2초, 8샘플): `startup_ioctl=6`, `total_ioctl=15`.

## 6. 구현물
- `probes/uimsg_1021.c` → `bin/uimsg_1021.exe`
- 사용: `uimsg_1021.exe [seconds]` (0이면 1회, >0이면 250ms 간격 감시)
- 검증 출력:
```
t=0 UIMessage size=83 cap=95 flags[+0x18]=0x1 [+0xC8]=0x100010101
     text="운영자의 요청 또는 정책에 의해 게임 접속이 종료되었습니다."
```
