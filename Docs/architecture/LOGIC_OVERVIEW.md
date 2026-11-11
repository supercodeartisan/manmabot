# 로직 개괄

기준: 2026-10-04 워크스페이스 코드. 파티 세션은 2026-11-10 정본을 따른다.
이 문서는 라이브 경로가 실제로 하는 일을 위에서 아래로 적는다.
9월 상태 문서·마스터 프롬프트·전투 설명서와 어긋나면 이 문서와 코드를 따른다.
파티가 켜진 세션은 이 개괄의 솔로 루틴이 아니다. 멤버는 `PartyMemberManager.decide`만 호출한다. 리더는 `PartyLeaderManager`가 스케줄과 랠리 대기를 준비한 뒤 솔로 열을 탄다. 정본은 [PARTY_RUNTIME.md](PARTY_RUNTIME.md), [PARTY_CODE_TO_ACTION.md](PARTY_CODE_TO_ACTION.md), [PARTY_EDGE_CASES.md](PARTY_EDGE_CASES.md).

상점과 월드 내비는 sticky `PlayerMode`다 (`SHOPPING`, `WORLD_NAV`). farming·traveling 열의 `shop.*` / `nav.world`는 진입 handoff다.

---

## 1. 제품이 하는 일

운영자가 스케줄에서 Start를 누르면, 계정이 있고 게임이 없으면 Purple 로그인을 시도하고, 게임이 있으면 그 세션에 붙는다. 붙은 뒤에는 워커 스레드가 한 틱에 행동 하나를 고른다.

한 세션의 목표는 루틴 행을 따라 사냥 맵에 도착하고, 그 맵에서 전투·줍기·회복을 반복하고, 무게나 소모품이 필요하면 상점에 다녀오고, 행의 분이 차면 다음 행으로 가는 것이다. 시간당 순아데나 회계는 마스터 프롬프트의 목표이고, 라이브 틱의 판단 기준은 아니다.

---

## 2. 모듈 의존

방향은 한 줄이다.

`UI → Engine → UserData / Drivers`

`Tools`는 실험용으로 Engine을 import할 수 있다. Engine은 UI를 import하지 않는다. `Research`는 라이브 import 경로에 없다.

```
run.py
  ├─ UI/ui                         스케줄 콘솔, 운영 코디네이터
  ├─ Engine/session                워커, 경로, 프로브, 드라이버, 핫키
  ├─ Engine/settings               UserData 읽기/쓰기, 태스크→프로필
  ├─ Engine/login → autologin      Purple/게임 로그인 제품
  ├─ Engine/app                    센서 → 월드(채우기) → _02_state → 의사결정 → 행동
  │    └─ _06_party                파티 리더 스케줄, 멤버 decide, 초대, 보급
  ├─ Engine/shop                   상점 YAML 실행 (구매·판매 창)
  ├─ Engine/hotbar                 핫바 스캔·아이콘 매칭
  └─ Engine/i18n                   문자열·표시 이름
```

`Engine/config/*.yaml`은 기본 상수다. Start 때 프로필이 그 위를 덮는다. `Engine/data`는 맵 팩·커서·월드 그래프·카탈로그. `Engine/analysis`는 메모리 DLL과 오프셋. `Engine/manmabot_v1`은 import하면 에러를 내는 껍데기다.

### 프로세스 경계

| 주체 | 스레드 | 하는 일 |
| --- | --- | --- |
| `schedule_ui` | UI | 설정 편집, Start/Stop 버튼 |
| `OperatorCoordinator` | UI + arming 스레드 | 로그인 준비, 그다음 `BotController.start` |
| `BotController` | 워커 `manmabot-v1-worker` | 캡처, 메모리, decide, act |
| `AutoLoginService` | arming 안에서 | Purple/게임 로그인 자식 |
| 게이트 클릭 | 워커 `execute` | Intent `GATE` → `ActionExecutor._gate` → `result` → `apply_gate_result` |

UI 스레드는 워커를 join하지 않는다. Stop은 이벤트를 세우고 돌아간다.

---

## 3. 세션이 시작되기까지

`OperatorCoordinator.start(unattended=False)`:

