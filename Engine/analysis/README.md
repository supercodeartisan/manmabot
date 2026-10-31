# 10_16 — Lineage Classic 9.30 메모리 모니터링 모듈 모음 (정본 트리)

`10_16` 은 **개발 정본(dev tree)** 이고, `10_16/dist` 는 그 **바이트 단위 미러(배포본)** 다.
모든 도구는 **단일 상수출처** `registry/LC930_REGISTRY.txt` 를 읽어 동작하며, 코드에 오프셋을
하드코딩하지 않는다.

## 원칙 (Iron Rule)
1. **단일 진실 공급처**: `registry/LC930_REGISTRY.txt` (VER 30). 갱신은 이 파일만.
2. **고정앵커 + 고정체인**: 서브시스템은 vft(RTTI)로 식별, 이후 포인터 체인으로 접근.
3. **메모리 읽기 = `signeddrv.sys` MmCopy 뿐** (`SignedReadMemory` / `SignedReadFast`).
   `ReadProcessMemory` 등 금지. 4KB **페이지 캐시**(`lc_pgRead`)로 IOCTL 최소화.
4. **출력 양식·파일명 보존**. 신규 속성은 스키마에 키를 **추가**만 한다.
5. **문서 동반**: 모듈 추가 시 `src/<mod>/` + `bin/<mod>_930.exe` + `docs/<mod>.md` 3종 세트.

## 운영 모듈 (29종)

번호는 `docs/PROJECT_MASTER.md` §5.1 과 동일하다.

| # | 모듈 | exe | 기능 | 앵커 |
|---|---|---|---|---|
| 1 | `charread` | `charread_930.exe` | 캐릭터 정보(레벨·HP/MP·좌표), 트리플 난독화 해독 | `CharacterDataSubsystem` |
| 2 | `enttrack` | `enttrack_930.exe` | 엔티티 전수 텍스트/JSON | `ActorSubsystem` |
| 3 | `etview` | `etview_930.exe` | 엔티티 화면 오버레이 시각화 + **Door 개폐 현시** | 동일(출력만 다름) |
| 4 | `etview_own` | `etview_own_930.exe` | 내 소유 엔티티만 시각화 | 동일 |
| 5 | `buff` | `buff_930.exe` | 버프 목록 정본(이름·남은초) | `HudSlotDataSubsystem` + CHAIN A/B/C |
| 6 | `realtime_buff` | `realtime_buff_930.exe` | 버프 실시간 스냅샷 | `lbuff.h` |
| 7 | `inventory` | `inventory_930.exe` | 인벤토리 슬롯 | `InventorySubsystem` |
| 8 | `hotbar` | `hotbar_930.exe` | 핫바 24슬롯 | `HudSlotDataSubsystem` |
| 9 | `shop` | `shop_930.exe` | 상점 리스트 | `ShopSubsystem` |
| 10 | `map` | `map_930.exe` | 맵ID + 지역/하위지역명 | `MapSubsystem` + `region_table.tsv` |
| 11 | `lasthit` | `lasthit_930.exe` | 지상 아이템 획득 귀속(GUID 근접 + 막타) | 드롭 아이템 + ActionComponent |
| 12 | `party` | `party_1009.exe` | 파티 멤버·리더·GUID·HP/MP%·좌표 | `PartySubsystem` → `Party` |
| 13 | `realtime_party` | `realtime_party_1009.exe` | 파티 실시간 + 호출수/시간 계측 | 동일(`lparty.h`) |
| 14 | `uidialogmon` | `uidialogmon_930.exe` | UI 창 상태 감시(5분류) | `UISubsystem` |
| 15 | `storelist` | `storelist_930.exe` | 창고 목록 정본(맡기기 ctx 벡터 / 찾기 ctx map 트리) | `StorageSubsystem` |
| 16 | `storewin` | `storewin_930.exe` | **창고 창 상태 + 화면 표시목록 직접 읽기**(독립) | `UISubsystem` 컨테이너 walk |
| 17 | `winmon` | `winmon_930.exe` | **UI 창 텍스트 모니터**(채팅/통보문, 실시간 콘솔) | `UISubsystem` 컨테이너 walk |
| 18 | `doorwatch` | `doorwatch_930.exe` | **Door(문) 개폐 실시간 감시**(열림/닫힘 + 전이) | 엔티티 스냅샷 + `ActionComponent+0xE0` |
| 19 | `storage` | `storage_930.exe` | 창고 컨테이너 원시 읽기 | `StorageSubsystem` |
| 20 | `chat` | `chat_930.exe` | 채팅 수신 라인 | `ChatSubsystem` |
| 21 | `chatwin` | `chatwin_930.exe` | 채팅 라인 레코드 탐색 | `ChatData` |
| 22 | `bodyact` | `bodyact_930.exe` | 내 행동(body action)+명령 모니터 | `ActionComponent+0xC8` / ActorController |
| 23 | `bodyactview` | `bodyactview_930.exe` | 행동 막대인형 뷰어 | 동일 |
| 24 | `hchurn` | `hchurn_930.exe` | 이동 중 애니율 필드 추적(연구용) | H 체인 + 1차 자식 |
| 25 | `prerender` | `prerender_930.c` → `prerender_930.exe` | `AC+0xC8` 이전에 갱신되는 필드 경합 추적(연구용) | H+0x40 / PRES_B |
| 26 | `ask` | `ask_930.exe` | 현재 위치의 **지역명 즉시 질의**(후보 rect 전수 + 규칙별 예측) | `MapSubsystem` rect 테이블 |
| 27 | `chatmon` | `chatmon_930.exe` | **채팅창 실시간 모니터**(발신자+채널+본문 스트리밍) | `UISubsystem` → 창→resource→라인 풀 |
| 28 | `partyhud` | `partyhud_930.exe` | **HUD 파티 바 판독**(창/위젯 트리/슬롯 HP·MP, 1회 호출) | `UISubsystem` → `HudPartyInfoLayoutPCImpl` |
| 29 | `partycap` | `partycap_930.exe` | **게임 화면 캡처 + 파티 위젯 오버레이**(BMP) | etview 캡처 + `partyhud` 좌표 |

