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
