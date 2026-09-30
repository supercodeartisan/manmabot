# 의사결정 수정 로그 — 악순환 분석

이 문서는 **한 곳의 텔레포트/회복/이동 규칙을 고치면 다른 모드가 같이 바뀌는** 이유를 기록한다.
이후 로직 수정은 이 문서의 **영향 고지 → 사용자 동의 → 구현 → 결과 기록** 순서로만 한다.

마지막 갱신: 2026-09-29 (CN59)

---

## 1. 작업 규칙 (2026-09-27 사용자 지시)

1. 수정 전에 **다른 기능에 미치는 영향**을 사용자에게 알린다.
2. **동의를 받은 뒤에만** 코드를 바꾼다.
3. 수정 과정과 사용자 피드백을 이 문서에 남긴다.
4. 증상만 때우지 말고, 공유 경로를 보고 악순환이 다시 열리는지 적는다.

고지 형식:

```
의도: (무엇을 바꾸려 하는지)
공유 함수: (같이 쓰이는 함수/모드)
영향받는 기능: (사냥 / 이동 / 후퇴 / 로그인 등)
의도하지 않은 부작용 후보:
동의 질문: 이 범위로 진행할까요?
```

---

## 2. 악순환의 구조

겉으로 보이는 패턴은 같다.

```
실기 관찰 → “지금은 이게 틀렸다” → 공유 함수에 가드/예외 추가
        → 다른 상황에서 반대 증상 → 같은 함수에 반대 가드 추가
        → 플래그가 늘고 조합이 예측 불능 → 다시 실기 관찰
```

원인은 “텔레포트가 많다/적다”가 아니다.
**탈출·회복·정지 해제가 모드별로 분리되지 않고, 같은 싱크를 여러 의도가 나눠 쓰기 때문**이다.

### 2.1 공유 싱크 (한 함수가 여러 의도)

| 공유 함수 | 쓰는 의도 | 파일 |
|---|---|---|
| `try_unstick_escape` | 이동 360° 실패, 3회/20초, 저HP, 농장 진입 경로 차단 | `unstick.py` ← `travel.py`, `search_hop.py`, `loot_hop.py` |
| `try_movement_unstick` | 이동 정지 2.5초 360°, `allow_escape`로 TP 허용/차단 | 위와 동일 |
| `begin_retreat` | HP 스파이크, HP 게이트, 귀환, MP 탈출, 세계수, 대기 중 10% 비상, 자연회복 피격 | `mode_control.py` ← `mode_actions.py`, `mode_ticks.py` |
| `_execute_hp_action` | 사냥 중 HP 순서, 스파이크, 자연회복 피격 탈출 | `mode_actions.py` |
| `apply_inplace_hp_support` | 후퇴 대기 힐/물약, **그리고** 자연회복 피격 탈출 | `mode_actions.py` ← `tick_retreating`, `apply_hp_actions(RETREATING)` |
| `apply_hp_actions` | 이동/사냥/던전 매 틱 HP | `mode_ticks.py` |
| `click_purple_control` / 로그인 템플릿 | 이메일, 비밀번호, Next, 기타 Purple 클릭 | `autologin/bot/base.py` |

모드(`TRAVELING` / `FARMING` / `RETREATING`)는 갈라져 보여도,
실제 클릭(텔레포트, 말하는 두루마리, 힐, 물약)은 위 싱크에서 다시 만난다.

### 2.2 같은 숫자를 다른 뜻으로 재사용

| 값 | 처음 뜻 | 나중에 붙은 뜻 |
|---|---|---|
| 2.5초 정지 | 이동 중 막힘 → 360° | 농장 진입 A* 실패 대기, (한때) 근접 접근 전투 |
| 반경 2 / 360° | 이동 막힘 해제 | “텔레포트는 이것 실패 후에만”이라는 전역 규칙처럼 읽힘 |
| HP 30% | 텔레포트 `hp_below` | 언스틱 긴급 탈출, 스파이크와 혼동 |
| HP 50% | 소모품 없을 때 후퇴 종료 | 자연회복 대기 = 안전하다는  implicit 가정 |
| `allow_escape` / `allow_outside_farm` / `urgent` / `retreat_starters` | 한 케이스를 막거나 열기 | 다음 케이스가 같은 플래그를 우회하거나 상속 |

숫자가 같아 보이면 에이전트와 사용자 모두 “같은 기능”으로 착각한다.
실제로는 **의도(이동 막힘 / 전투 / 농장 밖 / 회복 대기)** 가 다른데 타이머만 공유한다.

### 2.3 피드백이 반대 방향으로 교차

같은 주(2026-09-27) 안에서 사용자 요청은 서로 반대처럼 들린다.
요청 자체는 모순이 아니다. **상황 라벨이 코드에 없기 때문에** 한 패치가 다른 상황을 덮는다.

| 방향 | 사용자 말 | 코드가 한 일 | 다음 부작용 |
|---|---|---|---|
| TP 줄이기 | 근접 2.5초 정지는 언스틱 TP 금지 | `try_combat_approach_unstick` 비활성 | 접근 중 진짜 막힘은 다른 경로에 의존 |
| TP 줄이기 | Start 직후 TP 금지. 먼저 농장 진입/공격/루팅 | 농장 밖 TP 차단, 첫 틱 A* 실패로 즉시 TP 안 함 | “농장 진입 경로 차단”에서 TP가 사라짐 |
| TP 조건 | 텔레포트는 반경 2 클릭이 실패할 때만 | 문서/설명은 그렇게, 코드는 3회/20초·저HP 스킵 유지 | 사용자 기대와 구현이 어긋남 |
| TP 늘리기 | 농장 진입 경로 차단이면 TP/두루마리 (2.5초 후) | `allow_outside_farm=True` + 2.5초 후 `try_unstick_escape` | 농장 밖 탈출이 다시 열림. Start 직후 가드와 긴장 |
| TP 늘리기 | 자연회복 중 피격으로 HP가 계속 줄면 TP/두루마리, HP 순서 따름 | `apply_inplace_hp_support`에 탈출 훅, `hp_below` 무시 | 후퇴 대기·힐/물약 경로가 같은 함수를 씀. 사냥 중 소모품 없음은 의도적으로 제외 |

악순환의 한 바퀴:

1. “너무 일찍 텔레포트”를 막으려고 **공유 탈출 함수에 가드**를 넣는다.
2. 가드가 **필요한 텔레포트**까지 막는다.
3. 필요한 케이스만 열려고 **같은 함수에 예외 플래그**를 넣는다.
4. 예외가 **다른 모드의 이른 텔레포트**를 다시 살린다.
5. 테스트는 플래그를 모킹해서 통과하고, 실기는 다른 호출부가 같은 함수를 탄다.

### 2.4 근본 원인 (종합)

1. **정책 테이블이 없다.**  
   “누가 / 어느 모드에서 / 몇 초 후 / 360° 후에 / HP 몇 %에서 / 농장 밖에서 텔레포트·두루마리를 써도 되는가”가 한곳에 없고, if 플래그로 흩어져 있다.

2. **증상 패치.**  
   실기에서 본 한 문장을 공유 함수에 바로 넣는다. 호출부(travel / combat / retreat / loot / search)를 먼저 가르지 않는다.

3. **의도 라벨 없음.**  
   로그/상태에 `unstick teleport`만 보이고, `enter_farm_blocked` / `natural_recover_under_fire` / `sweep_exhausted`가 사용자에게 같은 말로 보인다.

4. **동의 없이 구현.**  
   영향 범위를 고지하지 않아, 사용자는 다음 실기에서 다른 기능이 깨진 뒤에야 안다. 그때 또 반대 패치가 들어온다.

5. **테스트가 결합을 숨긴다.**  
   `allow_escape`, `can_active_hp_recover`, `_execute_hp_action`을 테스트에서 바꿔 끼우면, 실제 호출 그래프의 회귀는 통과한다.

6. **로그인 쪽 같은 패턴.**  
   Purple 클릭을 한 함수로 통일 → 이메일 필드가 Next로 오인 → 필드 클릭 복구 → 대기/순서 추가.  
   “검증을 한곳으로”가 “모든 클릭이 같은 실패를 상속”으로 바뀐다.

---

## 3. 피드백·수정 타임라인 (2026-09-27 전후)

날짜는 세션 기준. 인용이 아닌 **요청의 뜻**만 적는다.

