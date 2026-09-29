# 던전 맵 파밍 — 구현 현황 보고서

- **기준일:** 2026-09-25
- **범위:** 현재 워크스페이스 코드만. 추측·기획은 반영하지 않음.
- **대상:** 던전 맵 스타일에서의 파밍, 아이템 획득, 회수, 상점, 사망, 이동. 섬 농장은 대조용으로만 적음.
- **한 줄:** 던전 **층 안에서** 싸우고 줍고 패트롤하는 루프는 연결되어 있다. 마을로 나가면 기란/TI로 착지하며, **입구 걷기 데이터가 없어 층 자동 재입장은 아직 없다.**
- **2026-09-25 이후:** 팩 id로 던전 판정, 허수아비 수련 제외, 던전 틱 사망 확인, 오프-층 전투 금지, 패트롤 오버레이 재적용, 기본 farms.yaml 미로드. 섬 틱은 그대로.

상태 표기:

| 상태 | 의미 |
| --- | --- |
| 연결됨 | 엔진 틱/파이프라인에서 실제로 동작 |
| 부분 | 일부만 동작하거나 착지·복귀가 어긋남 |
| UI만 | 저장·표시만 되고 엔진이 읽지 않음 |
| 깨짐 | 던전 세션에서 잘못된 맵으로 나가거나 재입장이 안 됨 |
| 없음 | 구현 없음 |

출처: `mode_ticks._tick_dungeon_farming`, `dungeon.py`, `patrol.py`, `combat_query.py`, `mode_actions.farm_loot_or_combat`, `talking_scroll.py`, `shop_trip.py`, `unstick.py`, `bot_controller.start_gates_ok` / `_worker`, `schedule_ui` 맵 탭.

`V1_IMPLEMENTATION_STATUS.md`의 “스케줄 Start TypeError”는 **현재 코드와 다르다.** `OperatorCoordinator.start(unattended=True)`는 인자를 받는다.

---

## 1. 요약

| 지표 | 내용 |
| --- | --- |
| 연결됨 | 패트롤, 4타일 홉, LOS 전투, 화면 줍기, HP 행동, 긴급 TP, 핫바 3버프 |
| 치명 구멍 | 상점·후퇴·막힘·부활 뒤 **선택 던전 층 재입장 없음** |
| 잘못 동작 | 레벨 1–4 허수아비 수련이 던전 틱에서도 TI로 나감 |
| UI만 | 포만 귀환, 보급 소진 마스터, Fix HP 귀환, 마법 개별 표 |

의도된 세션: **스케줄에서 던전 스타일 + 층 선택 → 패트롤 점 확인 → Start → 층 위 루프 → (위험/상점 시 마을) → 같은 층 복귀**. 마지막 복귀 단계가 없다.

---

## 2. 던전 모드가 켜지는 방식

### 2.1 판정

`is_dungeon_map()` (`engine/app/_04_decision/dungeon.py`)

- 인자가 없으면 `set_dungeon_mode_override` 값이 우선이다.
- 오버라이드가 없으면 활성 맵 팩 id/이름에 `dungeon`이 있으면 True.

`map_style_is_dungeon(map_id, map_style)` (`manmabot_v1/probes.py`)

- `map_style`가 비어 있지 않으면 `normalize_map_style == "dungeon"`만 본다.
- 비어 있으면 맵 id로 판정.

세션 시작 시 `bot_controller._worker`가 `profile.map_style`을 넘겨 `set_dungeon_mode_override(dungeon)`를 호출한다. 스케줄 Apply는 `map_style`과 농장 목록 비우기를 쓴다 (`task_runtime.apply_runtime_settings`).

### 2.2 주의

프로필 기본 `map_style`은 `"normal"`이다. 레거시 Setup 창(`main_window`)은 `map_style`을 쓰지 않는다. 거기서 던전 팩을 골라도 오버라이드가 False가 되면 **섬 틱**(농장 사각형·수색 홉)으로 들어가고, 농장이 없으면 Start가 `start_no_farms`로 막힐 수 있다.

