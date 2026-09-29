# MASTER PROMPT — 리니지 클래식 요정 자동조종 고도화 (아데나 순이익 최대화)

> 이 문서(PROMPT_MASTER.md)가 정본이며 `docs/prompt/*`는 파생 조각이다. 조각을 개별 수정하지 말고 정본만 갱신한다. 과업은 원칙적으로 T1~T24 순서로 수행하되, §6 의존성 그래프를 우선한다.

## 0. 역할과 최종 목표

너는 이 저장소의 자동조종 봇을 개선하는 시니어 코딩 에이전트다.

- 최종 목표: 몬스터 사냥 → 아데나·아이템 획득 → 아이템 판매를 반복하며 **시간당 순아데나(net adena/hr)를 최대화**한다.
- 기본 조종 대상: **요정(Elf)** = 활 원거리 클래스. 이동사격(무빙샷)이 기본 전투 모델.
- 원칙: **결정론적 규칙 + 고정 임계 + 게임DB 조회**. 학습(RL·밴딧·정책/EMA) 금지.

## 1. 절대 제약 (위반 시 작업 실패)

1. **EXP 사용 금지.** `expPct`/`exp_percent`를 의사결정에 쓰지 않는다(정확도 낮음). 표시 외 사용처 제거.
2. **학습 금지.** 밴딧/RL/정책학습/탐험 코드 금지. 측정은 합·비율(회계)까지만.
3. **새 메모리 오프셋 발굴 금지.** §3의 현재 필드만 사용.
4. **엔진 우선.** 조종·성능·계측은 `engine/`에서. UI는 필수 수정만(T21).
5. **사망 0**을 최우선 하드 제약으로.
6. **하드코딩 금지.** 모든 상수는 `engine/config/*.yaml` 경유, `_04_decision/configure.py`에서 로드.
7. 이상값은 위조하지 말고 보수적으로 강등/정지한다(§7.4).

## 2. 저장소 구조 (핵심 파일)

```
D:\ManmabotV1_final_v1\ManmabotV1_final
 engine/app/_01_capture/   screen_capture.py, window_bounds.py, content_crop.py
 engine/app/_02_vision/    vision_system.py, detector.py, classifier.py, tracker_pipeline.py, weight_hud.py
 engine/app/_03_world/     gamestate.py, objects.py, converter.py, memory_sync.py, memory_inventory.py,
                           memory_entities.py, realtime_monitor_reader.py, print_state_reader.py,
                           inventory_listen_reader.py, world_coords.py, battle_area.py, map_pack.py,
                           terrain_map.py, constants.py, enums.py, player.py, trust.py(신규)
                           # (목록은 비배타적; bot_log.py, farm_time.py, driver_setup.py 등도 포함)
 engine/app/_04_decision/  manager.py, mode_control.py, blackboard.py, configure.py, types.py,
                           target_selector.py, combat_query.py, attack_feedback.py, spells.py,
                           pathfinding.py, hierarchical_path.py, patrol.py, nav_config.py,
                           shop_trip.py, shops.py, ground_loot.py, economy.py(신규),
                           config_schema.py(신규), thresholds.py(신규), threat.py(신규),
                           data/{monster_kb,item_values,potion_kb}.json(신규),
                           behaviors/{mode_ticks,mode_actions,travel,search_hop,loot_hop,combat}.py
 engine/app/_05_action/    controller.py, mouse.py, keyboard.py, cursor_verify.py, spell_box.py,
                           combat_strategies/{__init__,elf,knight,mage,royal}.py
 engine/config/            decision.yaml, action.yaml, memory.yaml, vision.yaml, navigation.yaml, capture.yaml
 engine/maps/<id>/         meta.yaml, nav.png, farms.yaml, safe.yaml, home.yaml, patrol.yaml
 engine/scripts/classify_model/label_tables.json
 manmabot_v1/              bot_controller.py, debug_snapshot.py, probes.py, profile.py,
                           ui/{debug_ui,schedule_ui}.py, shopping/{runtime,behaviors}.py, hotbar/inspect.py
 tests/*.py
```
> 함수/클래스 이름이 기술과 다르면 **역할 기준으로 해당 함수를 찾아** 대응하라. 구현 전 관련 파일을 읽어 시그니처를 확인하라.

## 3. 사용 가능한 정보 (이 범위만)

- 플레이어(memory): `hp/max_hp, mp/max_mp, sp, level, pos(x,y,z), zone, weight/max_weight, stats(str..cha), classId, isChaotic, buffs[{id,remain,maxDur,stacks}], party`
- 엔티티(print_state + vision): `class, name, species, 월드셀(cx,cy), 화면(x,y)` + 비전 `bbox/정규화UV/속도/종족/레벨/occluded/frames_lost`
- 가방(inventory_listen, 백그라운드 20초 스캔): `items[{id,name,name_tw,count,kind}]`
  - 아데나=id 5, 화살=id 7, 은화살=id 96, 체력회복제=id 80, 해독제=id 76
- 알려진 한계(반드시 예외처리): 아그로/타겟/몹HP/스킬쿨/채팅 오프셋 없음. 가방 스캔 수 초·스테일 가능. 비전 CPU·라벨 스테일 가능. 커서 검증은 템플릿 부재 시 fail-closed. 창 최소화/BitBlt 실패 시 프레임 None.

## 4. 리니지 클래식 게임 사실 (판단 근거)

- 명중/AC: 명중은 레벨차·무기 명중, AC는 낮을수록 회피↑. 레벨차 크면 빗방 급증. (용던3층 에틴: 명중+1 유무로 46~91방)
- 최적 레벨밴드: 대략 내 레벨 −2 ~ +1.
- 몬스터 도감(예): 말섬 좀비 Lv6 HP45, 괴물눈 Lv7 HP40, 오크전사 Lv8 HP50, 해골 Lv10 HP80, 돌골렘 Lv13 HP150, 흑기사 Lv16 HP100, 라이칸스로프 Lv17 HP120, 웅골리언트 Lv18 HP200, 장로 Lv21 HP250, 글루디오 버그베어 Lv22 HP280, 오우거 Lv28 HP500, 개미굴 거대개미 Lv12 HP90, 거대병정개미 Lv20 HP150.
- 몰이(땡겨팟): 최고효율. 공식 ATS는 몰이 불가.
- 동족 인식(소셜 어그로): 오크 1마리 공격 시 무리 선공(카오틱 신전 등).
- HP 물약: 종류별 딜레이(체력 회복제, 주홍물약). **신속 물약은 딜레이 없음**(신속 체력 회복제 9~45, 신속 고급 33~89, 신속 강력 55~135).
- MP 물약: 즉시형 / 시간제(파란물약 600초 tick). 지혜의 물약 SP+2(법사).
- 버프: 초록물약(촐기) 5분 2배속, 강화 초록물약 30분, 엘븐 와퍼(요정) 8분 공속 60%↑, 용기의 물약(기사) 5분.
- 활/화살: 화살 6/5, 은화살 7/6(언데드에 강함), 미스릴화살 10/9. 사냥꾼활(명중+5), 장궁(요정, 대미지+3), 활 골무(원거리 명중+2).
- 아데나: 몹 드랍 + 아이템 판매로 획득. ATS 권장: 획득 무게 제한 49% 이하("무게 차면 틱이 안 차 유지력↓"), 아데나만 획득은 해제(잡템 팔아야), HP 30% 이하 귀환.
- 레벨밴드 사냥터: 5~10 필드, 10~20 글던1~2층(언데드, 은화살), 20~30 글던 저층/죽음의 폐허, 30+ 본던/용던.
- 요정: DEX 몰빵(명중·회피·안정성). 무과금/뉴비 원픽. 무빙샷 유리(북섬 등 개방 지형). 소울(HP→MP), 트리플 애로우(Lv30).
- ATS 설정(공식/커뮤니티): 탐색 범위 1~18걸음; 커뮤니티는 한 화면 유지 위해 2~4 + 연쇄인식 4 이하 권장. 아이템 우선/매너 사냥 사용, 선공 우선은 보통 끔.
- 운영: 초기 명중/회피/AC 정상화 점검 이력 → 전투값은 실측 보정 전제. 매크로/비인가 프로그램 대규모 제재 이력 → 휴머나이즈 유지.

