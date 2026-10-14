# Buff status catalog — prep (id → role → cast-if-missing)

상태: **문서만** (구현·동의 전).  
목표: 메모리 버프 `id`를 역할에 매핑한 뒤, **하드코딩 reuse 시계 대신 “없으면 시전”** 으로 `spell.buffs`를 바꾼다.

운영 메모 (2026-10-04): **`light`는 시전하지 않음** — `BUFF_ORDER`에서 제외, 슬롯 `enabled=False`. 카탈로그/채집은 `armor_up`·`power_up` 우선.

관련 정본:

- 계층: [`DECISION_HIERARCHY.md`](DECISION_HIERARCHY.md) L3 `spell.buffs` / L6 query
- 칸 주소: [`DECISION_STEPS.md`](DECISION_STEPS.md) (`spell.buffs`)
- 현재 틱 요약: [`LOGIC_OVERVIEW.md`](LOGIC_OVERVIEW.md) §7 버프 줄
- 라이브 코드: `app/_04_decision/spells.py` (`due_buff` / `maybe_cast_buff`),  
  메모리 반영: `app/_03_world/merge/memory_sync.py` → `PlayerState.buffs`

---

## 1. 왜 지금 reuse가 하드코딩인가

모니터는 매 스냅샷에 활성 버프를 읽는다.

| JSON 키 | Python `StatusEffect` |
| --- | --- |
| `id` | `name = str(id)` (**표시 이름 아님**) |
| `remain` | `duration` |
| `stacks` | `value` |
| `slot`, `maxDur` | state에 미반영 |

`id → 이름/역할` 표가 없어 decide는 “라이트가 켜져 있나?”를 알 수 없다.  
그래서 `buff_last_cast` + `BUFF_COOLDOWN_S` / `LIGHT_REUSE_S` / `BUFF_START_DELAY_S`로 **우리가 누른 시각**만 본다.

코드에 있는 id 인식은 독용 `"10"` 정도뿐 (`player_is_poisoned`).  
`skills_names.json`은 **배울 스킬** 카탈로그이며, 버프 배열 id와 동일 공간이라고 가정하지 않는다.

---

## 2. 목표 동작 (합의 대상)

```text
매 틱 spell.buffs:
  for role in BUFF_ORDER (armor_up → light → power_up):
    if role disabled or not on live hotbar → skip
    if memory shows active status for that role (remain > margin) → skip
    else if mana/magic_ready → emit BUFF(role)  # 한 틱 하나
```

- **진실:** 메모리에 해당 버프가 **없다** (또는 remain이 마진 미만) → 시전.
- **reuse 시계:** 1차 목표가 아님. 폴백(모니터 실패·id 미등록)용으로만 남길지 합의.
- **새 `ActionType` / `PlayerMode` 없음.** Intent는 기존 `BUFF`, 칸 id는 `spell.buffs` 유지.

---

## 3. 카탈로그 스키마 (제안)

경로 후보 (엔진 상수, 프로필 아님):

`Engine/data/catalog/buff_status.json`

프로필/계정에 두지 않는다. `cast`/`reuse_s`와 같이 **게임 규칙·관측 표**다.

```json
{
  "metadata": {
    "game": "Lineage Classic",
    "note": "Keys are status ids from realtime_monitor buffs[].id (decimal strings).",
    "updated": "YYYY-MM-DD"
  },
  "statuses": {
    "12345": {
      "role": "light",
      "ko": "라이트",
      "aliases": [],
      "notes": "실기 채집: 맵/클래스"
    },
    "10": {
      "role": "poison",
      "ko": "중독",
      "aliases": [],
      "notes": "기존 _POISON_IDS와 정합"
    }
  },
  "roles": {
    "armor_up": {
      "spell_slot": "armor_up",
      "status_ids": ["…"],
      "recast_margin_s": 30
    },
    "light": {
      "spell_slot": "light",
      "status_ids": ["…"],
      "recast_margin_s": 30
    },
    "power_up": {
      "spell_slot": "power_up",
      "status_ids": ["…"],
      "recast_margin_s": 30
    }
  }
}
```

규칙:

| 필드 | 의미 |
| --- | --- |
| `statuses[id].role` | decide 역할 또는 `poison` 등 특수 |
| `roles[role].status_ids` | 그 스킬이 걸면 생기는 status id 목록 (다중 가능) |
| `recast_margin_s` | remain ≤ 이 값이면 “없음”과 같이 재시전 |

`role` ↔ `spell_slot` id (`power_up` / `armor_up` / `light`)는 핫바·`BUFF` reason과 같게 유지.

---

## 4. 모듈 경계 (구조 보존)

| 층 | 임무 | 할 일 / 금지 |
| --- | --- | --- |
| `_01_perception` | 스냅샷에 `buffs[]` 이미 있음 | 스키마 변경 없음 |
| `_03_world` merge | `StatusEffect` 채움 | 선택: id→역할 resolve를 merge에 넣지 말고 **L6 query**에 둠 (state는 raw 유지) |
| `_04_decision` L6 | `player_has_buff_role(state, role)` | 카탈로그 로드·조회만. Intent 금지 |
| `_04_decision` L5 | `due_buff` / `maybe_cast_buff` | missing 판정으로 교체 (동의 후) |
| `_05_action` | `BUFF` 더블/싱글 프레스 | 카탈로그와 무관 (시전 방법만) |
| `Engine/data/catalog` | JSON 정본 | 프로필에 복사하지 않음 |
| UserData | — | **쓰지 않음** |