**스케줄 콘솔**에서 던전 라디오를 켜고 Apply한 뒤 Start하는 경로가 정식이다.

---

## 3. 시작 → 종료

| 단계 | 동작 | 상태 |
| --- | --- | --- |
| 1. 맵 스타일 던전 + 층 선택 | 스케줄 맵 탭. 기란/글루디오/사막/개미굴 각 층. 농장 체크는 비활성 | 연결됨 |
| 2. 패트롤 점 확인 | userdata 오버레이 `patrol.yaml` 우선, 없으면 팩 YAML. 0개면 `start_no_patrol` | 연결됨 |
| 3. Start / 로그인 | 계정 필수. 게임·메모리 램프. 던전이면 `farm_areas` 제거 후 패트롤 로드 | 연결됨 |
| 4. 층 위 루프 | 아래 틱 순서. 몹/아이템 없으면 패트롤 순환 | 연결됨 |
| 5. 위험·회복 | 급감·PK·포위·HP 목록. 안전은 TI 두루마리 3곳 회전 | 부분 |
| 6. 상점 | 중량≥설정(기본 85%) 판매 → HP → 해독 → 화살. 던전에선 걸어가서 못 감 | 부분 |
| 7. 상점/후퇴 이후 | 기란/TI 텔레포터로 복귀 시도. 지형 PNG가 마을이면 “이미 사냥맵”으로 판정 | 깨짐 |
| 8. 사망 | 후퇴 틱에서만 HP=0 2초 후 부활 클릭. 파밍 중 시체는 힐이 먼저 먹을 수 있음 | 부분 |
| 9. Stop | 오버라이드 해제. 패트롤 인덱스는 다음 Start/스크롤 때 리셋 | 연결됨 |

시작 게이트 (`bot_controller.start_gates_ok`):

- 게임 창 RED → `start_no_game`
- 맵 팩 없음 → `map_missing`
- 던전 스타일이면 패트롤 필수, 아니면 `selected_farms` 필수
- 메모리 RED → `start_no_memory`

Stop 시 `set_dungeon_mode_override(None)`.

---

## 4. 한 틱 순서 (`_tick_dungeon_farming`)

위가 이긴다. 하나라도 행동을 내면 아래는 그 틱에 돌지 않는다.

| # | 단계 | 조건 | 결과 | 상태 |
| --- | --- | --- | --- | --- |
| 1 | 긴급 텔레포트 | PK 또는 포위 몹 수. 마스터 AND (유저 또는 둘러싼 수) | 스킬 텔레포트 | 연결됨 |
| 2 | Recovery HP | 사용자 순서. 급감(1히트 ≥20%) + 4×5 박스 몹이면 TP → 안전 → 세계수 | 힐·물약·후퇴 | 연결됨 |
| 3 | MP / 유휴 귀환 | 법사 MP 탈출은 런타임 OFF. Fix MP·유휴는 두루마리 | 후퇴 모드 | 부분 |
| 4 | 지원 스킬 → 버프 | 핫바 역할만 | 시전 | 연결됨 |
| 5 | 초보 허수아비 | 레벨 1–4면 TI 허수아비로 스크롤/이동 | 던전에서 나감 | 깨짐 |
| 6 | 상점 | 중량/물약/화살. 농장 타이머 없음 | 마을 두루마리 | 부분 |
| 7 | 줍기 / 전투 | 스티키 → 4×5 → 아이템 → 최근접. 구역 제한 없음 | 공격·PICKUP | 연결됨 |
| 8 | 패트롤 | 지점 없으면 IDLE. 있으면 4타일 홉 | TRAVELING | 연결됨 |

섬 틱(`tick_farming`)에만 있고 던전에서 **호출하지 않는 것:**