## 5. 측정 정의 (모든 판단의 기준)

```
net_adena_per_hour = (loot_adena + sell_adena − buy_spent_adena) / 시간(h)
```
- loot_adena: 바닥 아데나 픽업 증가분. sell_adena: 상점 판매 증가분. buy_spent_adena: 화살·물약 구매 감소분.
- EXP는 등장하지 않는다.
- 세부 신호: adena_per_kill, kills_per_hour, time_per_kill, arrow_rate, potions_per_hour.
- 킬 판정: 엔티티 소멸 + 아데나/무게 델타로 근사(EXP 미사용).

## 6. 실행 순서(요약) 및 의존성

```
P0 계측(T1) ─▶ Trust(T2) ─▶ 소스 예외(T3~T6) ─▶ 조종 예외·복구(T13)
P0 ─▶ 설정 체계(T18~T20) ─▶ 요정 전투/표적/루팅/판매(T7~T11) ─▶ 자원 예측(T14) ─▶ 몰이(T15) ─▶ 경제·팜 루프(T16) ─▶ 임계 파생(T17)
병행: UI 최소(T21), 핫바 표준(T22)+자동사용(T23~T24)
```
- T1(계측) 없이 T7 이후 금지. T2(Trust)는 T7보다 먼저.
- 각 과업은 독립 커밋, 과업 ID 포함. 테스트 동반. 검증 불가 시 머지 금지.
## 7. 신뢰도(Trust) 모델과 예외처리 (부록 B)

### 7.1 신뢰도
소스별 `OK / DEGRADED / STALE / FAILED`: `memory, entity_sweep, inventory, vision, capture, input, cursor, focus`.
틱마다 산출, 블랙보드 저장, KPI/로그 노출.

### 7.2 결정 게이팅(하드 제약)
| 소스 상태 | 허용 | 금지 |
|---|---|---|
| memory OK | 전부 | — |
| memory STALE/FAILED | 비전 폴백 파밍·대기 | HP/MP 후퇴 판단, 귀환 단정 |
| entity_sweep DEGRADED | 비전 클릭 | 메모리 클릭 |
| vision FAILED | 대기·복구 | 공격/루팅 |
| inventory STALE | 보수 임계 | 판매/구매 트립 단정 |
| input/cursor FAILED | 복구 대기 | 클릭 주입 |
| focus 상실 | 일시정지 | 입력 |

**fail-safe**: `memory+vision+input` 중 2개 이상 FAILED → 입력 정지 + 복구(무한 재시작 금지, 예산 bounded).

### 7.3 예외 카탈로그
E1 드라이버/게임 종료, E2 오프셋 불일치(hp>max, pos(0,0), level≤0 → STALE), E3 스윕 실패, E4 화면밖 좌표, E5 비전 프레임 None, E6 추론 적체, E7 라벨 스테일, E8 track 스위치, E9 가방 스테일, E10 bag 미준비, E11 물약 딜레이 미상, E12 arrow_lack, E13 커서 템플릿 부재, E14 커서 마비, E15 포커스 상실, E16 경로 차단, E17 스턱, E18 사망 감지 실패, E19 구매 미검증, E20 버프 타이머 어긋남, E21 스레드 경합, E22 설정 drift, E23 맵팩/팜 누락, E24 지역모델 누락, E25 UI 램프, E26 정지 비원자성.

### 7.4 공통 구현 규칙
- 값 검증: `0 ≤ hp ≤ max_hp`(둘 다 >0), `1 ≤ level ≤ 99`, `pos ≠ (0,0)`. 위반 시 STALE, 필드는 None 유지(0 위조 금지).
- 스테일/이상 시 보수적 강등. 강등/복구/fail-safe는 구조화 로그(채널 `trust`)로 1회 기록(스팸 금지).
- 복구: 입력 락 → 원인 재확인 → 재연결(메모리/캡처) → 정상 복귀. 예산 초과 시 정지.
## 8. 설정값 체계 (부록 A: 단일 소스·검증·객관값)

### 8.1 아키텍처 규칙
- S1 단일 소스: 모든 튜너블은 `engine/config/*.yaml`에만. 모듈 상수 중복 금지. **import-by-value 재바인딩 금지**(예: `FARM_DURATION_LIMIT`).
- S2 precedence: `코드 기본값 < engine/config/*.yaml < profile.json < schedule task < 런타임 안전 오버라이드`. 확정값 로깅.
- S3 단위 명명: `_ratio(0~1), _tiles(정수), _px, _s, _ms, _frames, _deg, _ticks, _count, _thresh, _cell, _radius, _min, _weight`.
- S4 거리 통일: 게임 로직 거리는 정수 타일(Chebyshev). 픽셀은 렌더·클릭만.
- S5 시작 검증(fail-fast): 타입·범위·교차 제약 위반 시 기동 중단 + 명확 메시지.
- S6 파생값: `heal_until = hp_potion − margin`, `spell_reserve = mp_low` 등 중복 정의 금지.
- S7 충돌 감지: 아래 매트릭스 부팅 시 평가.
- S8 런타임 안전 키 화이트리스트(생존 임계·루팅모드·팜 선택) vs 재시작 키(캡처/비전 모델/지도).
- S9 유효 설정 dump(채널 `config`).
- S10 `config_version` + 마이그레이션.

### 8.2 교차 제약(부팅 검증)
| 체인 | 제약 |
|---|---|
| HP | idle_emergency < retreat < heal_until ≤ potion < almost_full < full |
| HP vs 귀환 | retreat ≤ return.hp < potion |
| MP | spell_reserve ≤ mp_low < recovered |
| 요정 거리 | range_back < range_fire_min < range_fire_max ≤ range_close ≤ weapon_range |
| 루팅/무게 | loot_skip_weight_ratio < sell_weight_ratio ≤ loot_adena_weight_ratio (adena_only ≥ sell 이면 사실상 해제) |
| 상점 | return_*_count < *_qty |
| 이동 | unstick_seconds < stuck_seconds; click_path_slack ≤ attack_path_slack |
| 몰이 | mob_min_count < flee_count (전 클래스 공통) |
| 비전 | config 임계 = 코드 부팅값 |
| 스킬 | mage_cast_interval_min ≥ magic_cooldown_s |