| # | 사용자 피드백 | 에이전트가 한 수정 | 고지/동의 | 다른 기능 영향 (사후) |
|---|---|---|---|---|
| L1 | Purple 클릭을 템플릿 확인 후로 통일 | `click_purple_control` 통합 | 계획에 “yes” | 이메일/비밀번호가 Next로 매칭되거나 미클릭 |
| L2 | Email/Password가 한 번도 안 눌림 | CTA 상대좌표 + 확정 저장좌표 복구 | 없음 | 로그인 분기가 다시 갈라짐. 통합의 이점이 희석 |
| L3 | 이메일 포커스·입력 후 1초 뒤 Next | 이메일 스텝 순서/대기 | 없음 | Next 타이밍만 변경. 비밀번호 스텝은 별도 |
| U1 | 언스틱 텔레포트는 언제인가? (설명 요청) | 설명 | — | — |
| U2 | 근접 접근 2.5초 정지 + 거리≥2는 언스틱 TP 금지 | 접근 전투 언스틱 비활성 | 없음 | 전투 중 2.5초 360°가 사라짐. 막힘 전투는 3초 몬스터 타일 경로만 남음 |
| U3 | Start 직후 언스틱 TP. 농장 진입/공격/루팅이 먼저 | 첫 틱 즉시 TP 제거, 농장 밖 탈출 제한 | 없음 | 농장 밖·경로 실패에서 TP가 부족해짐 |
| U4 | TP는 반경 2 클릭이 실패할 때만? | “대체로 그렇다 + 스킵 2개” 설명. 스킵은 유지 | 없음 | 기대(항상 360° 후)와 구현(저HP·3회 스킵) 불일치 유지 |
| U5 | 2.5초+반경2는 **이동 중만**. 공격/전투 금지 | 접근 전투 경로 재확인/유지 | 없음 | U2와 같음. 전투 막힘은 `try_combat_blocked_unstick`에 남음 |
| U6 | “enter farm, path blocked”는 언제인가? | 설명 | — | — |
| U7 | 그때는 TP/두루마리. 첫 Start 틱이 아니라 약 2.5초 후 | `try_unstick_escape(urgent, allow_outside_farm)` | 없음 | U3 가드의 예외. 농장 밖 탈출이 조건부로 부활 |
| H1 | 자연회복 중 피격으로 HP가 계속 줄면 TP/두루마리. HP 동작 순서 | `escape_natural_recover_under_attack`를 `apply_inplace_hp_support`에 연결. `hp_below` 무시 | **없음 (위반)** | 아래 §4 |

---

## 4. 이미 들어간 변경 — 사후 고지 (H1, 동의 없이 구현됨)

**의도:** 후퇴 대기에서 힐/물약/회복 아이템이 없고, 근처 몬스터 때문에 HP가 계속 떨어지면 안전 지대로 나간다.

**공유 함수:** `apply_inplace_hp_support`, `_execute_hp_action` → `begin_retreat`, `tick_retreating`

**영향받는 기능**

| 기능 | 예상 영향 |
|---|---|
| 후퇴 대기 (자연회복 50%) | HP가 ~1.5초/2% 이상 떨어지고 근처 몬스터가 있으면, 30% 게이트 전이라도 TP/두루마리 |
| 후퇴 대기 (힐/물약 있음) | `can_active_hp_recover`가 참이면 탈출 안 함. 기존 힐/물약 유지 |
| 사냥 중 전투 | 이 훅은 `apply_inplace`만. 사냥 소모품 없음 + 작은 피격으로 TP하지 않음 |
| HP 스파이크 (20%/0.5초) | 그대로. 히스토리 창만 0.5초 → 1.5초 보관으로 늘림 |
| 10% idle emergency | 그대로. 자연회복 피격이 더 일찍 가로챌 수 있음 |
| HP 동작 순서 | 켜진 텔레포트 → 안전지대(두루마리) → 세계수 순. `hp_below`는 이 탈출에서만 무시 |
| 상점 여행 | `shopping_blocks_teleport`면 탈출 안 함 |

**의도하지 않은 부작용 후보**

- 후퇴 지점이 아직 안전하지 않은데 HP가 조금 출렁이면 두루마리/TP가 반복될 수 있다.
- `_execute_hp_action("teleport")`는 실패 시 두루마리로 넘어간다. 순서에서 텔레포트만 켠 경우에도 두루마리가 나갈 수 있다.
- HP 히스토리 보관이 1.5초로 늘어서 스파이크 판정 샘플이 조금 더 길어진다.

이 변경을 **되돌리거나 가드를 더 조일지**는 다음 실기 피드백과 동의가 필요하다. 여기서 추가 패치하지 않는다.

---

## 5. 앞으로 패치하지 말고 먼저 합의할 것

공유 싱크를 또 고치기 전에, 아래를 **정책**으로 고정하는 편이 악순환을 끊는다.
아직 코드로 옮기지 않는다.

1. 텔레포트/두루마리 **허용 표**를 모드×의도별로 한곳에 적는다.
2. 2.5초·반경 2·HP %는 **의도마다 별 이름**을 쓴다. 같은 숫자를 다른 뜻에 재사용하지 않는다.
3. 새 요청이 “TP 해라 / 하지 마라”이면, 먼저 표의 어느 칸인지 고지하고 동의를 받는다.
4. 실기 로그 reason을 `unstick teleport` 하나가 아니라 의도 라벨로 남긴다.

---

## 6. 변경 기록

### CN01 — 2026-09-27
요청: HP가 안전지대(말하는 두루마리) 기준 이하인데 두루마리가 나가지 않음.
고지한 영향: 안전지대 칸은 랜덤 텔레포트 없이 두루마리만. 텔레포트 칸·언스틱·앞선 힐/물약/월드 트리는 그대로.
사용자 동의: 예
구현: `_execute_hp_action("safe_zone")`에서 텔레포트 선시도 제거. `prefer_scroll=True`, `allow_teleport=False`만 사용.
결과(실기/테스트): `tests/test_hp_actions.py`에 텔레포트 슬롯이 켜져 있어도 안전지대=두루마리 테스트 추가.
악순환 여부: 공유 싱크(`begin_retreat`)에 새 플래그를 넣지 않음. 안전지대 실행 경로만 닫음(텔레포트 선점 제거).

### CN02 — 2026-09-27
요청: 대상 몬스터 타일이 3초 안 바뀔 때 주변 2타일 360° 클릭을 제거하고, 죽을 때까지 공격만 유지.
고지한 영향: 전투 막힘 언스틱만 끔. 이동 2.5초 360°, 농장 진입 경로 차단 TP, HP 탈출, sticky kill은 그대로.
사용자 동의: 예 (명시 요청)
구현: `try_combat_blocked_unstick`를 항상 False. `continue_or_start_combat`에서 호출 제거.
결과(실기/테스트): `tests/test_unstick.py`에서 전투 360°가 나가지 않는지 확인.
악순환 여부: 공유 이동 언스틱을 열거나 닫지 않음. 전투 호출부만 끊음.

### CN03 — 2026-09-27
요청: 힐/빨간 물약이 없으면 후퇴를 50%에서 종료. HP 동작 순서 기준 이하면 지연 없이 해당 동작.
고지한 영향: 후퇴 종료 판정만 라이브 핫바 기준으로 좁힘. 후퇴 중 힐/물약을 90%까지 끌어올리지 않음. 후퇴에서도 텔레포트/두루마리/트리가 사용자 `hp_below`로 나감. 사냥 중 HP 순서는 그대로.
사용자 동의: 예 (명시 요청)
구현: `can_active_hp_recover`는 핫바의 힐 스킬 또는 실제 회복 아이템. `apply_inplace_hp_support`는 사용자 게이트 + 후퇴 스타터.
결과(실기/테스트): Setup 힐만 켜진 경우 50% 종료 테스트 추가.
악순환 여부: 후퇴 대기와 HP 순서를 같은 게이트로 맞춤. 새 플래그 없음.

### CN04 — 2026-09-27
요청: 바닥 아이템 클릭 확인 후 대기 0.5s → 0.9s.
고지한 영향: 루팅 idle만 길어짐. 사냥/이동에서 줍기 확인 후 0.9초 정지. 전투 대상 선정, HP, 로그인, 언스틱은 그대로.
사용자 동의: 예 (명시 요청)
구현: `LOOT_PICKUP_SETTLE_S = 0.9`.
결과(실기/테스트): `tests/test_loot_stand.py` settle idle 유지.
악순환 여부: 공유 탈출/회복 싱크를 건드리지 않음.

### CN05 — 2026-09-27
요청: 농장 진입 경로 차단 시 먼저 반경 5타일 보행 가능 칸을 둘러보고, 그때도 길이 없으면 기존 탈출. HP 순서는 힐/포션/TP가 두루마리보다 앞선 현재 설정을 유지.
고지한 영향: enter/next farm A* 실패만 5타일 우회. 전역 `TRAVEL_UNSTICK_RADIUS`(3)와 이동/수색/루팅 360°는 그대로. HP 동작 순서 코드는 그대로.
사용자 동의: 예
구현: `try_enter_farm_detour`. 반지 소진(또는 보행 칸 없음) 뒤에만 `try_unstick_escape`.
결과(실기/테스트): `tests/test_unstick.py` 우회 클릭 후 탈출, 이동 반경 회귀.
악순환 여부: 공유 이동 언스틱 반경을 바꾸지 않음. 농장 진입 호출부만 분리.