라이브러리: `src/api/` = `lcapi` 계열(모듈 內 엔진, exe 아님). `core/` = 공용(`lcore.h`, `lreg.h`, `lbuff.h` …).

## 최근 확정 결과 (요약)

- **Door 개폐 상태** = `ActionComponent+0xE0` (`0x1C`=열림 / `0x1D`=닫힘),
  (2026-10-29 클라 갱신: 상태 `+0xD8`→`+0xE0`, 동작 포인터 `+0xC0`→`+0xC8`)
  실시간 양방향 전이(`1D→1C→1D`)로 확정. etview 현시 = `open` / `close`.
  `not_permitted`(폐쇄)는 모델 ID 오해로 폐기(2026-10-30, `docs/DOOR_STATE.md` §0.1).
  → `docs/DOOR_STATE.md`
- **HUD 파티 바** = `HudPartyInfoLayoutPCImpl` vft `0x1294C80`. 창 `(26,281) 192x387`,
  슬롯 8개(guid/HP%/MP%) + 위젯 절대좌표(`+0xB0`). 화면 좌표는 GLView 스케일로 변환.
  → `docs/partyhud.md` · `docs/partycap.md`
- **IOCTL 불변 원칙**: 신규 속성은 "스냅샷이 이미 읽는 같은 4KB 페이지"에서 고르고
  스냅샷에서 1회만 읽어 캐시하면 출력 경로 IOCTL **0** (`bin/doormeasure_1018.exe` 실측).
  → `docs/READ_BATCHING.md`
- 창고 창 판정(맡기기/찾기)은 **표시목록 ↔ 가방 대조**(`storewin`), 찾기 정본은 ctx `std::map`.
  → `docs/storewin.md`, `docs/STORAGE_REVERSE_ENGINEERING.md`

## 빌드 / 검증

```
build_all.bat                     # 전 모듈+프로브 재빌드
tools/make_dist.ps1               # dist/ 재생성(미러 + MANIFEST + 해시 검증)
tools/check_dist.ps1              # dist == dev tree 대조(PASS/FAIL)
python tools/audit_dist.py        # 누락/불일치/고아 전수 감사
make_release.bat                  # 위 전체를 순서대로
```
- 실행 전제: `signeddrv`(WinNotify) RUNNING + `LC.exe` 실행 중.
- 출력물: `<exe>\out\*_out.txt` (모듈별 고정 경로).
- **드라이버 교체 시**: `tools/drv_restore.cmd` (관리자, 원본 `E:\…\signeddrv.sys` 로 복귀).

## 구조
`registry/ core/ src/ bin/ probes/ docs/ tools/ sample/ dungeon/ data/ dist/` + `build_*.bat`.
`dist/` 는 `make_dist.ps1` 이 만드는 **바이트 단위 미러**이며 `check_dist.ps1`/`audit_dist.py` 로 검증한다.