- `ensure_farm_tour`
- `_try_farm_upkeep` (농장 타이머, 빈 맵, 저수익, 근처 유저)
- `_enter_farm_if_needed`
- `_search_inside_farm` / `search_hop`

---

## 5. 기능별 현황

### 5.1 시작·모드

| 기능 | 상태 | 지금 | 고치거나 넣을 것 |
| --- | --- | --- | --- |
| 스케줄 맵 스타일 = 던전 | 연결됨 | Apply 시 `map_style=dungeon`, 농장 목록 비움 | 레거시 Setup은 `map_style`을 안 써서 섬으로 오판할 수 있음 |
| 패트롤 지점 게이트 | 연결됨 | overlay 우선, 없으면 팩 YAML | 0개면 `start_no_patrol` |
| 던전 틱 분기 | 연결됨 | override True면 `_tick_dungeon_farming` | 비어 있지 않은 `map_style`이 팩 id의 `dungeon` 문자보다 우선 |

### 5.2 이동·패트롤

| 기능 | 상태 | 지금 | 고치거나 넣을 것 |
| --- | --- | --- | --- |
| 패트롤 순환 | 연결됨 | 가까운 지점부터, 도착 체비쇼프 **2타일**, wrap | 지점이 2타일 안이면 중간점 건너뜀. UI 순서 변경 없음 |
| 한 클릭 홉 | 연결됨 | `DUNGEON_MAX_HOP_TILES = 4`. 전투·줍기 접근 포함 | 섬은 화면 평행사변형만 제한 |
| 농장 사각형 / 내부 수색 | 연결됨(미사용) | 던전 틱은 입장·search_hop 안 함 | nav이 기본 `farms.yaml`을 아직 로드할 수 있음. 틱은 안 씀 |
| 막힘 해제 | 부분 | 같은 칸 ~4.5초 → 반경 3 걷기 → 반경 2 소진 시 TP, 없으면 두루마리 | 두루마리 착지가 기란/TI. 던전 층이 아님 |

패트롤 로드: `patrol.load_patrol_waypoints_from_yaml` (걷기 가능 칸으로 반경 6 스냅). `ensure_patrol_index`는 가장 가까운 점부터. `begin_or_continue_patrol` → `purpose="patrol"`.

### 5.3 전투

| 기능 | 상태 | 지금 | 고치거나 넣을 것 |
| --- | --- | --- | --- |
| 스티키 + 4×5 + 화면 교전 | 연결됨 | `farm_loot_or_combat(restrict_to_farm=False)` | 약/강 구분 없음. 블랙리스트·잠든 골렘·레벨 5+ 허수아비 제외 |
| 직선 LOS | 연결됨 | 선분 위 벽이면 공격 불가. 옆칸(≤1)은 LOS 생략 | 섬은 A* 우회 가능 |
| 허수아비 수련 (레벨 1–4) | 깨짐 | 던전 틱 안에서도 TI 허수아비로 감 | 던전 세션에서는 이 분기를 빼야 함 |

전투 한 틱 우선순위 (`farm_loot_or_combat`):

1. 스티키 대상이 `print_state`에 살아 있으면 죽을 때까지
2. 가로 4 × 세로 5 칸 안 공격 가능 몹이면 줍기 중단
3. 화면 위 바닥 아이템
4. 화면 안 가장 가까운 공격 가능

법사는 주문 사거리 필터를 그대로 쓴다.

### 5.4 줍기

| 규칙 | 상태 | 메모 |
| --- | --- | --- |
| `all_items` / `adena_only` | 연결됨 | 프로필·스케줄 |
| 중량 ≥ 30% → 아데나만 | 연결됨 | `LOOT_ADENA_WEIGHT_RATIO` |
| 블랙/화이트 이름 | 연결됨 | 공식 item.json + ko/zh 별칭 |
| 화면 안만 선택 | 연결됨 | 거리 ≤ 2에서 PICKUP |
| 농장 안만 줍기 | UI만 | 라이브는 `restrict_to_farm=False` |