1. 이미 arming이거나 워커가 STOPPED가 아니면 무시한다.
2. 계정이 없고 게임 창도 없으면 `account_required`.
3. arming 스레드가 이전 워커 종료를 최대 12초 기다린다.
4. `prepare_session`: 게임이 없으면 `AutoLoginService.run`, 있으면 생략. 메모리는 `ensure_monitor_connected` (SignedDriver 포함).
5. 준비되면 `BotController.start(profile, unattended=)`.

`unattended=True`이면 콘솔이 포커스를 가져도 시작한다. 실행 중 게임 창이 포커스를 잃거나 최소화되면 자동 일시정지하고, 게임이 다시 포커스되면 재개한다.

워커 `_run_bot_loop` 준비 순서:

1. YAML을 읽고 프로필로 decision/navigation을 덮는다.
2. 종족 필터, 농장 사각형 또는 던전 패트롤, 루팅 이름 필터.
3. `GameState`, `DecisionManager`, 루틴 커서를 만들고 `request_world_nav(..., "start")`.
4. `PerceptionSensors`가 모니터·`print_state`·가방·핫바·버프·uidialog·공격자·경합 몹 핸들을 연다. 첫 `capture` → `apply_perception_buffer`로 `GameState`를 채운다.
5. `ActionExecutor`, 입력 캡처(클릭 경계용).
6. 핫바 F1–F3 스캔. 실패하면 워커를 멈춘다.
7. 루프. 첫 틱은 월드 칸과 MapSubsystem mapId가 준비될 때까지 최대 2.5초 기다린다. mapId 0(말하는 섬)은 유효하다. 모니터가 없으면 mapId 대기는 건너뛴다.

---

## 4. 설정이 틱에 닿는 경로

```
UserData (schedules, accounts, profile)
  → settings.schedule / accounts / profile
  → settings.task_runtime.apply_runtime_settings   태스크 → Profile
  → BotController가 decision YAML 딕셔너리를 덮어씀
  → configure_decision / configure_action / configure_navigation
  → player_mode 모듈 전역, nav_config, spell_box, shop 수량
```

`configure_decision`은 HP 비율, 농장 시간, 상점 수량, 전투 지터를 `player_mode` 같은 모듈 전역에 쓴다. 틱은 프로필 객체를 다시 읽지 않고 그 전역과 블랙보드를 본다.

UI에만 있고 이 경로에 없는 항목은 틱을 바꾸지 않는다. 헌트 공격 방식·카이팅, 마법 탭의 개별 스킬 표, 포만, 창고, `sell_npc` 선택이 그쪽이다. 판매 실행 자체는 연결되어 있다. 고르는 것은 YAML behavior id이다.

---

## 5. 한 틱의 데이터

워커 루프 body. 일시정지·최소화·창 없음·커서 마비·출발 대기는 decide 전에 빠진다.

```
창 클라이언트 사각형 + 4:3 클릭 경계 (픽셀 복사 없음)
  → PerceptionSensors.capture_tick → PerceptionBuffer (부분 필드 OK)
       매 틱: player / print_state / attacks_me / contested / buff / uidialog
       가방: force 이벤트만 스캔 시작; hotbar ~1s
  → apply_perception_buffer → _02_state.GameState (ok 필드만)
  → live mapId가 있으면 ensure_navigation_for_live_map_id
  → DecisionManager.decide → ActionIntent 하나 (+ `side_intents` 물약 병행)
  → 게이트 대기 중 mapId는 sensors.pull_player() (틱 버퍼와 별도)
  → ActionExecutor.execute(primary, side_intents=…)
```

읽기는 전부 `_01_perception` (주기·on-demand). 상점 루프는 `capture_shop()`, 핫바 스캔은 `capture_hotbar()`. uidialog OPEN 게이트/Esc는 `uidialog_gate`가 `capture_uidialog()`를 폴링한다. session/shop/hotbar/world_nav는 리더를 직접 부르지 않는다. 월드는 버퍼→state 변환만.

mapId는 MapSubsystem 경로만 진실이다. `player.mapId`가 0이어도 말하는 섬일 수 있다. 미발견과 0을 구분하는 플래그가 DLL에 있다. 월드 AABB로 mapId를 단정하지 않는다. 팩 맞춤은 mapId 다음이다.

---

## 6. 월드 모델

`GameState`는 틱 사이의 세계이다. 의사결정은 인식 프레임을 직접 보지 않고 이 객체를 본다.

