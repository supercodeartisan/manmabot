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