접근이 4.5초 막히면 이동과 같은 언스틱.

### 5.5 회복·탈출

| 기능 | 상태 | 지금 | 고치거나 넣을 것 |
| --- | --- | --- | --- |
| HP 행동 순서 | 연결됨 | 기본 힐 → 세계수 → 물약 → TP → 안전 | 던전 전용 임계 없음 |
| 급감 탈출 | 연결됨 | 한 샘플 낙폭 ≥ 20% + 근처 몹이면 TP → 안전 → 세계수 | 섬과 공유 |
| 긴급 TP (PK/포위) | 연결됨 | HP% 없음. 착지는 랜덤 TP | 던전 층 복귀 없음 |
| MP/유휴 두루마리 | 부분 | TI 마법서 / 허수아비 / 펫 회전. 랜덤 TP 금지 | 던전 층으로 돌아오는 행 없음 |
| Fix HP 귀환 | UI만 | Apply가 `return_hp`를 강제로 끔 | HP는 Recovery 목록으로만 |
| 포만 / 보급 소진 마스터 | UI만 | 저장만 | 연결하거나 UI에서 빼기 |

Recovery 기본 임계:

| # | 행동 | 기본 | 실제 |
| --- | --- | --- | --- |
| 1 | 힐 | ≤ 55% | 슬롯+마나. 실패하면 다음 |
| 2 | 세계수 | ≤ 30% | 엘프 + 슬롯 → 나무 → 마법서 상인 |
| 3 | 빨간 물약 | ≤ 55% | 아이템, 마나 게이트 없음 |
| 4 | 텔레포트 | ≤ 30% | 스킬 1회. 필요하면 안전으로 승격 |
| 5 | 안전지대 | ≤ 30% | 말하는 두루마리 (마법서 상인 → 허수아비 → 펫) |

해독제는 `ANTIDOTE_AUTO`가 켜져 있으면 HP보다 앞선다.

법사 MP 탈출(`_maybe_low_mp_to_safe`)은 이 워커에서 `mp.escape_enabled = False`라 **동작하지 않는다.**

### 5.6 상점·복귀

| 기능 | 상태 | 지금 | 고치거나 넣을 것 |
| --- | --- | --- | --- |
| 판매·물약·해독·화살 | 부분 | 두루마리로 마을 상점. 우선순위 중량 → HP → 해독 → 화살 | 주석의 “인벤 풀”은 거짓. `INVENTORY_FULL_RATIO`는 미사용 |
| 쇼핑 후 던전 재입장 | 깨짐 | `FARM_RETURN_SPOT_BY_MAP`는 `talking_island` / `mainland`만. 그 외(던전 id 포함)는 `giran_teleporter` | 던전 입구 두루마리 행 + `pack id == HUNT_MAP_ID` 비교 |
| 판매 NPC / 창고 / 수리 | UI만 | 엔진 미사용 | 기존 잡화·무기 정거장 큐만 |

`talking_scroll.py` 주석: `"Dungeon-exit / long-travel purposes land here later."` — 아직 없다.

`_maybe_scroll_to_hunt_map` / `player_on_selected_map`은 (a) 로드된 농장 사각형 안, 또는 (b) **현재** 지형 PNG ± 24타일이면 “이미 사냥맵”이다. 상점 후 지형이 TI/본토면 던전으로 다시 스크롤하지 않는다.

### 5.7 사망·버프·UI

| 기능 | 상태 | 지금 | 고치거나 넣을 것 |
| --- | --- | --- | --- |
| 부활 클릭 | 부분 | `tick_retreating`에서만 HP=0 2초 + 레벨 로드 | `tick_mode` 앞에서 처리. 부활 후 던전 복귀 없음(마법서 상인만) |
| 핫바 3역할 | 연결됨 | 방어 → 라이트(12분) → 힘. 힐/물약/TP/세계수 | 마법 개별 표는 UI만 |
| 패트롤 편집 | 연결됨 | 맵 탭에서 점 찍기, userdata overlay 저장 | 순서 변경·체류시간 없음. 스크롤 후 nav 리로드가 팩 YAML만 볼 수 있음 |