| 필드 | 출처 | 쓰는 곳 |
| --- | --- | --- |
| `player` HP/MP/레벨/무게 | 모니터, 이어서 print_state가 HP를 덮음 | 회복, 사망, 상점 무게 |
| `player.inventory` | inventory_listen, 수 초 간격 | 물약·화살·해독 needs |
| `last_print_entities` | print_state | 몹·바닥 아이템 칸, 클릭 |
| `last_attacks_me` | attacks_me.dll | 나를 치는 몹 강제 교전 |
| `last_contested_mobs` | contested_mobs.dll | 다른 플레이어가 친 몹 |
| `player.buffs` | buff_listen (구조 지문 재스캔) | `due_buff` 재시전 (remain/없음). 실패 시 타이머 폴백 |
| `last_buff` | 같은 JSON | 디버그 (`rescanned`/`reason`) |
| `last_uidialog` | uidialog_listen | 비의도 OPEN → Esc; 상점/스크롤 OPEN 게이트(3s) |
| `last_hotbar` | hotbar_listen | 슬롯 역할, 수량 0이면 건너뜀 |
| `last_memory_snapshot` | 모니터 | mapId, 좌표 |
| 오브젝트 딕셔너리 | 엔티티 행을 perception 객체로 합침 | 전투·루팅 쿼리 |

로컬 플레이어는 감지된 PLAYER 박스에서 만들지 않는다. 전투 영역 앵커와 메모리 바이탈이다.

`Blackboard`는 의사결정 기억이다. 틱마다 지우지 않는다. 모드, 목표, 스티키 대상, 루팅 대상, 이동 목적, 농장 인덱스, `scratch` 딕셔너리(상점 트립, 월드 내비 세션, 루틴 커서, 후퇴 이유)가 여기 있다.

`ActionIntent`는 이번 틱의 출력이다. `ActionType`과 이유, 목표 칸, 우선순위. 모드와 별개다. 모드가 `farming`이어도 의도는 `ATTACK`이나 `USE_TALKING_SCROLL`일 수 있다.

---

## 7. 의사결정의 뼈대

계층(모드 vs 사다리 vs emit vs query)의 정본은 [`DECISION_HIERARCHY.md`](DECISION_HIERARCHY.md)다. 아래는 틱 동작 요약이다.

`DecisionManager.decide`:

1. 틱 카운트, 라이브 핫바를 scratch에 넣음.
2. 농장 체류 샘플, 잠든 골렘 위험.
3. 공격 블랙리스트 프로브(`evaluate_attack_probes`)는 호출하지 않는다.
4. `tick_mode`를 최대 3번. 의도가 생기면 멈춘다. 도착 직후 같은 틱에 사냥으로 넘어가는 용도다.
5. 의도가 없으면 `IDLE`.

`tick_mode`는 모드 분기보다 먼저 두 가지를 본다.

- 사망 확정(HP 0이 2초, 레벨이 읽힘) → `RESPAWN`.
- 레벨이 오르면 `DISMISS_LEVEL_UP` (Esc 두 번).

그다음 모드 하나.

| 모드 | 틱 | 하는 일 |
| --- | --- | --- |
| `retreating` | `tick_retreating` | 전투 없이 회복·두루마리·안전 걷기 |
| `traveling` | `tick_traveling` | 같은 맵 걷기. 농장 입장, 다음 농장, 패트롤, 상점까지 걷기, 안전지대 |
| `farming` | `tick_farming` | 섬이면 수색, 던전이면 패트롤. 상점·월드 내비가 앞에 끼어 듦 |

던전 여부는 `is_dungeon_map()`이다. `tick_farming`이 참이면 `_tick_dungeon_farming`으로 넘어간다. 별도 모드가 아니다.

### 섬 사냥 틱 — 먼저 성립한 것이 틱을 가져감

