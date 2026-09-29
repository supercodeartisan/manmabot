## 7. 신뢰도(Trust) 모델과 예외처리 (부록 B)

### 7.1 신뢰도
소스별 `OK / DEGRADED / STALE / FAILED`: `memory, entity_sweep, inventory, vision, capture, input, cursor, focus`.
틱마다 산출, 블랙보드 저장, KPI/로그 노출.

### 7.2 결정 게이팅(하드 제약)
| 소스 상태 | 허용 | 금지 |
|---|---|---|
| memory OK | 전부 | — |
| memory STALE/FAILED | 비전 폴백 파밍·대기 | HP/MP 후퇴 판단, 귀환 단정 |
| entity_sweep DEGRADED | 비전 클릭 | 메모리 클릭 |
| vision FAILED | 대기·복구 | 공격/루팅 |
| inventory STALE | 보수 임계 | 판매/구매 트립 단정 |
| input/cursor FAILED | 복구 대기 | 클릭 주입 |
| focus 상실 | 일시정지 | 입력 |

**fail-safe**: `memory+vision+input` 중 2개 이상 FAILED → 입력 정지 + 복구(무한 재시작 금지, 예산 bounded).

### 7.3 예외 카탈로그
E1 드라이버/게임 종료, E2 오프셋 불일치(hp>max, pos(0,0), level≤0 → STALE), E3 스윕 실패, E4 화면밖 좌표, E5 비전 프레임 None, E6 추론 적체, E7 라벨 스테일, E8 track 스위치, E9 가방 스테일, E10 bag 미준비, E11 물약 딜레이 미상, E12 arrow_lack, E13 커서 템플릿 부재, E14 커서 마비, E15 포커스 상실, E16 경로 차단, E17 스턱, E18 사망 감지 실패, E19 구매 미검증, E20 버프 타이머 어긋남, E21 스레드 경합, E22 설정 drift, E23 맵팩/팜 누락, E24 지역모델 누락, E25 UI 램프, E26 정지 비원자성.

### 7.4 공통 구현 규칙
- 값 검증: `0 ≤ hp ≤ max_hp`(둘 다 >0), `1 ≤ level ≤ 99`, `pos ≠ (0,0)`. 위반 시 STALE, 필드는 None 유지(0 위조 금지).
- 스테일/이상 시 보수적 강등. 강등/복구/fail-safe는 구조화 로그(채널 `trust`)로 1회 기록(스팸 금지).
- 복구: 입력 락 → 원인 재확인 → 재연결(메모리/캡처) → 정상 복귀. 예산 초과 시 정지.