### 8.3 객관화된 핵심 값(커뮤니티·공식 근거)
| 키 | 값 | 근거 |
|---|---|---|
| hp.idle_emergency_ratio | 0.10 | — |
| hp.retreat_ratio | 0.35 | ATS HP30% 귀환 정합 |
| hp.heal_until_ratio | 0.55 | 파생 |
| hp.potion_ratio | 0.60 | — |
| hp.almost_full_ratio / full_ratio | 0.90 / 0.99 | — |
| mp.spell_reserve_ratio | 0.15 | ≤ mp_low |
| mp.low_ratio / recovered_ratio | 0.15 / 0.90 | — |
| return.hp_ratio | 0.35 | ATS 귀환 HP30%보다 약간 이른 복귀 |
| return.mp_ratio | 0.15 | — |
| elf.weapon_range_tiles | 8(실측 보정) | 활/변신 영향 |
| elf.range_close | 8 | ≤ weapon_range |
| elf.range_fire | [5,7] | 무빙샷 유지 |
| elf.range_back | 3 | 접근 시 후퇴 |
| elf.reposition_every_shots | 2 | 무빙샷 |
| elf.attack_interval_s | [0.15,0.25] | — |
| elf.silver_arrow_on_undead | true | 은화살 언데드 |
| combat.level_band_low/high | −2 / +1 | 명중 밴드 |
| combat.approach_bonus | 0.10 | — |
| combat.max_missed_frames | 2 | — |
| combat.engage_max_s | 10.0 | — |
| combat.giveup_cooldown_ticks | 160 | — |
| combat.courtesy_skip | true | ATS 매너 사냥 |
| combat.attack_first_bonus | 0.0 | 요정 낮게 |
| economy.loot_max_tiles / loot_pickup_tiles | 7 / 2 | — |
| economy.loot_skip_weight_ratio | 0.40 | ATS 무게 제한 원칙 |
| economy.loot_adena_weight_ratio | 0.85 | 아데나만 해제(≥ sell) |
| economy.sell_weight_ratio | 0.49 | ATS 무게49% 복귀 |
| economy.sell_batch_min_value | 5000 | — |
| economy.sell_batch_max_wait_s | 300 | — |
| economy.item_first | true | ATS 아이템 우선 |
| economy.arrow_unit_cost | 2 | 미스릴화살 개당 2아데나(거래소) |
| economy.arrow_unit_weight | 0.05 | 화살통: 3,200발=무게150 |
| economy.hp_trend_window_s | 5 | HP/MP 틱·물약 딜레이 정합 |
| economy.bag_confirm_retries | 2 | — |
| farm.duration_limit_s | 600 | 단일 소스 |
| farm.search_tile_min/max | 3 / 6 | 한 화면 |
| travel.arrive_tiles | 2 | — |
| travel.unstick_seconds / stuck_seconds | 5.0 / 10.0 | — |
| travel.reclick_s | 2.0 | — |
| nav.clearance_tiles / wall_penalty | 2 / 4 | — |
| nav.cluster_size / coverage_cell | 32 / 16 | — |
| nav.click_path_slack / attack_path_slack | 3 / 4 | — |
| shop.arrow_qty / silver_arrow_qty | 1000 / 0 | 무게 예산(화살1발≈0.05) |
| shop.buy_normal_arrows | true | — |
| shop.potion_qty | 150 | 커뮤니티 물약 140~150 |
| shop.restock_potions | true | — |
| shop.potion_suppress_s | 600 | — |
| shop.return_arrow_count | 동적 | 소모율 기반 |
| spells.magic_cooldown_s | 0.5 | 게임 쿨 |
| spells.mage_cast_interval_s | [0.50,0.55] | — |
| spells.buff_recast_margin_ratio / _min_s | 0.05 / 10 | 버프 지속 300~1800s |
| threat.aggro_radius | 10(화면) / 연쇄 4 | ATS/arca |
| threat.mob_min_count / flee_count | 3 / 4 | 하이네 포위 위험 |
| trust.mem_stale_s / inventory_stale_s / vision_lag_ms / failsafe_min_failed | 1.5 / 40 / 400 / 2 | — |
| capture.frame_fail_pause_n | 10 | — |

### 8.4 설정 스키마(신규 섹션)
```yaml
economy: { adena_item_ids:[5], scan_force_on_event:true, loot_value_filter:true,
  loot_max_tiles:7, loot_pickup_tiles:2, loot_adena_weight_ratio:0.85,
  loot_skip_weight_ratio:0.40, skip_value_per_weight_min:0.5, sell_weight_ratio:0.49,
  sell_batch_min_value:5000, sell_batch_max_wait_s:300, item_first:true,
  arrow_unit_cost:2, arrow_unit_weight:0.05, hp_trend_window_s:5, min_net_value:0, bag_confirm_retries:2 }
elf: { weapon_range_tiles:8, range_close:8, range_fire:[5,7], range_back:3,
  reposition_every_shots:2, attack_interval_s:[0.15,0.25], silver_arrow_on_undead:true }
combat: { level_band_low:-2, level_band_high:1, approach_bonus:0.10,
  max_missed_frames:2, engage_max_s:10.0, giveup_cooldown_ticks:160,
  halt_before_attack:true, courtesy_skip:true, attack_first_bonus:0.0,
  giveup_blacklist:true, probe_eval_enabled:true }
hp: { idle_emergency_ratio:0.10, retreat_ratio:0.35, heal_until_ratio:0.55,
  potion_ratio:0.60, almost_full_ratio:0.90, full_ratio:0.99 }
mp: { spell_reserve_ratio:0.15, low_ratio:0.15, recovered_ratio:0.90 }
return: { hp_ratio:0.35, mp_ratio:0.15, idle_enabled:false, idle_seconds:90.0 }
travel: { arrive_tiles:2, unstick_seconds:5.0, stuck_seconds:10.0, stuck_ticks:100,
  reclick_s:2.0, unstick_radius:3, cursor_fallback_radius:1 }
nav: { clearance_tiles:2, wall_penalty:4, cluster_size:32, coverage_cell:16,
  click_path_slack:3, attack_path_slack:4 }
shop: { arrow_qty:1000, silver_arrow_qty:0, buy_normal_arrows:true, buy_silver_arrows:false,
  restock_potions:true, potion_qty:150, potion_suppress_s:600, sell_mode:sell_only_garbage,
  arrive_tiles:7, npc_search_px:20, return_potion_count:20, return_arrow_count:dynamic }
spells: { magic_cooldown_s:0.5, mage_cast_interval_s:[0.50,0.55],
  buff_recast_margin_ratio:0.05, buff_recast_margin_min_s:10, unstick_teleport_cooldown_s:20 }
farm: { duration_limit_s:600, search_leg_ticks:30, search_tile_min:3, search_tile_max:6 }
trust: { mem_stale_s:1.5, inventory_stale_s:40, vision_lag_ms:400, failsafe_min_failed:2 }
capture: { frame_fail_pause_n:10 }
threat: { closing_speed_thresh:0.0, aggro_radius:10, chain_radius:4, mob_min_count:3, flee_count:4 }
vision: { coarse_class_conf_min:0.5, detail_conf_min:0.5 }
```

### 8.5 몬스터 지식베이스(monster_kb.json)
```json
{ "monster_좀비": {"level":6,"hp":45,"undead":true,"size":"small","social":false,"tier":1},
  "monster_버그베어": {"level":22,"hp":280,"undead":false,"size":"large","social":false,"tier":2},
  "monster_오크전사": {"level":8,"hp":50,"undead":false,"size":"small","social":true,"tier":1} }
```
- level 미표기 시 `label_tables.json` species_level 폴백, 미표기 종족은 밴드 통과로 안전 처리.