1. 사망.
2. 긴급 텔레포트 카드. 기본 꺼짐. 켜져 있으면 플레이어 감지 또는 포위. HP 퍼센트와 무관. 던전 틱은 이 단계를 호출하지 않는다.
3. `apply_hp_actions`. 후퇴가 시작되면 같은 틱에 `tick_retreating`.
4. 법사 MP 부족 → 후퇴. 요정은 이 경로가 없다.
5. 바이탈 귀환, 유휴 귀환.
6. `_shop_before_world_nav`. 상점이 필요하고 월드 내비 세션이 있으면 세션을 지우고 `after_shop`으로 다시 요청.
7. `_maybe_world_nav`. 세션이 걷고 있으면 전투·루팅이 홉만 대체할 수 있다. 두루마리·게이트·mapId·체류 시간은 그 전에 `tick_world_nav`가 돈다. 휴식 행은 여기서 IDLE.
8. 지원 스킬, 버프 (`armor_up` → `power_up`; **`light` 미사용**).
   지금은 `buff_last_cast` reuse 시계(메모리 버프 id 표 없음).
   이후 “없으면 시전” 전환 준비: [`BUFF_STATUS_CATALOG.md`](BUFF_STATUS_CATALOG.md).
9. 갇힘 탈출(섬만, 13초·5타일). 던전은 끄고 막힘/유휴 넛지를 쓴다.
10. 초보 허수아비(레벨 1–4).
11. 사망 후 마법서 상인.
12. 농장 시간·구역 순환 → `traveling`.
13. 상점 후 사냥터 복귀 요청.
14. 선택 맵이 아니면 월드 내비 요청.
15. `farm_loot_or_combat` (농장 사각형 밖이어도).
16. 농장 밖이면 입장 이동. 루팅이 입장보다 앞일 수 있다.
17. 농장 안 수색 홉.

던전은 1–7과 버프까지 같고, 그다음 막힘 스텝, 전투·루팅, 유휴 넛지, 패트롤 지점으로 `traveling`이다. 지점이 없으면 IDLE. 긴급 텔레포트와 갇힘 탈출은 없다. 선택 층이 아니면 수색하지 않고 IDLE.

### 이동 틱

사망, 긴급 텔레포트, HP, 법사 MP, 바이탈 귀환, 지원·버프, 갇힘, 그다음 상점. 상점이 두루마리·걷기를 시작하면 이번 틱은 상점이다. 이미 `PURPOSE_SHOP`으로 걷는 중이면 상점 틱은 None을 반환하고 아래 홉이 걷는다.

농장 입장·다음 농장·패트롤 목적이면 맵이 다를 때 월드 내비를 끼우고, 이어서 전투·루팅을 허용한다. 그 외 목적의 걷기는 교전하지 않는다.

도착하면 `complete_travel_arrival`이 목적에 따라 다음 패트롤 지점을 잡거나 `farming`으로 돌린다. `PURPOSE_SHOP`은 별도 분기가 없어 도착 처리가 `farming`으로 떨어진다. 상점 창은 scratch의 `shop_trip`이 다음 틱에 다시 연다.

홉이 실패하고 도착도 아니면 이동을 포기하고 `farming`으로 돌린다.

### 후퇴 틱

사망 화면이면 리스폰 클릭만. 부활하면 `arm_post_respawn_retreat`로 바로 `RETREATING`(farming 아님). 마더트리 가능 시 세계수 시전 → 회복 → 마법서 상인 두루마리; 아니면 마법서 스크롤/세이프에서 회복. 회복 조건이 되면 `finish_retreat`.

`finish_retreat`는 리스폰 후퇴면 `begin_world_nav("post_respawn")`. 이동 stash가 있고 복귀 모드가 `traveling`이면 그 걷기를 복원한다. 던전이거나 농장 밖이면 `begin_world_nav("post_retreat")` 하고 `farming`으로 둔다. `begin_retreat`는 들어갈 때 월드 내비 세션을 지운다. 루틴 커서는 남긴다.

후퇴 중에는 전투하지 않는다. 적이 없으면 루팅만 한다. 힐은 `apply_inplace_hp_support`. 물약은 `side_intents`.

---

## 8. HP

입구는 `apply_hp_actions`. 후퇴 중이면 곧바로 `apply_inplace_hp_support`.

HP가 0이면 아무것도 하지 않는다. 사망 처리가 이미 끝냈다. 독 자동은 기본 꺼짐.

독점 사다리의 기본은 힐 → 세계수 → 텔레포트 → 안전지대. 한 줄이 실행되면 주 Intent가 끝난다. HP/MP/해독 물약은 사다리에서 빼서 `arm_potion_side_intents`가 `blackboard.side_intents`에 올린다(새 ActionType 없음). Action은 주 Intent가 마우스 클릭이면 물약 키를 별도 스레드로 겹쳐 보내고(틱 내 직렬 금지), 키보드 프레스면 물약 키를 먼저 누른다.