### CN06 — 2026-09-27
요청: 샘플 비헤이비어(Practice)는 상점 두루마리가 되는데, Start 본 루프는 잘 안 됨.
고지한 영향: 상점 여행만 Practice와 맞춤. 두루마리 클릭 후 같은 맵 도보(`begin_travel` PURPOSE_SHOP)를 시작하지 않고 착지 대기. 두루마리 키/리스트 대기는 Practice와 동일(0.25/0.4/0.2). 후퇴·언스틱·HP·로그인 싱크는 그대로. 두루마리가 없거나 실패한 경우에만 기존처럼 같은 맵 도보.
사용자 동의: 샘플은 되고 본 프로젝트가 안 된다는 수정 요청으로 처리
구현: `tick_shop_trip` 스크롤 후 walk 제거. `_use_talking_scroll`을 Practice `_open_talking_scroll_and_click`과 동일 순서.
결과(실기/테스트): `tests/test_shop_trip.py`에 스크롤 우선·착지 대기 테스트 추가.
악순환 여부: `begin_retreat` / `try_unstick_escape` / HP 싱크에 플래그 없음. 상점 여행 호출부만 닫음(스크롤 직후 도보).

### CN07 — 2026-09-27
요청: 어떤 경우든 아이템 획득 우선. 예외는 (1) 아직 안 죽은 sticky 몬스터 (2) 아이템으로 걷는 중 반경 5타일 몬스터. 처치 후에 다시 줍기.
고지한 영향: `farm_loot_or_combat`만. 기존 4×5 박스 선교전을 제거. 후퇴는 계속 비전투. HP 4×5 근접 판정·언스틱·상점·로그인은 그대로.
사용자 동의: 예 (명시 요청)
구현: `LOOT_APPROACH_THREAT_TILES=5`. `loot_approach_active`일 때만 5타일 선교전. 그 외에는 루팅 후 원거리 교전.
결과(실기/테스트): `tests/test_combat_focus.py` 루팅 우선·걷다 5타일 끊기·sticky 유지.
악순환 여부: 공유 탈출/HP 싱크에 플래그 없음. 전투-루팅 호출부 순서만 바꿈.

### CN39 — 2026-09-28
요청: 포위 텔레포트는 메모리 전체가 아니라 플레이어 2타일 안 몬스터가 4마리 이상일 때만.
고지한 영향: `_maybe_emergency_teleport`의 포위 카운트만. `count_attackable`·HP 텔레포트·이동 갇힘 TP·전투 막힘·로그인·상점은 그대로. PK 유저 탈출은 그대로 우선.
사용자 동의: 예 (명시 요청)
구현: `count_monsters_within_tiles` + `SURROUND_TILES=2`. 산 몬스터만. 시체·허수아비·자는 골렘 제외. 경로/종 필터 없음.
결과(실기/테스트): `tests/test_combat_focus.py` 2타일 4마리만 TP, 3+원거리 1은 안 탐.
악순환 여부: 공유 탈출/HP 싱크에 플래그 없음. 포위 반경만 닫음.

### CN38 — 2026-09-28
요청: 전투 막힘 텔레포트 해제. 공격해도 몬스터 칸이 2초 안 움직이면 공격 방향에서 약 2타일 옆으로 이동 후 공격. 그래도 안 되면 다른 몬스터.
고지한 영향: `try_combat_blocked_unstick`만. 클릭 사거리 안에서도 동작. 360° 몬스터 칸 스윕·`try_unstick_escape` 호출 없음. 이동/수색 갇힘 TP·HP·로그인·상점·sticky 처치 확정은 그대로.
사용자 동의: 예 (명시 요청)
구현: 2초 시계. 공격선 수직 2타일 걷기(`sidestep combat block`). 한 번 옆걸음 후에도 2초 무이동이면 `give_up_target`.
결과(실기/테스트): `tests/test_unstick.py` 2초 대기·옆걸음·재실패 시 포기.
악순환 여부: 공유 탈출 싱크에 플래그 없음. 전투 막힘만 닫음.

### CN37 — 2026-09-28
요청: 같은 종도 없고 사망 신호도 없으면 락을 유지하지 말고 새 공격 대상을 찾는다.
고지한 영향: `rebind_sticky_target` / `continue_sticky_combat` / `continue_or_start_combat`만. 2타일 같은 종 추적·창 안 사망 확정은 CN36과 같음. 미확정 홀드·IDLE 재획득을 없애 농장은 기존 3타일 위협→루팅→신규 교전으로 넘어감. `try_unstick_escape`·HP·로그인·상점 그대로.
사용자 동의: 예 (명시 요청)
구현: 창 밖·사망 없음·같은 종 없음이면 `clear_engage_state`. 같은 틱에 `allow_new`로 새 대상. 목록 생략은 여전히 죽음이 아님.
결과(실기/테스트): `tests/test_combat_focus.py` 빈 창+무사망은 락 해제, 다른 종은 신규 교전.
악순환 여부: 공유 탈출/HP 싱크에 플래그 없음. sticky 미확정 홀드만 닫음.

### CN36 — 2026-09-28
요청: 2타일 추적은 일반 유지. 처치 확정은 2타일에서 사라짐 + 그 종 사망 신호가 같이 있을 때만. 신호 없이 2타일에서 사라지면 자기 주변 가장 가까운 같은 종을 찾아 공격.
고지한 영향: `rebind_sticky_target` / `continue_sticky_combat` / `farm_loot_or_combat`만. 목록 생략을 죽음으로 쓰지 않음. `memory_target_gone`의 루팅·신규 대상 선정은 그대로. `try_unstick_escape`·HP·로그인·상점 그대로.
사용자 동의: 예 (명시 요청)
구현: `species_death_signal`. 2타일 창이 비면 사망 신호일 때만 해제. 아니면 거리순 같은 종 재획득. 미확정이면 루팅 금지.
결과(실기/테스트): `tests/test_combat_focus.py` 생략≠죽음, 창 밖 같은 종 재획득, 창 안 DEAD만 확정.
악순환 여부: 공유 탈출/HP 싱크에 플래그 없음. sticky 처치 확정만 바꿈.

### CN35 — 2026-09-28
요청: 자동 로그인 후 Start에서 커서/본토 HP 상점 실패. HP 임계 이하이고 MP<5·회복 아이템 없으면 말하는 두루마리. HP 물약은 아데나≥52×설정수량일 때 설정수량, 아니면 52원 기준 최대. 전투는 잡은 타겟을 처치할 때까지 유지. 처치 후 2–3타일 근접 선교전, 루팅 이동 중 5타일 선교전.
고지한 영향: 상점 두루마리 후 착지 대기만. HP 물약 수량 클램프. sticky 재바인드는 마지막 칸 우선. `farm_loot_or_combat` 선교전 반경만 서 있을 때 3 / 걷을 때 5. `heal_blocked_by_mana`에 MP<5 바닥. Start 직후 2.5초 라이브 좌표 대기. `try_unstick_escape`·로그인 클릭·CN34 두루마리 1회는 그대로.
사용자 동의: 예 (명시 요청, 기존 흐름 유지)
구현: `SCRATCH_SHOP_SCROLLED`만으로 NPC를 열지 않음. `affordable_hp_potion_qty`. `POST_KILL_MELEE_TILES=3`. 재바인드 정렬을 last-cell 우선. 봇 루프 `waiting_live_origin`.
결과(실기/테스트): `tests/test_shop_trip.py` 착지 대기·아데나 수량. `tests/test_combat_focus.py` 마지막 칸 유지·서 있으면 5타일 루팅. `tests/test_hp_actions.py` MP<5.
악순환 여부: 공유 탈출/후퇴 싱크에 새 플래그 없음. 상점 착지와 전투 재바인드만 닫음.

### CN34 — 2026-09-28
요청: 말하는 두루마리로 말하는 섬 8번 NPC(허수아비 수련장)에 갈 때 내비게이션이 계속 반복됨. 한 번이면 충분.
고지한 영향: HP 안전 구역 두루마리는 후퇴당 1회. 도착 시 `configure_navigation_for_map`도 같은 맵이면 한 번만. `try_unstick_escape` 플래그·로그인·상점 구매 그대로. CN33의 즉시 두루마리는 유지하되 재발사만 막음.
사용자 동의: 예 (명시 요청)
구현: `SCRATCH_HP_SAFE_SCROLLED`, `SCRATCH_NAV_RELOAD_MAP`. `finish_retreat`에서 해제.
결과(실기/테스트): `tests/test_hp_actions.py` 두루마리 1회. `tests/test_shop_trip.py` 도착 내비 1회.
악순환 여부: 공유 탈출 싱크에 새 플래그 없음. 두루마리/내비 재시작만 닫음.

### CN33 — 2026-09-28
요청: HP가 안전 구역 기준 미만이고 앞선 힐/아이템/스킬을 쓸 수 없으면 즉시 말하는 두루마리. 한 번 잡은 몬스터는 처치할 때까지 추적 공격. 옆에 템이 떨어져도 줍지 않음.
고지한 영향: `_execute_hp_action("safe_zone")`가 두루마리를 같은 틱에 냄. `apply_hp_actions` / `apply_inplace_hp_support`는 앞선 행동이 불가면 안전 구역을 강제. `continue_or_start_combat`은 살아있는 sticky를 5회 무이동으로 포기하지 않음. `farm_loot_or_combat`는 살아있는 sticky면 루팅으로 떨어지지 않음. `try_unstick_escape` 플래그·로그인·상점 그대로. CN31의 5회 포기는 산 타겟에서 닫음.
사용자 동의: 예 (명시 요청, 기존 흐름 유지)
구현: 안전 구역은 `emit_talking_scroll` 즉시. `_force_safe_scroll_if_due`. 무이동 카운트는 기록만. 산 sticky면 루팅 금지.
결과(실기/테스트): `tests/test_combat_focus.py` 6회 무이동도 공격 유지·루팅 없음. `tests/test_hp_actions.py` 안전 구역/두루마리.
악순환 여부: 공유 탈출 싱크에 새 플래그 없음. 전투 포기와 안전 구역 실행만 좁힘.

