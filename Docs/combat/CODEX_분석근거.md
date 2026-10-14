# [CODEX 작성] 코드 근거와 검증 기록

분석일: 2026-09-28 · [설명서](CODEX_전투로직설명서.md) · [구성도](CODEX_전투로직구성도.html)

## 범위와 한계

Python 실시간 루프, 상태 전이, HP/MP/상점/공격/루팅/막힘 복구와 관련 설정을 추적했다. 기존 설명서와 코드 주석을 보조 자료로 읽되 실제 조건식을 우선했다. 계정 비밀번호나 인증 정보를 문서에 복사하지 않았다. 실게임, EXE 빌드 일치, DLL 내부 정확성 및 NPC 착지는 검증하지 않았다.

다른 편집기와 같은 폴더를 사용하므로 소스 전체를 불변 스냅샷으로 잠그지는 않았다. 이 기록 생성 시점의 해시와 비민감 설정 일부는 [CODEX_분석스냅샷.json](CODEX_분석스냅샷.json)에 있다. 이후 Cursor에서 변경하면 해당 파일 해시가 달라질 수 있다. 줄 번호는 이 기록 생성 시점 기준이다.

## 기존 테스트 실행 결과

관련 10개 파일: **168 passed, 2 failed (총 170개, 9.76초)**.

```powershell
$env:PYTHONPATH = "$PWD\engine;$PWD"
$env:PYTHONDONTWRITEBYTECODE = '1'
& .\python\python.exe -m pytest -p no:cacheprovider tests/test_hp_actions.py tests/test_shop_trip.py tests/test_combat_focus.py tests/test_ground_loot.py tests/test_loot_stand.py tests/test_unstick.py tests/test_dungeon_farming.py tests/test_hunt_attack_settings.py tests/test_buff_cadence.py tests/test_weight_source.py -q
```

실패:

- `test_combat_blocked_unstick_sweeps_around_click`: `try_combat_blocked_unstick(...) is True` 기대에 False 반환.
- `test_combat_blocked_unstick_resets_when_monster_moves`: `combat_block_tile` 키가 지워져 KeyError.

`test_unstick.py`만 단독으로 재실행: **25 passed, 2 failed (총 27개, 0.54초)**. 위와 동일한 두 사례다.

원인 추적: 테스트의 몬스터는 메모리 상대 거리가 10/12칸이지만 기본 화면 위치가 화면 안으로 분류된다. `in_attack_click_range()`의 화면 안 우선 True 분기 때문에 `try_combat_blocked_unstick()`가 시계를 지우고 조기 반환한다. 기대한 5초 우회 경로까지 가지 않는다. 따라서 다른 테스트 파일이 먼저 실행되어야 발생하는 현상은 아니다. 화면 안 대상 우선 정책 자체가 의도된 변경인지, 테스트를 고쳐야 하는지는 후속 합의가 필요하다. 이번에는 테스트나 런타임 소스를 수정하지 않았다.

## 입력 없는 조건 재현

실제 게임 객체 대신 메모리 수치만 가진 대체 객체를 만들어 함수 반환값을 확인했다. 게임 실행이나 마우스·키보드 입력은 없다.

- HP 99/100, MP 10/100, `retreat_for=return`: `retreat_exit_ready=True`.
- 같은 수치, `retreat_for=mp`: `retreat_exit_ready=False`.
- 몬스터 상대 위치 (12,0), 기본 화면 UV: `in_attack_click_range=True`.
- 같은 몬스터 화면 UV를 (2,2)로 화면 밖에 둠: `in_attack_click_range=False`.

이는 MP 후퇴 원인 구분과 화면 안 우선 분기가 실제 함수 반환에 영향을 준다는 증거다. 실게임 문제 원인의 확정이나 전체 시뮬레이션은 아니다.

## 구성도 검사

