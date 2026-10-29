# uidialog_listen — UI 대화창 열림/닫힘 (Manmabot)

정본: `D:\extra_ui` / 10_5 uidialogmon (고정앵커 + 컨테이너 walk).
봇 DLL: `analysis/lc930/uidialog/uidialog_listen.dll`.
소비: `capture_tick` → `GameState.last_uidialog` (매 틱 poll).

**시전/클릭하지 않는다.** 열림 판정만 한다.

---

## 1. 감시 라벨 (registry)

| Label | 용도 |
|---|---|
| `NPCDialog` | NPC 대화 / 텔레포터 옵션 |
| `NPCShop` | 상점 Buy/Sell |
| `NPCStorage` | 창고 |
| `Inventory` | 인벤토리 창 (사냥 중 비의도 → Esc) |
| `TalkingScroll` | 말하는 두루마리 목록 |

JSON: `windows.{Label}: bool`, `open: [..]`, `n_open`, `src`=`cont`.

---

## 2. Discover / Poll (realtime)

| 단계 | 주기 | 동작 |
|---|---|---|
| **Discover** | `UIDLG_SCAN_MS` **2000** | UISubsystem 컨테이너 walk → 감시창 `inst` 갱신 |
| **Poll** | **매 틱** (`snapshot`) | 창당 헤더 1 read → OPEN/CLOSED |

- 앵커: `VFT_UISUBSYSTEM=0x1182C50` (실제 UISubsystem). RTTI 이름 폴백.
- 체인: `UIDLG_CONT=0x38:0x18,0x28:0x28`, `UIDLG_CONT_VAL=0x38`.
- 봇 DLL: 디스크 PID 캐시 없음. 런타임 BFS/힙 스캔 **안 함**.
- 빈 결과·전부 vft 사망 시 즉시 rediscover.
- 툴 `scan()`: 동일 컨테이너 walk; 실패 시에만 구 BFS+힙 진단.

Python: 매 `capture_tick`마다 `snapshot_fresh()` 동기 poll. buff와 별도 스레드.

---

## 3. 틱 / 게이트 / Esc

| 경로 | 동작 |
|---|---|
| `capture_tick` | poll 스냅샷 → `last_uidialog` |
| Esc dismiss | watched OPEN이면 Esc |
| OPEN 게이트 | 해당 라벨 OPEN까지 대기. 타임아웃 3초 |

헬퍼: `app/_05_action/uidialog_gate.py`.

---

## 4. 비용 (extra_ui 실측, 창 5)

| 항목 | reads | 시간 |
|---|---|---|
| Discover (cont) | ≈350 / 2s | ≈2 ms |
| Poll | 5 / 틱 | 헤더만 |
| 상시 합 | ≈200 reads/s | ≈4.4 ms/s |