### CN32 — 2026-09-28
요청: HP 행동 순서 탭과 인벤토리 탭을 한 화면(왼쪽 순서, 오른쪽 가방)으로 합친다. 힐/텔레포트/안전 구역/세계수는 고정. 회복 아이템은 인벤토리에서 가져와 기존처럼 순서·임계값을 정한다.
고지한 영향: UI 배치와 `normalize_hp_actions`가 저장 목록의 `item:*`를 유지하는 부분만. `pick_hp_action` / `_execute_hp_action` / `apply_hp_actions` / 스파이크 / 후퇴 / 로그인 / 상점 / 전투는 그대로. 카탈로그 전체를 왼쪽 목록에 강제 추가하지 않음.
사용자 동의: 예 (명시 요청, 기존 흐름 유지)
구현: 회복 하위 탭을 `HP 행동 / 인벤토리`로 통합. 가방의 HP 회복 아이템을 왼쪽 목록에 합침. 엔진 normalize는 카탈로그 밖 `item:*`도 유지.
결과(실기/테스트): `tests/test_hp_actions.py` 인벤토리 아이템 유지·카탈로그 미강제, 가방 이름/ID 매칭.
악순환 여부: 공유 HP 실행 싱크에 가드/플래그 없음. 목록 소스만 가방으로 좁힘.

### CN31 — 2026-09-28
요청: 5회 무이동 공격 포기. HP 급감 시 사용자 HP 순서로 즉시 회복/탈출. 힐/물약 없으면 임계값에서 TP/두루마리. 처치 끝날 때까지 줍기 금지. 힐/TP MP 없으면 물약·두루마리.
고지한 영향: `continue_or_start_combat` 5회 같은 타일이면 `give_up_target`. `farm_loot_or_combat`는 살아있는 sticky를 루팅보다 앞. `apply_hp_actions` 스파이크는 사용자 순서. `_can_teleport_now`는 MP 부족이면 불가. `try_unstick_escape` 플래그·로그인·상점 그대로.
사용자 동의: 예 (명시 요청, 기존 흐름 유지)
구현: `ATTACK_STILL_TRIES=5`. 스파이크는 `pick_hp_action(0.0)`. 힐/TP는 `heal_blocked_by_mana`면 스킵.
결과(실기/테스트): `tests/test_combat_focus.py` 5회 포기·원거리 sticky 선전투. `tests/test_hp_actions.py` 스파이크 힐 우선·MP 없으면 두루마리.
악순환 여부: 공유 탈출 싱크에 새 플래그 없음. 전투 포기와 HP 가용만 좁힘.

### CN30 — 2026-09-28
요청: 라이브 상점 여행을 Practice 샘플과 동일하게. 다른 샘플 비헤이비어도 같은 경로.
고지한 영향: `tick_shop_trip`만 Practice `_travel_to_shop`. 두루마리 후 대기/도보 없음. 다음 틱 Esc → NPC 오픈. 도보는 두루마리 없을 때만. 구매/판매는 기존 `execute_calibrated_*`. 갇힘 TP는 상점 여행 전체 금지 유지. `try_unstick_escape` 플래그·HP·로그인 그대로.
사용자 동의: 예 (Practice 순서로 맞추자는 명시)
구현: `shop_scrolled`이면 바로 stop/run. CN29의 마을 도보·10초 재스크롤 제거. YAML id는 locale/모드가 샘플 목록만 고름.
결과(실기/테스트): `tests/test_shop_trip.py` 스크롤 후 즉시 오픈, 두루마리 없을 때만 도보, 라이브 id가 YAML에 존재.
악순환 여부: 공유 탈출 싱크에 새 플래그 없음. CN29 도보를 샘플에 맞춰 닫음.

### CN29 — 2026-09-28
요청: `waiting for shop map (buy_hp_potions_ch_mainland)`에서 NPC로 안 걷고 서 있음.
고지한 영향: `tick_shop_trip`과 `shopping_blocks_teleport`만. 마을 좌표면 NPC로 `begin_travel(PURPOSE_SHOP)`. 농장 좌표면 대기, 10초면 두루마리 재시도. 상점 여행 전체에서 갇힘 TP 금지. `try_unstick_escape` 플래그·HP 싱크·로그인은 그대로.
사용자 동의: 예 (실기 증상 + 같은 CN17 범위)
구현: 착지 80타일에서 열기를 제거. 클릭 가능할 때만 오픈. 마을 250타일이면 도보. `shopping_blocks_teleport`는 halt 전이라도 `shop_trip`이면 True.
결과(실기/테스트): `tests/test_shop_trip.py` 농장 대기·마을 도보·10초 재스크롤·상점 중 갇힘 스킵.
악순환 여부: 공유 탈출 싱크에 새 플래그 없음. 기존 상점 게이트를 여행 전체로 넓힘. 상점 중 HP 후퇴 TP도 같이 막힘(힐/물약은 유지).

### CN28 — 2026-09-28
요청: 이동 전에 줍기한 아이템이 메모리에서 빠졌는지 확인.
고지한 영향: 줍기 클릭 후 `SEARCHING`/`TRAVELING`만 막음. 목록에서 빠지면 즉시 다음. 최대 2초. 5타일 전투는 그대로. HP·로그인·언스틱 플래그는 그대로.
사용자 동의: 예 (명시 요청)
구현: `loot_await_gone_id`. `memory_target_gone`이면 대기 해제. 타임아웃은 유령/남의 드롭.
결과(실기/테스트): `tests/test_loot_stand.py` 남아 있으면 IDLE, 빠지면 이동.
악순환 여부: 공유 탈출/HP 싱크에 플래그 없음. 줍기 후 걷기만 메모리로 닫음.

### CN27 — 2026-09-28
요청: 갇힘 20s→13s(반경 5). 줍기 우선, 5타일 안 몬스터면 처치 후 줍기. 템 없으면 화면 가장 가까운 몬스터. 커서 탐색 0.2.
고지한 영향: `UNSTICK_CONFINED_*`, `farm_loot_or_combat` 5타일 선교전, `ATTACK_CURSOR_SEARCH_TILES`. `try_unstick_escape` 플래그·HP·로그인은 그대로. 갇힘 반경은 4→5.
사용자 동의: 예 (명시 요청)
구현: 갇힘 5타일/13초. 걷든 서든 5타일 위협이면 전투. 템 없으면 `screen_only` 최근접. 공격 커서 헌트 0.2. 줍기 헌트는 0 유지.
결과(실기/테스트): `tests/test_unstick.py` 13초/5타일. `tests/test_combat_focus.py` 서서도 5타일 교전. `tests/test_attack_cursor_search.py` 0.2.
악순환 여부: 공유 탈출 싱크에 새 플래그 없음. 갇힘 숫자와 루팅 선교전만 바꿈.

### CN26 — 2026-09-28
요청: 힐은 자기만 쓰니 더블 F키만. 자기 클릭 제거.
고지한 영향: `ActionExecutor._heal`만. 키 더블 후 캐릭터 클릭을 안 함. `emit_heal`·HP 순서·언스틱·로그인은 그대로. 커서가 힐로 남을 수 있음.
사용자 동의: 예 (명시 요청)
구현: `_press_assigned_skill("heal")`만. `cast: double`은 유지.
결과(실기/테스트): `tests/test_combat_focus.py` 힐이 자기 클릭을 안 함.
악순환 여부: 공유 탈출 싱크에 플래그 없음. 힐 입력만 키로 닫음.

### CN25 — 2026-09-28
요청: 줍기 확인 후 0.9초 서지 말고, 메모리로 확인되면 바로 다음 템/전투. 남의 킬 템은 포기.
고지한 영향: 줍기 settle과 아이템 커서 실패 포기만. `LOOT_PICKUP_SETTLE_S=0`. 루팅 클릭이 4번 실패하면 `abandon_loot_item`. 전투 커서 실패는 그대로 유지. HP·로그인·언스틱 플래그는 그대로.
사용자 동의: 예 (명시 요청)
구현: settle IDLE 제거. `recently_clicked_loot`로 먹은 칸은 건너뛰고 다음 템으로. 아이템 커서 실패 4회면 포기.
결과(실기/테스트): `tests/test_loot_stand.py` settle 없음·4회 실패 포기. `tests/test_combat_focus.py` 몬스터 커서는 포기 안 함.
악순환 여부: 공유 탈출/HP 싱크에 새 플래그 없음. 줍기 대기만 닫음.

