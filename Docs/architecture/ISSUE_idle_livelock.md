# ISSUE — 틱 단위 무한 IDLE (livelock)

상태: **기록만** (로직 수정·상한 제거 없음)  
관련: [DECISION_STEPS.md](DECISION_STEPS.md), [DECISION_HIERARCHY.md](DECISION_HIERARCHY.md), `manager.decide` handoff 루프

## 요약

`decide`의 handoff 상한(`range(3)`)은 **한 호출 안**의 모드 왕복만 끊는다.  
상한에 걸리면 intent가 없어도 **합성 `IDLE`**이 나간다.  
다음 틱에 조건이 그대로면 **같은 ping-pong → 또 IDLE**이 반복될 수 있다.  
이는 CPU 무한루프가 아니라 **틱 단위 livelock**(계속 IDLE만 실행).

정상 설계 기대: 상한이 없어도 같은 틱 순환이 구조적으로 불가능해야 한다. 상한은 비상 브레이크일 뿐.

## IDLE 두 갈래

| 종류 | 원인 | 식별 |
| --- | --- | --- |
| A1 칸 IDLE | step이 `emit(IDLE)` | `reason=` 구체적 |
| A2 합성 IDLE | emit 없이 decide 종료 | `_no_intent_reason` / handoff 로그 |

## 이론상 같은 틱 handoff 순환 (상한 없을 때)

emit 없이 모드만 토글되면 decide가 안 끝남.

1. farming ⇄ retreating (`return_vitals`/`hp` 열기 ↔ `finish_retreat` 즉시 닫기)
2. traveling ⇄ farming (즉시 도착 ↔ `enter`/`upkeep` 재출발)
3. farming ⇄ traveling (입장 실패/경계 도착)
4. retreating ⇄ traveling (finish가 stash trip 복원 후 다시 후퇴)

상한 있으면: 최대 3회 후 **A2 IDLE**.

## 틱을 넘긴 무한 IDLE 버킷

| ID | 버킷 | 종류 | 설명 |
| --- | --- | --- | --- |
| B1 | wait | A1 | 의도적 대기(리스폰·후퇴 회복·break). 탈출 조건이 영구히 거짓이면 고장 |
| B2 | handoff_pingpong | A2 | 매 틱 모드 왕복 후 합성 IDLE |
| B3 | empty_policy | A1/A2 | 할 일 없음(패트롤 없음·틀린 층·빈 농장) |
| B4 | path_fail | A1 | 입장/상점/hop 실패가 IDLE만 반복, 실패 미소비 |
| B5 | relieve_fail | A1 | nudge/unstick 실패 → 상위 IDLE |
| B6 | external_stall | A1 | 게이트·상점 UI·mapId 불변 대기 |
| B7 | bare_synthesize | A2 | handoff 없이도 열 전체 pass → 합성 IDLE |

공통 필요조건: 관측 불변, 또는 정책이 실패를 소비하지 않음, 또는 대기 탈출 조건 영구 거짓.

## 비범위 (지금 안 함)

- handoff DAG / 같은 틱 왕복 금지
- stuck 시계·알림
- `range(3)` 제거 또는 변경
- HP·후퇴·이동 로직 수정

## 다음 (별도 동의)

칸 표의 `idle_kind`를 기준으로 wait vs fail 화이트리스트·실패 토큰 설계.