급감(짧은 시간에 HP가 크게 떨어지고 근처 몹이 있거나 이미 교전 중)이면 힐·물약을 건너뛰고 텔레포트 → 세계수 → 안전 두루마리만 본다. 던전 급감은 안전 두루마리를 빼서 텔레포트 → 세계수이다.

던전은 이 함수 앞에서 `dungeon_policy`의 트리/상점 조기 분기가 있다. 5% 텔레포트 계단은 쓰지 않는다.

힐·텔레포트는 현재 MP가 20 미만이면 나가지 않는다. 물약이 없고 HP가 텔레포트 기준 이하면 텔레포트는 한 번. 그 실패는 세계수, 세계수가 불가능하면 상점이다. `is_low_level_hp_mode`는 항상 거짓을 반환한다. 레벨로 힐·물약을 막지 않는다. `LOW_LEVEL_HP_CAP`과 “15 미만이면 필드에서 힐 금지” 주석은 파일에 남아 있다.

후퇴를 시작하는 함수는 `begin_retreat`이다. 섬·던전·루팅이 공유한다. 말하는 두루마리가 있으면 랜덤 텔레포트 대신 목록 NPC로 간다. HP 안전은 허수아비 수련장, 그 외 귀환은 마법서 상인·허수아비·펫 관리인을 돌린다. 요정 세계수는 텔레포트 대신 나무.

---

## 9. 전투와 루팅

입구는 `farm_loot_or_combat`. 농장 안만 줍기 플래그는 호출부가 `restrict_to_farm=False`이다.

1. 살아있는 스티키 대상이 있으면 그것만. 같은 종·칸으로 다시 묶고, 사라지면 잠금을 푼다.
2. `attacks_me`로 나를 치는 몹이 있으면 블랙리스트를 넘어 강제 교전. 죽을 때까지 스티키. 접근 루팅(`SEARCHING`)은 기다린다. 다만 이미 줍기 거리인 아이템은 `arm_loot_side_intent`가 `side_intents`에 `PICKUP`을 올려 Action이 주 Intent(전투 등) **전에** F4한다.
3. 화면 안(또는 메모리상 가까운) 바닥 아이템이 주 Intent로 이길 때. 아데나 우선. 무게가 문턱 이상이면 아데나만. 접근은 루팅이 주 Intent일 때만.
4. 직전 루팅 커서 실패면 공격 가능 몹으로 양보.
5. 줍기 직후 그 더미가 메모리에 남아 있으면 다시 클릭하거나 걸어간다.
6. 화면 안 가장 가까운 공격 가능 몹.

섬 대상은 플레이어 레벨 이하. 레벨을 모르는 몹은 강적. 골렘은 최소 레벨과 거리. 레벨 5 이상은 허수아비를 치지 않는다. 던전은 화면에 잡힌 몹을 약한/강으로 나누지 않는다. 블랙리스트, 잠든 골렘, 레벨 미달은 뺀다. 던전 공격은 벽이 있으면 LOS가 없고, 옆칸은 LOS를 생략한다.

의사결정은 `ATTACK`과 `target_id`만 낸다. 클래스별 입력은 행동 층이다.

| 클래스 | 전략 | 입력 |
| --- | --- | --- |
| 요정 | `ElfCombatStrategy` | 기사와 같은 간격 좌클릭. 무빙샷 전용 분기는 없다 |
| 기사 | `KnightCombatStrategy` | 홀드가 아닌 간격 클릭 |
| 군주 | `RoyalCombatStrategy` | 기사와 동일 |
| 법사 | `MageCombatStrategy` | 스킬 키 후 클릭, 사거리·시전 간격 |

커서 순서는 엔티티 UV, 메모리 칸, 0.2타일 8점, 픽셀 링. 템플릿이 없으면 실패로 닫는다. 실패를 보고 대상을 버리는 프로브는 `decide`에 연결되어 있지 않다.

---

## 10. 상점

필요 판정은 `choose_shopping_behavior`. 이미 트립 중이면 그 behavior id를 유지한다.

우선순위: 과중량 판매 → HP 물약(아데나가 가격 미만이면 요구를 끔) → 해독 → 화살(은화살 또는 일반, 둘 다 켜면 은화살을 끈다).

`tick_shop_trip`은 세 단계다.