---

## 6. 섬 농장과 다른 점

| 항목 | 섬 (`tick_farming`) | 던전 (`_tick_dungeon_farming`) |
| --- | --- | --- |
| 이동 | 농장 사각형 입장 후 내부 수색 홉 | 패트롤 중점, 4타일 홉 |
| 농장 사각형 | 필수. 체류·로테 | 틱에서 미사용 |
| 구역 회전 | 빈 맵 / 저수익 / 근처 유저 | 스킵 |
| 공격 경로 | A* + slack 4 | 직선 LOS. 벽이면 불가 |
| 대상 필터 | 약한 몹 위주 | 화면 몬스터 전부(블랙·골렘 규칙만) |
| 상점 | 같은 `shop_trip`, 같은 맵이면 걸어갈 수도 있음 | 팩 ≠ 상점맵이라 걸을 수 없음 |
| 복귀 | TI/기란 텔레포터 → 농장 걷기 | 같은 텔레포터. **층 재입장 없음** |
| 도착 판정 | 체비쇼프 2타일 | 동일 |

---

## 7. 선적된 던전 맵

팩+userdata 양쪽에 `patrol.yaml`이 있는 층:

- `giran_dungeon_F1` … `F4`
- `gludio_dungeon_F1` … `F5`
- `desert_dungeon_F1` … `F4`
- `ant_cave_dungeon_F1_1` … `F1_8`

스케줄 던전 콤보는 `_FARM_MAP_IDS = {talking_island, mainland}`가 **아닌** 맵이다.

---

## 8. 손볼 것

### 수정

1. 레거시 Setup이 `map_style`을 안 쓰면 던전 팩도 섬 게이트(`start_no_farms`)로 막힌다. 팩 id에 `dungeon`이 있으면 스타일을 맞추거나, 스타일이 `"normal"`이어도 팩 id를 존중하게 한다.
2. 말하는 두루마리 후 nav 리로드가 **팩** `patrol.yaml`만 다시 읽어 userdata 오버레이가 빠질 수 있다. 오버레이를 다시 적용한다.
3. `player_on_selected_map`은 현재 지형 PNG가 아니라 **라이브 팩 id vs `HUNT_MAP_ID`**를 봐야 한다.
4. 던전 오버라이드가 켜져 있을 때 기본 섬 `farms.yaml`을 로드하지 않는다.

### 추가

1. 선택 던전 층으로 돌아가는 두루마리 행(또는 입구까지 걷기).
2. 사망 확인을 `tick_mode` 앞에서 처리하고, 부활 후 같은 층으로 복귀.
3. 던전 세션에서 `_tick_newbie_training`을 호출하지 않는다.

### 삭제·정리

1. 던전 틱 주석 “Inventory full → talking scroll” — 실제 조건은 중량·물약·화살 개수. `INVENTORY_FULL_RATIO`는 미사용.
2. 던전에서 농장 로테/체류/구역 회전 UI 의미 — 스케줄에서는 이미 비활성. 엔진 기본 농장 파일 로드만 남음.
3. 포만·보급 소진 마스터는 연결하거나 UI에서 뺀다.

### 의도대로 두면 되는 것

패트롤 루프, 4타일 홉, LOS 공격, 스티키/4×5/줍기 우선순위, 중량→아데나만, 급감 탈출 순서, 막힘 4.5초 쓸기, **이미 마을에 있을 때**의 상점 구매·판매.

---

## 9. 핵심 파일