### 8.6 물약/아이템 지식(potion_kb.json / item_values.json)
```json
// potion_kb.json  (딜레이 유무 중심; 회복량은 운영자 캘리브레이션)
{ "빨간물약":{"tier":"low","delay":true}, "주홍물약":{"tier":"mid","delay":true},
  "신속 체력 회복제":{"tier":"low","delay":false}, "신속 고급 체력 회복제":{"tier":"mid","delay":false},
  "신속 강력 체력 회복제":{"tier":"high","delay":false}, "엔트의 열매":{"tier":"high","delay":true} }
// item_values.json (루팅/판매 우선순위, 운영자 설정)
{ "아데나":{"value":1,"weight":0}, "젤":{"value":10}, "무기 마법 주문서":{"value":50},
  "최고급 다이아몬드":{"value":100} }
```
## 9. 아이템·마법 표준세팅 + 핫바 자동운용 (부록 C)

### 9.1 원칙
- 역할(role) 기반: 봇은 키가 아니라 역할로 판단. 시작 시 핫바 스캔(`manmabot_v1/hotbar/inspect.py`)이 아이콘→역할 매핑, 실패 시 §9.3 표준 레이아웃 폴백.
- 상태 기반 트리거: HP/MP/buff remain/무게/디버프/화살 재고.
- 하드 게이트: 마법 공유 쿨(`spells.magic_cooldown_s=0.5`), 물약 딜레이, 버프 중복 금지, 죽음/귀환 중 전투마법 금지.
- **자기 버프는 더블탭**(리니지 공식: 술자 버프는 단축키 두 번).

### 9.2 역할 카탈로그 (기존 spell_box.SLOT_IDS 확장)
기존: power_up, armor_up, light, heal, hp_potion, mp_potion, teleport, mage_attack, talking_scroll, mother_tree, hp_to_mp.
추가/정리:

| role | 설명 | 소비 | cast | 게이트 | 우선순위 |
|---|---|---|---|---|---|
| hp_potion | 일반 체력 회복제(딜레이) | 아데나 | press | 딜레이, HP임계 | 생존 |
| hp_potion_fast | 신속 물약(딜레이 없음) | 아데나 | press | HP임계 | 생존(최우선) |
| mp_potion | 마나 회복(즉시/시간제) | 아데나 | press | MP임계 | 생존 |
| heal | 힐(자기) | MP | double | MP reserve | 생존 |
| depoison | 해독제/비취물약 | 아데나 | press | 독 상태 | 생존 |
| teleport | 순간이동(회피/이동) | 주문서 | press | 쿨, 위협 | 생존 |
| return_scroll | 귀환 주문서 | 주문서 | press | HP/무게 임계 | 생존 |
| haste | 가속(초록/엘븐와퍼) | 아데나 | press | remain | 버프 |
| shield | 실드/방어버프 | MP | double | remain, reserve | 버프 |
| light | 라이트 | MP | double | remain | 버프(저) |
| attack_buff | 홀리웨폰/인챈트/파워업 | MP | double | remain, reserve | 버프 |
| spell_attack | 요정 트리플/정령 공격 | MP(+정령옥) | press 후 대상클릭 | 쿨, 사거리, reserve | 전투마법 |
| control | 어스 바인드/구속 | MP(+정령옥) | press 후 대상클릭 | 쿨, 위협 | 전투마법 |
| summon | 서먼 몬스터 | MP(+마력의돌) | press | 쿨, 안전 | 유틸 |
| pickup | 아이템 획득(지상 클릭; F4 사용 안 함) | — | click | 근접 | 유틸 |

### 9.3 요정 표준 핫바 레이아웃(게임 내 설정 권장)
Box1(F1) 생존: F5 hp_potion_fast, F6 hp_potion, F7 depoison, F8 heal, F9 teleport, F10 return_scroll, F11 haste, F12 shield
Box2(F2) 특수/공격: F5 talking_scroll, F6 mother_tree, F7 hp_to_mp, F8 spell_attack, F9 control, F10 attack_buff, F11 summon, F12 light
Box3(F3) 예비.
> 봇은 스캔 우선, 실패 시 이 표준안을 폴백으로 사용.

### 9.4 상태 기반 자동 사용 우선순위
`생존 > 버프유지 > 공격마법 > 유틸`. 상위 RUNNING이면 하위 평가 금지.
```
생존:
 hp ≤ eff_retreat → (저지연 우선) hp_potion_fast → hp_potion(딜레이 게이트)
                   → heal(MP reserve) → teleport(쿨/위협) → return_scroll
 mp ≤ mp.low(요정): 안전 시 hp_to_mp → mp_potion
 독 감지: depoison
 weight_ratio ≥ 0.49: 귀환·판매 트립 우선
버프(remain 기반, 타이머 금지):
 role ∈ {haste, shield, attack_buff, light}, remain ≤ margin(=max(buff_recast_margin_min_s, buff_recast_margin_ratio·maxDur)), MP≥reserve → cast
공격마법:
 적 사거리 내 & MP≥spell_reserve & cooldown_ok:
   train_size ≥ mob_min & MP 충분 → spell_attack(다중)
   위협 → control
   그 외 → spell_attack
유틸:
 바닥템 근접 & 미획득 → pickup(지상 클릭)
```
중복/가드: 마법 역할 간 공유 쿨, 버프는 `buffs`에 존재하면 재시전 금지(만료 임박만), 소모품 재고 부족 시 역할 비활성.

### 9.5 상태→역할 트리거
| 조건 | 역할 |
|---|---|
| HP ≤ retreat | hp_potion_fast → hp_potion → heal |
| HP ≤ emergency | teleport / return_scroll |
| MP ≤ low(요정) | hp_to_mp(안전) / mp_potion |
| 독 | depoison |
| buff.remain ≤ margin | haste/shield/attack_buff/light |
| 적 사거리 & MP≥reserve | spell_attack/control |
| train ≥ mob_min | spell_attack(다중) |
| train ≥ flee_count | teleport/후퇴 |
| 무게 ≥ 0.49 | 귀환·판매 |
| arrow_lack | 상점 |
| 바닥템 근접 | pickup(지상 클릭) |

### 9.6 hotbar 설정 스키마
```yaml
hotbar:
  layout: { elf: {
    box1: [hp_potion_fast, hp_potion, depoison, heal, teleport, return_scroll, haste, shield],
    box2: [talking_scroll, mother_tree, hp_to_mp, spell_attack, control, attack_buff, summon, light],
    box3: [] } }
  cast_mode: { heal: double, shield: double, attack_buff: double, light: double, default: press }
  buff_role_map: { shield: [실드, shield], haste: [가속, 엘븐 와퍼, 초록물약],
                   attack_buff: [홀리 웨폰, 인챈트 웨폰, 파워 업] }
  triggers: { buff_recast_margin_ratio: 0.05, buff_recast_margin_min_s: 10, magic_cooldown_ref: spells.magic_cooldown_s,
              potion_delay_aware: true, prefer_fast_potion: true }
```
## 10. 과업 목록 (T1~T24, 순서대로)

형식: 목표 / 변경 파일 / 구현 / 완료기준 / 금지

### T1 — 순아데나 계측(회계) [선행 필수]
- 파일: `_03_world/player.py`, `_03_world/memory_inventory.py`, `_03_world/memory_sync.py`, 신규 `_04_decision/economy.py`, `blackboard.py`(ledger 저장), `configure.py`, `debug_snapshot.py`, `bot_controller.py`(강제 스캔 훅)
- 구현: `InventoryState.adena`·`mp_potion`; `ADENA_IDS={5}`, `ADENA_NAMES`; `player_from_snapshot`에 weight/max_weight 매핑; `AdenaLedger`(observe/note_event/net_per_hour/adena_per_kill); 아데나 픽업·판매·구매 직후 `LiveInventorySweep.poll(force=True)`.
- 완료: `tests/test_economy.py`(net=loot+sell−buy), `tests/test_no_exp.py`.