### CN24 — 2026-09-28
요청: 오크전사와 오크 전사를 같은 종으로 맞춘다.
고지한 영향: 종 필터 비교만. 공백 없는 메모리 키(`monster_오크전사`)와 공식 키(`monster_오크 전사`)를 같은 항목으로 본다. `try_unstick_escape`·HP·로그인·루팅 클릭은 그대로.
사용자 동의: 예 (명시 요청)
구현: `_fold_species_key`. 별칭도 공식 키로 통일.
결과(실기/테스트): `tests/test_attack_filter.py` 화이트리스트에 띄어쓰기 키가 있어도 오크전사 공격.
악순환 여부: 공유 탈출/HP 싱크에 플래그 없음. 종 이름 접기만.

### CN23 — 2026-09-28
요청: 핫바 스킬/아이템을 실시간으로 찾아 쓴다.
고지한 영향: 누르는 칸만. Setup F키 대신 `last_hotbar` 이름→역할→box/key. 물약은 기존 `find_hp_restore_hotbar`. 텔레포트는 스킬 이름만(`텔레포트`/`傳送術`). 매스·마법서·주문서 제외. `try_unstick_escape` 플래그·HP 순서·로그인 클릭은 그대로.
사용자 동의: 예 (명시 요청)
구현: `find_role_on_hotbar` / `hotbar_has_role`. `_press_assigned_skill`·두루마리가 라이브 칸을 씀. 스냅이 없으면 Setup 키로 폴백.
결과(실기/테스트): `tests/test_hotbar_inspect.py` 힐/두루마리/텔레포트 이름. `tests/test_buff_cadence.py` 힐 칸이면 라이트 생략. `tests/test_unstick.py` 텔레포트 스킬만.
악순환 여부: 공유 탈출/HP 싱크에 새 플래그 없음. 키 해석만 라이브 핫바로 닫음.

### CN22 — 2026-09-28
요청: Start를 누르면 마우스 커서가 힐 사용 형태로 바뀜.
고지한 영향: 핫바 merge와 버프 준비만. 스캔이 차지한 F칸에 예전 라이트 매핑을 남기지 않음. 라이브 칸이 힐/빈칸이면 그 버프를 누르지 않음. `begin_retreat`·언스틱·로그인 클릭은 그대로.
사용자 동의: 예 (실기 증상 + 확인 요청)
구현: F10 실칸은 `初級治癒術`인데 `light`와 `heal`이 같이 F10. Start 후 라이트 버프가 힐을 누름. armor_up은 빈 box2에도 매핑되어 있었음.
결과(실기/테스트): `tests/test_hotbar_inspect.py` 같은 키는 스캔 승. `tests/test_buff_cadence.py` 힐 칸이면 라이트 생략.
악순환 여부: 공유 탈출/HP 싱크에 플래그 없음. 버프 키만 핫바 이름으로 닫음.

### CN21 — 2026-09-28
요청: 갇힘 탈출은 순간이동이 기본. 핫바에 텔레포트 스킬이 있을 때만 쓰고, 없으면 말하는 두루마리.
고지한 영향: `try_unstick_teleport`가 라이브 핫바 이름(`텔레포트`)을 확인. Setup 슬롯만 켜져 있으면 성공 처리하지 않음. 갇힘은 다시 TP→두루마리. `try_unstick_escape` 플래그·HP `begin_retreat`·로그인은 그대로.
사용자 동의: 예 (명시 요청)
구현: `teleport_on_live_hotbar`. 마법서/매스/마더/두루마리는 제외. `decide`가 `live_hotbar` scratch를 매 틱 넣음.
결과(실기/테스트): `tests/test_unstick.py` 핫바 없음→두루마리, 있음→순간이동, 마법서/매스 제외.
악순환 여부: 공유 탈출 싱크에 새 플래그 없음. 텔레포트 준비 판정만 핫바로 닫음.

### CN20 — 2026-09-28
요청: 갇힘 탈출이 여전히 안 됨 (4타일/20초).
고지한 영향: `try_confined_escape`만. 두루마리를 먼저 쓰고, 두루마리가 없을 때만 기존 `try_unstick_escape`(순간이동). `try_unstick_escape` 플래그·HP·로그인·전투 360은 그대로. sticky 전투 중 미발동은 유지.
사용자 동의: 예 (실기 증상 + 수정 요청)
구현: 실기 로그는 `unstick confined` 순간이동이 21초마다 반복되고 바로 `enter farm, walk around`로 돌아감. 랜덤 TP가 같은 주머니에 떨어져 두루마리가 한 번도 안 나감.
결과(실기/테스트): `tests/test_unstick.py` 두루마리 우선, 없으면 TP.
악순환 여부: 공유 탈출 싱크에 새 플래그 없음. 갇힘 호출부만 두루마리를 앞에 둠.

### CN19 — 2026-09-28
요청: HP가 사용자 설정값 아래로 떨어져 안전지대로 갈 때는 두루마리 8번째(가장 안전한 NPC)로. 20초 동안 반경 4타일 안에서 왔다 갔다 하면 순간이동 또는 말하는 두루마리.
고지한 영향: `begin_retreat`의 HP(`RETREAT_FOR_HP`) 두루마리 목적지만 허수아비 수련장(`ti_scarecrow`, 클릭 가능한 8번째 행)으로 고정. Fix/Return·MP 후퇴는 기존 3곳 회전. `UNSTICK_CONFINED_TILES` 5→4. 20초·sticky 전투 중 시계 정지·`try_unstick_escape` 플래그·로그인 클릭은 그대로.
사용자 동의: 예 (명시 요청)
구현: `HP_SAFE_SCROLL_PURPOSE=training`. 갇힘 반경 상수/yaml만 4.
결과(실기/테스트): `tests/test_hp_actions.py` HP 안전지대=허수아비 수련장, 귀환은 회전 유지. `tests/test_unstick.py` 4타일 20초 탈출, 5타일이면 리셋.
악순환 여부: 공유 후퇴 싱크에 새 플래그 없음. HP reason만 목적지를 고정. 갇힘 탈출은 기존 `try_unstick_escape`를 그대로 호출.

### CN18 — 2026-09-28
요청: 샘플(Practice)에서 이미 되는 상점 비헤이비어와 라이브를 동일하게.
고지한 영향: `tick_shop_trip`만 Practice `_travel_to_shop`과 맞춤. 두루마리 착지 후 도보 없음. 마을 좌표가 보이면 Esc 후 NPC 오픈. 판매 오픈도 `open_shop_npc`. 구매 수량 백스페이스 1회. 두루마리 클릭 `snap=True` + 프레임 갱신. 후퇴·언스틱·HP·로그인 싱크는 그대로.
사용자 동의: 예 (명시 요청)
구현: 착지 준비되면 `_at_shop`이 아니어도 stop→run. 두루마리 없는 같은 맵만 도보.
결과(실기/테스트): `tests/test_shop_trip.py` 착지 후 SHOP_STOP/BUY, 농장 좌표면 대기.
악순환 여부: 공유 탈출/HP 싱크에 플래그 없음. 상점 여행만 Practice 순서로 닫음.

### CN17 — 2026-09-28
요청: 커서 헌트 0.1→0.15. 20초/5타일 탈출은 전투 중이 아니라 이동 등에서만. 상점 맵에서 HP 물약 0인데 NPC로 안 감.
고지한 영향: `ATTACK_CURSOR_SEARCH_TILES`만 0.15. `_maybe_confined_escape`는 sticky 전투 중 시계/탈출 정지(CN10과 동일). `tick_shop_trip`은 두루마리 착지 후 마을 안이면 NPC로 도보. `try_unstick_escape` 플래그·HP 싱크·로그인 클릭은 그대로.
사용자 동의: 예 (명시 요청)
구현: 전투 중 20초 탈출 제거. 두루마리 후 idle 대기는 착지 전만. 착지하면 `begin_travel(PURPOSE_SHOP)`.
결과(실기/테스트): `tests/test_unstick.py` sticky면 탈출 없음. `tests/test_shop_trip.py` 착지 후 도보, 농장 좌표면 대기. `tests/test_attack_cursor_search.py` 0.15.
악순환 여부: 공유 탈출 싱크에 새 플래그 없음. 상점 도보는 착지 좌표 가드로만 염.

### CN16 — 2026-09-28
요청: 5타일 안에 20초면 TP/말하는 두루마리. 커서 헌트 0.2→0.1. dialog.png면 클릭 금지(상점 NPC만 예외).
고지한 영향: `_maybe_confined_escape`가 sticky 전투 중에도 20초 시계를 셈. 공격 커서 헌트 반경만 0.1. dialog 거부는 `cursor_verify` 클릭 게이트. `try_unstick_escape` 플래그·HP·로그인·상점 `dialog_click`은 그대로.
사용자 동의: 예 (명시 요청)
구현: sticky로 시계를 멈추지 않음. `ATTACK_CURSOR_SEARCH_TILES=0.1`. 공격/마법 헌트는 dialog 지점을 건너뜀. `dialog_click`만 dialog 클릭 허용.
결과(실기/테스트): `tests/test_unstick.py` sticky 중에도 20초 탈출. `tests/test_attack_cursor_search.py` 0.1·dialog 스킵.
악순환 여부: 공유 탈출 싱크에 새 플래그 없음. CN10의 sticky 시계 정지만 되돌림.

