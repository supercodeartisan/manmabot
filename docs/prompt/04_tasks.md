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
