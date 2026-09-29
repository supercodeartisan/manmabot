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