| 영역 | 파일 |
| --- | --- |
| 던전 틱 | `engine/app/_04_decision/behaviors/mode_ticks.py` (`_tick_dungeon_farming`) |
| 모드·LOS·홉 | `engine/app/_04_decision/dungeon.py` |
| 패트롤 | `engine/app/_04_decision/patrol.py` |
| 전투 후보 | `engine/app/_04_decision/combat_query.py` |
| 줍기/전투 | `engine/app/_04_decision/behaviors/mode_actions.py` |
| 두루마리 | `engine/app/_04_decision/talking_scroll.py` |
| 상점 | `engine/app/_04_decision/behaviors/shop_trip.py` |
| 막힘 | `engine/app/_04_decision/behaviors/unstick.py` |
| Start/오버라이드 | `manmabot_v1/bot_controller.py` |
| 맵 UI | `manmabot_v1/ui/schedule_ui.py` |
| 패트롤 YAML | `engine/maps/<id>/patrol.yaml`, `userdata/maps/<id>/patrol.yaml` |

---

## 10. 입구 월드 좌표를 주면 자동화가 되나

**아닙니다.** 좌표는 재입장 구현의 재료입니다. 좌표를 파일에 넣기만 해서는 캐릭터가 들어가고 나오고 회복·파밍을 이어서 하지 않습니다.

### 좌표가 있으면 열 수 있는 단계

1. 마을(mainland / talking_island) 내비에서 입구 칸까지 걷기
2. 입구 위에 GATE/DOOR 커서가 뜰 때까지 조준한 뒤 클릭
3. 로딩 후 선택 층 팩을 다시 열고 패트롤 재개

지금 코드에는 1–3이 없습니다. 오프 층이면 `dungeon, off hunt floor`로 IDLE합니다. `cursors/gate.png`, `door.png`는 있지만 결정 틱이 쓰지 않습니다. 이동 클릭은 NORMAL 커서만 허용합니다.

### 좌표 외에 같이 적을 것

| 필드 | 이유 |
| --- | --- |
| overworld_map_id | 입구가 본토인지 말하는 섬인지 |
| dungeon_pack_id | 그 문이 어느 층으로 가는지 (F1 vs F3) |
| world_x, world_y | 게임 월드(~32xxx). 내비 타일 아님 |
| kind | gate / door / stairs |
| direction | enter / exit / floor_up / floor_down |
| dest_pack_id | 클릭 후 로드할 맵. 개미굴은 구역이 여럿 |

입구만이 아니라 **출구와 층 사이 계단**도 필요합니다. 기란 던전 입구만 주면 F2–F4와 개미굴 내부는 그대로입니다.

### 흐름별 구멍 (좌표 제공 후에도 구현이 필요)

| 흐름 | 이미 됨 | 구멍 |
| --- | --- | --- |
| Start, 이미 층 위 | 패트롤·LOS 전투·줍기·HP 순서 | 없음 |
| Start, 마을에 있음 | 던전 모드 판정 | 입구 워크+클릭 없음 |
| 회복 | 층 안 힐/물약/스킬 TP | 안전=TI 두루마리. 끝난 뒤 재입장 없음 |
| 상점 | 두루마리로 기란/TI | 끝난 뒤 텔레포터. 입구 워크 없음 |
| 막힘/부활 | 던전 틱 부활 클릭 | 스폰이 마을이면 같은 재입장 구멍 |
| 층 이동 | 선택한 한 층 패트롤 | 내부 계단 없음 |
| 퇴장 | 두루마리로 마을 | 계단으로 필드 퇴장 없음 |

두루마리 목록에는 던전 층이 없습니다. 글루디오·사막 입구는 기란 착지 후 본토 내비로 걸어야 합니다.

---

## 11. 참고

이 문서는 2026-09-25 코드 기준 던전 전용 보고서이다. 입구 좌표 표와 게이트 클릭이 들어가면 10절을 다시 맞춘다.

화면 요약: `canvases/dungeon-farming-status.canvas.tsx`, 입구 좌표 질문: `canvases/dungeon-entrance-coords-gaps.canvas.tsx`.
