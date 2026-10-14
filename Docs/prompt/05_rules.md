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