### CN15 — 2026-09-28
요청: Stop 후 Start를 다시 누르면 커서가 전혀 클릭하지 않음.
고지한 영향: Interception 캡처 수명만. `release_capture`가 Stop에서 핸들을 닫고 바로 다시 열지 않음. 다음 Start/로그인이 장치를 다시 잡음. 의사결정·이동·전투·HP·로그인 클릭 템플릿은 그대로.
사용자 동의: 예 (실기 증상 + 수정 요청)
구현: Stop은 버튼만 떼고 컨텍스트를 비움. 죽은 컨텍스트를 남기지 않음. 워커 시작 시 `prepare_capture`, 종료 시 항상 `release_capture`.
결과(실기/테스트): `tests/test_input_capture.py` — Stop 재오픈 금지, 죽은 컨텍스트 교체, Stop 후 drop이 재캡처하지 않음.
악순환 여부: 공유 탈출/HP 싱크에 플래그 없음. 입력 드라이버 수명만 닫음.

### CN14 — 2026-09-27
요청: 줍기 0.2 헌트 제거. 블랙리스트는 8타일 사거리와 무관. 루팅 실패 루프/공격 빗나감 포함 워크플로 수정.
고지한 영향: 줍기 클릭 점, `in_attack_click_range`(화면이면 사거리 무시), `farm_loot_or_combat` 줍기 커서 실패 시 전투, 공격 클릭 순서(몸통 먼저), 메모리 엔티티는 occluded여도 후보. 후퇴·HP·로그인·상점 이동은 그대로.
사용자 동의: 예
구현: `LOOT_CURSOR_SEARCH_TILES=0`. 화면 몬스터는 8타일과 무관하게 클릭 가능. `loot_click_failed`면 다음 틱 전투. 공격 포인트는 UV·메모리 칸 → 픽셀 링 → 0.2.
결과(실기/테스트): `tests/test_attack_cursor_search.py` 줍기 더미만, `tests/test_combat_focus.py` 줍기 실패 후 전투, `tests/test_attack_filter.py` 화면 원거리·occluded 메모리.
악순환 여부: 새 가드 플래그 없이 scratch 한 틱만 사용. 블랙리스트와 클릭 사거리를 분리.

### CN13 — 2026-09-27
요청: 아이템 옆에 도착하고도 바로 안 줍고 다른 데 갔다가 다시 옴.
고지한 영향: `tick_loot_item` 도착/줍기 판정만. 전투·HP·로그인·상점·이동 360°는 그대로. 농장 `ARRIVE_TILES=2`를 루팅 홉에 재사용하지 않음.
사용자 동의: 예 (실기 증상 + 수정 요청)
구현: 줍기는 메모리·origin 중 더 가까운 값. `LOOT_HOP_ARRIVE_TILES=1`. 홉 도착 후 사거리면 즉시 PICKUP, 새 SEARCHING 클릭 없음.
결과(실기/테스트): `tests/test_loot_stand.py` origin이 더미 위면 줍기, 홉 도착 시 재보행 없음.
악순환 여부: 공유 탈출 싱크에 플래그 없음. 루팅 홉 완료만 닫음.

### CN12 — 2026-09-27
요청: 루팅 커서 탐색도 공격과 같이 0.2타일. 줍기 확인 후 대기 0.7s → 0.9s.
고지한 영향: 줍기 클릭 헌트와 settle idle만. 전투 커서·이동 360°·HP·로그인·상점은 그대로. 공격 0.2와 숫자는 같지만 `LOOT_CURSOR_SEARCH_TILES`로 분리.
사용자 동의: 예 (명시 요청)
구현: `object_loot_screen_points`가 `LOOT_CURSOR_SEARCH_TILES=0.2`를 씀. `LOOT_PICKUP_SETTLE_S=0.9`.
결과(실기/테스트): `tests/test_attack_cursor_search.py` 루팅 0.2 헌트, `tests/test_loot_stand.py` settle 0.9.
악순환 여부: 공격 픽셀 링을 루팅에 열지 않음. 새 가드 플래그 없음.

### CN11 — 2026-09-27
요청: 화면 몬스터는 즉시·가장 가까운 것부터 원거리 클릭 공격(0–8타일, 바짝 다가가지 않음). 루팅은 최우선. 2타일 이내 대치에서 몬스터 칸 불변 5초 → 360°는 불필요.
고지한 영향: `list_attackable` 걷기 경로 필터를 클릭 사거리 안에서는 건너뜀. `nearest_attackable`은 타일 거리. `farm_loot_or_combat`에서 sticky는 2타일 이내일 때만 루팅을 막음. `try_combat_blocked_unstick`은 클릭 사거리(0–8, 2타일 대치 포함)에서 꺼짐. 후퇴·HP·로그인·상점·이동 360°는 그대로.
사용자 동의: 예 (명시 요청)
구현: `ATTACK_CLICK_TILES=8`, `STICKY_LOOT_HOLD_TILES=2`, `LOOT_KEEP_TILES=8`. 화면 밖 UV라도 메모리 8타일 안 아이템은 유지.
결과(실기/테스트): `tests/test_combat_focus.py` 원거리 클릭·원거리 sticky 시 루팅, `tests/test_unstick.py` 근접/사거리 안 360 생략, `tests/test_ground_loot.py` 근거리 UV 이탈 유지.
악순환 여부: 전투 360을 사거리 안에서 닫음. 새 가드 플래그 없음. 숫자 8은 공격 클릭과 루팅 유지에 쓰이지만 상수 이름이 다름.

### CN10 — 2026-09-27
요청: 20초 동안 캐릭터가 반경 5타일 안에서만 움직이면 텔레포트 또는 말하는 두루마리.
고지한 영향: 이동/사냥 틱에서 HP·버프 다음, 상점·전투·수색 전에 검사. 살아 있는 sticky 몬스터를 때리는 동안은 시계를 멈추고 탈출하지 않음(처치 후 다시 셈). 후퇴·사망·쇼핑 차단은 그대로. 농장 밖에서도 20초면 `allow_outside_farm`으로 탈출 가능. 3회/20초 정지 버스트와 숫자는 같지만 상수 이름이 다름.
사용자 동의: 예 (명시 요청)
구현: `UNSTICK_CONFINED_TILES=5`, `UNSTICK_CONFINED_SECONDS=20`. `try_confined_escape` → `try_unstick_escape(urgent, allow_outside_farm)`.
결과(실기/테스트): `tests/test_unstick.py` 20초 5타일 탈출, 5타일 벗어나면 리셋.
악순환 여부: 공유 탈출 싱크를 쓰되 새 가드 플래그는 없음. 전투 중 TP를 열지 않음.

### CN09 — 2026-09-27
요청: 이동 끼임 대기 2.5s → 5s. 공격 시작 후 5초 동안 몬스터 칸이 안 바뀌면 클릭 지점 주변 2타일 360°로 경로를 찾음.
고지한 영향: 이동/수색/루팅 걷기 언스틱만 5초로 늦춤. 전투는 `try_combat_blocked_unstick`만 다시 켬(반경 2, 텔레포트 없음). 농장 입장 우회 5타일·HP·로그인·상점·후퇴는 그대로. 플레이어가 공격 중 2.5초 정지하는 접근 언스틱은 계속 꺼짐.
사용자 동의: 예 (명시 요청)
구현: `TRAVEL_UNSTICK_SECONDS` / `LOOT_APPROACH_STUCK_SECONDS` / `COMBAT_BLOCKED_UNSTICK_SECONDS` = 5. `continue_or_start_combat`에서 몬스터 불변 5초 후 `unstick combat path`.
결과(실기/테스트): `tests/test_unstick.py` 5초 대기, 클릭 주변 스윕, 몬스터 이동 시 리셋.
악순환 여부: 전투 360°를 이동 반경 3·텔레포트와 분리. 숫자 5는 이동 대기와 전투 관찰에 쓰이지만 상수 이름이 다름.

### CN08 — 2026-09-27
요청: 줍기 확인 후 정지 0.9s → 0.7s.
고지한 영향: 루팅 idle만 0.2초 짧아짐. 전투/이동/HP/언스틱/로그인은 그대로.
사용자 동의: 예 (명시 요청)
구현: `LOOT_PICKUP_SETTLE_S = 0.7`.
결과(실기/테스트): settle 판정은 상수만 사용. 기존 `test_loot_stand.py` 유지.
악순환 여부: 2.5초 이동 언스틱과 숫자를 공유하지 않음. 줍기 전용 타이머만 변경.