1. 판매대 월드 좌표에 있으면 창을 연다. `SHOP_STOP` 다음 `SHOP_RUN`(Intent: `shop_behavior_id` / `shop_kind` / `shop_qty` / `shop_equip` / `shop_use_recover`). 실행은 `shop.runtime.execute_shop_intent` 한 곳.
2. 두루마리를 썼으면 착지를 기다린다. 타임아웃이면 재시도 또는 중단.
3. 걸을 수 있으면 `begin_travel(..., purpose=PURPOSE_SHOP)`으로 `traveling`에 맡긴다.

판매 실행은 같은 스크롤 페이지를 고른 뒤 confirm 한 번, 창이 닫히면 다시 열어 목록이 빌 때까지이다. 판매 뒤 보관 목록 밖이 남으면 `give_goods`를 한 번 더 한다. 판매 NPC를 UI에서 고르는 기능과 창고는 이 경로에 없다.

가방 스캔은 느리다. 상점 직후 워커가 가방을 한 번 강제 폴링한다. needs_*는 그 스냅샷 기준으로 늦게 떨어질 수 있다.

상점 트립 중에는 `shopping_blocks_teleport`가 갇힘 탈출과 일부 텔레포트를 막는다. HP 후퇴(나무·텔레포트·안전)는 상점 중에도 허용한다.

---

## 11. 월드 내비

루틴은 스케줄 행의 목록이다. `RoutineCursor`가 인덱스를 가진다. 각 행은 맵, 종류(`battle` / `break`), 체류 분이다.

`tick_world_nav`:

- 세션이 실패면 다음 행으로 건너뛴다. 한 바퀴가 전부 실패면 scratch에 정지를 올리고, 워커가 Stop한다.
- 세션이 끝나면 도착 처리로 그 행의 팩·농장·던전 플래그를 적용한다. 무장 시점에는 적용하지 않는다. 출발 맵 지형을 목적지 팩으로 바꾸지 않기 위해서다.
- 걷고 있거나 스크롤·게이트 중이어도 행의 분이 차면 다음 행을 집는다. 전투가 걷기 홉을 가져가도 시계는 이 함수 안에서 먼저 돈다.
- 요청만 있고 세션이 없으면 `arm_world_nav`.

플래너 스텝은 세 종류다. `walk`, `talking_scroll`, `map_transition`.

세션 phase: `ready` → `walk` 또는 `scroll` 또는 `gate_approach` → `gate_click` → 다시 `ready`, 끝나면 `done`, 막히면 `fail`.

걷기 전에 현재 칸이 비가보면 2타일 안 가보 칸으로 시작점을 당긴다. 전환점 목표도 2타일 스냅이다. 이미 2타일 안이면 실패가 아니라 도착이다. 게이트 성공은 mapId와 착지 xy(±24)가 둘 다 맞을 때다. mapId만 먼저 바뀌면 짧은 시간 기다린다.

게이트 클릭은 decide가 Intent `GATE`를 내고, 워커 `ActionExecutor._gate`가 커서 링·클릭을 한 뒤 `ActionResult`로 착지를 돌려준다. 프로브 중에는 캐시 좌표만 읽고, 클릭 뒤에만 pull-now 스냅샷으로 착지를 본다. `snapshot(fresh=True)`의 discoverNow는 워커를 오래 막아서 쓰지 않는다.

맵이 바뀌는 틱에는 `ensure_navigation_for_live_map_id`가 팩을 동기로 맞춘다. 프로필에 던전 팩이 남은 채 말하는 섬 칸으로 A* 하면 origin이 음수로 나가 경로가 없다.

---

## 12. 같은 맵의 이동

`traveling`과 수색 홉은 현재 팩의 nav.png와 A*다. 월드 내비의 그래프(맵 사이)와 다르다.

- 농장 입장·순환: 사각형 안쪽 가보 칸, 도착 판정 체비쇼프 2타일. 가장자리에서 도착으로 오판하면 더 안쪽으로 다시 잡는다.
- 수색: 농장 안 홉. 실패하면 나선형 폴백.
- 던전 패트롤: 가까운 지점부터, 홉은 최대 4타일, 도착하면 다음 지점.
- 같은 칸에 오래 머물면 작은 보폭, 더 오래면 텔레포트 언스틱. 상점 트립 중에는 막는다.
- 계층 경로 `hierarchical_path`는 맵 전환 직후처럼 시작·목표가 비가보일 때 둘 다 2타일 스냅한다.