app 밖이 필요하면:

- 카탈로그 파일만 `Engine/data` (app이 읽음).
- UI 편집기가 필요해지면 Tools — 라이브 틱 경로에 UI import 금지.

---

## 5. Query API (구현 시 스케치)

이름은 합의 후 확정. 의도만 고정한다.

```text
load_buff_status_catalog() -> catalog
status_ids_for_role(role) -> list[str]
role_for_status_id(id) -> str | None
player_buff_remain(state, role) -> float | None
  # max remain among matching ids; None = 모니터에 없음/미매칭
player_needs_buff(state, role, *, margin_s) -> bool
  # True when remain is None or remain <= margin
```

`due_buff` 교체 방향:

1. `player_needs_buff` → True인 첫 `BUFF_ORDER` 역할  
2. 핫바·enabled·`can_cast_spell`·`magic_ready`는 유지  
3. 시전 성공 기록(`mark_buff_cast`)은 **폴백 시계용**으로만 남기거나 제거 — 합의 항목

---

## 6. 채집 절차 (표 만들기)

실기에서 역할당 최소 1 id:

1. 버프 전부 off(또는 신규 캐릭)에서 스냅샷 → 베이스라인 id 집합  
2. `armor_up`만 시전 → 새로 나타난 `id` 기록 + remain/maxDur  
3. `light`, `power_up` 반복  
4. 클래스/서버(한/중)별 차이 있으면 `statuses`에 메모, `roles.*.status_ids`에 복수 등록  
5. 독·기타 디버프는 `role: poison` 등으로 같은 파일에 확장 (기존 `_POISON_IDS` 이관)

채집 로그 위치 제안: `UserData/logs/` 또는 Research 노트 — **라이브 import 경로에 넣지 않음**.

디버그 스냅샷에 이미 `buffs` id/remain/stacks가 있으므로, 채집 UX는 디버그 패널 “현재 버프 id 복사” 정도로 충분할 수 있음 (UI는 별도 동의).

---

## 7. 마이그레이션 / 폴백

| 상황 | 동작 (제안, 합의 필요) |
| --- | --- |
| 카탈로그 파일 없음/손상 | 현재 시계 `due_buff` 유지 |
| 역할의 `status_ids` 비어 있음 | 그 역할만 시계 폴백 |
| 모니터 `buffs` 비어 있음 (배열 미발견) | 전 역할 시계 폴백 또는 buff 칸 skip — **합의** |
| 시전 후 N초 내 여전히 missing | 재시도 상한 / 핫바·더블프레스 의심 로그 |

`BUFF_START_DELAY_S`(시작 후 power 10분 등)는 “없으면 시전”과 충돌한다.  
목표 정책이면 **지연 제거 또는 “첫 틱에 없는 것만”** 으로 바꾼다 — 별도 동의.

---

## 8. 영향 고지 초안 (구현 착수 시)

의도: 버프 재시전을 메모리 status 존재 여부로 판단.  
공유: `due_buff` / `maybe_cast_buff` / (신규) buff catalog query; 독 id 표는 같은 JSON으로 이관 가능.  
영향: `spell.buffs`가 있는 모든 열 (world_nav, farming, traveling). HP·전투·상점 불변.  
부작용 후보: id 오등록 시 과도 시전/미시전; 모니터 공백 시 폴백 정책; 시작 지연 제거 시 로그인 직후 버프 폭주.  
새 Intent/모드: 없음.  
질문: “이 범위로 카탈로그 로드 + `player_needs_buff` + `due_buff` 교체 진행할까요?”

---

## 9. 아직 정하지 않은 것

1. `recast_margin_s` 기본값 (예: 30s)  
2. 모니터 실패 시 skip vs 시계 폴백  
3. `BUFF_START_DELAY_S` 폐기 여부  
4. `mark_buff_cast` / persist 타이머 파일 유지 여부  
5. 카탈로그에 물약 버프·음식 등 non-hotbar status를 넣을지  
6. `StatusEffect`에 `maxDur`/`slot`을 올릴지 (쿼리만으로도 가능하면 state 변경 최소화)

---

## 10. 구현 체크리스트 (동의 후)

- [ ] `buff_status.json` 스키마 확정 + 실기 id 채집 (최소 3 역할)  
- [ ] L6 로드/쿼리 모듈 (app 안, data는 `Engine/data/catalog`)  
- [ ] `due_buff` → needs-buff (폴백 명시)  
- [ ] 독 `_POISON_IDS` → 카탈로그 이관 여부  
- [ ] 테스트: 카탈로그 hit/miss, margin, 모니터 빈 목록, 핫바 없음  
- [ ] `decision_change_log.md` 동의·결과  
- [ ] `DECISION_STEPS` / `LOGIC_OVERVIEW` 한 줄 갱신 (시계 → status)

이 문서만으로는 런타임이 바뀌지 않는다.