### CN40 — 2026-09-29
요청: (1) 말하는 섬 농장 복귀 착지를 텔레포터→마법서 상인 (2) 5칸/13초 갇힘 시계를 고정 전투 중 리셋 (3) 루팅 위협 거리를 서 있을 때·걸을 때 모두 5칸 (4) HP 안전 두루마리 착지 후 같은 후퇴에서 텔레포트 금지 (5) 텔레포트 사전 마나 검사를 HP 경로와 정체 탈출에 통일.
고지한 영향: `farm_return_scroll_spot` / `FARM_RETURN_SPOT_BY_MAP`(상점 복귀·사냥맵·정체 두루마리), `_maybe_confined_escape`+`reset_confined_progress`, `farm_loot_or_combat` 위협 반경, `_hp_action_availability`+후퇴 pending TP, `try_unstick_teleport`/`_emit_escape_teleport` 마나 게이트. 허수아비 HP 안전지대·사망 후 마법서·본토 기란 텔레포터는 유지.
사용자 동의: 예 (솔루션대로 feature별 수정 요청)
구현:
- `talking_scroll.FARM_RETURN_SPOT_BY_MAP[talking_island]=ti_spellbook`
- sticky combat 중 confined clock clear
- loot threat always `LOOT_APPROACH_THREAT_TILES` (5); `POST_KILL_MELEE_TILES=5`
- `SCRATCH_HP_SAFE_SCROLLED` → teleport unavailable + pending TP cleared
- unstick/escape TP refuse when known MP≤reserve or MP&lt;5; unstick then scroll
결과(실기/테스트): `test_unstick` / combat focus 5-tile / `test_hp_safe_landed_blocks_teleport_row` / dungeon farm return spot 통과.
악순환 여부: 갇힘 시계는 전투와 분리됨. TP 마나 게이트는 HP·정체 경로를 맞춤. 긴급 PK/포위 TP도 `_emit_escape_teleport`를 거쳐 같은 마나 사전검사를 받음(마나 부족 시 무반응, 두루마리 추가 없음).

### CN41 — 2026-09-29
요청: (1) dialog 커서 대기점 클릭 방지 보강 (2) 섬 전투에 벽/울타리 LOS 추가—기존 8칸·A* 유지, 벽이면 우회 가능 시에만 공격, 신규·고정 대상 모두 (3) HP 30/50/90은 문서 정리만 (4) 상점 착지 IDLE 고착 타임아웃·재시도·생존 예외 (5) 긴급 TP UI를 감지에 맞추고 실패 반복 쿨다운.
고지한 영향:
- `_retreat` → `travel_click`+링; `TRAVEL_CURSOR_FALLBACK_RADIUS` 1→2 (이동/수색/후퇴)
- `can_engage_target` + `list_attackable` / `continue_sticky_combat` (섬 전투 선택·포기)
- `shop_trip` 착지 대기 25s·최대 2회 재스크롤 후 `clear_shop_trip`; HP 후퇴 starters·긴급 TP는 `shopping_blocks` 우회
- `_maybe_emergency_teleport` 8s 쿨다운; UI `teleport_player` 문구
의도하지 않은 부작용 후보: 벽 맵에서 근거리 몬스터를 더 자주 포기; 상점 중 HP 후퇴가 구매를 끊음; 긴급 TP가 상점 착지를 끊음.
사용자 동의: 예 (“solution looks good” + 섬 LOS 범위 명시 + feature별 구현)
구현:
- controller `_retreat` NORMAL 검증; decision.yaml / player_mode fallback 2
- `combat_query.can_engage_target`; sticky wall give-up
- `SHOP_LANDING_WAIT_S` / retries; HP retreat_starters always; emergency TP ignores shop block
- schedule_i18n teleport_player = visible player (en/ko/zh)
결과(실기/테스트): `test_combat_focus` wall/sticky/emergency cooldown·shop bypass; `test_shop_trip` landing timeout; 기존 shop wait IDLE 유지.
악순환 여부: 상점 생존 예외는 confined/unstick 차단과 분리(shopping_blocks는 이동 탈출에만 유지). 긴급 TP 쿨다운은 새 scratch 키만 사용.

### CN42 — 2026-09-29
요청: 모든 기능·이벤트·결과를 UI 실행 로그에 상세히 보이게 해서 버그 추적 가능하게.
고지한 영향: `bot_log.configure(ui_sink=…)` → 스케줄/디버그 로그 패널이 세션 파일과 동일 INFO+ 수신. `decision`/`combat`/`shop`/`hp`/`nav`/`action` 채널 이벤트 로그 추가. 틱 반복은 기존처럼 50회마다. HP·상점·전투·커서 거부·두루마리·언스틱 TP. 후퇴 begin/finish. 로그인 클릭 로직 변경 없음.
사용자 동의: 예 (명시 요청)
구현: UI sink; richer `_log_decision`; event logs in combat/shop/hp/mode_control/talking_scroll/spells/manager cursor path.
결과(실기/테스트): `tests/test_bot_log.py`; 기존 combat/shop 회귀.
악순환 여부: 새 가드 플래그 없음. 로그 볼륨만 증가(INFO 전환·50틱 반복 유지).

### CN43 — 2026-09-29
요청: LOS가 직선 벽/울타리인지 확인; 벽이면 A*/근처 이동으로 공격 시도; 아이템은 가급적 포기하지 않고 A*/360° 링; Diagnostics 로그 전체 문자열 표시.
고지한 영향: `line_of_sight_clear`(사이 칸만), sticky 즉시 give-up 제거 → `try_combat_wall_detour`+blocked unstick, `abandon_loot_item`이 combat give-up 맵을 쓰지 않음, Other/Diagnostics 로그 가로스크롤+전체 줄 패널.
사용자 동의: 예 (범위 명시 요청)
구현: dungeon LOS skip goal; combat wall detour; loot ring/unstick before soft skip; schedule_ui log_detail.
결과(실기/테스트): LOS goal-skip / sticky keep / combat+shop 회귀.
악순환 여부: sticky 벽 즉시 포기 제거. 루팅 160틱 오염 제거.

### CN44 — 2026-09-29
요청: 수색 사냥 몬스터/아이템 교전 거리(5칸 위협 포함) 문서화 + 주요 분기 INFO를 Diagnostics에 전부 보이게.
고지한 영향: 거리 수치(5/8/2) 변경 없음. `bot_log.event()`; `farm_loot_or_combat` 분기(sticky/threat5/loot_miss/loot/screen/none); search/travel hop; loot begin/pickup; confined·enter farm·escape TP 보강. ATTACK reason에 threat5/screen engage.
사용자 동의: 예 (플랜 구현 지시)
구현: 전투로직설명서 ranges; event helper; mode_actions/loot_hop/search_hop/travel/mode_ticks 로그; test_bot_log event sink.
결과(실기/테스트): `tests/test_bot_log.py` event helper; 수치 변경 없음.
악순환 여부: 새 가드/플래그 없음. INFO 분기 로그만 추가(틱 IDLE 스팸 없음).

### CN45 — 2026-09-29
요청: 줍기 후 IDLE 대기 제거(A)+타임아웃 단축(B); 루팅을 전투보다 우선(sticky 킬만 예외).
고지한 영향: `farm_loot_or_combat`에서 5칸 threat 인터럽트 제거 → sticky 후 루팅 → (미스 시) 전투 → 화면 전투. `continue_or_start_loot`가 await 중 IDLE 미방출·해당 id만 skip. `LOOT_AWAIT_GONE_S` 2→0.4. HP/후퇴/로그인 미변경.
사용자 동의: 예
구현: mode_actions loot-first+await; player_mode/decision.yaml/configure; 전투로직설명서; combat_focus/loot_stand 테스트 갱신.
결과(실기/테스트): combat_focus·loot_stand.
악순환 여부: 루팅 중 피격↑ 가능. 새 플래그 없음. threat5 게이트 제거(의도).

### CN46 — 2026-09-29
요청: 줍기 클릭 후 바로 떠나서 안 줍히는 실기 → await 중 재클릭/재접근.
고지한 영향: `try_finish_pending_pickup`; await 중 수색·다른 템·화면전투로 이탈 금지(sticky 킬은 유지). `LOOT_AWAIT_GONE_S` 0.4→0.8.
사용자 동의: 예
구현: loot_hop try_finish; continue_or_start_loot 우선 호출; yaml/player_mode; loot_stand 테스트; 설명서 §10.
결과(실기/테스트): loot_stand / combat_focus.
악순환 여부: 남템·고스트에 최대 0.8초 재클릭. 긴 IDLE 복귀 아님.

### CN47 — 2026-09-29
요청: HP 급락(0.5초/20%p) 시 힐·물약 말고 텔레포트/말하는 두루마리 직행.
고지한 영향: `apply_hp_actions` 스파이크 분기만 `teleport`→`safe_zone`. 일반 `hp_below` 순서 유지. mother_tree·heal·items 스파이크에서 제외.
사용자 동의: 예
구현: mode_actions spike filter; test_hp_actions; 전투로직설명서.
결과(실기/테스트): test_hp_actions spike.
악순환 여부: 급피격 시 후퇴↑. 새 플래그 없음.

### CN48 — 2026-09-29
요청: (1) 일시정지/재개 시 버프(라이트 등) 타이머 유지 (2) 레벨&lt;15 필드 힐/물약 스킵→세계수/마법서 두루마리, 도착 후 회복 또는 50% 대기; ≥15는 기존+스파이크에 세계수; 스파이크 &lt;15는 세계수/두루마리.
고지한 영향: spells persist/restore; blackboard.reset이 버프 시각 유지; `is_low_level_hp_mode`/`LOW_LEVEL_HP_CAP=15`; `_hp_action_availability`; spike 순서 TP→tree→scroll; low-level safe scroll→마법서 상인.
사용자 동의: 예
구현: spells/blackboard/manager; mode_actions; mode_control scroll_purpose; tests; 설명서.
결과(실기/테스트): test_buff_cadence, test_hp_actions.
악순환 여부: &lt;15 필드 회복 없음→후퇴↑. 새 플래그 없음(레벨 분기만).