### T2 — 신뢰도 계층 + 결정 게이팅 [T7 이전 필수]
- 파일: 신규 `_03_world/trust.py`, `blackboard.py`, `behaviors/mode_ticks.py`, `manager.py`, `debug_snapshot.py`, `bot_controller.py`(request_pause 추가)
- 구현: `TrustMonitor.update(...) -> {source: Trust}`; §7.2 게이팅; fail-safe `request_pause("trust_failsafe")`.
- 완료: `tests/test_trust.py`.

### T3 — 메모리/엔티티 예외처리
- 파일: `realtime_monitor_reader.py`, `memory_sync.py`, `memory_entities.py`, `print_state_reader.py`
- 구현: §7.4 값 검증·STALE·None 유지; 화면밖/중복 엔티티 스킵; offsets 버전 경고.
- 완료: `tests/test_memory_sanity.py`.

### T4 — 비전/캡처 예외처리
- 파일: `_01_capture/screen_capture.py`, `window_bounds.py`, `_02_vision/vision_system.py`
- 구현: 프레임 None 연속 `frame_fail_pause_n`→DEGRADED·입력 락; GameGuard($GIVEmeMINT)/최소화/해상도·DPI 변경 감지; 프레임 적체 시 스킵·위험 우선.
- 완료: `tests/test_capture_degrade.py`.

### T5 — 가방/경제 예외처리
- 파일: `inventory_listen_reader.py`, `memory_inventory.py`, `shop_trip.py`
- 구현: 스테일/미준비 시 판매·구매 금지·보수 임계; 구매/판매 후 adena 델타로 성공 검증(`bag_confirm_retries`).
- 완료: `tests/test_inventory_guard.py`.

### T6 — 입력/커서/포커스 예외처리
- 파일: `mouse.py`, `cursor_verify.py`, `controller.py`, `probes.py`, `driver_setup.py`, `bot_controller.py`
- 구현: Interception 미준비 시작 차단; 템플릿 0개 fail-closed+경고; cursor_paralyzed 입력 락; 포커스 상실 일시정지; stop 후 입력 종료 ack.
- 완료: `tests/test_input_guard.py`.

### T7 — 요정 거리 유지 + 무빙샷
- 파일: `_05_action/combat_strategies/elf.py`(기사 상속 해제, 상태 전이 소유), `_04_decision/behaviors/combat.py`(APPROACH/REPOSITION/BACKOFF 전이), `blackboard.py`(elf 상태 필드), `target_selector.py`, `combat_query.py`, `controller.py`
- 구현(Chebyshev): APPROACH(d>range_close) → FIRE(range_fire, attack_click/커서 arrow 검증) → REPOSITION(reposition_every_shots마다 측면 1~2타일 후 재발사) → BACKOFF(d<range_back). `in_elf_range` 헬퍼.
- 완료: `tests/test_elf_range.py`(밴드 유지율 ≥80%), 타 클래스 회귀 없음.

### T8 — 레벨밴드·가치 표적 선택
- 파일: 신규 `monster_kb.json`, `target_selector.py`, `combat_query.py`, `configure.py`
- 구현: `band_ok=(−2≤gap≤+1)`, `score=tier_value/max(1,t_kill(hp/dps_prior))`, 접근中 적 가산. kb 누락 시 밴드 통과.
- 완료: `tests/test_target_value.py`(밴드 외 <5%, 단조 정렬).

### T9 — 루팅 가치/무게 필터
- 파일: `combat_query.py`(list_lootable), `ground_loot.py`, `mode_actions.py`, 신규 `item_values.json`
- 구현: 아데나 최우선 → value/weight 상위 → 무게 ≥ `economy.loot_skip_weight_ratio`(0.40)면 `skip_value_per_weight_min` 미만 스킵. `item_first`.
- 완료: `tests/test_loot_filter.py`.

### T10 — 배치 판매
- 파일: `shop_trip.py`, `manmabot_v1/shopping/behaviors.py`
- 구현: `sellable_value_est ≥ sell_batch_min_value` 또는 `sell_batch_max_wait_s` → 판매 트립. sell_only_garbage + item_values.json.
- 완료: 트립당 실현 아데나↑·트립 수↓ 로그.

### T11 — 소모 비용 인지
- 파일: `economy.py`, `target_selector.py`, `combat_query.py`
- 구현: `net_value = tier_value − (arrow_cost + potion_cost_est) > min_net_value` 표적만. (화살비≈0 반영)
- 완료: 저가치 표적 스킵 시 net/hr 개선(모의).

### T12 — 고성능·저지연
- 파일: `_05_action/controller.py`, `inventory_listen_reader.py`, `bot_controller.py`, `vision_system.py`, `config/vision.yaml`
- 구현: 블로킹 time.sleep → 논블로킹 상태 대기; 이벤트 트리거 스캔; GPU 활성·재분류 예산/간격 튜닝; 틱 예산·프레임 스킵.
- 완료: 입력 공백 0, 최대 틱 지연 감소.

### T13 — 조종 예외·복구·관측
- 파일: `behaviors/{travel,search_hop,loot_hop}.py`, `combat.py`, `attack_feedback.py`, `bot_log.py`, `bot_controller.py`, `configure.py`
- 구현: 도달불가/무효 표적 give-up+블랙리스트(`evaluate_attack_probes` 부활); 스턱 3단계(언스턱→랜덤→텔포)+실패 누적 시 팜 전환; 사망 확정 대기; 강등/복구 로그.
- 완료: `tests/test_control_fallback.py`, `tests/test_recovery_flow.py`.

### T14 — 자원 예측(화살·물약·은화살)
- 파일: `memory_inventory.py`, `shop_trip.py`, `target_selector.py`, 신규 `_04_decision/data/potion_kb.json`
- 구현: `arrow_rate`·time_left 기반 동적 재보급 임계; 물약 등급·딜레이 정적 테이블(신속 우선) + 피격 추세; 언데드 표적 은화살 매칭.
- 완료: 화살 소진 공백 0, 물약 지출/hr↓.

### T15 — 몰이 + 소셜 어그로
- 파일: 신규 `_04_decision/threat.py`, `mode_actions.py`, `combat_query.py`
- 구현: `A={m: closing_velocity>θ and dist≤aggro_radius}`; `|A|≥mob_min & MP 충분`→측면 유도 후 다중 사격; `|A|≥flee_count or hp_trend<0`→해산/후퇴; kb.social 보정.
- 완료: 처치/hr↑, 사망 0.

### T16 — 자원 소비/경제 루프 (팜·귀환)
- 파일: `economy.py`, `nav_config.py`, `mode_ticks.py`
- 구현: 소비율 예측 기반 귀환·재보급; 무게 0.49 도달 시 귀환; (선택)고정 우선순위 팜(레벨밴드 prior) — 학습 금지.
- 완료: 귀환 낭비↓, net/hr↑.