- 7개 탭, 7개 SVG의 XML 문법, HTML ID 중복, 기준값 전환용 데이터, 연결 문서 파일 존재, UTF-8 대체문자 부재, 외부 자원 의존성 부재를 정적으로 검사했다.
- 전체/사냥/HP/보급/전투·루팅/후퇴/이동·막힘의 7개 상세도를 제공한다.
- Node.js의 `new Function`으로 HTML 내 전환 스크립트의 JavaScript 문법 검사를 통과했다. DOM/렌더링 검증은 아니다.
- 저장 프로필/엔진 기본값 선택, 확대, 전체 인쇄 버튼이 포함된다. 엔진 기본값 보기는 현재 실행값을 의미하지 않는다.
- **브라우저 자동 보안 검토가 file:// 프로토콜 열기를 거부하여 실제 브라우저 렌더링·클릭 검증은 수행하지 못했다.** 정적 검사 통과를 화면 검증 완료로 해석하지 않는다.
- 재생성: `python/python.exe docs/CODEX_구성도생성.py`. 정적 검사 및 근거 갱신: `python/python.exe docs/CODEX_정적검증.py`. 이 도구들은 CODEX 문서 파일만 기록하며 게임을 시작하거나 입력하지 않는다. 과거 테스트 실행 결과는 자동 재실행하지 않는다. 구성도의 문구·분기·저장값은 분석 시점 내용을 수동으로 정의한 것이므로 소스나 프로필 변경 시 생성 도구의 데이터와 설명서도 함께 갱신해야 한다.

## 기존 설명서/주석과 다른 주요 지점

1. HP 행동 순서는 UI가 변경할 수 있다. 저장 순서는 힐→빨간 물약→텔레포트→안전지대→나무다.
2. 공격 커서 실패로 몬스터를 횟수 기반 포기하지 않는다. 4회 포기는 아이템에 적용된다.
3. 화면 안 몬스터는 8칸을 넘어도 클릭 가능 분기가 먼저다.
4. 무게는 메모리가 우선이다. HUD 전용으로 설명하면 잘못이다.
5. 이동 모드도 사냥터 진입/교대/순찰 목적이면 교전·루팅을 한다.
6. 현재 V1 시작은 별도 MP 후퇴를 강제로 끈다. Fix/Return MP 귀환과 구분해야 한다.
7. 막힘 탈출은 텔레포트 우선, 불가하면 두루마리다. 상점/전투에는 예외가 있다.
8. 사냥터별 3600초 설정, 무게 판매 30%, 화살 100/100, 물약 1/3은 YAML 기본값과 다르다.
9. 상점 성공 피드백은 구매 수량 증가가 아니라 UI 절차 완료 기준이다.
10. 전투 중 갇힘 검사 생략은 벽시계 자체 정지와 같지 않다.

## 함수별 코드 위치

- [manmabot_v1/bot_controller.py](../manmabot_v1/bot_controller.py)
  - `_run_bot_loop`: 589행
  - `_commit_hotbar_scan`: 250행

- [manmabot_v1/task_runtime.py](../manmabot_v1/task_runtime.py)
  - `apply_runtime_settings`: 39행

- [manmabot_v1/hp_actions.py](../manmabot_v1/hp_actions.py)
  - `to_engine_actions`: 328행
  - `normalize_hp_actions`: 197행

- [engine/app/_04_decision/manager.py](../engine/app/_04_decision/manager.py)
  - `decide`: 43행
  - `apply_cursor_verify_feedback`: 166행

- [engine/app/_04_decision/configure.py](../engine/app/_04_decision/configure.py)
  - `configure_decision`: 16행

- [engine/app/_04_decision/behaviors/mode_ticks.py](../engine/app/_04_decision/behaviors/mode_ticks.py)
  - `tick_mode`: 1296행
  - `tick_farming`: 1055행
  - `tick_traveling`: 640행
  - `tick_retreating`: 478행
  - `_tick_dungeon_farming`: 1168행
  - `_maybe_return_on_vitals`: 158행
  - `_maybe_return_on_idle`: 181행
  - `_maybe_emergency_teleport`: 117행
  - `_maybe_confined_escape`: 615행
  - `_tick_newbie_training`: 836행
  - `_maybe_post_shop_farm_return`: 223행
  - `_maybe_low_mp_to_safe`: 352행

- [engine/app/_04_decision/behaviors/mode_actions.py](../engine/app/_04_decision/behaviors/mode_actions.py)
  - `apply_hp_actions`: 775행
  - `apply_inplace_hp_support`: 866행
  - `_hp_action_availability`: 506행
  - `_execute_hp_action`: 553행
  - `_can_teleport_now`: 472행
  - `can_active_hp_recover`: 460행
  - `farm_loot_or_combat`: 1199행
  - `maybe_escalate_teleport_to_safe`: 990행
  - `_effective_loot_mode`: 47행
  - `_force_safe_scroll_if_due`: 947행