---

## 13. 행동 층

`ActionExecutor.execute`는 주 Intent와 선택적 `side_intents`(물약)를 입력으로 바꾼다. 창 경계가 없으면 클릭하지 않는다. 틱 결과는 `executor.result` (`ActionResult`: shop/gate)로만 되돌린다.

전투·루팅이 아니면 종류별로 `_idle`, `_search`, `_travel`, `_heal`, `_teleport`, `_buff`, 두루마리, `GATE`, `_shop_run`, 리스폰, 레벨업 닫기. 물약(`USE_HP_POTION`/`USE_MP_POTION`/`USE_DEPOISON`)은 주로 `side_intents`로 병행한다. 상점 qty·shop_land_wait·`mid_act`는 Intent가 싣는다. Action은 `mid_act`를 읽기만 한다(뒤집지 않음). 전투와 루팅은 매 틱 전략이 돈다.

상점·두루마리·텔레포트·세계수·리스폰·레벨업 닫기 중에는 떠 있는 창을 Esc로 걷어차지 않는다. 그 외 행동에서는 3–5초 간격으로 Esc를 넣을 수 있다.

커서는 Interception. 일시정지·최소화·커서 마비·종료 때 버튼을 뗀다. 마비 중에는 decide와 act를 건너뛴다.

---

## 14. 로그인·메모리·입력

로그인 제품은 `Engine/autologin`이다. `Engine/login/autologin_service.py`가 요청을 만들고 자식 프로세스를 기다린다. 단계의 뼈대는 사전점검, Purple 창, 자격, Start Game, 포커스, 게임 로그인(동의·서버·캐릭터), deviceTag, 완료이다. 계정의 서버·슬롯이 요청에 들어간다. 스케줄 행이 계정 저장값과 다른 서버·슬롯을 덮는지는 `apply_runtime_settings`가 계정 저장을 바꾸는지에 달려 있고, 로그인 요청은 `AccountStore`의 선택 계정을 읽는다.

메모리 읽기는 워커 프로세스 안 DLL이다. 별도 모니터 콘솔이 아니다. SignedDriver 서비스는 `session.monitor_launch`가 `Drivers/SignedDriver/load_signeddrv.ps1`로 올린다. 입력은 Interception.

---

## 15. 여러 모드가 한 함수를 쓰는 곳

이곳을 고치면 섬, 던전, 걷기, 루팅이 같이 바뀐다.

| 함수 | 누가 호출하나 | 같이 바뀌는 것 |
| --- | --- | --- |
| `apply_hp_actions` | 사냥, 던전, 이동 | 회복 순서, 급감, 던전 조기 분기 |
| `apply_inplace_hp_support` | 후퇴, HP 사다리의 후퇴 분기 | 제자리 힐(물약은 side) |
| `arm_potion_side_intents` | decide 말미 | HP/MP/해독 side_intents |
| `arm_loot_side_intent` | decide 말미 | 줍기거리 `PICKUP` side (주 Intent 전 F4) |
| `begin_retreat` / `finish_retreat` | HP, MP, 귀환, 급감 | 모드 전환, 월드 내비 세션 삭제, 복귀 시 재요청 |
| `set_mode` / `begin_travel` / `complete_travel_arrival` | 농장, 패트롤, 상점 걷기, 안전 | 모드와 이동 목적 |
| `tick_shop_trip` | 사냥의 상점 선행, 이동 틱 | 구매·판매, 상점 목적의 걷기 |
| `tick_world_nav` | 사냥, 던전, 맵 불일치, 상점 후, 후퇴 후 | 루틴 시계, 게이트, 두루마리 |
| `farm_loot_or_combat` | 사냥, 던전, 입장 이동, 월드 내비 걷기 | 스티키, 루팅 우선 |
| `ensure_navigation_for_live_map_id` | 매 틱의 mapId 변화, 게이트 착지 | 이후 A*의 origin·지형 |
| 로그인 클릭 통일 | autologin 단계 | 서버·캐릭터·동의 화면 |

`clear_world_nav_run`은 세션·게이트·요청만 지운다. 루틴 커서는 유지한다. 후퇴가 대표 호출자다.

---

## 16. 패키지 안쪽

### `app/_01_perception`