### T17 — 조종 임계 파생·위협 적응
- 파일: 신규 `_04_decision/thresholds.py`, `mode_control.py`, `behaviors/mode_ticks.py`
- 구현: `heal_until=hp_potion−margin`, `spell_reserve=mp_low`; `eff_retreat=clamp(0.35+k_threat·train+k_gap·gap,0.30,0.55)`; `eff_potion`; 히스테리시스(전환 확인 틱·표적 switch_margin).
- 완료: `tests/test_derived_thresholds.py`(데드존 0, 진동 억제).

### T18 — 설정 단일 소스 + 재바인딩 버그 제거
- 파일: `configure.py`, `behaviors/mode_ticks.py`, `farm_time.py`, `_03_world/constants.py`
- 구현: import-by-value 제거 → getter; `FARM_DURATION_LIMIT` 단일 소스.
- 완료: `tests/test_config_single_source.py`.

### T19 — 설정 스키마·검증·교차제약·충돌검출·유효값 로그
- 파일: 신규 `_04_decision/config_schema.py`, `configure.py`, `bot_log.py`
- 구현: §8.3/8.4 파싱, §8.2 교차제약, 위반 시 기동 중단, resolved dump.
- 완료: `tests/test_config_validation.py`, `tests/test_config_conflicts.py`.

### T20 — 단위 명명·단위 통일
- 파일: `world_coords.py`, `constants.py`, `combat_query.py`, `config/*.yaml`
- 구현: 거리 정수 타일 통일, 접미사 규칙, `ATTACK_RANGE`/`MAGE_SPELL_RANGE` 중복 정리.
- 완료: `tests/test_units.py`.

### T21 — UI 최소 수정 (우선순위 낮음; 단 Lamp 버그는 즉시성 있음 — T22~T24 뒤로 미루지 말 것)
- 파일: `probes.py`, `ui/debug_ui.py`, `ui/schedule_ui.py`, `debug_snapshot.py`
- 구현: `Lamp.AMBER` 버그 수정(호출부 2곳을 `Lamp.YELLOW` 참조 또는 별칭 추가; `_refresh_operator`는 수정 대상 아님); 개요에 `net_adena/hr · adena/kill · kills/hr` 1줄.
- 금지: 그 외 UI 구조 변경.

### T22 — 표준 핫바 역할 확장 + 스캔 정합
- 파일: `spell_box.py`, `hotbar/inspect.py`, `profile.py`, `spell_defaults.py`, 설정
- 구현: §9.2 역할 추가, §9.3 표준 레이아웃 기본값, 스캔→역할 매핑 확장, 스캔 실패 폴백.
- 완료: `tests/test_hotbar_roles.py`.

### T23 — 상태 기반 자동 사용 조종논리
- 파일: `spells.py`, `behaviors/mode_ticks.py`, `behaviors/mode_actions.py`, `controller.py`
- 구현: §9.4/9.5 트리거·우선순위, 버프 remain 기반, 더블탭, 재고 게이트.
- 완료: `tests/test_spell_usage.py`.

### T24 — 물약 딜레이·쿨·중복 가드
- 파일: `controller.py`, `spell_box.py` (데이터 `_04_decision/data/potion_kb.json` 는 T14에서 생성)
- 구현: 물약 딜레이 인지(신속 우선), 마법 공유 쿨, 버프 중복 금지, 소모품 재고 연동.
- 완료: `tests/test_potion_delay.py`, `tests/test_no_duplicate_buff.py`.
## 11. 에이전트 실행 규칙

1. 과업 착수 전 관련 파일을 실제로 읽어 함수/클래스 이름·시그니처를 확인한다. 기술과 다르면 역할 기준으로 대응.
2. 과업 1개 = 커밋 1개(메시지에 과업 ID 포함).
3. 각 과업마다 단위 테스트를 함께 작성·실행한다.
4. 신규 상수는 config 경유. 기존 클래스(기사/마법사/군주) 동작은 회귀 방지(요정 경로만 분기).
5. 검증 불가한 변경은 머지하지 않는다.
6. 막히면 추측하지 말고 읽은 근거와 함께 불명확점을 보고한다.
7. EXP·학습·신규 오프셋·무관한 UI 리팩터링 금지.

## 12. 테스트 목록 (필수)

`tests/test_economy.py`, `test_no_exp.py`, `test_trust.py`, `test_memory_sanity.py`,
`test_capture_degrade.py`, `test_inventory_guard.py`, `test_input_guard.py`, `test_input_latency.py`,
`test_elf_range.py`, `test_target_value.py`, `test_loot_filter.py`,
`test_control_fallback.py`, `test_recovery_flow.py`, `test_config_single_source.py`,
`test_config_validation.py`, `test_config_conflicts.py`, `test_units.py`,
`test_derived_thresholds.py`, `test_hotbar_roles.py`, `test_spell_usage.py`,
`test_potion_delay.py`, `test_no_duplicate_buff.py`
— 기존 `tests/test_memory_entities.py`, `tests/test_live_ui_smoothness.py` 회귀 통과.

## 13. Definition of Done (전역)

1. EXP 미사용(`test_no_exp.py` 통과).
2. `net_adena_per_hour` 실시간 산출·노출.
3. Trust 틱 산출 + §7.2 게이팅 + fail-safe 동작.
4. 요정이 사거리 밴드를 유지하며 무빙샷.
5. 표적이 레벨밴드·가치 기준으로 선택.
6. 루팅·판매가 가치/무게/비용 반영.
7. 화살 소진 공백 0, 구매/판매 성공 검증.
8. 설정 충돌 0(부팅 통과), 유효 설정 로그 dump, import-by-value 0.
9. HP/MP/거리/무게 임계 데드존 0.
10. 핫바 역할이 상태 기반으로 자동 사용(버프 가동률 ≥95%, 물약 낭비 0).
11. 이상값/스테일로 인한 오클릭 0.
12. 동일 조건 대비 net_adena/hr 상승(최소 20%, A/B 로그).

## 14. 보고 형식 (과업 완료 시)

```
[과업 ID] / [상태: 완료|부분|차단]
변경 파일: ...
핵심 변경: ...
테스트: 실행 명령 + 결과
검증 지표: net_adena/hr 또는 명시 지표 before→after
미해결/불명확: ...
```

## 15. 최종 체크리스트 (에이전트가 커밋 전 자문)

- [ ] EXP를 어디에서도 의사결정에 쓰지 않았는가?
- [ ] 학습/밴딧 코드를 넣지 않았는가?
- [ ] 새 설정을 config 경유로 추가했는가? 단위 접미사·범위·교차제약을 정의했는가?
- [ ] 요정 경로만 분기했고 타 클래스 회귀가 없는가?
- [ ] 이상값/스테일 시 보수적 강등(위조 금지)인가?
- [ ] 테스트가 통과하고 지표로 검증했는가?
## 16. 부록 D — 확정 사양 (모호성 해소, 이 부록이 상위 우선)

> 검증 결과 확인된 모호/모순을 확정한다. 충돌 시 **이 부록이 §7~§10보다 우선**한다.

### D1. 설정 레이아웃 (기존 로더 유지)
- `engine/config/decision.yaml` 루트는 기존 구조를 **유지**한다: 최상위 `farming:`, `decision:` 아래에 `hp/mp/return/teleport/spells/farm/shop/travel/combat/search` + 신규 `economy/elf/combat(확장)/trust/threat/hotbar`.
- `capture:`는 `capture.yaml`, `vision:`은 `vision.yaml` 유지.
- `config_version: 1`을 decision.yaml 최상위에 추가.
- `configure.py`는 기존대로 `config["decision"]`·`config["farming"]`·`config["navigation"]`를 읽고, 신규 섹션은 `config["decision"]["economy"]` 등으로 읽는다(플랫 재구조화 금지).
- **§8.4의 플랫 예시는 "키-값 사전"으로만 해석**하고, 실제 위치는 위 트리다.