### CN49 — 2026-09-29
요청: 레벨&lt;15 스파이크에도 텔레포트를 세계수/두루마리보다 먼저.
고지한 영향: 스파이크만 TP 재허용; 필드 &lt;15 일상 HP는 여전히 TP/힐/물약 스킵.
사용자 동의: 예
구현: apply_hp_actions spike preferred 통일 + spike_can teleport; 테스트/설명서.
결과(실기/테스트): test_hp_actions spike low-level teleport.
악순환 여부: 급피격 시 저레벨 TP↑. 필드 일상은 변경 없음.

### CN50 — 2026-09-29
요청: 핫바에 빨간 물약(및 다른 회복 아이템)이 있으나 count=0일 때 다음 HP 우선순위가 실행되지 않음. 힐은 수량 문제 아님(이번 범위 밖).
고지한 영향: `_hp_item_count`만 — 라이브 핫바에 아이템이 보이면 그 count(0 포함)를 가방보다 우선. `_can_item_now`→`apply_hp_actions`/`can_active_hp_recover`/후퇴 종료. 힐 스킬·탈출 조건·스파이크 분기 변경 없음.
사용자 동의: 예
구현: mode_actions `_hp_item_count` 핫바 우선; test_hp_actions; 전투로직설명서.
결과(실기/테스트): test_hp_actions (hotbar 0 + stale bag fallthrough 포함) pass.
악순환 여부: 빈 칸 SUCCESS 고착 완화. 새 플래그 없음. 핫바 미갱신 시 가방에 있어도 잠깐 스킵 가능.

### CN51 — 2026-09-29
요청: 레벨≥15에서도 HP 문턱/급락 시 캐릭터가 아무 행동도 하지 않음.
고지한 영향: (1) `HP_SPIKE_WINDOW_S` 0.5→1.5 (2) 힐: 핫바 스냅 없으면 슬롯 ON만으로 허용 (3) TP pending 실패 시 `arm_hp_escape_fallback` 두루마리/세계수 (4) 문턱 이하인데 can 전무 시 `hp idle` 로그. 물약 count=0 폴스루는 CN50 유지.
사용자 동의: 예
구현: player_mode/decision.yaml; mode_actions; mode_ticks; tests; 설명서.
결과(실기/테스트): test_hp_actions + test_combat_focus (spike 1.2s, heal no-snap, TP→scroll fallback) pass.
악순환 여부: 후퇴 중 두루마리↑ 가능. 새 플래그 없음.

### CN52 — 2026-09-29
요청: TP/두루마리 안전지 착지 후 힐·물약 없고 HP&lt;50%이면, 50% 자연회복 대기 **전에** 세계수 1회.
고지한 영향: `maybe_mother_tree_before_passive_wait`만. 필드 탈출 순서 변경 없음. scratch `hp_post_land_tree_tried` 1회 가드. `finish_retreat`에서 클리어.
사용자 동의: 예
구현: mode_actions; mode_ticks; mode_control finish; tests; 설명서.
결과(실기/테스트): test_hp_actions (post-land mother tree / heal skip) pass.
악순환 여부: 착지 후 세계수↑. 필드 탈출 싱크는 그대로.

### CN53 — 2026-09-29
요청: Fix/HP 기본 줄 5개만. 가방 자동 추가 없음. 「HP 순서에 추가」로 아무 가방 아이템이나 수동 추가·우선순위.
고지한 영향: `default_hp_actions`/`normalize` fill_catalog 기본 False; 엔진 default도 빨간 물약만; UI `_sync_hp_actions_from_inventory` no-op; `inventory_item_key_for_hp_action`. 전투 게이트는 기존 `item:*` 경로.
사용자 동의: 예
구현: manmabot_v1/hp_actions; engine hp_actions; schedule_ui/i18n; tests; 설명서.
결과(실기/테스트): test_hp_actions + test_game_catalog 57 passed.
악순환 여부: 공유 탈출 싱크 변경 없음.

### CN54 — 2026-09-29
요청: 메모리 기반 NPC 판매(shopwatch→shop_listen), keep-only + 전체 item 카탈로그 UI, 판매 스크롤(빈 첫 페이지 조기 종료) 수정.
고지한 영향: `execute_calibrated_sell`, `ShoppingUiClicks.calibrated(sell)`, `SellFilterPanel`, `SELL_MODE` 기본 `sell_except_keep`, (신규) `shop_listen.dll`/`shop_listen_reader.py`. 구매·HP·로그인 미변경. 템플릿 판매는 `execute_calibrated_sell_legacy_template`로 보존.
사용자 동의: 예
구현: shop_listen.c+DLL+reader; runtime 메모리 idx→scroll/click; sell UI=list_item_rows keep-only; defaults/profile/schedule/shops.
결과(실기/테스트): DLL 빌드 OK; Python import/필터 스모크. 실기(NPC Sell 탭 스크롤·판매) 대기.
악순환 여부: 판매 공유 경로 개방(메모리+스크롤). 새 플래그 없음. `sell_only_garbage` YAML 동작은 유지·UI에서 제거.

### CN55 — 2026-09-29
요청: 몬스터를 새로 보고 공격하기로 한 직후, 공식 타겟/공격 클릭 전에 Esc를 즉시 누르고 기존 공격 로직 진행.
고지한 영향: `_halt_before_attack` + knight/mage `attack`(elf·royal 상속). `stop_before_attack_wait_s` 0. 클릭 간격 early-return **전에** Esc. sticky 재클릭(`mid_act`)은 Esc 없음. decision `continue_or_start_combat`/`begin_engage` 미변경.
사용자 동의: 예
구현: knight.py / mage.py halt-before-gap; controller wait skip when 0; action.yaml + humanize default 0.0.
결과(실기/테스트): 구문 검사; 실기(첫 engage Esc) 대기.
악순환 여부: 공유 탈출 싱크 변경 없음. 새 플래그 없음. Esc가 상점/대화 UI를 닫을 수 있음.

### CN56 — 2026-09-29
요청: Sell 버튼 후 판매 창에 보이는 아이템은 전부 판매 (keep 필터 무시). 아데나만 제외.
고지한 영향: `execute_calibrated_sell`의 `sellable_rows`만. keep/garbage 미적용. HP·이동·로그인 미변경.
사용자 동의: 예
구현: shop_listen 전 행 판매(id 5 제외).
결과(실기/테스트): 대기 — Sell 탭 전 품목 연속 판매.
악순환 여부: 판매 경로만. 새 플래그 없음.

### CN57 — 2026-09-29
요청: 메모리 목록은 유지하되, DB에서 Keep이 아닌(Sell) 항목만 판매.
고지한 영향: `execute_calibrated_sell`의 `sellable_rows`만 — `load_sell_filters` + `item_passes_sell_filter` 재적용. HP·이동·로그인 미변경.
사용자 동의: 예
구현: keep_list에 있는 이름/카탈로그 키는 건너뛰고, 그 외(및 sell_only_garbage면 garbage만) 판매. 아데나 id 5 제외.
결과(실기/테스트): 대기.
악순환 여부: 판매 필터만. 새 플래그 없음.

### CN58 — 2026-09-29
요청: 라이브 판매 필터를 Debug 창과 동일 로직으로 맞춤.
고지한 영향: `resolve_active_sell_mode` 공유; `execute_calibrated_sell`이 YAML `sell_only_garbage` 대신 Debug와 같이 keep_list 있으면 `sell_except_keep`. Debug 테이블도 동일 함수 사용. HP·이동·로그인 미변경.
사용자 동의: 예
구현: behaviors.resolve_active_sell_mode; runtime + debug_snapshot 연결.
결과(실기/테스트): 대기 — Debug Sell 행과 동일 대상 판매.
악순환 여부: 판매 필터만. 새 플래그 없음.

### CN59 — 2026-09-29
요청: 타겟 포기 초기값을 20초로.
고지한 영향: `ABANDON_SECONDS`와 프로필/일정 기본값만. 포기 조건(`abandon_same`이 켜져 있고 경과 시간이 기준 이상)은 그대로. 이미 저장된 일정의 초는 바꾸지 않음. HP·이동·로그인 미변경.
사용자 동의: 예 (초기값을 20으로 설정하라고 지정)
구현: UI 스핀·프로필·일정 스냅샷·런타임 폴백·`combat.ABANDON_SECONDS`를 20으로.
결과(실기/테스트): 대기.
악순환 여부: 새 플래그 없음. 같은 숫자의 다른 의미로 재사용하지 않음.

---

## 7. 이후 항목 양식

```
### CNxx — YYYY-MM-DD
요청:
고지한 영향:
사용자 동의: 예 / 아니오 / 조건부
구현:
결과(실기/테스트):
악순환 여부: 공유 싱크를 열었는가 / 닫았는가 / 새 플래그를 추가했는가
```