- [engine/app/_04_decision/mode_control.py](../engine/app/_04_decision/mode_control.py)
  - `begin_retreat`: 283행
  - `retreat_exit_ready`: 428행
  - `finish_retreat`: 453행
  - `update_death_timer`: 187행
  - `death_confirmed`: 215행

- [engine/app/_04_decision/hp_actions.py](../engine/app/_04_decision/hp_actions.py)
  - `default_hp_actions`: 61행
  - `pick_hp_action`: 120행

- [engine/app/_04_decision/shops.py](../engine/app/_04_decision/shops.py)
  - `resolve_shopping_behavior_id`: 94행
  - `resolve_sell_behavior_ids`: 133행
  - `buy_qty_for_behavior`: 172행
  - `affordable_hp_potion_qty`: 186행

- [engine/app/_04_decision/shop_trip.py](../engine/app/_04_decision/shop_trip.py)
  - `shopping_blocks_teleport`: 42행
  - `bag_weight_ratio`: 73행
  - `choose_shopping_behavior`: 134행
  - `tick_shop_trip`: 266행
  - `_at_shop`: 217행

- [engine/app/_03_world/memory_inventory.py](../engine/app/_03_world/memory_inventory.py)
  - `inventory_state_from_snapshot`: 93행
  - `refresh_shop_needs_from_inventory`: 166행

- [engine/app/_03_world/memory_sync.py](../engine/app/_03_world/memory_sync.py)
  - `game_to_nav`: 49행
  - `player_from_snapshot`: 84행

- [engine/app/_04_decision/combat_query.py](../engine/app/_04_decision/combat_query.py)
  - `in_attack_click_range`: 130행
  - `object_on_screen`: 174행
  - `list_attackable`: 232행
  - `nearest_attackable`: 450행
  - `memory_target_gone`: 39행
  - `_is_adena`: 284행

- [engine/app/_04_decision/behaviors/combat.py](../engine/app/_04_decision/behaviors/combat.py)
  - `rebind_sticky_target`: 235행
  - `continue_sticky_combat`: 255행
  - `advance_engage_or_give_up`: 294행

- [engine/app/_04_decision/attack_feedback.py](../engine/app/_04_decision/attack_feedback.py)
  - `note_cursor_verify_fail`: 39행

- [engine/app/_04_decision/behaviors/unstick.py](../engine/app/_04_decision/behaviors/unstick.py)
  - `try_unstick_escape`: 286행
  - `try_combat_blocked_unstick`: 499행
  - `try_enter_farm_detour`: 246행
  - `try_confined_escape`: 357행
  - `note_confined_progress`: 332행

- [engine/app/_04_decision/behaviors/travel.py](../engine/app/_04_decision/behaviors/travel.py)
  - `travel_arrived`: 68행
  - `start_travel`: 41행
  - `emit_travel_hop`: 159행

- [engine/app/_04_decision/behaviors/loot_hop.py](../engine/app/_04_decision/behaviors/loot_hop.py)
  - `mark_loot_clicked`: 54행
  - `loot_awaiting_memory_gone`: 70행
  - `tick_loot_item`: 319행

- [engine/app/_04_decision/talking_scroll.py](../engine/app/_04_decision/talking_scroll.py)
  - `emit_talking_scroll`: 303행
  - `apply_talking_scroll_arrival`: 345행
  - `farm_return_scroll_spot`: 419행
  - `player_on_selected_map`: 456행

- [engine/app/_04_decision/spells.py](../engine/app/_04_decision/spells.py)
  - `can_cast_spell`: 93행
  - `maybe_heal_after_teleport`: 110행
  - `due_buff`: 216행
  - `try_unstick_teleport`: 282행

- [engine/app/_04_decision/hunt_area.py](../engine/app/_04_decision/hunt_area.py)
  - `rotate_reason`: 71행

- [engine/app/_04_decision/species_rules.py](../engine/app/_04_decision/species_rules.py)
  - `is_avoided_species`: 204행
  - `is_newbie_player`: 83행

- [engine/app/_05_action/controller.py](../engine/app/_05_action/controller.py)
  - `execute`: 179행
  - `_shop_buy_arrows`: 725행
  - `_shop_run_behavior`: 754행
  - `_teleport`: 674행

- [manmabot_v1/shopping/runtime.py](../manmabot_v1/shopping/runtime.py)
  - `execute_calibrated_buy`: 322행
  - `execute_calibrated_sell`: 373행