### D2. 키 이름 변경 → 별칭(alias)으로 흡수(하드 리네임 금지)
| 기존 | 신규(별칭 허용) |
|---|---|
| `hp.critical_ratio` | `hp.retreat_ratio` |
| `hp.low_ratio` | `hp.potion_ratio` |
| `combat.max_engage_seconds` | `combat.engage_max_s` |
| `combat.give_up_cooldown_ticks` | `combat.giveup_cooldown_ticks` |
| `shop.sell_weight_ratio`(=shops.SELL_WEIGHT_RATIO) | `economy.sell_weight_ratio`(단일 소스화) |
| `return.idle_seconds`(60) | 90(값 변경) |
- 로더는 두 이름 모두 허용(신규 우선). `shops.SELL_WEIGHT_RATIO` 하드코딩 제거 → config 경유.

### D3. 값 정본(canonical)
- **§8.3 값을 정본**으로 하고 §8.2 제약과 정합하도록 이미 교정함(루팅/무게·귀환·몰이).
- 비전 임계: `vision.yaml`(0.5/0.5)을 정본으로 하고 `constants.py` 부팅 기본값(0.7/0.7)을 **0.5로 수정**(config가 유일 소스).

### D4. Trust 계약
- 위치: **`engine/app/_03_world/trust.py`** (T2의 표기 채택; §2 표기 수정).
```python
class Trust(Enum): OK; DEGRADED; STALE; FAILED
class TrustMonitor:
    def update(self, *, snapshot, sweep_ok: bool, inventory_age_s: float,
               frame_ok: bool, lag_ms: float, cursor_ok: bool, focus_ok: bool) -> dict[str, Trust]: ...
    def gating(self) -> "Gating": ...   # 허용/금지 판정
```
- 저장: `Blackboard.trust: dict[str, Trust]`, `Blackboard.gating`.
- 게이팅: `mode_ticks` 진입부에서 `gating()`로 후보 필터(§7.2 표). 예외를 던지지 않고 후보를 **제거**한다.
- 일시정지 API: `BotController`에 **`request_pause(reason: str)` 신규 추가**(기존 `pause_user`와 별개, 내부 사유 기록). fail-safe는 `request_pause("trust_failsafe")`.

### D5. AdenaLedger 계약
```python
class AdenaLedger:
    def observe(self, adena: int, now: float) -> None: ...
    def note_event(self, cause: Literal["loot","sell","buy"], now: float) -> None: ...
    def net_per_hour(self) -> float: ...
    def adena_per_kill(self) -> float: ...
    def kills_per_hour(self) -> float: ...
```
- `adena` 출처: `InventoryState.adena`. 이벤트 귀속: 이벤트 직후 강제 스캔 델타.
- 저장: `Blackboard.ledger`(인스턴스). 노출: `debug_snapshot.build_runtime_snapshot`의 `overview`에 `net_adena_per_hour/adena_per_kill/kills_per_hour` 문자열.
- 강제 스캔 훅: 픽업(`ActionType.PICKUP` 처리 후), 판매/구매(`controller.last_shop_buy_ok` 세팅 지점) 직후 `LiveInventorySweep.poll(force=True)`.

### D6. 역할→액션(ActionType) 계약
- `ActionType`에 신규 추가: `SPELL_ATTACK`, `RETURN_TOWN`, `USE_ITEM`.
- `ActionIntent`에 필드 추가: `slot_id: str | None`(역할/슬롯 id), `target_id`는 기존 활용.
- 매핑:
  - `hp_potion/hp_potion_fast/mp_potion/depoison` → `USE_ITEM` + `slot_id`(해당 역할). (기존 USE_HP_POTION/USE_MP_POTION은 별칭으로 유지)
  - `heal/light/shield/attack_buff/haste(스킬일 때)` → `BUFF` + `slot_id`.
  - `teleport` → `TELEPORT`; `return_scroll` → `RETURN_TOWN`; `mother_tree` → `RETURN_TO_MOTHER_TREE`; `hp_to_mp` → `HP_TO_MP`; `talking_scroll` → `USE_TALKING_SCROLL`.
  - `spell_attack/control` → `SPELL_ATTACK` + `target_id`(대상 클릭 필요).
  - `pickup` → 기존 `PICKUP`(지상 아이템 **클릭**). **F4는 사용하지 않는다.**
- 실행기(`ActionExecutor.execute`): `slot_id`가 있으면 `_press_assigned_skill(slot_id)`; `SPELL_ATTACK`은 스킬 프레스 후 대상 content 클릭; 공유 마법 쿨(`spells.magic_cooldown_s`, §8.4 정본)을 모든 마법 역할에 적용.
- cast mode: `spell_box.cast_mode`(§9.6) — `double` 역할은 두 번 탭.

### D7. 파일 위치 확정
- `trust.py` → `engine/app/_03_world/trust.py`
- KB 데이터 → **`engine/app/_04_decision/data/`** 아래: `monster_kb.json`, `item_values.json`, `potion_kb.json`
- `economy.py / config_schema.py / thresholds.py / threat.py` → `engine/app/_04_decision/`
- T24 파일 목록에 위 전체 경로 사용.

### D8. KB/스코어링 계약
- KB 로더: `_04_decision/data/*.json`을 부팅 시 캐시 로드, 없으면 안전 기본(빈 dict, 밴드 통과). 디렉터리 미존재 시 생성 시도하며, 실패해도 빈 dict로 fail-safe(기동 오류 금지).
- 키 규칙: `monster_kb`는 species id(`monster_좀비`), `item_values`/`potion_kb`는 **아이템 이름**(`InventoryItem.name`) 우선, 없으면 id.
- `dps_prior`: `config.decision.combat.dps_prior_by_level: {level: dps}` 테이블(운영자 값)에서 조회, 없으면 선형 근사(`dps ≈ 20 + 5*level`). **정적 테이블, 학습 아님.**
- `t_kill = hp / max(1, dps_prior)`; `tier_value = monster_kb.tier`를 `item_values` 스케일로 환산(기본 tier*100).
- `sellable_value_est = Σ item_values.value*count` (보유 아이템).
- `skip_value_per_weight_min` 단위: `value / (weight_ratio*100)` (무게 1%당 가치).
- `hp_trend`: 최근 N초 hp_ratio 선형 기울기(측정).
- `closing_velocity`: `WorldObject.velocity`(비전) 또는 `world_rx/ry` 차분(메모리). 없으면 0.

### D9. T1/T3 스냅샷 키·검증
- 무게 키는 스냅샷 원시 키 `weight`, `maxWeight`(확인됨)이며 `PlayerState` 필드 `weight`, `max_weight` 로 매핑한다. 미존재 시 None(0 위조 금지).
- 검증: `0 ≤ hp ≤ max_hp`, `0 ≤ mp ≤ max_mp`, `1 ≤ level ≤ 99`, `pos ≠ (0,0)`, `weight ≤ max_weight`. 위반 시 STALE.

### D10. T12 범위(블로킹 대기 목록)
- 변환 대상: `_fixed_wait`, `select_skill_box` 대기, `_press_assigned_skill`의 마법 쿨 대기, `_shop_ui_wait`, `SHOP_ARRIVE_WAIT`, `ESCAPE_WAIT`. 각각 "다음 틱까지 유예" 상태로 기록.