모든 메모리 읽기. API: `capture_tick`, `capture_hotbar`, `capture_inventory`, `capture_shop`, `capture_uidialog`, `pull_player`. `shared_sensors()`가 프로세스 공유 핸들. 창 기하는 `_05_action`.

### `app/_02_state`

디버그·결정이 읽는 자료구조만. `GameState`, `PlayerState`, `WorldState`, `WorldObject`, `BattleArea`, `WorldOrigin`, `enums`, `ObjectObservation`. 퍼셉션 적용 로직 없음.

### `app/_03_world`

버퍼 → `_02_state` 변환만. DLL 읽기 없음. `create_game_state()`로 빈 상태 생성. import는 `merge.` / `space.` / `catalog.` / `debug.` 하위 경로만 (루트 shim 없음).

| 하위 | 내용 |
| --- | --- |
| `merge/` | `apply_perception`, `track`, `memory_*`, `converter` |
| `space/` | 좌표·맵 로더 |
| `catalog/` | 이름표 |
| `debug/` | 미리보기·히스토리 로거 |

### `app/_04_decision`

계층: L1 `manager` → L2 `PlayerMode`/`mode_control` → L3 `mode_ticks` 사다리 → L4 concerns → L5 emit (`mode_actions` 등) → L6 query (`combat_query`, `hp_actions` schema). 상세는 [`DECISION_HIERARCHY.md`](DECISION_HIERARCHY.md).

`shop_trip`·`world_nav`·`patrol`/`farm_*`는 L4. `blackboard`는 L7. `configure`가 YAML을 전역에 심는다. `legacy/`와 `build_*_node`는 라이브 계층 밖이다.

### `app/_05_action`

`controller`가 분배한다. `mouse`·`keyboard`·`humanize`가 입력이다. `cursor_match`·`cursor_verify`·`cursor_catalog`가 커서다. `spell_box`가 핫바 슬롯 역할이다. `combat_strategies`가 클래스별 공격 입력이다. `travel_click`이 걷기 클릭이다. 창 사각형·4:3 경계(`window_bounds`, `content_crop`)와 미리보기용 프레임 복사(`screen_capture`)도 여기 있다.

### `session`

워커와 수명, 디버그 스냅샷, 게임 창 프로브, 드라이버 기동, 관리자 권한, 핫키, 입력 복구, 사망·끊김 후 `RecoveryBudget`.

### `settings`

프로필, 스케줄, 계정(DPAPI), HP 행동 표, 농장 체류, 스킬 카탈로그, 던전 에셋 경로. 엔진 규칙을 다시 구현하지 않는다.

### `shop`

YAML behavior 로드, NPC UV, 판매 슬롯, 캘리브레이션된 판매 실행. 트립을 열지는 않는다. 여는 쪽은 `shop_trip`이다.

### `hotbar`

시작 시와 주기 스캔, 아이콘 매칭, 슬롯 레이아웃. 역할(`heal`, `hp_potion`, `teleport`, `mother_tree`)은 스캔 결과가 spell box로 들어간다.

### `login` / `autologin`

서비스 어댑터와 Purple·게임 로그인 트리. 사냥 틱과 코드를 공유하지 않는다. 끝난 뒤에야 워커가 시작한다.

### `UI`

`schedule_ui`가 기본 진입이다. `operator_coordinator`가 Start의 소유자다. `app.py`의 운영 창은 `--operator`이다. UI는 UserData와 코디네이터만 건드린다.

---

## 17. 읽을 때 우선순위

코드와 다른 설명이 있으면 아래 순서로 버린다.

1. `Engine/app/_04_decision/behaviors/mode_ticks.py`의 사다리와 `bot_controller._run_bot_loop`의 틱.
2. `Docs/architecture/DECISION_HIERARCHY.md`의 층 정의.
3. `Docs/decision/decision_change_log.md`의 2026-10-03 이후 항목.
4. 이 문서.
5. `Docs/architecture/LAYOUT.md`의 폴더 역할.
6. `Docs/combat/전투로직설명서.md`, `Docs/status/*`, `Docs/prompt/PROMPT_MASTER.md`는 각각 9월 말 틱 순서, 9월 24일 감사, 설계 목표이다. 경로(`manmabot_v1`, `D:\...`)와 “판매 미구현”, “15레벨 미만은 힐 금지”는 현재 코드와 다르다.
