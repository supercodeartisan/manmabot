# `app._06_party` — Party module

파티 **행동·초대·집결** 로직의 홈 패키지.  
솔로 `_04_decision` 사냥 컬럼과 독립이다. 세션(`BotController`)이 프로필 역할에 따라 이 패키지와 `Engine/websocket`·`_05_action.chat`을 붙인다.

| | |
|--|--|
| **문서 갱신** | 2026-10-21 |
| **런타임 상태** | live (멤버=`PartyMemberManager` farm=`party`\|`solo`, 리더=솔로 decide + setup/rally + `party_policy` + 터렛 앵커 `party_turret`) |
| **comms/** | **적용됨** — 세션·rally·manager는 `comms` 경유 (와이어 불변) |
| **미적용 계획** | manager 분해, brains 실배선, `websocket/party_orders` 본문 이전 |

---

## 1. 책임 경계

| 하는 일 | 하지 않는 일 |
|---------|----------------|
| 멤버 1틱 결정 (`PartyMemberManager.decide`) | WebSocket 전송 스택 (`Engine/websocket`) |
| 팔로우 / 어시스트 / 루팅 / 맵 합류 | 솔로 사냥 컬럼 (`_04_decision`) |
| 리더 Start 초대 오케스트레이션 (`setup`) | 타이핑 구현 (`_05_action.chat` → enter_chat.dll) |
| 리더 첫 사냥 집결 FSM (`leader_rally`) | 프로필 UI / `party_listen` 센서 |
| 전술 순수 라이브러리 (`tactics/`) + 조합 모듈 (`turret_seat`, `formation`) | 메모리 읽기·입력 (호출자가 지형·타일 전달) |

**역할**

- **Leader:** 솔로 `DecisionManager`로 사냥 + `setup` / `leader_rally` + websocket 명령. **전역** 사냥 방식(터렛/이동)·루팅·로스터 역할은 리더 Party 탭에서 설정하고 `party_policy`로 브로드캐스트. 터렛이면 `_04_decision/behaviors/party_turret.py`가 사냥 지점에 앵커를 박는다.
- **Member:** `PartyMemberManager`가 decide peer. 기본 farm=`party` (리더 대상 공격), `solo` = 리더 근처 자기 몹. 정책은 `merge_leader_policy`로 수신. 리더 본체는 인게임 파티 메모리 `resolve_leader`.

**사냥 방식 — 두 축**

| 설정 | 위치 | 값 | 의미 |
|------|------|----|------|
| `leader_mode` | 리더 (policy로 전송) | `turret` (기본) | 리더 앵커 ~5×7 야드. 멤버는 야드 안에서만 전투 (party·solo 모두) |
| | | `moving` | 리더가 이동 사냥, 야드 없음. 통로(NARROW)에서 멤버는 리더 발자국 한 줄(자리 번호 × 2걸음 뒤). 멤버 절반 이상이 `lag_tiles`(기본 30, 파티 탭) 넘게 뒤처지면 리더가 최대 8초 대기 후 6초 쿨다운 |
| `farm_mode` | 멤버 자신 | `party` (기본) | 리더가 싸우는 대상 공격 |
| | | `solo` | 리더 근처 자기 몹 사냥 |

**터렛 — 리더 (`party_turret`, 파티 리더 + turret + 집결 대기 끝난 뒤만)**

- 앵커 = 활성 파밍 영역 안에서 처음 선 타일 (영역 없는 던전은 사냥 맵 첫 사냥 타일). mapId별 보관 → 상점/후퇴 후 같은 자리로 복귀. 40타일 넘게 멀어지면 새로 잡음.
- `party.turret_leash` (`farm.engage` 앞): 앵커 2타일 + 사거리(원거리) 밖 몹·2타일 밖 루팅을 `excluded_target_ids`에 추가, 존 밖 sticky 대상 해제, 앵커에서 3타일 이상 벗어나면 복귀 (사거리 안 대상과 싸우는 중이면 유지).
- `party.turret_idle` (`farm.engage` 뒤): 할 일 없으면 `farm.search`/`dungeon.patrol` 대신 앵커로 복귀(>1타일) 또는 대기.
- 솔로 봇·이동 모드 리더는 플래그가 없어 두 단계 모두 no-op.

**터렛 — 멤버**

- 야드 밖 대상: CLOSE_IN으로 추격, 그 전투(같은 대상)는 야드 밖에서도 끝까지. 끝나면 야드로 복귀. 야드 밖에 있을 때 새로 잡힌 야드 밖 대상은 무시하고 먼저 복귀.
- 대상 없을 때: 로스터 순번(`seat_index`)으로 `tactics.radial.fan_slots` 링 자리(반경 ≤2)에 선다 (`turret_seat.py`). 막힌/안 보이는 자리는 `resolve_slot`으로 가까운 칸.

**루팅**

- Solo loot (`random_loot`): 전원 줍기
- Responsible: 로스터 행의 `loot=responsible` 멤버만 줍기

**멤버 정책 오버레이 (임시)**

- `PartyMemberManager.base_config` = 멤버 자신의 프로필 값. `apply_leader_policy`는 그 위에 리더 정책을 **메모리에서만** 덮는다 (`clear_leader_policy`로 원복). 프로필/설정 파일에는 쓰지 않는다.
- 정책 변경 또는 자기 캐릭터 이름 확인 시 재적용 (초대 전 수신 → 이름 미확정 → 이후 roster seat/loot 해석).
- 솔로 실행(파티 off)은 `party_brain`이 없으므로 항상 원래 프로필 사용.

---

## 2. 패키지 구조

```
_06_party/
  README.md                 ← 이 문서
  __init__.py / _public.py  # 공개 API (동일 내용 — §6.3)
  config.py · state.py · types.py · policy.py
  manager.py                # 멤버 뇌 허브
  leader.py · follow*.py · intents.py
  assist.py · loot.py · support.py · join_map.py
  invite.py                 # 파티 초대 전부 (채팅 문구 · PartyInviter · LeaderInvites)
  leader_rally.py
  party_log.py
  comms/                    # 파티 통신 파사드 (아래 §4)
  brains/                   # 역할별 뇌 스텁 (미배선)
  turret_seat.py            # 터렛 링 자리 (radial) — 배선됨
  formation.py              # 이동 모드 지형 판별 + 한 줄 trail (멤버) / 뒤처짐 대기 (리더)
  tactics/                  # terrain_kind · radial · trail · focus_fire (순수)
```

### 2.1 파일 규모 (대략, `.py` 줄 수)

| LOC | 파일 | 역할 한 줄 |
|-----|------|------------|
| ~956 | `manager.py` | 멤버 decide 허브 |
| ~655 | `assist.py` | 어시스트 전투 |
| ~379 | `loot.py` | 파티 루팅 |
| ~356 | `intents.py` | Intent 조립 |
| ~333 | `leader.py` | 리더 해석 |
| ~250 | `follow.py` / `follow_field.py` | 추종 밴드·필드 |
| ~180 | `support.py` / `join_map.py` | 서포트·맵 합류 |
| ~390 | `invite.py` | 파티 초대 |
| ~160 | `leader_rally.py` / `policy.py` | 집결·정책 |
| ~10–140 | 나머지·`tactics/*`·`brains/*` | 상수·스텁·전술 |

### 2.2 패키지 밖 의존 (파티 시스템)

```text
┌─────────────────────┐
│  BotController       │  글루: 소켓 수명, 초대 1회, rally 훅,
│  (session)           │       leader/member tick, publish/ingest
└──────────┬──────────┘
           │
     ┌─────┴──────┬──────────────────┐
     ▼            ▼                  ▼
_06_party     websocket/        _05_action/chat
(행동·FSM)    (전송·주문)       (enter_chat 타이핑)
```

| 경로 | 역할 |
|------|------|
| `Engine/websocket/` | `PartyServer`/`PartyClient`, `party_orders`, `leader_decisions`, `member_status` |
| `Engine/app/_05_action/chat/` | `/초대`·`파티탈퇴` 타이핑 |
| `session/bot_controller.py` | `_start_party_*`, `_run_leader_party_setup`, `_leader_party_tick`, `_member_party_tick`, `_drain_party_reports`, `_install_party_nav_hooks` |

---

## 3. 런타임 흐름

### 3.1 멤버

```text
_member_party_tick(send=False)
  → member_orders.ingest(client.drain())
PartyMemberManager.decide(world)
  → policy → join_map | follow | assist | loot | support | gather(walk)
_member_party_tick(send=True)
  → heartbeat / report
```

`manager`가 gather할 때 `websocket.party_orders.member_orders`를 **lazy import**.

### 3.2 리더 Start

```text
(once) _run_leader_party_setup → invite.LeaderInvites.start
  → party_policy 전송 → (남의 파티면) 파티탈퇴 → PartyInviter 생성 (15분 창)
(매 틱) _leader_invite_tick → LeaderInvites.tick  — 블로킹 없음, 틱당 최대 1줄
  → 파티에 없는 로스터 이름마다 20s 간격 /초대 (가입 확인되면 중단)
  → 이름별 초대는 그 멤버가 현재 정책(policy_id)에 policy_ack 보낸 뒤에만 (타임아웃 없음)
  → 직전 행동이 상점·게이트·텔레포트·스크롤·리스폰이면 그 틱은 건너뜀
  → 15분 끝: 미가입 = 배제(excluded). 이후 늦게 가입하면 배제 해제
LeaderStartRally.begin(deadline=초대 창 끝) → (travel 시) on_plan / should_hold
  → Rally.arm: rally stages start | planned | landed
  → 초대와 병행 (이동하면서 초대). 공통 기한에 어떤 상태든 종료 → 미도착 기록 후 사냥
대기 중: set_party_hold + drain reports
모니터: PHASE (forming / rally / hunting + 남은 시간), 멤버별 초대 횟수·가입·도착·배제/미도착
이후: 솔로 decide → _leader_party_tick(recovery + party_policy) → publish_leader_decision
```

### 3.3 모듈 기능표

| 모듈 | 기능 |
|------|------|
| `policy` | `MemberKind` 우선순위 (순수, I/O 없음) |
| `manager` | kind 분기, gather 걷기, `MemberRuntime` |
| `leader` | 리더 이름·타일·거리 |
| `follow*` / `intents` | 추종·정착 Intent |
| `assist` / `loot` / `support` | 전투·루팅·물약 |
| `join_map` | 리더 맵 합류 내비 |
| `invite` | 초대 전부: 채팅 문구(`/초대 `, `파티탈퇴`), 로스터 이름·탈퇴 판정, `PartyInviter`(15분 창·20s 간격·배제), `LeaderInvites`(정책 먼저·소켓 대기·위험 행동 회피·틱 진행), `deliver_chat` |
| `leader_rally` | 첫 사냥 집결 FSM, WorldNav `hold_at_step` |
| `party_log` | `Engine/logs/party-*.log` 채널 |
| `brains/*` | `make_brain(role)` 스텁 — **세션 미사용** |
| `turret_seat` | 터렛 멤버 링 자리 (`tactics.radial` 사용) — **배선됨** |
| `formation` | `MemberFormation` (리더 발자국 기록 + 개활지/통로 판별 → 통로면 자리 번호별 trail 타일), `LeaderLineWatch` (알려진 멤버 절반 이상이 `lag_tiles` 넘게 뒤처지면 정지 — 뒤처짐 = 직선거리와 trail 걸음 중 큰 값, 다른 맵 = 뒤처짐; 최대 8초 후 6초 쿨다운), `followers_from_party` — 멤버: `manager._formation_trail_tile`, 리더: `bot_controller._leader_line_hold` → `set_party_hold` |
| `tactics/terrain_kind` | 반경 6 창의 보행 비율·통로 비율 + 히스테리시스 → `open`/`narrow` |
| `tactics/radial` | 링/부채꼴 자리, 시야선 보정 |
| `tactics/trail` | `LeaderTrail`, `leader_hold` (None = 위치 모름, 건너뜀) |
| `tactics/focus_fire` | 과잉 공격 방지 대상 분배 — **라이브러리만** (몹 HP·멤버 데미지·분배 메시지 필요) |

---

## 4. 통신 (`comms/`)

파티 코드의 **유일한 통신 진입점**. 전송 구현은 여전히 `Engine/websocket`.

```text
comms/
  __init__.py / facade.py   PartyComms (세션용)
  orders.py                 rally/report 타입·싱글톤 재export
  link.py                   서버/클라이언트 start·stop
  publish.py                decision / recovery / body
  ingest.py                 member orders / leader reports
  status.py                 member heartbeat·arrival report
```

와이어 JSON (불변):

```text
{"sender": "<name>", "ts": <float>, "message": <str|object>}
```

| `message.type` | 방향 | 의미 | 상태 |
|----------------|------|------|------|
| `decision` | L→M | 리더 행동 | 송신 live |
| `rally` + `stage` | L→M | 집결 `start`/`planned`/`landed` | live |
| `recovery` | L→M | 마더트리 좌표 | 송신 live / **멤버 본처리 미완** |
| `party_policy` | L→M | leader_mode·루팅·야드·party_size·roster·`policy_id` (farm_mode·거리는 멤버 자신) | live (멤버 `merge_leader_policy`) |
| `policy_ack` | M→L | 정책 적용 확인 (`from`, `policy_id`). 리더 초대 게이트 | live |
| `report` | M→L | 위치·도착 | live |

**의존 방향 (목표 달성)**

- `leader_rally` / `manager` → `comms.orders` (더 이상 `websocket.party_orders` 직import 없음)
- `BotController` → `PartyComms` (소켓 수명·tick·publish)
- `comms.*` → `websocket.*` (구현만)

초대 채팅은 **소켓이 아님** (`send_chat_line` → enter_chat.dll + Interception).

---

## 5. 공개 API

`__init__.py` / `_public.py`의 `__all__`:

`PartyMemberConfig`, `PartyMemberManager`, `MemberRuntime`, `MemberKind`, `decide_policy`, `LeaderView`, `resolve_leader`, `party_loot_ownership_filter`, `party_may_loot`, `party_log`

세션이 **패키지 밖에서 직import** 하는 것: `invite`, `leader_rally` (공개 목록에 없음).

---

## 6. 소프트웨어공학 이슈 (모듈 관리)

### 6.1 결합 (coupling)

| ID | 문제 | 영향 |
|----|------|------|
| C1 | `BotController`가 소켓·초대·rally·decide·publish를 한곳에 보유 | 파티 변경 시 세션 파일 충돌·회귀 범위 큼 |
| C2 | ~~도메인이 `websocket.party_orders` 직의존~~ → `comms.orders`로 완화 | 본문(Rally 클래스)은 아직 `websocket/`에 있음 |
| C3 | ~~세션이 websocket을 직접 호출~~ → `PartyComms` | 모니터 UI는 여전히 `_party_ws` 미러 |
| C4 | `manager`가 전역 `member_orders` 싱글톤 읽기 | 숨은 공유 상태 (미해결) |

### 6.2 응집 (cohesion) · 크기

| ID | 문제 |
|----|------|
| H1 | `manager.py` ~950 LOC — follow/assist/loot/gather/join 혼재 |
| H2 | `assist.py` ~650 LOC — 전투가 패키지 무게의 큰 몫 |
| H3 | `websocket/party_orders.py` — 빌더 + FSM + 전역 인스턴스 한 파일 |

### 6.3 API · 중복 · 이중 진입점

| ID | 문제 |
|----|------|
| A1 | `__init__.py` ≡ `_public.py` — 이중 유지 |
| A2 | 패키지 docstring이 member-only — 리더 setup/rally 책임이 안 보임 |
| A3 | `brains/` vs `PartyMemberManager` — 스텁과 실경로 병존 |
| A4 | 리더 API가 `__all__` 밖 — import 규약이 문서화되지 않음 |

### 6.4 미완성 · 관측 함정

| ID | 문제 |
|----|------|
| D1 | 배선: radial(터렛 자리), `formation`(terrain_kind+trail, 이동 모드). 미배선: focus_fire. teleport_sync·stagger는 삭제(2026-10-21) |
| D2 | `recovery` 멤버 처리 미완 |
| D3 | `traffic_log`의 `local chat`은 타이핑/와이어 성공 증거가 **아님** |
| D4 | 과거 빌드 `invite chat disabled (empty)` 로그와 현재 코드 혼동 |

### 6.5 테스트

- `Others/tests/test_party_invite_setup.py`, `test_party_rally.py`, `test_party_hold_ground.py`, `test_party_member.py`, …
- 초대 성공 판정: 로그에 `Party chat "…"` + 약 1초 소요 또는 `failed:` / `not delivered` (재시도 포함).

### 6.6 권장 개선 (우선순위)

1. ~~**`comms/` 파사드**~~ — **완료** (2026-10-20).  
2. ~~**`BotController` 파티 I/O → PartyComms**~~ — **완료** (모니터 미러 핸들은 유지).  
3. **`manager` 분해** 또는 `brains` 실배선.  
4. **`Rally`/`MemberOrders` 본문을 `_06_party/comms`로 이동** 후 `websocket`은 thin re-export.  
5. **`__init__`/`_public` 단일화** + 리더 공개 API 명시.  
6. **`tactics`/`brains` 상태 배지** — wired / stub / library-only.

---

## 7. 의존 규칙 (의도)

| From → To | 허용? |
|-----------|--------|
| `_06_party` → `_03_world` / 순수 유틸 | 예 |
| `_06_party` → `_04_decision` (제한적, assist/support) | 현행 허용 — 확대 자제 |
| `_06_party` (행동) → `comms` | **예** |
| `_06_party/comms` → `websocket.*` | **예** (구현 전용) |
| `_06_party` (행동) → `websocket.*` | **금지** |
| `_06_party` → `session` | **금지** |
| `websocket` → `_06_party` | **금지** (순환 방지) |
| `session` → `comms` + `_06_party` + `chat` | **예** (`websocket` 직import 금지 목표) |

---

## 8. 불변 조건

- 라이브 **mapId**: MapSubsystem만 (`mgr → holder → subs → MapSubsystem → +MapIdOff`). 플레이어 `MapId +0x134` 금지.
- 초대 입력: **Interception / enter_chat**. SendInput·클립보드·Ctrl+V 금지.
- 결정·로그인·이동·전투·HP 공유 로직 변경: 사전 동의 + `Docs/decision_change_log.md`.
- 와이어 `type` / `rally.stage` 변경: 리더·멤버 동시 배포.

---

## 9. 문서 이력

| 날짜 | 내용 |
|------|------|
| 2026-10-20 | 초안: 구조·기능·통신·SE 이슈 |
| 2026-10-20 | **갱신:** LOC표, 런타임 시퀀스, bot_controller 메서드명, brains/tactics 상태, 의존 규칙표, 이슈 ID(C/H/A/D), recovery·관측 함정 보강 |
| 2026-10-20 | **comms/ 적용:** `PartyComms` + orders/link/publish/ingest/status. 세션·rally·manager 경유 변경. 와이어 불변. |
| 2026-10-21 | 리더 터렛/이동 · 멤버 파티/솔로 분리, 멤버 소켓 게이트·재연결, 리더 터렛 앵커, 멤버 야드 밖 CLOSE_IN, radial 자리 배선. |
| 2026-10-21 | tactics 정리: teleport_sync·stagger 삭제, `formation.py`(terrain_kind+trail) 추가, focus_fire 라이브러리 유지. |
| 2026-10-21 | formation 배선: 이동 모드 멤버 통로 한 줄 trail, 리더 뒤처짐 대기(절반 이상 > `party_lag_tiles` 기본 30, 파티 탭 설정). |