### D11. T21 근본 원인·수정
- 버그는 **호출부**에 있음: `ui/debug_ui.py:626`, `ui/schedule_ui.py:5615`가 `Lamp.AMBER` 참조(미정의).
- 수정: 두 호출부를 `Lamp.YELLOW`로 교체(또는 `Lamp`에 `AMBER=YELLOW` 별칭 추가). `_refresh_operator` "순서 결함"은 근거가 없으므로 **수정 대상에서 제외**(재현 시에만 처리).

### D12. 이중 SLOT_ID 소스
- `SLOT_IDS`/기본 슬롯이 `_05_action/spell_box.py`와 `manmabot_v1/spell_defaults.py` 두 곳에 존재하고, `hotbar/inspect.py`가 후자로 역할 CSV를 검증한다.
- T22는 **두 곳을 동기화**하고, 가능하면 `spell_defaults`가 `spell_box`를 단일 소스로 참조하도록 정리한다.

### D13. DoD #12(A/B 20%) 검증 방법
- 세션 로그(채널 `config`+`economy`)에서 `net_adena_per_hour`를 구간별 산출. 변경 전/후 **동일 맵·동일 레벨밴드** 30분 이상 로그 비교. 자동 하네스가 없으면 로그 파서 스크립트(`scripts/compare_net_adena.py`)로 계산.

### D14. 잔여 확정 (2차 검증 B1~B5 + nit)
- **B1 상점**: `shop.potion_qty:150` 추가. 제약 `return_potion_count < potion_qty`, `return_arrow_count < arrow_qty`. `return_arrow_count`는 동적: `clamp(k·arrow_rate, 100, arrow_qty-1)`.
- **B2 키 통일**: `economy.loot_pickup_tiles` 단일 키(구 `pickup_tiles`, `player_mode.LOOT_PICKUP_TILES`는 별칭/이관).
- **B3**: `economy.hp_trend_window_s: 5` 추가(T14/T15/T17 공통 사용).
- **B4 파일 명시**: `ActionType` → `engine/app/_03_world/enums.py`; `ActionIntent` → `engine/app/_04_decision/types.py`.
- **B5 T12 검증**: 테스트 `tests/test_input_latency.py`(최대 틱 지연·입력 공백 측정). DoD#10 버프 가동률 = 세션에서 Σ(버프별 가동 초) / Σ(파밍 초) 로그 집계(≥95%).
- **nit1**: `hotbar` 섹션 실제 위치는 `decision.hotbar`(D1 우선). §9.6의 루트 표기는 예시로만.
- **nit2**: `pickup`은 지상 아이템 클릭(F4 미사용).
- **nit3**: `adena_only` = `loot_adena_weight_ratio` 초과 시 아데나만 루팅.
- **nit5**: A/B는 "30분 이상" **또는** "누적 300처치" 중 먼저 도달 시점까지로 한다.
## 17. 부록 E — 2차 검증 잔여문제 수정 (커뮤니티·가이드 근거)

> 출처: NC 공식 파워북(MP 회복 틱), 인벤(화살통/아이템 DB), 린클·게임팟·팔복소프트(물약/도감), 커뮤니티(요정 150물약+1000화살=무게50%↑, 거래소 미스릴화살 2아데나). 이 부록이 §16 D14를 대체한다.

### E1. 근거가 되는 게임 사실
- **무게와 재생**: "무게 게이지가 **50% 이하**이며 포만도 17% 이상일 때 MP 자연회복. 정지 15초/이동 32초/전투 64초마다." → 무게 50% 초과 시 회복 중단(유지력↓). ATS 49% 권장과 정합. **sell=0.49, loot_skip=0.40의 직접 근거.**
- **화살 무게**: 화살통(가죽=3200발, 수렵꾼=6400발)이 각각 무게 150/300 감소 → **화살 1발 ≈ 0.047(≈0.05), 무게 0 아님.**
- **휴대 실측**: 커뮤니티 "요정 물약 150개 + 화살 1000개 → 무게 50% 초과".
- **물약 무게**: 빨간8, 비취8, 주홍10, 맑은12, 파란7, 초록(촐기)23, 강화초록14, 엘븐와퍼4, 용기9, 엔트열매5.
- **버프 지속**: 초록 300s, 강화초록 1800s, 엘븐와퍼 480s, 용기 300s, 파란물약 600s tick, 변신 1200s, 에바 1800s.
- **화살 대미지/가격**: 화살 6/5, 은화살 7/6, 미스릴화살 10/9. 거래소 미스릴화살 500,000발=1,000,000아데나 → **약 2아데나/발**. (커뮤니티 은화살 5발/1아데나 수준)

### E2. 잔여문제 수정 (B1~B5)
- **B1 상점/자원 파라미터화**:
  - `shop.potion_qty: 150`(커뮤니티 140~150), `shop.arrow_qty`는 **무게 예산으로 산출**:
    `arrow_qty = floor((max_weight·k_carry − Σ potion_weight·수량) / arrow_unit_weight)`.
    기본값 1000(무게≈50). `arrow_unit_weight: 0.05`.
  - `return_arrow_count = clamp(k·arrow_rate, 100, arrow_qty−1)` (동적).
  - 제약: `return_potion_count < potion_qty`, `return_arrow_count < arrow_qty`.
- **B2 키 통일**: `economy.loot_pickup_tiles` 단일 키(구 `pickup_tiles`, `player_mode.LOOT_PICKUP_TILES` 별칭/이관).
- **B3**: `economy.hp_trend_window_s: 5` (MP 틱 15~64s·물약 딜레이 대비 교전 되먹임에 충분).
- **B4 파일 명시**: `ActionType` → `engine/app/_03_world/enums.py`; `ActionIntent` → `engine/app/_04_decision/types.py`.
- **B5 검증**: `tests/test_input_latency.py`(T12); DoD#10 버프 가동률 = Σ(버프별 가동 초)/Σ(파밍 초) 로그 집계(≥95%).

### E3. 값 교정(§8 대비 변경)
| 키 | 변경 | 근거 |
|---|---|---|
| economy.arrow_unit_cost | 0 → **2** | 미스릴화살 2아데나/발 → 비용 인지 유효 |
| economy.arrow_unit_weight | 신규 **0.05** | 화살통 3200발=150 |
| economy.hp_trend_window_s | 신규 **5** | 틱/딜레이 정합 |
| shop.potion_qty | 신규 **150** | 커뮤니티 |
| shop.arrow_qty | 999 → **1000(무게 예산 산출)** | 무게 50% |
| shop.return_arrow_count | 300 → **dynamic** | 소모율 기반 |
| spells.buff_recast_margin | s=10 → **ratio 0.05 + min 10s** | 버프 300~1800s |

### E4. nit 확정
- `hotbar` 실제 위치는 `decision.hotbar`(D1 우선).
- `pickup` = 지상 클릭(F4 미사용).
- `adena_only` = `loot_adena_weight_ratio` 초과 시 아데나만 루팅.
- A/B는 30분 **또는** 누적 300처치 중 먼저 도달 시점까지.

### E5. 무게 상한 운용(근거 반영)
- 파밍 중 `weight_ratio`를 **0.49 이하** 유지(MP/HP 재생 보존). 0.49 도달 시 판매 트립.
- 화살·물약 구매량은 "무게 예산 − 장비/루팅 여유"로 계산, 고정값 999 사용 금지.
