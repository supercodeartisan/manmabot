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
