# 의사결정 수정 로그 — 악순환 분석

이 문서는 **한 곳의 텔레포트/회복/이동 규칙을 고치면 다른 모드가 같이 바뀌는** 이유를 기록한다.
이후 로직 수정은 이 문서의 **영향 고지 → 사용자 동의 → 구현 → 결과 기록** 순서로만 한다.

마지막 갱신: 2026-10-14 (수색 홉 우회 + 재클릭)

---

## 2026-10-14 — 사냥 수색 홉에 plan_body_click + 0.1s 재클릭

의도: 커버리지 `next_leg` 목표는 유지하고, 클릭만 travel/loot와 같이 `plan_body_click` 우회 홉으로 고른다. 도착 대기 중 몸이 안 걸으면 ~0.1s 같은 홉 재클릭. `farm_visit`은 `search_leg_goal` 도착 시에만.
공유: `emit_search_hop`, `plan_body_click`, blackboard `search_leg_goal` / `search_click_at`.
영향: farming SEARCHING만. 전투·루팅·travel·LEG_TICKS/unstick 상수 불변.
동의: 사용자 (“2단계까지 적용”).
결과: 구현.

---

## 2026-10-14 — until_walk 재클릭에도 NORMAL 커서 재확인

의도: travel `until_walk`가 첫 NORMAL 검증 후 0.1s 재클릭할 때 커서가 arrow 등으로 바뀌면 더 이상 누르지 않는다 (`how=cursor`). 흑기사 등 블랙리스트 위를 이동 중 오공격하는 경로를 막는다.
공유: `MouseController.click(cursor_ok=)`, `_click_until_walk`, `verified_click` until_walk 게이트.
영향: `travel_click` 지면 홉(수색/이동/루팅 접근/unstick). 공격·루팅 단발 클릭 불변.
동의: 사용자 (“until_walk 재클릭에도 커서 확인을 적용”).
결과: 구현.

---

## 2026-10-14 — until_walk 0.4s 예산 제거

의도: 지면 홉은 다시 몸이 stand/walk 될 때까지(또는 unread 1s) 재클릭한다. 0.4s `GROUND_CLICK_BUDGET_S` early exit는 처치 직후 search `hold`와 겹쳐 걷기 없이 수 초 정지를 만들었다. execute pose-pulse는 유지.
공유: `MouseController._click_until_walk`만. `GROUND_CLICK_BUDGET_S` 삭제.
영향: SEARCHING / TRAVELING / 루팅 접근 / unstick 지면 홉. 공격 클릭·pose-pulse 불변.
동의: 사용자 (“예산 제거만 실행”).
결과: 구현.

---

## 2026-10-14 — execute가 막혀도 캐릭 좌표는 계속 갱신

의도: `until_walk`·상점·게이트처럼 execute가 길면 틱이 안 돌아 디버그/decide 좌표가 고정된다. execute 동안 0.1s마다 모니터 pose를 스탬프하고, ground-click은 0.4s 예산으로 틱에 반환한다.
공유: `refresh_live_player_pose`, `ActionExecutor.execute` pose-pulse 스레드, `MouseController._pose_pulse`, `GROUND_CLICK_BUDGET_S=0.4`, bot_controller가 blackboard 전달.
영향: 이동/검색/상점/게이트/스크롤 실행 중 라이브 xy·mapId·`world_origin`. 전투 클릭 자체는 until_walk 없음. print_state player x/y도 모니터에 맞춰 패치.
동의: 사용자 (“어떤 경우에도 매 틱에 필요한 좌표를 갱신”).
결과: 구현. **후속: 예산만 2026-10-14 항목에서 제거(pose-pulse 유지).**

---

## 2026-10-14 — talking scroll 착지 = 스폿 좌표 4타일 / 마더트리는 버프

의도: `apply_talking_scroll_arrival`이 클릭 직후 팩만 바꾸던 것을, 스폿에 기록된 mapId·xy 체비셰프 ≤4일 때만 성공으로 바꾼다. 마더 트리 귀환은 라이브 xy가 아니라 기존처럼 `세계수의 가호` 버프로 도착을 본다.
공유: `talking_scroll._arm_scroll_arrival` / `apply_talking_scroll_arrival`, `SCROLL_ARRIVAL_SLACK=4`, bot 루프 매 틱 폴링. `mode_ticks._hold_until_world_tree_blessing` 주석만.
영향: 말하는 두루마리 착지·팩 전환 타이밍. 월드내비 스크롤 wait(±8)·상점 `_at_shop`·전투/HP 로직 불변. 마더 트리 판정 불변.
동의: 사용자.
결과: 구현.

---

## 2026-10-14 — world-nav: NPC 텔레포트 착지는 xy가 옮겨진 뒤에만

의도: 글루딘 던전 텔레포트는 mapId가 그대로(4)라서, SHOP_RUN 종료 1초 후 한 번 읽은 좌표가 텔레포터 칸이면 입구를 마을에서 걸어가는 클릭이 나간다. 착지 확정은 라이브 xy가 NPC 칸에서 체비셰프 >15로 떠난 뒤로만 한다.
공유: `WorldNavSession.note_npc_teleporter_ok` / `_tick_npc_teleporter_settle`, `NPC_TP_LAND_MOVE_TILES` / `NPC_TP_LAND_TIMEOUT_S`, 착지 시 `world_origin` 스탬프.
영향: 월드내비 NPC 텔레포트 → 게이트 접근만. 스크롤 착지·전투·HP·로그인 불변. 텔레포트가 실패하면 마을에서 입구까지 걷지 않고 스텝 실패.
동의: 사용자 (“텔레포터 이용후에 맵 좌표를 갱신하고 다음 동작으로… 수정”).
결과: 구현. 원인: 2026-10-05 설계가 “클릭 종료 +1초 후 pose 1회”였고, 연출이 느리면 구좌표를 착지로 잠근다(17:19 로그).

---

## 2026-10-14 — 죽은 소스 몹이 있으면 드랍은 OTHER

의도: etview와 같이, 기여도 0인 더미는 스윕에 남아 있는 소스 액터 guid가 인접하면 OTHER다. 죽은 액터를 명단에서 빼면 그 더미가 FREE로 바뀌어 줍게 된다.
공유: `print_state.c`의 스윕 보관과 JSON 출력. 전투·루팅 명단에는 죽은 액터를 넣지 않는다. 줍기 조건(FREE 또는 contrib>30)은 그대로다.
영향: 소스 시체가 메모리에 있는 동안의 아이템 `own`. 살아 있는 몬스터 목록은 그대로다.
동의: 사용자. etview 판단을 기준으로, etview 코드는 가져오지 않음.
결과: `print_state.dll` 재빌드.

---

## 2026-10-14 — 루팅 결심 때 아이템 클레임을 로그에 남긴다

의도: 아이템을 줍기로 한 순간 `own`/`contrib`/`guid`와 메인 게이트 허용 여부를 한 줄로 남긴다. 고르는 조건은 그대로다.
공유: `begin_loot_item`의 `loot decide via=main`, 발밑 F4의 `loot decide via=side`. F4는 같은 id·클레임이면 틱마다 반복하지 않는다.
영향: 로그뿐. 전투·이동·줍는 대상은 그대로다.
동의: 사용자.
결과: 구현. `test_ground_loot.py`.

---

## 2026-10-14 — 다른 캐릭이 치는 몬스터는 guid로 제외

의도: 새 교전 후보는 contested DLL의 `guid`와 `memory_guid`가 같을 때만 뺀다. 월드 칸은 쓰지 않는다. guid가 없는 몬스터는 이 필터에 안 걸린다.
공유: `contested_mob_guids`, `is_contested_monster`, `list_attackable`, `describe_attackable_filter_skips`.
영향: 농장·던전에서 `nearest_attackable`로 새로 고르는 대상. 스티키와 나를 친 몹 강제 교전은 그대로 이 목록을 타지 않는다.
동의: 사용자.
결과: 구현. `test_attack_filter.py`. 다음 봇 실행 로그의 `contested guid filter`로 확인.

---

## 2026-10-14 — 클릭이 10초 없으면 패트롤 점을 넘긴다

의도: 가이드는 있는데 살아있는 장애물 때문에 클릭이 없는 상태가 그 점 기준으로 10초 이어지면 다음 패트롤 점으로 간다. 클릭이 나오거나 지형 경로가 없으면 시계는 다시 시작한다. 지형 경로가 없는 실패는 그대로다.
공유: 패트롤 `emit_travel_hop`, `skip_blocked_patrol_point`. 루팅, 필드 이동, 전투 선택은 그대로다.
영향: 던전 패트롤에서 클릭을 못 고르는 동안.
동의: 사용자.
결과: 구현. `test_patrol_skip.py`.

---

## 2026-10-14 — 던전 루팅은 15칸, 블랙리스트 공격은 무시

의도: 던전에서 새 루팅은 A* 15칸 이하만 집는다. 전투의 새 목표 한도는 30칸이다. 던전에서 블랙리스트 종이 공격해도 반격하지 않고, 그 종에 걸린 락도 놓는다. 필드에서는 공격받으면 블랙리스트를 넘어 반격한다.
공유: `list_lootable`의 경로 한도, `list_attacked_me_targets`, `nearest_attacks_me_force`, `continue_sticky_combat`.
영향: 던전에서 고르는 더미, 던전에서 블랙리스트 종의 반격. 필드 루팅 거리와 필드 반격은 그대로다.
동의: 사용자.
결과: 구현. `test_ground_loot.py`, `test_attacks_me_finish_kill.py`.

---

## 2026-10-14 — 던전 패트롤과 루팅은 살아있는 장애물을 피해 걷는다

의도: 패트롤과 루팅 걸음만 중간 경유점 다음 클릭이다. 루팅 목적지는 더미 칸이다. 걷지 않으면 0.1초마다 같은 클릭을 다시 보낸다. 클릭이 없으면 다음 틱에 다시 고르고, 지형 경로가 없을 때만 기존 실패 처리로 간다.
공유: `plan_body_click`. 패트롤의 `emit_travel_hop`, 루팅 접근. 필드 이동·상점·후퇴·언스틱의 `plan_travel_click`은 그대로다. 전투·루팅 선택 순서와 줍기 거리는 그대로다.
영향: 던전 패트롤 클릭과 더미로 걸어가는 루팅. 그 두 걸음은 클릭이 안 먹어도 2초를 서서 기다리지 않는다.
동의: 사용자. 루팅 목적지는 더미, 0.1초 재클릭은 필수.
결과: 구현. `test_avoidance_click.py`.

---

## 2026-10-13 — 대각 틈은 양쪽이 벽일 때만 닫힘

의도: 어깨가 살아있는 장애물 둘이거나, 살아있는 장애물과 벽이면 그 대각으로 빠질 수 있다. 양쪽이 모두 벽일 때만 막힌다. 밟는 칸이 벽이거나 살아있는 몸통이면 그대로 거절한다.
공유: `click_clear`, 회피 창 검색. 이동 홉의 `is_game_walk_clear`와 `select_click_waypoint`는 그대로다.
영향: avoid-view가 어깨에 몸통이 있는 대각 클릭을 고를 수 있다.
동의: 사용자 (클라이언트에서 그 짬으로 빠진다고 확인).
결과: 구현. `test_avoidance_click.py`.

---

## 2026-10-13 — 클릭 걷기는 대각 다음 축

의도: 지면 클릭의 타일 순서는 좌표계에서 대각을 먼저 걷고, 남은 칸만 축으로 간다. `|dx|=|dy|`는 끝까지 대각이다.
공유: `game_client_walk_tiles`. 이것을 보는 `is_game_walk_clear`, `is_click_valid`, `click_clear`, 회피 클릭, avoid-view 주황선.
영향: 이동 홉이 허용하는 클릭, 루팅·전투의 지면 클릭 가능 판정. 공격 사거리는 직선이라 그대로다.
동의: 사용자 (클라이언트에서 대각이 먼저임을 확인).
결과: 구현. `(0,0)→(5,2)`는 `(1,1) (2,2) (3,2) (4,2) (5,2)`.

---

## 2026-10-13 — 막힌 대각 핀치는 경로가 아님

의도: 양쪽 어깨가 막힌 대각은 이동이 아니다. 내비는 그 칸을 연결로 보고 경로를 내지 않는다.
```
X B
A X
```
공유: `diagonal_open` → `find_path`, `build_portal_graph`, `neighbors8`, 월드 내비 `astar_nav`. 클릭 폴리라인 판정, 후퇴, 전투 시전, 로그인은 그대로.
영향: 그 한 칸이 유일한 통로이면 경로가 없다. 어깨 한쪽이 열려 있거나 돌아가면 기존처럼 간다. 맵 에디터·던전 패트롤의 `find_path`도 같은 규칙을 본다.
동의: 사용자 (못 가는 것이 정상이고, 내비가 연결로 보는 것이 오류).
결과: 구현. `test_portal_graph.py`. 이미 만든 `nav_prebuild`는 다시 빌드해야 그래프가 갈라진다.

---

## 2026-10-12 — 텔레포트 투 마더를 가호가 있을 때까지 반복

의도: 한 번 시전을 세계수 도착으로 보지 않는다. HP가 95% 미만인 동안, 시전 2초 뒤 버프에 세계수의 가호가 없으면 MP가 10 이상일 때 다시 누른다. MP가 모자라면 후퇴를 유지한 채 마나를 기다린다. HP가 95% 이상이면 가호가 없어도 후퇴를 끝낸다.
공유: `_tick_mother_tree_retreat`. 세계수로 가는 진입(HP 후퇴, 착지 후, 텔레포트 폴백, 리스폰, 던전 GUI)은 이 틱을 이미 탄다.
영향: 가호 확인 전의 대기. 가호가 있거나 스킬을 더 쓸 수 없으면 기존 힐·바디 투 마인드. 상점, `begin_retreat`, 버프 읽기, 키 입력은 그대로.
동의: 사용자. HP가 회복되면 가호 없이도 후퇴를 끝낸다.
결과: 구현. 단위 테스트. 실기는 봇 재시작 후.

---

## 2026-10-12 — 마더트리 회복 HP/MP 기준을 일정에서 설정

의도: 마더트리 대기에서 바디 투 마인드와 힐이 보는 HP/MP 퍼센트를 복구 설정의 마더트리 회복 블록에서 바꾼다. 체크를 끄면 그 스킬만 나가지 않는다.
공유: 일정 `recovery.mother_tree_*` → 프로필 비율 → `decision.mother_tree` → `HP_TO_MP_*` / `MP_TO_HP_*`. 시전은 기존 `maybe_hp_to_mp` / `maybe_heal_mp_to_hp_at_tree`.
영향: 그 두 스킬의 문턱과 사용 여부. 없는 항목은 기본값(바디 투 마인드 HP 85·MP 80, 힐 HP 40·MP 80, 둘 다 사용).
그대로: 슬롯 선택, 쿨다운, 마나 바닥, 95% 이탈, 상점, 사냥터 복귀.
동의: 사용자 (UI에서 네 값을 직접 설정).
결과: 구현. 단위 테스트. 일정 창은 다시 열어야 칸이 보인다.

---

## 2026-10-12 — 마더트리 회복 대기에서 MP를 힐로 소비

의도: 마더트리에 도착해 회복 대기 중일 때만, HP ≤ 40%이고 MP ≥ 80%이면 기존 힐로 MP를 써 HP를 올린다. 매 틱 다시 보고, HP > 40% 또는 MP < 80%이면 멈춘다.
공유: `maybe_heal_mp_to_hp_at_tree` → `heal_press_slot`, `heal_blocked_by_mana`, `emit_heal`. 호출은 `_tick_mother_tree_retreat`의 `recharge`뿐.
영향: 그 대기 틱. 힐이 나가면 그 틱의 바디 투 마인드는 없다. 조건이 안 맞거나 마나 바닥·쿨다운·슬롯이 없으면 트리 앞 대기로 남는다.
그대로: 95% 이탈, 바디 투 마인드(HP ≥ 85%, MP < 80%), 상점, 필드 힐 문턱, 물약 옆 채널.
동의: 사용자 (회복 대기 중에만 이 조건으로 추가).
결과: 구현. 단위 테스트 추가. 실기는 봇 재시작 후.

---

## 2026-10-12 — 실험 중이던 회피 걷기를 봇에서 제거

의도: 이동·수색·루팅은 다시 가이드 웨이포인트를 클릭한다. 근처 살아있는 몸이 그 클릭을 바꾸거나, 홉을 끊거나, `avoid_blocked`로 홉을 실패시키지 않는다.
공유: 봇은 `collect_body_tiles`, `plan_avoidance_click`, `click_clear`, `apply_avoidance`를 호출하지 않는다. `decide()`는 몸 타일을 갱신하지 않는다. `avoidance.py`는 avoid-view 도구용으로 남긴다.
영향: 이동, 수색, 루팅, 그리고 그 홉으로 걷는 모드.
그대로: 전역 A*, 전투 클릭, unstick, 2초 재클릭, 1칸 도착.
동의: 사용자 (본 프로젝트에서 제거. 실험에서 성능이 확인된 뒤에만 다시 넣는다).
결과: 코드 제거. 재시작 후 실기 대기.

---

## 2026-10-11 — 지면 클릭은 걷기가 시작될 때까지 반복

의도: 몸이 공격·방향전환·줍기·피격 중이면 클라이언트가 지면 클릭을 무시한다. 수색·이동·후퇴·unstick·루팅 접근의 지면 홉은 0.1초마다 같은 점을 누르고, 몸이 서거나 걷기가 시작되면 멈춘다. 처치 뒤에 다음 마우스 클릭을 장전하던 방식은 공격 클릭에도 붙었으므로 제거한다.
공유: `travel_click` → `Mouse.click(until_walk=True)`. 간격 `GROUND_CLICK_INTERVAL_S`, 몸 읽기 실패 상한 `GROUND_CLICK_UNREAD_S`.
영향: `SEARCHING` / `TRAVELING` 지면 홉. 이미 서 있거나 걷는 중이면 한 번이다. 틱은 클릭 함수가 끝날 때까지 기다린다.
그대로: 공격, 게이트, 상점, 말하는 두루마리, 사망 화면, F4, 로그인. `clickgap`은 기록만 한다.
동의: 사용자 (지면 클릭마다, 처치 전용 장전은 쓰지 않음).
결과: 구현. 단위 테스트 갱신. 실기는 봇 재시작 후.

---

## 2026-10-11 — 공격은 직선 위 장애물만 막는다

의도: 몬스터가 공격 가능한지는 캐릭터와 몬스터 사이 직선에 막힌 칸이 있는지만 본다. 클릭 사거리 안이고 그 선이 비어 있으면 공격한다. 필드와 던전이 같다. 클라이언트 걷기 폴리라인은 공격 판정에 쓰지 않는다.
공유: `can_engage_target`. `list_attackable`과 스티키 전투가 호출한다. 필드에서 선이 막히면 기존 벽 우회로 넘어간다. 던전 스티키 해제는 그대로다.
영향: 신규 대상은 나무 뒤면 고르지 않는다. 이미 붙은 필드 대상은 화살 대신 우회한다. 화면 밖이고 8칸보다 멀면 선이 비어도 여기서는 공격하지 않는다.
그대로: 이동·수색·루팅의 `is_game_walk_clear`, 던전 신규 대상 경로 길이 상한.
동의: 사용자 (제시한 범위로 YES).
결과: 단위 테스트 갱신. 실기(나무 너머 화살) 대기.

---

## 2026-10-11 — 후퇴가 끝나면 사냥 맵 밖에서는 월드 내비로 복귀

의도: 마더트리·텔레포트·말하는 두루마리로 맵이 바뀐 뒤, 저장해 둔 던전 순찰 칸을 현재 맵에서 걷지 않는다. 루틴 맵으로의 복귀는 월드 내비가 맡는다.
공유: `finish_retreat`. 같은 사냥 맵 안에서의 이동 재개, 상점 트립 재개, 사망 후 `post_respawn`은 그대로다.
영향: 후퇴가 `traveling` 도중 시작되고 착지가 사냥 맵 밖이면 `begin_world_nav(..., "post_retreat")`. 던전 순찰 중 마더트리로 본토에 내린 경우가 이 경로다. 사냥 맵 안에 있으면 저장한 목적지를 그대로 걷는다.
동의: 사용자 (월드 내비가 마지막 농장/던전 복귀를 맡도록 지금 고치기).
결과: 구현.

---

## 2026-10-10 — 처치 뒤 반복 클릭은 걷기가 시작되면 멈춤

의도: 0.1초 반복은 몸이 설 때만 멈췄다. 클릭이 걷기를 시작하면 서는 상태가 오지 않아 같은 점을 계속 눌렀다. 몸 동작이 걷기이면 반복을 멈춘다.
공유: `Mouse._click_until_stand`. 장전 조건과 0.1초 간격은 그대로다.
영향: 처치 뒤 첫 마우스 클릭. 공격·방향전환·줍기 중에는 계속 누르고, `MovingAction` 또는 `MovingBackAction`이 보이면 다음 클릭을 내지 않는다. 읽기 실패 1초 상한은 그대로다.
동의: 사용자 (“실제로 움직이기 시작하면 클릭을 멈추자”).
결과: 구현.

---

## 2026-10-10 — 처치 뒤 첫 클릭은 설 때까지 0.1초마다

의도: 선 자세를 확인한 뒤 한 번 누르는 방식은 동작이 끝나기 전에 다음 행동이 가능한 시점보다 늦다. 처치 뒤 다음 클릭은 바로 누르고, 몸이 설 때까지 0.1초마다 같은 점을 다시 누른다.
공유: `Mouse.click`, `take_post_kill_stand`. 장전 조건은 그대로다.
영향: `no-rematch` / `dead-window` / `finish-gone` / `exp` 뒤의 첫 마우스 클릭. 이미 서 있으면 한 번만 나간다. 공격·이동·줍기 동작이 보이는 동안은 0.1초마다 반복되고, 그 틱은 설 때까지 멈춘다. 몸 동작을 읽지 못하면 1초 뒤 반복을 멈춘다. 그 외 클릭과 F4는 한 번이다.
동의: 사용자 (“0.1s/click till standing”을 구현).
결과: 구현.

---

## 2026-10-10 — 마더트리 켠 동안 스킬 MP 비용으로 마나 15 확보

의도: 후퇴 1순위인 마더트리(카탈로그 10 MP)를 위해, 마더트리가 켜진 엘프는 다른 마법이 `현재 MP − 스킬비용 < 15`이면 시전하지 않는다. 마더트리·바디투마인드는 예외.
공유: `mother_tree_mana_blocks`, `spell_mp_cost_for_role`, `can_cast_spell`, `heal_blocked_by_mana`, `_press_assigned_skill`, `_mana_blocks_teleport`. 비용은 `analysis/list/*/spell.json`의 `consumables.mp`(핫바 이름 → 역할 폴백).
영향: 사냥 버프/힐/마법공격/텔레포트(마더트리 켜진 경우). 마더트리 후퇴·로그인·`RETREAT_METHOD_ORDER`·기존 20% 예비는 그대로. 마더트리 설비가 꺼지거나 논엘프면 비활성.
동의: 사용자 (카탈로그 비용 + 마더트리 on일 때만, 바닥 15).
결과: 구현.

---

## 2026-10-10 — 처치 뒤 첫 클릭은 선 자세를 기다린 한 번

의도: 0.2초 4연타를 없앤다. 처치 뒤 다음 마우스 클릭은 한 번이고, 몸 동작이 서 있을 때 누른다. 결심 뒤 1초 안에 클릭이 안 나가면, 판별이 실패해도 그 클릭을 한 번 강제로 누른다.
공유: `log_sticky_release`, `arm_post_kill_stand`, `take_post_kill_stand`, `Mouse.click`, `body_is_standing`.
영향: 사냥에서 `no-rematch` / `dead-window` / `finish-gone` / `exp` 뒤의 첫 마우스 클릭(탐색, 이동, 다음 공격 중 먼저 나오는 것). 전투 중의 공격 클릭, F4 줍기, 포기, 블랙리스트, 던전 벽은 즉시 한 번이다. 로그인과 HP는 그대로다. 대기 중 그 틱은 최대 1초 멈춘다. 2초 재클릭은 클릭이 나간 뒤에 시작한다.
동의: 사용자 (4연타 제거, 선 자세까지 한 번, 1초 강제 클릭).
결과: 구현.

---

## 2026-10-09 — 처치 뒤 첫 클릭 간격 0.2초

의도: 횟수는 네 번 그대로 두고 간격만 0.2초로 늘린다.
공유: `POST_KILL_INTERVAL_S`.
영향: 처치 직후 첫 마우스 클릭. 네 번의 간격은 0.6초다.
동의: 사용자 (“0.2 초 간격으로 4번 클릭으로 바꾸어보시오”).
결과: 구현.

---

---

## 2026-10-09 — 처치 뒤 첫 클릭은 0.1초 간격 4회

의도: 같은 실험의 횟수와 간격만 바꾼다. 처치 뒤 다음 결심의 클릭은 같은 점에서 0.1초 간격으로 네 번이다.
공유: `POST_KILL_CLICKS` / `POST_KILL_INTERVAL_S`. 장전 조건과 평소 한 번 클릭은 그대로다.
영향: 처치 직후 첫 마우스 클릭의 길이. 네 번의 간격은 0.3초다.
동의: 사용자 (“0.1초 간격으로 4번으로 바꾸시오”).
결과: 구현.

---

## 2026-10-09 — 처치 뒤 첫 클릭만 0.03초 간격 5회

의도: 3연타를 거두고 평소 클릭은 한 번으로 되돌린다. 몬스터 처치 해제가 난 뒤 다음 결심의 마우스 클릭만 같은 점에서 0.03초 간격으로 다섯 번 누른다. 공격 동작이 끝나기 전에 클라이언트가 이동을 무시하는지를 보는 실험이다.
공유: `Mouse.click`. 장전은 `no-rematch` / `dead-window` / `finish-gone` / `exp`만. 포기·블랙리스트·던전 벽은 한 번이다. 아이템을 주운 뒤의 클릭에는 아직 넣지 않는다.
영향: 사냥 중 처치 직후 첫 마우스 클릭(탐색, 이동, 룻 접근, 다음 공격 중 먼저 나오는 것). 그 외 클릭과 F4 줍기는 한 번이다. 2초 재클릭 대기는 다섯 번이 끝난 뒤에 그대로다.
동의: 사용자 (“3번 매시브를 한번 클릭으로 되돌리고, 몬스터를 죽인 다음 클릭은 0.03초 간격 5번. 줍기 다음 클릭은 실험 후에”).
결과: 구현. 평소 경로는 `click(x, y, delay=…)` 한 번. 장전된 경우만 이어서 네 번을 0.03초 간격으로 더 누른다.

---

## 2026-10-09 — 마우스 이동은 곡선, 0.02초 안에 끝

의도: 공격·탐색·이동 클릭도 곡선으로 옮기되, 한 번의 이동이 0.02초를 넘지 않게 한다. 상단 토글로 끈 경우에는 커서가 바로 점프한다.
공유: `MouseController.move`. 키 입력 인간화(`humanize`)와는 따로다.
영향: 공격 조준, 탐색·이동·룻 호버, 두루마리 휠 위치, 상점 클릭, 사망 화면 재시작. 목표는 같고 도착이 최대 0.02초 늦어진다. 클릭 판정과 전투 선택은 그대로다.
동의: 사용자 (“인간화 이동을 적용하되 속도를 높여… 0.02초내에… 토글을 UI에 추가”).
결과: 구현. 토글은 콘솔 상단. 켜진 상태는 프로필 `humanize_move`에 저장되고 실행 중에도 바로 바뀐다.

---

## 2026-10-09 — 두루마리가 2초 안에 안 열리면 키를 한 번 더

의도: 직전 구현의 “안 열리면 클릭”은 오타였다. 2초 안에 TalkingScroll이 안 열리면 칸을 다시 고르고 키를 한 번 더 누른 뒤 다시 2초를 기다린다. 그래도 안 열리면 휠과 클릭을 하지 않는다.
공유: `ActionExecutor._use_talking_scroll`.
영향: 월드 내비·상점·후퇴의 말하는 두루마리. 열린 뒤에만 휠과 목록 클릭. HP·전투·일반 이동 불변.
동의: 사용자 (“2초안에 열리지 않았으면 두루마리 켜기를 한번 더 시도. 클릭이 아니다”).
결과: 구현. 재시도 후에도 닫혀 있으면 `skip wheel and click` 후 반환.

---

## 2026-10-09 — 말하는 두루마리는 열린 뒤에만 휠

의도: 키를 누른 뒤 TalkingScroll OPEN이 확인되면 휠을 돌린다. 2초 안에 열리지 않으면 휠 없이 목적지 클릭만 한다.
공유: `ActionExecutor._use_talking_scroll`, `wait_uidialog_open(TalkingScroll, 2s)`.
영향: 월드 내비·상점·후퇴의 말하는 두루마리. 열린 경우에는 기존처럼 휠 다음 클릭. HP·전투·일반 이동 불변.
동의: 사용자 (“켜졌다는것이 확인 된 후에 휠… 2초내에 켜지지 않았으면 클릭”).
결과: 직후 정정. 미오픈 시 클릭은 제거되고, 키 재시도로 바뀜.

---

## 2026-10-09 — 실행 중 게임 포커스 상실이면 일시정지

의도: 스케줄 시작(`unattended`)이 포커스 감시를 끄고 있어, 게임 창이 뒤로 가도 봇이 계속 클릭했다. 실행 중에는 포커스 상실·최소화로 자동 일시정지한다.
공유: `BotController.auto_pause_tick`. 시작 순간 콘솔이 포커스를 가져도 `unattended` 시작 자체는 RUNNING으로 들어간다. 다음 감시에서 포커스가 없으면 멈춘다. 게임이 다시 포커스되면 기존 자동 재개.
영향: 스케줄·던전 도구를 포함한 실행 중 입력. 사용자 일시정지(핫키)와 재개 조건은 그대로다. 커서가 게임 밖에 있는 것만으로는 멈추지 않는다.
동의: 사용자 (“게임창의 포커스가 없어지면 봇을 일시 정지… 지금 작동하지 않고 있다”).
결과: 구현. `test_unattended_run_pauses_on_focus_loss`.

---

## 2026-10-09 — 처치 뒤 첫 클릭은 3연타

의도: 몬스터가 처치된 뒤 나오는 첫 마우스 클릭을 같은 점에서 세 번 연속으로 보낸다. 한 번만 누르면 걷기가 시작되지 않고 2초 재클릭 대기에 들어간다.
공유: `Mouse.click`. 스티키 해제가 `no-rematch` / `dead-window` / `finish-gone` / `exp`일 때만 장전한다. 포기·블랙리스트·던전 벽은 장전하지 않는다. 재클릭 2초는 그 연타 다음에 그대로다.
영향: 사냥 중 처치 직후 첫 클릭. 룻 접근, 탐색, 이동, 다음 몬스터 공격 중 먼저 나오는 클릭이 세 번 나간다. 전투 중의 공격 클릭은 바뀌지 않는다.
동의: 사용자 (“첫 클릭을 매시브로 3번 연속 클릭. 룻만이 아니라 몬스터 처치후 다음 첫 클릭”).
결과: 구현. 처치 해제만 3을 돌려주고, 그 다음 클릭은 1임을 단위 테스트로 확인.

---

## 2026-10-09 — 클릭 지연 진단 로그

의도: 한 동작 다음 클릭이 늦는 이유만 남긴다. 전투·이동·룻 결정은 그대로다.
공유: 채널 `clickgap`. 공격 클릭/스킵, 이동·탐색·룻의 계획과 보류, 스티키 해제 이유, 스티키 중 경험치 상승. 경험치 필터는 여전히 꺼져 있고 상승은 로그만 한다.
영향: 로그 양. 사냥·이동·룻의 클릭 시각은 바뀌지 않는다.
동의: 사용자 (“필요한 세부정보들을 로그에 추가하시오”).
결과: 구현. 경험치 필터가 꺼진 상태의 기존 단위 테스트는 유지.

---

## 2026-10-09 — 경험치 처치 필터는 꺼 둠

의도: (레벨, 경험치) 증가로 스티키를 푸는 경로는 코드에 남기고, 지금은 동작하지 않게 한다.
공유: `sample_kill_progress`. `EXP_KILL_RELEASE_ENABLED = False`이면 `decide`가 호출해도 비교·해제·번호 제외를 하지 않는다. 켜면 이전과 같이 처치로 보고 즉시 해제한다.
영향: 사냥 스티키. 경험치가 올라도 잠금은 유지된다. 이동·후퇴·루팅·로그인 불변.
동의: 사용자 (“현재는 이 필터를 비활성화하시오”).
결과: 구현. 기본값에서는 경험치가 올라도 스티키가 남고, 스위치를 켠 테스트에서는 해제가 유지됨을 확인.

---

## 2026-10-09 — 경험치가 오르면 스티키를 즉시 해제

의도: 전 틱보다 (레벨, 경험치)가 커지면 잡고 있던 몬스터를 처치로 보고 스티키를 그 틱에 푼다. 레벨이 오르면 경험치 퍼센트가 내려도 처치다.
공유: `sample_kill_progress`(`decide` 시작), 해제 시 `note_monster_kill`·`clear_engage_state`·`finish_kill` 정리. `excluded_target_ids`에 그 번호를 명단에서 빠질 때까지만 넣는다. `give_up_target` 쿨다운은 쓰지 않는다. 타겟을 고르는 거리 규칙은 그대로.
영향: 사냥 중 스티키 공격. 경험치가 오른 틱에는 그 대상을 다시 클릭하지 않고, 루팅이나 다른 대상으로 넘어간다. 파티 경험치처럼 다른 이유로 경험치가 올라도 스티키가 있으면 같이 풀린다. 첫 표본·읽기 실패·스냅 출처가 바뀐 틱은 풀지 않고 기준만 갱신한다.
동의: 사용자 (“전 틱과 (레벨,경험치)를 비교해 증가했으면 몬스터가 처치된것으로 판정하고 즉시 해제”).
결과: 구현. 단위 테스트로 경험치 증가·레벨업은 해제, 감소·첫 표본은 유지, 시체 번호는 명단에서 빠지면 제외가 끝나는 것을 확인.

---

## 2026-10-09 — 엔티티 명단 벡터, AC 한 번 읽기, 버프 1버킷

의도: 라이브 엔티티 명단은 ActorSubsystem 평면 벡터(`+0x8A8`)로 읽고, 비거나 실패하면 셀맵을 쓴다. 사망·미끼는 AC `0x140` 한 블록과 슬롯 지문으로 판정한다. 버프 맵 마스크가 0(버킷 하나)이어도 수집한다.
공유: `print_state`의 `slowSweep` / `readAcFlags`, `lbuff_poll`. 좌표 폴링(PRES_B, 매 스냅샷), 슬로 주기(100ms), 죽은 엔티티를 명단에서 빼는 정책, 맵 ID, HP·전투·이동·로그인 불변.
영향: 사냥 중 엔티티 스윕 비용. 벡터가 엔티티를 주면 셀맵은 걷지 않는다. 지문이 같은 동안 이미 본 사망은 유지되어, 슬롯이 안 바뀐 채 되살아난 액터는 다음 슬롯 변경 전까지 명단에 안 들어온다. 버프가 버킷 하나뿐일 때 빈 목록으로 보이던 경우가 채워진다.
동의: 사용자 (“좋은것 3개를 모두 적용하시오”).
결과: 구현. `print_state.c`·`buff_listen.c` 컴파일됨. 실행 중인 프로세스가 `print_state.dll`과 `buff_listen.dll`을 잠가 교체는 실패했고, `print_state.new.dll`·`buff_listen_build.dll`이 만들어졌다. 다음 기동은 더 새로운 쪽을 읽는다. 이번 프로세스는 예전 DLL을 유지한다.

---

## 2026-10-09 — 말하는 두루마리는 기동 스캔 칸만

의도: 말하는 두루마리 사용 여부와 누를 칸은 이번 실행의 기동 단축바 스캔에만 따른다. 프로필에 남아 있던 칸은 쓰지 않는다. 기동 이후 새로고침은 그 판정을 바꾸지 않는다.
공유: `begin_talking_scroll_boot`, `apply_boot_talking_scroll`, `slot_is_enabled` / `slot_press`의 talking_scroll, `talking_scroll_available`, 실행기의 `_live_or_assigned_slot`. 다른 역할의 저장 칸 유지는 그대로.
영향: 농장으로의 월드 내비, 상점 이동, HP 안전지대, 후퇴, 갇힘 탈출, 초보 수련. 기동 스캔에 말하는 두루마리가 없으면 그 실행은 두루마리 없이 걷거나 경로가 없으면 쉰다. 힐·텔레포트·물약 칸은 그대로.
동의: 사용자 (“저장된 칸을 이용하는것을 없애시오. 오직 봇 기동시 스캔으로부터 얻은 슬롯 정보”).
결과: 구현. 단위 테스트로 저장 칸은 무시하고, 기동 스캔 칸은 이후 스캔이 달라도 유지됨을 확인.

---

## 2026-10-09 — 바디 투 마인드는 세계수의 가호가 있을 때만

의도: 바디 투 마인드(hp_to_mp)는 캐릭터에게 세계수의 가호(strId 993)가 걸려 있을 때만 시전한다. 이 버프가 마더 트리 회복 범위에 있다는 증거다.
공유: `maybe_hp_to_mp`. 호출부는 `apply_hp_actions`, `apply_inplace_hp_support`, `maybe_hp_to_mp_at_tree`(세계수 recharge). HP 문턱(85%/80%)·핫바·마법 쿨다운은 그대로. 후퇴 시작, 힐, 텔레포트, 전투, 로그인 불변.
영향: 사냥·후퇴 중 필드 HP 사다리와 세계수 대기. 가호가 없으면 그 틱은 스킬을 내지 않고 사다리를 통과한다. 버프 스냅이 없거나 비어 있으면 없는 것으로 본다. 세계수에 도착해도 가호가 읽히기 전에는 시전하지 않고 기존처럼 대기한다.
동의: 사용자 (“세계수의 가호 버프가 걸려 있는지를 보고 바디 투 마인드 사용 여부를 결정”).
결과: 구현. 단위 테스트로 가호가 있으면 시전하고, 실드만 있거나 버프 스냅이 없으면 시전하지 않음을 확인.

---

## 2026-10-09 — 수색 홉이 끊기면 폐기하고 재개 틱에 새 클릭

의도: 전투·루팅·버프 등으로 수색이 1틱보다 길게 끊기면 기억된 홉을 도착 대기하지 않는다. 홉을 지우고, 수색이 돌아온 그 틱에 현재 위치에서 새 클릭 지점을 골라 바로 누른다.
공유: `emit_search_hop`, `clear_search_hop`. 이동 홉(`emit_travel_hop`)은 원래 끊기면 지우고 다시 계획한다. HP·후퇴·전투 대상 선택·로그인 불변.
영향: 농장 수색. 헤이스트처럼 수색을 한 틱 건너뛰는 행동도 홉을 끝내고, 다음 수색 틱에 새 지점을 클릭한다. 끊기지 않은 홉은 도착 또는 30틱까지 클릭 없이 유지된다.
동의: 사용자 (“홉이 일단 다른 액션에 의해 정지되면 그 홉을 완전히 정지하고 다음번 탐색 재개시 새 클릭 지점을 찾아 즉시에 탐색 클릭”).
결과: 구현. 단위 테스트로 끊긴 홉은 새 좌표를 즉시 클릭하고, 연속 틱은 같은 홉을 유지함을 확인.

---

## 2026-10-08 — 공격·줍기 클릭 간격을 틱에 맡김

의도: 법사를 제외한 공격 클릭과 줍기(F4)가 이전 대상의 잔여 간격 때문에 새 대상의 첫 입력을 건너뛰지 않게 한다. 틱이 한 번 돌 때마다 공격 클릭·F4는 각각 최대 한 번이므로, 90–140ms / 150–250ms 시계를 뺀다.
공유: `KnightCombatStrategy.attack` (엘프·군주 상속), `ActionExecutor._loot`. 법사 `MageCombatStrategy.attack`의 0.50–0.55초 시전 간격은 유지.
영향: 사냥 중 공격 클릭과 줍기 F4의 속도. 같은 틱에 거리 안 아이템이 있으면 F4(사이드)와 공격 클릭이 함께 나갈 수 있던 구조는 그대로이며, 그 F4도 더 이상 150ms에 막히지 않는다. HP·후퇴·이동·로그인 불변.
동의: 사용자 (“법사는 생각하지 말고 기타의 공격 및 줍기 동작 시 간격을 없애도…”).
결과: 구현. 루프에 0.1초 sleep은 없다. 다음 클릭은 그 행동을 다시 요청한 다음 틱에서 나간다.

---

## 2026-10-07 — 게이트 링 한 바퀴마다 중심 재계산 + 월드내비 실패 시 다음 일정

의도: (1) GATE 링 탐색에서 5반경 한 바퀴(bundle)가 끝날 때마다 플레이어 xy를 다시 읽어 입구 투영 중심을 갱신. 묶음 안 샘플마다 재중심하지 않음. (2) 월드내비 plan/exec 실패 시 봇 Stop 대신 루틴 다음 행으로 스킵·재arm. 한 라운드에서 전 행 실패해도 마스크를 비우고 다음 라운드에서 재시도(영구 스킵 없음).
공유: `world_nav.gate._one_gate_attempt`, `hooks._fail_skip`, `bot_controller` `SCRATCH_WORLD_NAV_PAUSE` 무시 계속.
영향: 게이트 클릭 링·월드내비 실패 복구. 로그인·전투·HP 사다리 불변. 단일 행 루틴은 실패 후 같은 행을 바로 다시 시도.
동의: 사용자 (“링 한 바퀴… 중심 재계산” + “다음 일정으로… 당시 한번뿐… 다음 라운드 다시”).
결과: 구현.

---

## 2026-10-07 — Shopping Practice: world-nav 텔레포터 체크박스

의도: 월드내비 NPC 텔레포터 허용 목록을 코드 상수 대신 `shopping_behaviors.yaml`의 `world_nav`로 둔다. Shopping Practice Behaviors에서 텔레포터마다 체크·저장.
공유: `ShoppingBehavior.world_nav`, `npc_teleporters.list_world_nav_teleporter_base_ids` / `resolve_world_nav_teleporter_ids`, 에디터 체크박스.
영향: world-nav 플랜에 포함되는 텔레포터 집합. 체크 안 한 텔레포터는 두루마리+도보만. 후퇴·HP·로그인·전투 불변. 키 생략 시 TI/기란/글루딘은 예전과 같이 기본 ON.
동의: 사용자 (“툴에서 직접 추가하도록”).
결과: 구현.

---

## 2026-10-07 — world-nav 텔레포터 id: shop_locale(ko/zh) 대응

의도: buy/sell과 같이 봇 UI·계정 `shop_locale`/`game_language`에 따라 텔레포터 YAML id를 고른다. `zh` → `<base>_ch`, `ko` → base.
공유: `npc_teleporters.resolve_world_nav_teleporter_ids`, `WORLD_NAV_TELEPORTER_BASE_IDS`, `load_npc_teleporter_links` 기본 want.
영향: world-nav NPC 텔레포터 링크·SHOP_RUN behavior_id. 굴리딘은 YAML에 `teleport_gludin_ch`만 있으면 중국어에서만 연결. 후퇴·HP·로그인·전투 불변.
동의: 사용자 (“대면부 언어에 따라 두 언어방식이 바뀌도록 수정”).
결과: 구현.

---

## 2026-10-07 — 내비게이션 오프라인 프리빌드

의도: 세션에서 `nav.png`→포털 그래프 런타임 빌드를 하지 않는다. 맵 폴더 `nav_prebuild/`에서 walkable·라벨·Coarse·그래프를 로드.
공유: `nav_prebuild.py`, `configure_navigation` / `_load_navigation_graphs`, `Tools/nav/build_nav_prebuild.py`.
영향: 맵 전환·세션 시작 로드 시간. 경로 탐색 결과·전투·HP·로그인 불변. `nav.png` 변경 시 오프라인 재빌드 필요(불일치면 로드 실패).
동의: 사용자 (“오프라인 빌드… 프리빌드된 데이터에서 로드”).
결과: 구현.

---

## 2026-10-07 — 복구 HP 행 복구 (`_rebuild_hp_rows`)

의도: HP/핫바 탭에 물약·힐·안전지대 이동 행과 % 문턱 스핀이 다시 보이게.
원인: 핫바 지정 패치 중 `_rebuild_hp_rows` / `refresh_hp_hotbar_keys`가 빠짐.
공유: `UI/ui_qt/editors/recovery_tab.py`만. HP 엔진 문턱 로직 불변.
영향: 복구 UI. 의사결정 사다리·물약/힐 실행 규칙 불변.
동의: 사용자 (행이 안 보임 보고).
결과: 구현.

---

## 2026-10-07 — 엔티티 contrib/own + 메인 루팅 필터

의도: extra_ent의 드랍기여·소유(`contrib`/`own`)를 `print_state`에 이식.
메인 루팅 인텐트는 `FREE` 또는 `contrib>30`만 접근/픽업.
사이드 F4(`loot_sides`)는 소유 필터 없음.
공유: `print_state.c` (`ENT_GUID`/`OFF_ITEM_CONTRIB`/`LH_DELTA_MAX`),
`entity_offsets.txt`, `memory_entities`/`converter`/`WorldObject`,
`loot_ownership_allowed`, `list_lootable(ownership_filter)`,
`mode_actions` sticky drop, `loot_sides`.
영향: 사냥 메인 루팅 후보. 사이드 인텐트 F4·이름 화이트/블랙·아데나 모드 유지.
동의: 사용자 (“엔티티 읽기 교체 + free/contrib>30 메인만, F4 사이드는 필터 없음”).
결과: 구현. DLL 재빌드 필요. `Others/tests/test_ground_loot.py` ownership 테스트.

---

## 2026-10-07 — 복구 HP: L라벨 제거 · 후퇴 문구 · 핫바 지정

의도: HP 행동 UI에서 L0/L1/L3 숨김. 「후퇴」→「안전지대로 이동」.
사이드 인벤토리를 핫바 스캔으로 바꾸고, HP 물약·힐을 칸 지정 가능.
지정 없으면 기존처럼 라이브 핫바 자동 선택.
공유: `settings.hp_actions` (box/key/item 보존, `apply_recovery_to_spell_slots`);
엔진 `assigned_hotbar_slot` / `controller._live_or_assigned_slot` /
`_use_hp_potion` / `_can_heal_now`·`_can_potion_now`; Qt `recovery_tab`.
영향: 복구 HP UI·물약/힐 키 선택. 후퇴 문턱·트리/스크롤/TP 순서 불변.
동의: 사용자 (라벨·문구·핫바 지정 요청).
결과: 구현.

---

## 2026-10-07 — 던전 HP도 필드 사다리

의도: 던전에서도 HP 후퇴는 어머니 나무 → 말하는 두루마리 → 텔레포트. 힐/물약 문턱은 그대로.
공유: `apply_hp_actions`, `apply_inplace_hp_support`, `_execute_hp_retreat_layers`, `_execute_hp_action`, `escape_natural_recover_under_attack`, `_maybe_retreat_talking_scroll`, `filter_hp_availability`.
영향: 던전 사냥·후퇴 HP. 막힌 칸 넛지, 이동 unstick 끄기, 긴급 PK 텔레포트 끄기, 가방 수량만으로 물약 상점 여는 규칙은 그대로.
동의: 사용자 (“던전에서도 우리가 논의한 HP 관련 정책을 그대로 이용”).
결과: 구현. `Others/tests/test_hp_actions.py` `test_dungeon_hp_uses_field_retreat_scroll`.

---

## 2026-10-07 — 던전: idle_nudge를 사다리 맨 뒤로

의도: 넛지 필요 여부가 불확실하므로 `dungeon.idle_nudge`를 `dungeon.patrol` 뒤로.
패트롤 웨이포인트가 있으면 패트롤이 이기고 넛지는 그 틱에 안 탐.
공유: `FARMING_DUNGEON` 컬럼 순서; `_step_dungeon_patrol` (웨이포인트 없으면
`None`으로 폴스루, 패트롤 경로의 내부 `try_idle_nudge` 폴백 제거).
영향: 던전 farming만. 섬 농장·traveling·HP·로그인 불변.
부작용 후보: 패트롤이 있어도 travel이 emit 없이 실패하면 예전처럼 즉시 넛지하지
않고 다음 틱/다른 스텝에 맡김. 웨이포인트 없을 때만 컬럼 끝 넛지 가능.
동의: 사용자 (“사다리의 제일 마지막으로 옮기시오”).
결과: 구현.

---

## 2026-10-06 — 다른 플레이어가 나를 치면 텔레포트 탈출

의도: `attacks_me`에 `class=Player`가 있으면 즉시 텔레포트 스킬로 탈출. 보이는 플레이어 옵션(`TELEPORT_ON_PLAYER`)과 무관. 핫바 텔레포트가 준비된 경우만.
공유: `player_attacking_me`, `_maybe_emergency_teleport`, `_emit_escape_teleport`. 쿨다운은 기존 `EMERGENCY_TP_COOLDOWN_S`(8s) 공유. `begin_retreat` / `try_unstick_escape` / HP 후퇴 두루마리 불변.
영향: 사냥·이동·후퇴·월드내비 survival 틱. 로그인 불변. 몹 attacks_me 강제 교전은 그대로.
동의: 사용자 (“다른 플레이어가 나를 공격하는것이 감지되는 경우 텔레포터를 타고 탈출”).
결과: 구현.

---

## 2026-10-06 — HP 행동 3행: 물약 L3 / 힐 L1 / 후퇴 L0

의도: 복구 HP/인벤토리 탭은 세 문턱만. 저장 순서로 두루마리·나무를 고르지 않는다. HP≤L0 후퇴는 어머니 나무 → 말하는 두루마리 → 텔레포트.
공유: `normalize_hp_actions`, `apply_hp_actions`, `apply_inplace_hp_support`, `arm_potion_side_intents`, Qt `recovery_tab`.
영향: 사냥/후퇴 HP. 로그인·이동 unstick·상점 두루마리 그대로.
동의: 사용자 (3행 + 순서 로직 제거).
결과: 구현.

---

## 2026-10-06 — dxcam import: SetProcessDpiAwareness HRESULT 예외

의도: `win32_prototypes`가 `SetProcessDpiAwareness` restype를 `HRESULT`로 두면 실패 코드(E_ACCESSDENIED)가 PermissionError가 되어 dxcam import에서 워커가 죽는다. restype는 `c_long`, dxcam import는 `OSError`도 잡아 mss로 넘어간다.
공유: `win32_prototypes.bind_shcore`, `screen_capture.py` dxcam import.
영향: 화면 캡처 초기화만. 이동·전투·HP 불변.
동의: 사용자 (워커 크래시 로그).
결과: 구현.

---

## 2026-10-06 — HP 정책: keep mode, 후퇴는 95%까지, 두루마리 휠0 랜덤(마법서 제외)

의도: HP 층은 행동만. `HP<30%`일 때만 Retreating. 후퇴는 안전지대 대피 후 `HP≥95%`에만 이전 모드로. 힐/물약은 keep mode. 급감 분기 없음. 바디 투 마인드는 `HP≥85%`이고 `MP<80%`일 때만. 텔레포트는 1회 후 안전지대로. HP 두루마리는 휠 0 스폿 중 에피소드당 1회 추첨, 마법서 상인 제외.
공유: `apply_hp_actions`, `apply_inplace_hp_support`, `begin_retreat`, `finish_retreat`, `retreat_exit_ready`, `maybe_hp_to_mp`, `_tick_mother_tree_retreat`, `pick_hp_safe_scroll_spot`.
영향: 사냥·이동·후퇴·던전 HP, HP 안전 착지, 세계수 후 마법서 자동 두루마리 삭제. `try_unstick_escape`·로그인·가드 전투는 그대로. Fix/Return 두루마리 회전(마법서 포함)은 그대로.
동의: 사용자 (HP 방안 동의 + 대륙 이동 허용 + 마법서 상인 추첨 제외 + 구현 요청).
결과: 구현.

---

## 2026-10-06 — Win32 ctypes: 64-bit HANDLE overflow 크래시

의도: `CopyIcon(hcursor)` 등 타입 없는 windll 호출이 64비트 핸들을 `c_int`로 넣어 `OverflowError`로 워커가 죽지 않게 한다.
공유: `Engine/win32_prototypes.py`, `cursor_capture.py`, `window_bounds.py`, session/login/autologin Win32 바인딩. 캡처 실패는 `None` (마비 게이트는 False).
영향: 커서 검증·창 핸들·ShellExecute/프로세스 핸들 호출. 이동/전투/HP 분기 불변.
동의: 사용자 (유사 overflow 전반 수정).
결과: 구현. `Others/tests/test_win32_prototypes.py`.

---

## 2026-10-06 — 말하는 두루마리 착지 후 2초 뒤에 다음 클릭

의도: 월드 내비에서 두루마리 착지 직후 땅을 찍지 않고 2초 선다. 텔레포터 NPC가 클릭 거리면 걷기 hop을 건너뛰고 그 다음 NPC 클릭으로 간다.
공유: `WorldNavSession._tick_scroll_wait` / `_tick_scroll_settle`, `SCROLL_LAND_SETTLE_S=2`, `_start_walk` skip 반경(다음 스텝이 `npc_teleporter`이면 `NPC_TP_APPROACH`).
영향: 월드 내비 두루마리 경로(상점 스크롤 착지 포함). 후퇴 두루마리는 world_nav 세션이 아니면 불변. 로그인·전투·HP 불변.
동의: 사용자 (“착지한 다음 2초후에 클릭”).
결과: 구현.

---

## 2026-10-06 — NPC open: click_offset_uv 있으면 단일 클릭, 없으면 커서 탐색

의도: 캘리브레이터로 잰 UV 오차(A→B)를 `shopping_behaviors.yaml`에 보관하고, 텔레포터/상점 등 NPC 오픈 시 오차가 있으면 `A+offset` 한 번만 클릭, 없으면 기존 커서 탐색.
공유: `ShoppingBehavior.click_offset_uv`, `update_click_offset_uv`, `open_shop_npc` 분기, `Tools/bot_data_editors/npc_click_offset_calibrator.py`.
영향: buy/sell/store/teleporter 오픈 경로. 후퇴·로그인·전투·HP 불변. 오차 미설정 behavior는 기존 search 유지.
동의: 사용자 (“오차필드 추가… 오차 있으면 단일 클릭, 없으면 커서 탐색… 툴이 곧장 데이터 반영… bot_data_editors 폴더”).
결과: 구현. `Tool_Npc_Click_Offset.bat` → `Tools/bot_data_editors/`.

---

## 2026-10-06 — uidialog: 컨테이너 discover(2s) + 매 틱 poll

의도: `D:\extra_ui` 정본으로 교체. BFS/틀린 Screenshot 앵커 제거. Discover=컨테이너 walk 2s, Poll=매 틱 헤더.
공유: `uidialog_listen.c`(`containerScan`/`anchorUI`), registry `VFT_UISUBSYSTEM=0x1182C50`/`UIDLG_CONT*`/`UIDLG_SCAN_MS=2000`, `capture_tick`→`snapshot_fresh`.
영향: uidialog JSON·상점/창고/두루마리 OPEN 게이트·Esc dismiss. buff/이동/전투 불변.
동의: 사용자 (“discover는 2s… 매틱마다 poll… 새 uidialog읽기 도입”).
결과: 구현. DLL 재빌드 필요.

---

## 2026-10-06 — haste: 지정은 인벤이 아니라 핫바 칸

의도: 사냥 탭에서 강화 물약을 고를 때 가방이 아니라 24칸 핫바에서 box/key를 고른다. 지정된 칸을 그대로 누른다. 체크만이면 기존처럼 CSV haste.
공유: `hunt.haste_potion_box`/`haste_potion_key`, `apply_haste_potion_to_spell_slots(box, key)`, Qt/ttk 사냥 탭 테이블.
영향: haste 지정 UI·바인딩. HP 인벤 지정·이동·로그인 불변.
동의: 사용자 (“인벤토리로부터 지정이 아니라 핫바로부터”).
결과: 구현.

---

## 2026-10-06 — haste: 인벤 지정 슬롯 우선, 미지정이면 CSV

의도: 사냥 탭에서 강화 물약 칸을 지정하면 그 box/key를 누르고, 사용 체크만 있으면 `hotbar_role_map.csv` haste 역할을 쓴다. CSV에 없는 이름도 지정만 되면 시전.
공유: `settings.haste_potion.resolve_haste_press_slot`, `assigned_buff_on_live_hotbar`, `ActionExecutor._live_or_assigned_slot` (haste만).
영향: `spell.buffs` haste 키. armor/power·HP·이동·로그인 불변.
동의: 사용자 (“슬롯 수동 지정… 체크만이면 CSV 매칭”).
결과: 구현. `Others/tests/test_haste_slot_policy.py`.

---

## 2026-10-05 — uidialog: 타 PC에서 전부 false 고착 수정

의도: 공유폴더 배포 시 `uidialogmon_cache.txt`/RESCAN=0 때문에 창이 영원히 closed로 보이던 문제.
공유: `uidialog_listen.c` DLL은 디스크 캐시 미사용, `UIDLG_RESCAN_MS` 최소 3s, JSON에 `src/ui/layouts`.
영향: uidialog 인식만. buff/전투/이동 불변.
동의: 사용자(다른 컴퓨터에서 모두 false).
결과: DLL 재빌드. 배포 시 `uidialog_listen.dll`+registry 갱신 필요.

---

## 2026-10-05 — perception: buff 읽기를 `E:\\Lineage\\extra` lbuff로 교체

의도: 구 HudSlot BFS/캐시 대신 extra 정본(BuffSubsystem unordered_map walk) 사용.
공유: `core/lbuff.h` 이식, `buff_listen.c` 재작성, registry `BUFF_MAP_*`/`BUFF_NODE_*`, DLL 재빌드.
영향: 버프 인식만. JSON API·`due_buff` 계약 유지. uidialog/HP/이동 불변.
동의: 사용자 (“extra … 알아서 처리”).
결과: 구현. `buff_listen.dll` 재빌드(21:01).

---

## 2026-10-05 — perception: buff/uidialog 틱을 툴과 동일 동기 fresh

의도: 스레드 캐시가 믿을 수 없어 봇도 Memory Watch처럼 매 틱 동기 DLL 읽기.
공유: `snapshot()`=`snapshot_fresh`, 폴러 기본 OFF, `capture_tick`에서 buff/uidialog 두 스레드로 동시 fresh 후 join.
영향: 인식만(틱당 드라이버 비용↑). 시전/이동/HP/로그인 규칙 불변.
동의: 사용자 (“캐시는 믿을수 없어보인다. 툴처럼 동기화”).
결과: 구현.

---

## 2026-10-05 — buff: false-empty 스냅샷이 armor 3초 스팸 유발

의도: 툴은 실드가 보이는데 봇은 armor_up을 cast-guard(3s)마다 재시전하던 문제 수정.
공유: `apply_buff_snapshot`(cache>0 & buffs=[] 거부), `_memory_buffs_ready`(동일 → 타이머 폴백), `buff_listen.c` 재스캔 시 ntrack 리셋, tick false-empty 시 fresh 1회.
영향: 버프 시전 케이던스만. HP/이동/로그인 불변.
부작용 후보: 레코드만 남고 활성 버프 0인 짧은 구간은 타이머 폴백(20분).
동의: 사용자(봇 실드 스팸 보고).
결과: 구현. DLL 재빌드.

---

## 2026-10-05 — unstick: 클릭 타일·좌표 랜덤화

의도: 막힘 복구가 나침반 고정 순·격자 중심만 누르던 것을, 미시도 walkable 중 랜덤 타일 + 타일 내 ±0.35 지터로 클릭.
공유: `next_sweep_tile`, `unstick_click_dest`, enter-farm detour / combat sidestep·wall ring.
영향: 이동/전투 막힘 복구 클릭만. TP·두루마리 탈출 조건·반경·버스트 불변.
동의: 사용자 (“랜덤으로 누르도록”).
결과: 구현. `Others/tests/test_unstick.py`.

---

## 2026-10-05 — shop: 화살 재고 = 일반+은화살 합산 ≤ 귀환 개수

의도: 일반 화살만 300 이하일 때 사던 것을, 일반+은화살 합이 `return_arrow_count`(기본 300) 이하일 때만 구매하도록 변경.
공유: `refresh_shop_needs_from_inventory` (`needs_arrows`).
영향: 상점 arm 타이밍만. 구매 종류(일반/은)·수량·HP/로그인/전투 불변.
동의: 사용자 (“일반화살과 은화살을 모두 합쳐도 300개 이하이면”).
결과: 구현. `Others/tests/test_shop_trip.py` 합산 케이스.

---

## 2026-10-05 — perception: stand buff/uidialog 알고리즘 + 전용 스레드

의도: 소모시간 손해를 감수하고 stand(`buff_930`/`uidialogmon`)와 동일하게 실시간 buff·uidialog를 정확히 읽는다. 두 읽기는 각각 별도 스레드.
공유: `buff_listen.c`(rootSig+period), `uidialog_listen.c`(RESCAN/dead rediscover), `BuffListenReader`/`UiDialogListenReader` 데몬 폴러, registry `UIDLG_RESCAN_MS=5000`.
영향: 인식(버프 목록·창 OPEN). 시전/이동/전투/HP/로그인 규칙 불변. `capture_tick`은 최신 스냅샷 복사만.
부작용 후보: 드라이버 호출 증가(BFS/재스캔); 틱 지연은 스레드 분리로 완화.
동의: 사용자 (“stand 알고리즘 그대로… 두가지 읽기를 모두 별도의 스레드”).
결과: 소스·Python 구현 완료. VS2022 Build Tools 설치 후 `buff_listen.dll`/`uidialog_listen.dll` 재빌드 성공(2026-10-05 20:22).

---

## 2026-10-05 — UserData: 타임라인→일정→(계정,설정,루틴) + 트라이얼

의도: 봇 운영 정본을 계층화. 타임라인은 트리거만, 일정은 계정·설정·루틴을 보관. 타임라인/계정 없이 현재 설정으로 돌리는 Trial 모드 추가. profile.json↔schedules.json 이중 저장 제거.
공유: `ops_migrate`, `timeline`, `trial_store`, `settings_sections`, `ScheduleStore`(디렉터리), `load_profile`/`save_profile`→trial, Qt `Trial` 버튼.
영향: `UserData/timeline.json`, `schedules/{id}/`, `trial/`, `app.json`. 구 `profile.json`/`schedules.json`은 1회 마이그레이션 후 `.bak`. 계정 파일·전투/HP 규칙 불변.
부작용 후보: 첫 기동 시 마이그레이션; named `profiles/*`는 `_preset_*`로만 이관(목록 비표시).
동의: 사용자 (계층 토의 후 “구현 하시오” + trial).
결과: 구현. `Others/tests/test_ops_userdata_layout.py`.

---

## 2026-10-05 — buff: haste 표시명 `가속 효과` 매칭

의도: 라이브 버프 표시 문자열에 `가속 효과`가 있으면 haste로 인식.
공유: `spells._BUFF_MATCH[haste].needles`만.
영향: haste 있음/없음 판정. armor/power·HP·이동 불변.
동의: 사용자 (“가속 효과… 이용… 오케이”).
결과: 구현. needle 앞에 `가속 효과` 추가.

---

## 2026-10-05 — hunt: 강화 물약(가속) 토글 + 인벤 임포트

의도: 사냥/공격 전투 보조에 `use_haste_potion` 체크 + 인벤토리에서 물약 지정(복구/HP와 동일). 체크 시에만 haste 버프 물약 사용.
공유: `spells.due_buff`/`USE_HASTE_POTION`/`HASTE_POTION_ITEM`, `settings.haste_potion.apply_haste_potion_to_spell_slots`, hunt 설정·핫바 스캔 동기화.
영향: haste 시전 게이트. armor/power·HP·이동·로그인 불변. 기본 OFF(옵트인).
동의: 사용자 (“강화 물약 사용 토글… 인벤토리로부터 임포트… 체크했을 때만 버프물약”).
결과: 구현. Qt/ttk 전투 보조 UI + `Others/tests/test_buff_cadence.py`.

---

## 2026-10-05 — talking scroll: uidialog OPEN 게이트 임시 우회

의도: uidialog가 TalkingScroll OPEN을 못 잡아 휠/클릭이 스킵되던 문제 회피. 키 후 **0.1초** 고정 대기 뒤 휠/클릭. uidialog가 안정되면 `wait_uidialog_open` 복구.
공유: `ActionExecutor._use_talking_scroll`.
영향: 말하는 두루마리 사용(world_nav/상점/후퇴 스크롤). HP·전투·이동 본문 불변.
동의: 사용자 (“0.1초후에 마우스 휠과 클릭… 나중에 uidialog 깨끗해지면 본래로”).
결과: 구현. 로그 `open-fallback sleep` / `uidialog OPEN gate bypassed`.

---

## 2026-10-05 — routine: TRAVELING duration 즉시 전환 + break 카운트다운

의도: (1) 여행(TRAVELING/패트롤) 중 행 분이 끝나면 즉시 다음 행으로 arm. (2) SHOPPING은 duration으로 중단하지 않음(상점 종료 후 기존 farming/world_nav 틱이 만료 시 advance). (3) 판매는 다음 행 전환 후에도 shop.trip으로 가능 → break 전 가방 정리. (4) break UI는 카운트다운 표시(`kind=break`면 Moving 억제), 도착 시 stale `need_world_nav` 제거.
공유: `take_next_routine_if_due`, `routine.duration` TRAVELING step, `_on_world_nav_arrived`, `_routine_clock_from_board` / schedule timer paint.
영향: 던전 패트롤·여행 중 스케줄 전환 타이밍, break 타이머 UI. 상점 트립 본문·HP/전투 규칙 불변.
동의: 사용자 (“합의 된 정책을 구현… 쇼핑 중단 말 것… 여행 중 만료면 바로 다음 행… 가방 정리 후 휴식… break 거꿀계수”).
결과: 구현. `Others/tests/test_routine_duration_travel.py`.

---

## 2026-10-05 — buff: haste(초록 물약) 역할 추가

의도: 가속 버프가 없으면 armor/power와 같이 핫바 키를 한 번 눌러 살림. 새 후퇴/전투 로직 없음 — `BUFF_ORDER` 대상만 확장.
공유: `spells.due_buff` / `maybe_cast_buff`, `_BUFF_MATCH`, 슬롯 `haste`, `controller._buff`, `hotbar_role_map.csv`(초록/강화초록/엘븐와퍼/용기/헤이스트→haste).
영향: `spell.buffs` 틱. haste는 아이템이라 MP 예약·매직 쿨 비적용. 기본 키 box1 F12·enabled. HP/이동/로그인 불변.
부작용 후보: 핫바에 초록 물약이 없으면 역할이 안 잡혀 스킵. 기존에 초록을 power_up으로 쓰던 매핑은 haste로 이전.
동의: 사용자 (“haste계열 물약… 버프 대상을 하나 늘리기만”).
결과: 구현. `Others/tests/test_buff_cadence.py` 갱신.

---

## 2026-10-05 — 리스폰 후 RETREATING (마더트리 회복 후 귀환)

의도: 리스폰 직후 HP가 낮은데 farming으로 바로 들어가지 않고 RETREATING으로 회복. 전투지에서 이미 이탈한 상태이므로 마더트리 스킬이 있으면 세계수로 가서 회복한 뒤 돌아온다.
공유: `arm_post_respawn_retreat`, `update_death_timer`, `finish_retreat`, `begin_retreat` / `_tick_mother_tree_retreat`, `SCRATCH_POST_RESPAWN_RETREAT`, `begin_world_nav("post_respawn")`.
영향: 사망 확인 후 부활 틱. FARMING의 `farm.post_respawn_spellbook` 암은 더 이상 세우지 않음(레거시 폴백만 유지). 마더트리 불가 시 마법서 상인 스크롤(또는 세이프 회복) 후 world_nav. 로그인·전투 선택 규칙 불변.
부작용 후보: 부활 직후 핫바 미로드면 마더트리 unread→allow로 시도할 수 있음(기존 `elf_uses_mother_tree`와 동일). 회복 전에 farming/engage로 안 감.
동의: 사용자 (“리스폰후에는 … retreating … 마더트리 … 회복을 하고 돌아오도록”).
결과: 구현.

---

## 2026-10-05 — inventory: 60초 주기 재스캔 → needs_* 갱신

의도: 가방을 60초마다 백그라운드 재스캔해 `needs_potion` / `needs_arrows` / `needs_depoison`이 주기적으로 갱신되고 쇼핑이 제때 arm 되도록 함.
공유: `LiveInventorySweep.poll` (interval 스케줄 + daemon 스레드), 기존 `apply_inventory_snapshot` / `refresh_shop_needs_from_inventory` (스냅샷 객체 변경 시).
영향: 지각 인벤 경로·상점 arm 타이밍. HP/전투/이동/로그인 규칙·Fix/Return 문턱 수치 불변. 틱은 스냅샷 반환만(DLL 스캔 비동기).
동의: 사용자 (“진행… 별도 스레드… 틱소모시간에 영향 없음”).
결과: 구현. 기본 `interval_s=60`. `Others/tests/test_inventory_listen.py`.

---

## 2026-10-05 — loot: 아이템 최초 관측·드롭 몹 위치 로그

의도: 그라운드 아이템이 메모리에 처음 잡힐 때 abs/rel/uv와, sticky 전투 셀(체비셰프≤3, 20초)로 추정한 드롭 몹 id·species·위치를 로그. `begin_loot_item`에 first_age_ms·drop_mob 요약 부착.
공유: `item_sight.note_item_first_seen` / `note_monster_cell` / `note_monster_kill`, `track._apply_one`, `stamp_sticky_target`, death clear, `begin_loot_item`.
영향: 로그만. 루팅/전투/이동 선택 규칙 불변. 드롭 매칭은 최근접 combat 셀 추정(확정 서버 드롭 테이블 아님).
동의: 사용자 (“아이템당 최초 관측 시각 및 위치… 타겟 몬스터 위치… 어느 몬스터에서 떨어졌는지”).
결과: 구현. `Others/tests/test_item_sight.py`.

---

## 2026-10-05 — world-nav walk: sticky/loot 시 hop 억제 + screen_combat 스킵 로그

의도: 월드내비 walk 중 sticky·loot·screen combat이 있으면 nav hop을 그 틱에 진행하지 않음(교전이 웨이포인트에 먹히지 않게). `farm branch=none`일 때 screen_only/path 등으로 걸러진 근접 후보를 1초 스로틀로 로그.
공유: `_drive_world_nav`, `farm_loot_or_combat`, `describe_attackable_filter_skips`.
영향: WORLD_NAV walk 오버레이 전투/루팅 우선. scroll/gate/teleporter 페이즈 불변. 사냥 본문·HP·로그인 불변.
동의: 사용자 (“1,2를 구현” — sticky 시 hop 억제 + 스킵 후보 로그).
결과: 구현. `Others/tests/test_attackable_filter_skips.py`.

---

## 2026-10-05 — world-nav: same-map 인터맵 금지 + 입구 50타일 TP 억제

의도: 이미 목적 맵이면 scroll(타맵)/transition/NPC 텔레포터를 쓰지 않고 걷기만. 목적 던전 `ground_enter`로부터 체비셰프 ≤50이면 텔레포터 대신 걸어서 입구 접근.
공유: `WorldNavPlanner.plan`, `near_goal_ground_enter`, `NEAR_ENTRANCE_NO_TELEPORTER_TILES`.
영향: 월드내비 플랜만. 세션 실행·로컬 travel·전투·HP·로그인 불변. 같은 맵 허브로의 talking scroll은 허용.
동의: 사용자 (“same-map이면 인터맵 금지… 입구 근처(체비쉐브 50)이면 텔레포터 사용하지 말고”).
결과: 구현. `Others/tests/test_world_nav_plan_guards.py`.

---

## 2026-10-05 — attacks_me라도 dead/bait면 공격 금지

의도: `force_attacks_me` / `finish_kill` 합성이라도 DEAD·bait면 sticky/신규 공격 중단. attacks_me 목록에서 빠지면 DEAD 처리(시체 연타 방지).
공유: `memory_target_gone`, `sync_attacks_me_force_targets`, `_attack_candidates`, `nearest_attacks_me_force`, `sticky_target_alive`, `rebind_sticky_target`.
영향: 자위(attacks_me) 교전·finish_kill sticky. 일반 사냥 bait 제외는 유지. 이동·HP·로그인 불변.
동의: 사용자 (“attack_me몬스터라도 dead이거나 bait이면 공격하지 않게”).
결과: 구현. 테스트 `test_attacks_me_finish_kill.py` 갱신.

---

## 2026-10-05 — bait 몬스터 공격 제외

의도: ActionComponent bait/dormant(AC+0x40==0x78) 몹은 신규 공격 대상에서 제외.
공유: `print_state` JSON `bait`, `WorldObject.bait`, `_attack_candidates` / `list_attackable`.
영향: 사냥 교전 선택. `force_attacks_me`(나를 친 합성)는 예외로 유지. 루팅·HP·이동 불변.
동의: 사용자 (“공격에서 미끼(bait)몬스터는 제외하도록 게이트를 설정”).
결과: 구현. `entity_offsets` ACT_BAIT_*; print_state.dll 재빌드 필요.

---

## 2026-10-05 — uidialog: 매 틱 + 비의도 Esc + OPEN 게이트 3초

의도: 매 틱 uidialog 읽고, 비의도 OPEN(인벤 포함)이면 Esc; 상점/창고/텔레포터/말하는 두루마리는 창 OPEN 후에만 다음 입력. 게이트 타임아웃 3초.
공유: `capture_tick`/`last_uidialog`, `uidialog_gate.wait_uidialog_open`, `_maybe_dismiss_ui`, `open_shop_npc`/`_use_talking_scroll`, `action.yaml dismiss_ui_enabled=true`.
영향: 사냥(오클릭 UI 닫기), SHOPPING/창고/텔레포터, 말하는 두루마리. 전투·HP·이동 본문 규칙 불변. DLL 없으면 게이트 실패·Esc 스킵.
동의: 사용자 (매 틱·Esc·게이트; 사냥 인벤 비의도; 타임아웃 3초 적용).
결과: 구현. 명세 `analysis/lc930/docs/uidialog.md`.

---

## 2026-10-05 — buff: due_buff 메모리 remain 우선

의도: 주기(20분) 재시전을 라이브 버프 목록으로 교체. 없거나 remain≤10초면 시전.
공유: `due_buff`, `_BUFF_MATCH`, `slot_ready`(버프는 3초 가드만), `apply_buff_snapshot`/`last_buff`.
영향: `spell.buffs` / `maybe_cast_buff` (사냥 등). 이동·HP·텔레포트 불변. DLL 없으면 타이머 폴백.
동의: 사용자 (“OK” — remain 우선 + 타이머 폴백 범위).
결과: 구현. 명세 `analysis/lc930/docs/buff.md` §4.

---

## 2026-10-05 — Practice: NPC 커서 스캔 복구

의도: Practice가 humanize=False라 `dialog_click_ring`이 `_fixed_wait`를 건너뛰며 스캔 없이 즉시 실패. 점간 `time.sleep`을 강제하고, `open_shop_npc`는 타일 커서 헌트(`dialog_click_destinations`) 후 픽셀 링.
공유: `cursor_verify.dialog_click_ring`, `shop.runtime.open_shop_npc`, Practice sell도 `open_shop_npc`.
영향: Practice·라이브 SHOP_RUN NPC 오픈. 전투/이동/HP 불변.
동의: 사용자 (“커서 스캔이 없이 NPC를 찾지 못했다고… 커서 스캔은 있어야”).
결과: 구현.

---

## 2026-10-05 — teleporter destination_dungeon + Fill NPC from memory 수정

의도: 같은 텔레포터 NPC가 여러 던전으로 갈 수 있으므로 behavior에 목적 던전(LC mapId)을 두고, 월드내비는 그 맵으로 가는 ground_enter만 링크한 뒤 착지 후 최근접 입구로 게이트 탐색. Fill NPC from memory는 전용 모니터를 fresh+close 하다가 네이티브 크래시 나던 경로를 shared_sensors(fresh=False)로 교체.
공유: `ShoppingBehavior.destination_dungeon`, Behaviors 편집기 Dest dungeon, `npc_teleporters` 필터/`nearest_ground_enter_for_destination`, session settle 시 다음 map_transition rewrite, `Tools/shopping/memory_fill.py`.
영향: 텔레포터 플랜·실행, 에디터 저장 스키마. 요금·스크롤·일반 상점 불변. Giran→53은 behavior를 하나 더 두거나 dest를 53으로 바꿔야 함(기본 YAML은 dest=30).
동의: 사용자 (“목적 던전 필드를 추가하고… 게이트 탐색… Fill npc from memory… 수정”).
결과: 구현.

---

## 2026-10-05 — world-nav: 텔레포터 3개 → 던전 ground_enter

의도: `teleport_talking_island` / `teleport_giran` / `teleport_gludin`을 월드내비 경로에 넣어 던전 입구로 가는 지름길로 쓴다. 착지 xy는 플랜 시점에 없고, SHOP_RUN 클릭 종료 후 1초 뒤 라이브 pose로 읽는다. 착지 맵 = NPC 맵.
공유: `world_nav/npc_teleporters.py` 링크, planner `npc_teleporter` op, session SHOP_RUN+settle, `adena` 부족 시 엣지 제외, manager가 world-nav teleporter에 `mark_post_shop_return` 생략.
영향: 월드내비 플랜/실행, shop_ok 피드백 분기. 로그인·전투·HP·일반 상점 구매 불변. 게이트 approach는 착지 후 라이브 pose에서 입구로 걸어감.
동의: 사용자 (“착지 좌표는 텔레포터 사용후에… 1초후에 읽기… 맵은 NPC… 현재 있는 3개를 연결”).
결과: 구현.

---

## 2026-10-05 — shopping_behaviors.yaml → Engine/data/maps

의도: NPC 카탈로그는 엔진 데이터이지 UserData 운영 설정이 아니다.
공유: `shop.behaviors.BEHAVIORS_PATH` = `Engine/data/maps/shopping_behaviors.yaml`, 에디터/Practice 문구, seed_userdata에서 제거. 레거시 UserData 파일은 로드 시 1회 이관.
영향: 경로만. 스키마·Decide 로직 불변.
동의: 사용자 (“UserData에 있을것이 아니다. engine의 데이터에… 이동하고 연관부분 수정”).
결과: 구현.

---

## 2026-10-05 — NPC scroll_wheels 제거, 말하는 두루마리 hub 전체 스폿

의도: 휠은 두루마리 사용규칙(hubs)에 이미 있으므로 behavior에서 제거. 에디터 Scroll spot은 hub 73개 전부 선택.
공유: `talking_scroll.scroll_spot_plans`/`list_talking_scroll_spot_choices`, `emit_talking_scroll`이 spot의 `scroll_times` 전달, Behaviors 콤보.
영향: 상점·후퇴 등 `emit_talking_scroll` 경로가 hub wheels를 Intent에 싣는다. 기존 first-screen ROWS 클릭 UV는 유지. `adena_cost`는 유지.
동의: 사용자 (“NPC_behavior에는 휠이 필요 없고… 스폿 리스트를 편집툴에… 모든 스폿”).
결과: 구현.

---

## 2026-10-05 — NPC behavior: scroll_wheels + teleporter adena_cost (편집 툴)

의도: 던전 입구용 텔레포터 요금·말하는 두루마리 휠 회수를 YAML/에디터에 담는다. 월드내비·상점 emit 연동은 다음 단계.
공유: `shop.behaviors` `scroll_wheels`/`adena_cost`, Behaviors 탭 입력, `shopping_catalog` 설명.
영향: userdata 스키마·편집 툴만. Decide/이동/전투/HP 불변 (라이브 shop scroll은 아직 wheels=0).
동의: 사용자 (“먼저 behavior 편집 툴을 이에 맞게 완성… 휠 회수도… 자료구조와 편집 툴”).
결과: 이후 항목에서 `scroll_wheels` 철회·hub 스폿으로 대체.

---

## 2026-10-05 — NPC 카탈로그 buy|sell|store|teleporter, give_goods→store

의도: shopping behavior action을 4분류로 고정하고 창고 `give_goods`를 `store`로 분리한다. 실행 경로는 당분간 sell과 동일.
공유: `shop.behaviors` ACTIONS/`ACTION_STORE`, `shops.is_store_behavior`, runtime/practice `kind in (sell,store)`, editor 콤보, `UserData/shopping_behaviors.yaml`.
영향: 상점 분류·에디터·YAML만. 이동/전투/HP/로그인 로직 불변. 파일명 `npc_behaviors` 리네임은 보류.
동의: 사용자 (“먼저 4분류로 가르고 give_goods는 store로”).
결과: 구현. 레거시 `give_goods`+`action:sell` 로드/저장 시 `store`로 승격.

---

## 2026-10-05 — 일반 필드 arrive_tiles 1

의도: 필드 목표 도착 판정을 Chebyshev 1타일로 조인다 (기존 2).
공유: `farm_area.ARRIVE_TILES`, `decision.yaml` `farm.arrive_tiles`, `world_nav.session.ARRIVE_TILES`.
영향: 필드 travel/patrol/농장 입장·world_nav walk/게이트 접근 스냅. 던전(`DUNGEON_ARRIVE_TILES=1` 유지)·상점(`SHOP_ARRIVE_TILES=7`) 불변.
동의: 사용자 (“일반 필드에서 arrive_tiles를 1타일로”).
결과: 구현.

---

## 2026-10-05 — 벽 근접 path cost 패널티 시험 비활성

의도: 장애물 주변 soft cost 때문에 기하적으로 더 짧은 길을 버리는 현상을 없앤다. 나쁘면 플래그만 되돌린다.
공유: `terrain_map.WALL_CLEARANCE_PENALTY_ENABLED=False` → `_build_clearance_and_costs`의 step cost가 walkable에서 항상 1.
영향: A*/계층 경로의 벽 우회 선호도. clearance 배열·스냅·walkable 판정 불변. 이동/unstick/게이트 로직 불변.
동의: 사용자 (“패널티를 없애시오… 효과 나쁘면 되돌리겠음”).
결과: 구현. 복구: `WALL_CLEARANCE_PENALTY_ENABLED = True`.

---

## 2026-10-05 — 게이트 탐색 묶음마다 링 중심 갱신

의도: 5개 반경 링을 한 묶음으로 보고, 묶음 시작마다 플레이어 좌표를 다시 읽어 입구 투영 중심을 갱신한다. 묶음 안 샘플마다 재중심하지는 않음.
공유: `world_nav.gate._one_gate_attempt` (fresh pose timeout → cache → intent pose).
영향: GATE 클릭 링만. approach walk·착지 판정·재시도 횟수 불변.
동의: 사용자 (“매 탐색 전에 중심점 좌표를 갱신… 한 묶음을 시작할 때마다”).
결과: 구현. 로그에 `player=(x,y) pose=fresh|cache|intent`.

---

## 2026-10-05 — finish_kill은 타겟 우선권만, give-up sticky 해제 허용

의도: `attacks_me` finish_kill이 커서 give-up을 막아 슬라임에 영원히 sticky 되던 증상을 없앤다. finish_kill은 자기방어 타겟 우선권만 준다.
공유: `give_up_target` (finish_kill skip 제거, `finish_kill_ids` discard), `advance_engage_or_give_up` (finish_kill 시계 면제 제거), `nearest_attacks_me_force`가 give-up ``exclude`` 존중(재sticky 방지). engage 우선·근거리 rematch는 유지.
영향: 전투 sticky / give-up / abandon / max-engage / attacks_me 재선택. 이동·HP·로그인 불변.
동의: 사용자 (“finish_kill은 … 타겟 우선권만을 부여하고 give-up시 스티키 해제는 다치지 않도록”).
결과: 구현.

---

## 2026-10-05 — spell 원 커서·스킬 키 누름 로그

의도: buff 후 `spell` 커서가 남아 travel이 막히는 증상을 로그로 바로 보이게 한다.
공유: `ActionExecutor._press_assigned_skill` → `skill press name=…`; `DecisionManager._log_travel_cursor_outcome` → `spell circle cursor seen … blocks travel` (1초 throttle).
영향: 로그 채널만. 클릭/버프/이동 로직 불변.
동의: 사용자 (“원이 알아보고 스킬 건 누를 때 로그에 남기도록”).
결과: 구현.

---

## 2026-10-05 — 던전 hop 3타일, 던전 arrive 1타일 (필드 불변)

의도: 던전 패트롤 hop arrive→재클릭 루프 완화. 필드 파라미터는 그대로 둔다.
공유: `DUNGEON_MAX_HOP_TILES=3`, `DUNGEON_ARRIVE_TILES=1`, `travel_arrive_tiles()` → travel/patrol만. `farm_area.ARRIVE_TILES` / `decision.yaml` `farm.arrive_tiles`는 **2 유지** (farm enter·search_hop·필드 travel).
영향: 던전 travel/patrol 도착·hop 상한만. 필드 hop 5·arrive 2·상점/world_nav arrive 불변.
동의: 사용자 (“3타일… ARRIVE 1”) + 보정 (“던전에서만… 필드 파라미터는 달라지지 말아야”).
결과: 구현. 처음에 전역 ARRIVE를 1로 내린 것은 필드까지 건드려 되돌림.

---

## 2026-10-04 — travel/search 커서 확인 분석 로그

의도: 대화창 open 감지 전에, travel/unstick 클릭이 NORMAL로 통과했는지·링에서 dialog를 몇 번 봤는지 로그로 추적한다.
공유: `ActionExecutor._search` → `last_travel_cursor_stats`; `DecisionManager._log_travel_cursor_outcome`; 스냅샷 `action_result.travel_cursor`.
영향: action 채널 로그·디버그 스냅샷만. 클릭/게이트/사다리 불변.
동의: 사용자 (“대화창 오픈여부… 그에 맞게 커서 확인 분석용 로그를 추가”).
결과: 구현. `travel click ok|failed … cursor=… dialog_seen=… reason=…`.

---

## 2026-10-04 — 주 Intent 중 in-range 루팅 F4 side

의도: 전투 등 다른 주 Intent가 이겨도, 줍기 거리 아이템이 있으면 F4로 놓치지 않는다. 접근(`SEARCHING`)은 루팅이 주 Intent일 때만.
공유: `loot_sides.arm_loot_side_intent` / `find_pickup_range_loot`, `decide` 말미 호출, `ActionExecutor`가 `PICKUP` side를 주 Intent **전에** `_loot`(F4). 물약 side와 분리.
영향: farming/dungeon/traveling/retreat 등 모든 주 Intent 틱. 사다리 순서·스티키 전투 불변. 새 ActionType 없음.
동의: 사용자 (“콤뱃…이어도 F4” + “모든 주인텐트 수행중에도…놓치는 아이템 없게” + “루팅용 접근은 루팅이 주 인텐트일 때만”).
결과: 구현.

---

## 2026-10-04 — 물약 전 계열 side_intents 병행

의도: HP/MP/해독 물약은 독점 사다리를 이기지 않고, 주 Intent와 같은 틱에 병행한다. 새 ActionType 없음.
공유: `potion_sides.arm_potion_side_intents`, `Blackboard.side_intents`, `apply_hp_actions`/`apply_inplace_hp_support` 물약 exclusive emit 제거, `maybe_use_antidote` no-op, `ActionExecutor.execute(..., side_intents=)`, `bot_controller` 전달.
영향: 사냥/후퇴/이동의 회복·전투·루팅·이동 틱 — 물약이 주 Intent를 막지 않음. 마우스 주 Intent면 물약 키를 사이드 스레드로 클릭과 겹침(틱 내 직렬 아님). 키보드 주 Intent면 물약 키 먼저. 힐/세계수/TP/안전 사다리는 유지.
동의: 사용자 (“모든 물약 계열은 병행… 사다리에서 빼고… 마우스면 동시, 키보드면 물약 먼저”). 보정: “틱 내 실행도 직렬로 하지 말 것”.
결과: 구현. 마우스 경로는 `threading.Thread`로 `_execute_side_intents` 겹침 후 join.

---

## 2026-10-04 — light 버프 시전 안 함

의도: 라이트를 쓰지 않는다.
공유: `spells.BUFF_ORDER`에서 `light` 제거; `spell_defaults`/`spell_box` 및 UserData `light.enabled=False`.
영향: `spell.buffs` — armor_up → power_up만. 핫바에 라이트 아이콘이 남아도 due되지 않음. HP/전투/상점 불변.
동의: 사용자 (“라이트는 사용하지 않도록 바꾸시오”).
결과: 구현.

---

## 2026-10-04 — 버프 id→role 카탈로그 문서 (구현 전)

의도: reuse 하드코딩 이유를 고정하고, 앞으로 “버프 없으면 시전”으로 바꾸기 위한 스키마·층·폴백·동의 고지 초안을 남긴다.
공유: 문서만 [`Docs/architecture/BUFF_STATUS_CATALOG.md`](../architecture/BUFF_STATUS_CATALOG.md). `due_buff`/모니터/프로필 코드 불변.
영향: 없음 (런타임 변경 없음).
동의: 사용자 (“대응표를 추가하고 … 필요한 문서를 준비”).
결과: 문서 작성. 구현은 별도 동의 후.

---

## 2026-10-04 — spell_slots 프로필은 box/key/enabled만

의도: 시전 방식(`cast`)·재사용(`reuse_s`)은 계정/캐릭터가 아니라 엔진 규칙이다. 프로필·스케줄에 두면 엔진과 충돌·분석 혼선이 난다.
공유: `spell_defaults.spell_slot_bindings` / `merge_spell_slots`(바인딩만 오버레이), `spell_box.merge_slots`·`configure_spell_box`, `Profile.to_dict`/`from_dict`, 핫바 커밋·스케줄 저장.
영향: 핫바 배치·enabled만 UserData에 남음. `heal_double_press`/`buff_cooldown_min`은 cast/reuse를 더 이상 덮지 않음(필드 자체는 호환용 잔존). Intent/모드 불변.
app 밖: `settings/*`, `session/bot_controller`, `UI` 저장 경로, UserData JSON — 프로필이 정본 저장소라 strip이 필수.
동의: 사용자 (“프로필에서는 box/key/enabled만…”).
결과: 구현. UserData `cast`/`reuse_s` 제거 확인.

---

## 2026-10-04 — power_up cast=double (heal과 동일)

의도: 파워 업은 Fn 두 번 연속 눌러 시전한다. 한 번만 누르면 스킬 선택/시전 대기로 남아 travel의 NORMAL 커서 검증이 실패했다 (`no NORMAL in ring`).
공유: `_press_assigned_skill`의 `slot_is_double` 경로 (힐과 동일 메커니즘). `armor_up`/`light`는 `press` 유지.
영향: world_nav·farming·traveling 열의 `spell.buffs` → `BUFF`/`power_up` 실행만. 모드·Intent·사다리 순서 불변. 핫바 스캔은 `DEFAULT_SPELL_SLOTS`의 cast를 복사.
app 밖: `settings.spell_defaults` (역할 카탈로그 정본), 라이브 덮어쓰기인 `UserData/profile.json`·`schedules.json`·defaults·profiles — 프로필 `cast:"press"`가 엔진 기본을 덮어 라이브 반영에 필요.
동의: 사용자 (“파워 업과 힐만 두번 누르기이다. 수정하시오”).
결과: 구현. `power_up` 기본/프로필 `cast=double`.

---

## 2026-10-04 — app 정리 1단계 후 운영 오류 수정

의도: app tidy 이후 운영/테스트에서 터질 수 있는 import·wire 잔존을 고친다. 의사결정 틱 정책·HP·전투 로직은 바꾸지 않는다.
공유:
- `app._05_action.__init__`를 지연 로드(`importlib`) — `shop_trip`→`spell_box`가 OpenCV(`cursor_verify`)를 끌어오지 않게 함
- `ActionType._missing_`: 옛 wire `shop_buy_arrows` → `SHOP_RUN`
- `ActionExecutor`에 `last_shop_*` / `last_gate_*` 호환 property (`result` 위임)
- `Others/tests`·`Research/.../live_runner`의 `manmabot_v1.*` → `session`/`settings`/`shop`/`hotbar`/`ui`/`i18n`/`login`
- 상점 워크/사냥맵 스크롤 테스트를 sticky `SHOPPING` / `WORLD_NAV` 계약에 맞춤
- `session.probes._ensure_ui_on_path` — 분해 후 `ui` 패키지(`UI/`)를 probe 로컬라이즈에서 찾게 함
영향: decide/shop import 경로, 옛 ActionType 문자열, Tools/스냅샷·테스트 호환. world_nav overlays·상점 qty/kind·틱 정책 불변.
동의: 사용자 (“정리결과로 … 오류들을 찾아 수정”). 결과: 구현.

---

## 2026-10-04 — shop ↔ decide/act Intent 박화

의도: Action이 buy/sell/teleporter·recover UI를 다시 고르지 않게 한다. shop 제품 모듈은 밖에 두고, Intent로 계약을 얇게 한다.
공유: `ActionIntent.shop_kind` / `shop_equip`; `_emit_shop_run`이 kind·equip·qty 설정; `shop.runtime.execute_shop_intent` / `execute_recover_arrow_buy`; `ActionExecutor._shop_run`은 facade만 호출.
영향: 상점 실행 경로. decide의 트립 선택·근접 판정은 유지(shop.runtime 조회). HP/전투 불변.
동의: 사용자. 결과: 구현.

---

## 2026-10-04 — world_nav I/O 주입 (A안)

의도: decision이 `session.probes` / `settings.farm_schedule`을 직접 읽지 않게 한다. Start가 normalize·맵 오버레이를 blackboard에 넣고, decide는 dict만 읽는다.
공유: `session.world_nav_inject.install_world_nav_overlays`, `world_nav.overlays` (`SCRATCH_MAP_OVERLAYS`), `init_routine_on_blackboard(entries_normalized=True)`, `goal_for_entry(entry, blackboard)`.
영향: world_nav arm/도착 farm·dungeon·patrol 경로의 의존 방향만. 틱 정책·HP·전투 불변. overlays 미주입 시 farm/patrol은 비고 dungeon은 pack_id 문자열 폴백(기존 ImportError 열화와 동급).
동의: 사용자 (“A선택”). 결과: 구현.

---

## 2026-10-04 — 모듈 경계 tidy (로직 무변경 목표)

의도: 라이브 틱 로직은 건드리지 않고, 모듈 분담만 명백히 한다.
공유: `legacy/`·BT `build_*_node`·BT-only `survival.py`/`loot.py` 제거; `spell_box`가 `settings.spell_defaults`의 `SLOT_IDS`/`SKILL_KEYS`/cast 모드를 re-export; `ground_loot` zh_names 경로를 `Engine/hotbar/...`로 수정; TRADING TODO·hotbar 문서 경로 정합.
영향: 경계·문서. world_nav→session.probes 결합(항목 2)은 미변경(토론). shop↔decide 추가 박화(항목 1)는 방향만 동의.
동의: 사용자. 결과: 구현(3·4·5).

---

## 2026-10-04 — `mid_act` 소유권을 decide로 이동

의도: Action이 Intent의 `mid_act`를 뒤집던 anti-spam/stuck 카운터를 제거하고, sticky 여부는 decide emit만 맡는다.
공유: `ActionExecutor.execute`는 `mid_act` 읽기만; `_act_counter`/`_stuck_limit`/`_sample_stuck_limit` 삭제. travel/search/combat emit 경로 불변(이미 decide가 `mid_act`를 넣음). 라이브 stuck 임계는 사실상 0이라 행동 변화 거의 없음.
영향: 실행기. 루팅 F4 이중경로·죽은 loot 헬퍼는 사용자 지시로 유지.
동의: 사용자 (“남긴다, 결정으로 옮긴다”). 결과: 구현.

---

## 2026-10-04 — Action Intent 상점 계약 + ActionResult

의도: action이 qty·상점 착지·recover를 다시 고르지 않게 하고, gate/shop `last_*` 부채널을 `ActionResult`로 접는다.
공유: `ActionIntent.shop_qty` / `shop_use_recover` / `shop_land_wait`; decide `_emit_shop_run`·`emit_talking_scroll(PURPOSE_SHOP)`; `ActionExecutor._shop_run` / `_shop_run_recover`; `executor.result`; wire `SHOP_RUN="shop_run"`; `maybe_run_pending_gate` 삭제.
영향: 상점·게이트·상점 스크롤 실행 경로. HP 사다리·전투·F4 loot 이중경로 불변((4) 보류).
동의: 사용자 (“(3)까지 정리, (4)는 토론”). 결과: 구현.

---

## 2026-10-04 — 상점 모드 승급 (`PlayerMode.SHOPPING`)

의도: 상점 트립을 sticky `PlayerMode.SHOPPING`으로 승급한다. world_nav와 동급 peer (숨은 scratch 세션이 아님).
공유: `shop_trip.ensure_shopping_mode` / `begin_shopping` / `leave_shopping_mode_if_idle`, `tick_shopping` + `SHOPPING` 열 (`shop.drive`), farming·world_nav·traveling handoff, `PURPOSE_SHOP` 도착은 SHOPPING 유지(TRAVELING 미사용), 후퇴 resume·`after_shop` need 재무장.
영향: 상점 scroll/walk/STOP/RUN 틱 경로. HP 사다리·전투 본문 불변. Intent 집합 불변 (`SHOP_RUN`/`STOP`/scroll/walk).
동의: 사용자 (“상점을 모드로 승급”). 결과: 구현.

---

## 2026-10-04 — 월드 내비 모드 승급 + 게이트 Intent

의도: 게이트 클릭을 `ActionType.GATE` Intent로 맞추고, 월드 내비를 sticky `PlayerMode.WORLD_NAV`로 승급한다. traveling과 동급 peer (흡수 아님).
공유: `ActionIntent` 게이트 필드, `ActionExecutor._gate` → `run_gate_click`, `apply_gate_result`, `begin_world_nav` / `tick_world_navigating` / `WORLD_NAV` 열. worker `maybe_run_pending_gate` 핫패스 제거.
영향: 루틴 맵 이동, farming `nav.world` handoff, 후퇴 후 `post_retreat`, Start arm. HP 사다리·같은맵 traveling 본문 불변.
동의: 사용자. 결과: 구현.

---

## 2026-10-04 — 칸 이름표 코드 적용 (열 runner, 동작 유지)

의도: `DECISION_STEPS` id 열을 `steps/columns.py` + `run_column`으로 옮기고, `tick_mode` / farming / traveling / retreating이 그 열을 돈다. HP·후퇴·언스틱·handoff 상한 본문은 그대로.
공유: `run_column`, 열 tuple, `mode_ticks` 핸들러 어댑터. `scratch["winning_step"]`에 이긴 칸 id.
영향: 모드 틱 골격(주소만). 전투 완성·IDLE livelock 수정 없음.
동의: 사용자 (“칸 이름표 적용”). 결과: 구현.

---

## 2026-10-04 — 틱 무한 IDLE livelock 이슈 기록 (수정 없음)

의도: handoff 상한·합성 IDLE·틱 단위 무한 IDLE 가능성을 이슈로만 남기고, 칸 표에 `idle_kind`를 붙인다. 로직·상한 변경 없음.
공유: 문서만. `ISSUE_idle_livelock.md`, `DECISION_STEPS.md`.
동의: 사용자. 결과: 기록.

---

## 2026-10-04 — ActionType 중복 제거 (라이브 이름만 유지)

의도: 비슷한 이름 정리로 칸/의도 구분을 쉽게. 라이브가 안 쓰던 별칭 삭제.
삭제: `COMBAT`(→ATTACK), `LOOTING`(→PICKUP), `RETREATING` ActionType(→TRAVELING; PlayerMode는 유지), `ESCAPE`(→TELEPORT), `MOVE`(미사용).
이름: `SHOP_BUY_ARROWS`→`SHOP_RUN` (wire 값 `shop_buy_arrows` 유지).
공유: `ActionType`, `ActionExecutor` 분기, preview, legacy emit. HP/전투 판단 사다리 불변. executor의 dead `_retreat`/`_escape` 제거(TRAVELING→`_travel`, TELEPORT→`_teleport`만).
영향: 실행 레이어·디버그 색·legacy. 라이브 decide emit 집합은 사실상 동일.
동의: 사용자. 결과: 구현 (18종).

---

## 2026-10-04 — 결정 구조화 목표 명시 (모드=행동 열)

의도: 1순위는 로직 완성/위험 감소가 아니라 **맞물림 뻔한 경계**로 수정·보충·고지 비용을 줄이는 것. 모드 소수 유지, 행동 칸을 열로 조합.
공유: `DECISION_HIERARCHY.md` §0. 틱 로직 불변.
동의: 사용자. 결과: 문서 갱신.

---

## 2026-10-04 — 결정 모드/행동 계층 명문화 (코드 분할 없음)

의도: 직접 정돈에 앞서 L0–L7(세션→decide→모드→사다리→concern→emit→query→blackboard)을 문서·패키지 docstring으로 고정한다. BT가 라이브가 아님을 명시.
공유: 문서/`__init__`·주요 모듈 docstring만. 틱 로직·HP·전투·후퇴 불변.
동의: 사용자 (계층 우선). 결과: `Docs/architecture/DECISION_HIERARCHY.md` + LOGIC/LAYOUT 링크.

---

## 2026-10-04 — world flat shim 제거 + Tools/Research sensors 통일

의도: (1) `_03_world` 루트 re-export shim 삭제, import를 `merge/`·`space/`·`catalog/`·`debug/`로 고정. (2) Tools/Research의 `shared_hotbar`/`shared_monitor`/`LiveEntitySweep`/`LineageMonitor` 직접 호출을 `PerceptionSensors`로 통일. (3) `_01_perception` 패키지 공개 API는 sensors만.
공유: import 경로·Tools 읽기 진입점. 틱 판단/HP/전투/로그인 불변.
동의: 사용자. 결과: 구현.

---

## 2026-10-04 — `_00_tool` 및 미사용 perception 기하 shim 삭제

의도: 죽은 `app._00_tool`과 action으로 옮긴 뒤 아무도 안 쓰는 perception `window_bounds`/`content_crop`/`screen_capture` shim, 낡은 world `prompt.md`를 지운다. session probe/debug·UI 핫바는 `shared_sensors`로 맞춤.
공유: import 정리만. 틱 로직 불변.
동의: 사용자. 결과: 구현.

---

## 2026-10-04 — Perception 주기 소유, 제품 경로는 sensors API만

의도: 모든 메모리 읽기는 `_01_perception`이 주기를 갖고 소유한다. 매 틱 필수는 아니다. session/shop/hotbar/world_nav는 `shared_sensors()` API만 쓴다. world는 버퍼→state. LiveEntitySweep·리더/타입 shim 제거.
공유: `capture_tick` / `capture_shop` / `capture_hotbar` / `pull_player`, `create_game_state`. HP·전투·상점·내비·로그인 규칙 본문 불변.
영향: 읽기 진입점. 틱 로직(판단) 불변.
동의: 사용자 (플랜 승인). 결과: 구현.

---

## 2026-10-04 — GameState/geometry를 state로, world는 변환만

의도: 디버그를 위해 살아 있는 상태를 `_02_state`에 모은다. `GameState`, `BattleArea`, `WorldOrigin`, `ObjectObservation` 이동. 엔티티 갱신·약/강 분류는 `merge.track`. 월드는 퍼셉션→state 변환.
공유: `apply_entity_handoff`, `create_game_state`. `_03_world.GameState`는 기본 플레이어만 넣는 얇은 하위클래스.
영향: 패키지. HP·전투·상점·내비·로그인 규칙 본문 불변.
동의: 사용자. 결과: 구현.

---

## 2026-10-04 — `_02_state`에 자료구조만, `_03_world`는 채우기

의도: 플레이어/월드/오브젝트 타입을 `_02_state`로 분리. `_03_world`는 PerceptionBuffer를 맞춘다.
공유: import 경로. shim. 규칙 본문 불변.
동의: 사용자. 결과: 구현(이후 GameState까지 state로 이동).

---

## 2026-10-04 — `_03_world`를 merge/space/catalog/debug로 정돈

의도: 월드 패키지를 역할별로 나눈다. 합치기·공간·카탈로그·디버그. 평탄 import는 shim으로 유지. `__init__`에서 모니터 DLL re-export 제거.
공유: import 경로만. HP·전투·상점·월드 내비·로그인 규칙 본문 불변.
영향: 패키지 위치·문서. 라이브 틱 로직 불변.
동의: 사용자 (정돈 순서 동의). 결과: 구현.

---

## 2026-10-04 — PerceptionBuffer만으로 GameState를 채움 (폴백 없음)

의도: 퍼셉션이 읽은 값을 `PerceptionBuffer`에 넣고, 월드의 `apply_perception_buffer`만 `GameState`로 넘긴다. `inv.json`·엔티티 stale hold·비전 대체 경로는 쓰지 않는다. 센서가 실패하면 그 필드는 비운다.
공유: `PerceptionSensors.capture`, `apply_perception_buffer`, `BotController` 틱. `decision_rows` hold 제거. 가방 DLL만.
영향: 틱 데이터 경로. HP·전투·상점·월드 내비·로그인 규칙 본문 불변.
동의: 사용자 (예외·폴백 없이 버퍼→월드 명백 구현). 결과: 구현.

---

## 2026-10-04 — perception을 메모리 센서로, 창 기하를 action으로

의도: `_01_perception`의 본체를 DLL 메모리 리더로 두고, 창 위치·4:3 클릭 경계는 `_05_action`으로 옮긴다. 월드는 스냅샷을 `GameState`에 합치는 쪽만 맡는다.
공유: import 경로. `memory_sync` / `memory_entities` / `memory_inventory`는 world에 유지. 옛 `_03_world.*_reader`와 `_01_perception.window_bounds`는 shim.
영향: 패키지 위치·문서. HP·전투·상점·월드 내비·로그인 규칙 본문 불변.
동의: 사용자 (그대로 정돈). 결과: 구현.

---

## 2026-10-04 — 클릭 경계는 Win32 창 사각형, 픽셀 복사는 미리보기만

의도: 포커스·최소화·창 위치만 필요하고, 프레임 판정은 없다. 틱의 클릭 경계를 `GetClientRect` + 4:3 계산으로 바꾸고, 디버그 미리보기가 꺼져 있으면 BitBlt를 하지 않는다.
공유: `ScreenCapture.refresh_click_bounds`, `BotController._sample_capture`, 미리보기 루프. 말하는 두루마리 직전 프레임 대기를 경계 갱신으로 바꿈. 판매의 라이브 경로는 프레임을 받지 않는다.
영향: 클릭 좌표, 창 없음/최소화 대기. HP·전투·상점 규칙·월드 내비·로그인 화면 분류 불변. 커서 템플릿 불변.
동의: 사용자 (이 범위로 진행). 결과: 구현.

---

## 2026-10-03 — manmabot_v1 → session/settings/shop/hotbar/i18n/login

의도: 제품 접착층을 용도별 패키지로 분해해 찾기 쉽게 한다. 본봇 코어는 `app/`에 유지.
공유: import 경로만. 의사결정·로그인·이동·전투·HP 규칙 본문 불변.
영향: `manmabot_v1.*` import → `session/settings/shop/hotbar/i18n/login`. Tools 핫바 패키지명 `hotbar_tool`.
동의: 사용자 (분해까지). 결과: 구현. `Engine/manmabot_v1`는 ImportError shim.

---

## 2026-10-03 — 루트 모듈 재배치 (Engine/UserData/Drivers/UI/Docs/Tools/Research/Others)

의도: 란잡한 루트를 용도·파이프라인별로 모듈화. `_01_capture` → `_01_perception`.
공유: 경로/`sys.path`/`MANMABOT_ROOT`만. 의사결정·로그인·이동·전투·HP 규칙 본문은 불변.
영향: 진입점 이름, import 경로, UserData/Engine 폴더명. 라이브 틱 로직 불변.
동의: 사용자 (상위 폴더 구조 지정). 결과: 구현. `Engine/analysis`는 런타임 DLL이라 Research가 아니라 Engine에 유지.

---

## 2026-10-03 — 루틴 분이 차면 다음 행으로 월드 내비

의도: 걷기 세션이 전투에 막혀 열려 있어도 행의 `duration_minutes`가 끝나면 다음 루틴으로 이동한다. 전투·루팅은 걷기 홉만 바꾸고, 말하는 두루마리와 맵 전환(게이트 접근, 커서 클릭, mapId 감시)은 그대로 틱한다. 후퇴·상점·사냥맵 복귀 도착은 체류 시계를 다시 시작하지 않는다.
공유: `tick_world_nav`, `_take_next_routine_if_due`, `_maybe_world_nav`, `RoutineCursor.mark_arrived`.
영향: 섬·던전 사냥 중 월드 내비. 로그인·HP 사다리 불변.
동의: 사용자 (스케줄에 맞추어 다음 행으로 월드 내비, 걷기만 전투에 양보). 결과: 구현.

---

## 2026-10-03 — 판매는 한 페이지 묶어서 confirm 1회

의도: Practice처럼 같은 스크롤 페이지의 판매 대상을 모두 선택(클릭+수량)한 뒤
confirm을 한 번만 누르고, 창이 닫히면 다시 열어 목록이 빌 때까지 반복한다.
공유: `execute_calibrated_sell`만.
영향: 상점 판매 실행. HP·로그인·이동 불변.
동의: 사용자 (한 번에 가능한 만큼 판매). 결과: 구현.

---

## 2026-10-03 — 판매 confirm마다 상점 재오픈 (연속 판매)

의도: NPC 판매 확인 시 창이 닫히므로, Practice처럼 아이템마다 Sell 탭을 다시 열고
판매 가능 목록이 빌 때까지 연속 판매한다. 수량는 shop_listen `count`가 있으면 그 값,
없으면 `default_qty`.
공유: `execute_calibrated_sell`만.
영향: 상점 판매 실행. HP·로그인·이동·world_nav 우선순위 불변.
동의: 사용자 (yes). 결과: 구현.

---

## 2026-10-03 — 구매/판매를 world_nav보다 먼저

의도: 무게·소모품으로 상점이 필요하면 사냥지 world_nav보다 먼저 구매/판매 동선을 탄다.
공유: `_shop_before_world_nav`, `_maybe_shop_trip`, `clear_world_nav_run` / `request_world_nav`(세션 중단일 때만).
영향: 섬·던전 `tick_farming`. HP·로그인·전투 규칙 불변. mid-nav 중 상점 필요 시 world_nav 세션을 지우고 `after_shop`으로 재요청.
동의: 사용자 (yes). 결과: 구현.

---

## 2026-10-03 — HP는 레벨 무관, 텔레포트 1회, MP 20

의도: 15레벨 미만 필드에서 힐/물약이 막히던 검증을 끈다.
물약이 없고 HP가 텔레포트 기준 이하이면 텔레포트는 한 번만.
HP가 세계수 기준 이하이고 현재 MP가 20 미만이면 텔레포트를 멈추고
세계수를 시도하고, 세계수가 불가능하면 상점을 시도한다.
힐·텔레포트 스킬은 현재 MP가 20 이상일 때만.
던전의 5% 텔레포트 계단은 쓰지 않는다.
공유: `is_low_level_hp_mode`, `apply_inplace_hp_support`, `apply_hp_actions`,
`heal_blocked_by_mana`, `begin_retreat`, `execute_teleport_dungeon`.
영향: 필드·던전 사냥, 후퇴, 루팅. 로그인·이동 경로 불변.
동의: 사용자 (응, MP는 20으로). 결과: 구현.

---

## 2026-10-03 — 판매는 창을 유지하고, 잔여 물품은 give_goods

의도: 판매 창을 아이템마다 닫지 않고 스크롤로 보관 목록 밖 항목을 이어서 판다.
상점 판매가 끝난 뒤 보관 목록 밖 아이템이 남아 있으면 `give_goods`를 실행하고,
그다음 예정된 NPC(물약·화살)로 간다.
공유: `execute_calibrated_sell`, `advance_sell_trip`, `item_passes_sell_filter`.
영향: 무게 초과 판매 이동. 전투·HP 순서 불변.
동의: 사용자. 결과: 구현.

---

## 2026-10-03 — 전환 착지 후: 시작점도 2타일 가보 스냅

의도: TRANSITION_LANDED map1 (32669,32802) 성공 후 WALK no_path.
착지 셀 nav (93,98)이 F1 nav.png에서 비가보 → A* 시작 불가.
수정: walk/게이트 접근 전 `_snap_live_origin` (r≤2);
hierarchical도 start/goal 모두 ≤2 스냅.
공유: `WorldNavSession._snap_live_origin`, `plan_travel_click_hierarchical`.
영향: 맵 전환 직후 워크. 동의: 사용자 (전환 성공 후 실패). 결과: 구현.

---

## 2026-10-03 — walk: already_arrived를 실패가 아니라 도착으로

의도: 전환점 2타일 안(스냅 가보)에 서 있으면 travel이
`already_arrived`를 반환하는데 월드내비가 WALK_FAIL로 처리해
바로 PAUSE. 서 있는 위치가 곧 게이트 접근 완료인데 실패로 보임.
수정: `already_arrived` / `hop_arrive_final` / `travel_arrived` →
WALK_ARRIVE + 다음 스텝(게이트). 시작 시 abs≤2면 hop 생략.
공유: `WorldNavSession._start_walk` / `_tick_walk` / `_finish_walk_step`.
영향: 월드내비 walk만. 동의: 사용자 (현재 위치에서 실패). 결과: 구현.

---

## 2026-10-03 — 맵 전환점: 2타일 내 가보로 경로

의도: `map_transitions` 셀(예: 32478,32851)이 nav.png에서 비가보면
`plan_travel_click`이 즉시 no_path. 전환점은 비가보일 수 있음 →
**2타일(Chebyshev) 안 가보 칸으로 스냅**해 경로/접근. 도착 판정도
기존 `ARRIVE_TILES=2`.
공유: `session._snap_nav_walkable` (walk·게이트 접근),
`WalkGrid.snap_walkable` 기본 r=2, hierarchical 목표 스냅.
영향: 월드내비 walk/게이트 접근. HP/전투 불변.
동의: 사용자 (전환점 비가보 → 2타일 근방 도달로 경로). 결과: 구현.

---

## 2026-10-03 — 게이트: mapId만이 아니라 착지 xy까지 대기

의도: TRANSITION_LANDED 후 바로 WALK_FAIL no_path. 로그상
`map=1 x=32477,32852`(TI 셀)인데 계획은 `map1(32669,32802)`.
mapId가 먼저 바뀌고 절대좌표가 한 틱 늦게 갱신되면 던전 팩으로
TI 셀을 변환 → origin≈(-99,148) → no_path. 전환 자체는 성공.
수정: 게이트 성공 = mapId + 계획 to-xy ±24; walk 시작 전 from과
멀면 idle 대기. 대기 5s.
공유: `gate.run_gate_click(expect_xy=)`, `WorldNavSession._start_walk`.
영향: 맵 전환 검증·직후 워크만. HP/전투 불변.
동의: 사용자 (전환 성공인데 월드내비 실패 원인 질문). 결과: 구현.

---

## 2026-10-03 — live mapId마다 맵 팩 동기 (중앙 ensure)

의도: 매 틱 mapId 갱신 후, **시작·mapId 변경 틱**에 해당 팩을
동기 로드해 다음 decide/act가 잘못된 origin/지형을 쓰지 못하게 함.
원인: profile 던전 팩 + async configure가 TI에서 origin=(-98,151) /
no_path를 반복 유발. mapId는 맞아도 팩이  lagged.
공유: 신규 `live_map_pack.ensure_navigation_for_live_map_id` /
`ensure_navigation_for_pack_id`. `bot_controller` 매 틱 호출.
게이트/스크롤/마더트리/루틴 apply의 async 팩 전환 → sync ensure.
영향: 이동·월드내비·쇼핑 착지 팩. HP/전투 정책 불변.
부작용: 맵 전환 틱이 팩 로드만큼 블로킹(정확성 우선).
동의: 사용자 (이런 오류 재발 금지 / 시작·변경 틱 맵데이터 로드).
결과: 구현.

---

## 2026-10-03 — 월드내비 walk: 팩 동기 전환 (origin=-98,151)

의도: 시작 시 profile 던전 팩이 남은 채 map0 워크 → nav origin
`(-98,151)`(= talking_island_dungeon_F1 @ TI 셀) → `no_path`.
mapId는 이미 0으로 읽힘; 문제는 `_ensure_map_pack`이 async라
지형 clear + 잘못된 map_origin으로 hop.
수정: walk/gate/scroll 전 `configure_navigation_for_map` **동기**;
첫 live mapId에서 현재 맵 팩으로 즉시 sync.
공유: `WorldNavSession._ensure_map_pack`, `bot_controller` 시작 틱.
영향: 월드 내비 걷기·게이트 접근·스크롤 착지 팩. 전투/HP 정책 불변.
부작용: 맵 전환 시 첫 walk가 팩 로드만큼(수백ms~) 블로킹.
동의: 사용자 (origin=-98,151 재발 / 시작 mapId·팩 불일치 보고).
결과: 구현.

---

## 2026-10-03 — mapId: 매틱 갱신 유지 + 게이트 pull-now 수정

의도: 봇 시작·맵 전환에서 MapSubsystem mapId가 반드시 읽히게 함.
측정: `snapshot(fresh=False)` ≈ 17–21ms (30ms 이하) → 매 틱 전체
스냅샷에 이미 포함된 mapId 갱신을 유지(별도 경로 불필요).
원인: 게이트 착지 대기가 DLL `fresh=True`(`discoverNow`)를 써서
hang/timeout → 동결된 `last_memory_snapshot`으로 오판.
수정: `live_pose_from_state(fresh=True)` = pull-now `snapshot(False)`.
DLL에 `mapIdOk`(MapSubsystem 발견 여부) 추가 — TI의 mapId=0과
미발견 구분. 시작 시 mapId 로그 + mapId 준비 대기.
공유: `session.live_pose_from_state`, `gate` timeout 1.0s,
`player_map_id_from_snapshot`, `bot_controller` tick, monitor DLL.
영향: 월드 내비 전이 검증·시작 대기. 이동/전투/HP 정책 불변.
동의: 사용자 (시작/전환 mapId + 30ms 이하 매틱 검토). 결과: 구현.

---

## 2026-10-03 — 게이트 커서 탐색 hang(=크래시) 수정

의도: attempt 사이 `read_land()`(fresh 모니터)가 ~28초 블록되어
워커가 죽은 것처럼 보이던 문제 제거. 프로브 전/중에는 캐시 pose만.
클릭 후 mapId만 timeout(0.45s) 있는 fresh. 프로브 `snap=True`로
링 샘플을 실제로 순회. 로그에 rings_frac/rings_px/center 명시.
공유: `gate.run_gate_click`, `maybe_run_pending_gate`.
링: 0.02..0.1×client_h, 30° (안→밖). 두루마리·동일맵 걷기 불변.
동의: 사용자 (커서 탐색 크래시·링 확인). 결과: 구현.

---

## 2026-10-03 — 게이트: 클릭=시도 / 3초 mapId / 1회 재시도 / 탐색지도 경고

의도: 게이트 커서 발견 후 클릭을 전환 *시도*로 보고, 3초 안에
MapSubsystem mapId가 목적지가 되면 성공. 실패 시 커서 탐색을
한 번 더 돌리고, 또 실패하면 탐색 지도 탭에 경고.
커서 탐색 중 `fresh` 모니터 연타로 워커 hang/크래시 나던 것도
프로브는 캐시 pose만, 착지 대기만 fresh로 분리해 수정.
공유: `gate.run_gate_click`, `maybe_run_pending_gate`,
`SCRATCH_NAV_GATE_WARN`, debug 탐색 지도 배너/HUD.
영향: 월드 내비 map_transition만. 두루마리·동일맵 걷기·HP 불변.
동의: 사용자 (게이트 오류/크래시 수정 요청). 결과: 구현.

---

## 2026-10-03 — 게이트 대기 mapId 스냅샷 동결 수정

의도: 월드 내비 게이트 클릭이 워커 루프를 막아 `last_memory_snapshot`이
TRANSITION_WAIT 동안 갱신되지 않던 문제 해결. 로그상 착지 후 다음 틱에는
이미 목표 mapId인데도 `mapId did not become N`으로 실패함.
공유: `live_pose_from_state(fresh=True)`, `maybe_run_pending_gate._read`.
MapSubsystem 경로 불변; print_state xy 우선·monitor mapId.
영향: 월드 내비 map_transition 판정만. 전투·HP·로그인 불변.
동의: 사용자 (맵아이디 실시간 로드 원인 분석·해결). 결과: 구현.

---

## 2026-10-03 — Start가 스케줄 루틴 없이 기동하던 버그

의도: 게임이 떠 있을 때 Start가 `apply_task` 없이 낡은 profile로
바로 `coordinator.start` 하던 이중 경로 제거. 스케줄이 있으면
apply_task(루틴 포함) 후 기동. 에디터 루틴도 profile에 동기화.
공유: `schedule_ui._start`, `_sync_routine_from_editor`.
영향: 월드 내비 목표가 UI 루틴과 일치. 의사결정 틱 로직 불변.
동의: 사용자. 결과: 구현. profile.json도 활성 일정으로 동기화.

---

## 2026-10-03 — 월드 내비 걷기 중 전투·루팅 (TRAVELING과 동일)

의도: world-nav `walk` / `gate_approach` 중 `farm_loot_or_combat`
(restrict_to_farm=False). scroll·gate_click은 내비만.
공유: `_maybe_world_nav`만. enter-farm travel 로직 불변.
영향: 월드 내비 도중 이동 경로상의 몹/드랍. HP/후퇴는 기존처럼 상위 우선.
동의: 사용자. 결과: 구현.

---

## 2026-10-03 — M3 단행 battle duration 순환 + M2 manmabot 임포트 안전

의도:
- duration은 `len>=1`이면 항상 만료 처리. 같은 맵이면 체류/farm tour 갱신,
  헌트맵 밖일 때만 world-nav 재arm. 다른 맵이면 기존처럼 nav(도착 후 apply).
- 이미 목표에 있어 빈 플랜이면 fail_skip 대신 arrival 처리.
- `normalize_routine` / probes ImportError 시 로컬 폴백·로그 (워커 사망 방지).
공유: `hooks.tick_world_nav` / `arm_world_nav`, `routine.py`.
동의: 사용자. 결과: 구현.

---

## 2026-10-03 — 월드 내비 전이를 map_transitions.json으로

의도: 사용자가 수동 수정한 `engine/data/world/map_transitions.json`을
라이브 `load_graph` 전이 정본으로 사용. hubs/스크롤은 providers 유지.
`ground_enter`+`floor_ladder`만 플래너에 넣음. 파일 없으면 기존 provider 폴백.
공유: `world_nav/ready/graph.py`. 실행 세션/게이트 로직 불변.
동의: 사용자 (“수동 입력 수정 데이터 사용”). 결과: 구현.

---

## 2026-10-03 — world_nav 전 루틴 실패 시 Stop (Pause 아님)

의도: full-cycle fail 시 auto-pause 대신 `stop(reason=world_nav_cycle_failed)`.
로그·푸터·상태 사유 표시. 스케줄 armed면 disarm (자동 재시작 방지).
사용자는 원인 수정 후 Start 가능. fail_mask는 stop 전에 리셋.
공유: `_fail_skip`, `bot_controller` 워커, schedule `_paint_run_status`.
동의: 사용자. 결과: 구현.

---

## 2026-10-03 — begin_retreat 시 world-nav 실행 상태 정리

의도: 후퇴가 캐릭터를 가져가면 in-flight world-nav session/gate/need 제거.
루틴 cursor는 유지. `finish_retreat`의 `post_retreat` 재요청은 그대로.
공유: `clear_world_nav_run`, `begin_retreat`.
영향: 후퇴 중·직후 stale nav 이어가기 방지. HP/트리/스크롤 목적지 로직 불변.
동의: 사용자. 결과: 구현.

---

## 2026-10-03 — world_nav gate: pop-before-result soft-lock 제거

의도: gate scratch는 `note_gate_result` 후에만 제거. 예외/Stop도 fail로 마감.
`gate_click`인데 payload 없으면 세션 fail (안전망).
공유: `maybe_run_pending_gate`, `WorldNavSession.tick` gate_click 분기.
영향: 맵 전이 게이트 클릭만. 플래너/arm 불변.
동의: 사용자. 결과: 구현.

---

## 2026-10-03 — world_nav: 목적지 runtime은 도착 후에만

의도: arm / fail_skip / duration advance 직후 `apply_routine_entry_runtime` 제거.
가는 동안은 step `_ensure_map_pack`만. 세션 done 시 `_on_world_nav_arrived`에서 apply.
공유: `hooks.py`만. MapSubsystem mapId 경로 불변.
영향: 월드 내비 이동 중 terrain/`HUNT_MAP`/던전 플래그가 목적지로 선적용되지 않음.
동의: 사용자. 결과: 구현.

---

## 2026-10-03 — break-only 루틴: UI 경고 + 실행 차단

의도: 휴식 맵만 있는 루틴(단행·다행 break만)은 시작 불가.
요약 경고, 추가/삭제 시 messagebox, 일정 저장(collect) 거부,
`start_gates_ok` → `start_break_only`, 메인/스케줄 Start 사전 차단.
다행 duration 순환·단행 battle duration 무시는 유지.
공유: `routine_is_break_only`, `start_gates_ok`, schedule/main UI.
영향: 시작·일정 저장. 전투/이동 틱 로직 불변.
동의: 사용자. 결과: 구현.

---

## 2026-10-03 — world_nav arm: plan/begin 예외를 fail_skip으로

의도: `goal_for_entry`와 `session.begin`(내부 `api.plan`)을 같은 try에 묶어
예외 시 기존 `_fail_skip`만 탐. manager/planner 로직 불변.
공유: `arm_world_nav`만.
영향: 월드 내비 arm 실패 시 워커 사망 대신 다음 루틴/pause.
동의: 사용자. 결과: 구현 (`hooks.py`).

---

## 2026-10-03 — world_nav `_start_walk`가 bool 반환하던 크래시

의도: `emit_travel_hop`의 bool을 mode tick Status와 섞지 않음.
게이트 접근과 동일 — hop 호출 후 intent 있으면 SUCCESS, 없으면 IDLE Status.
공유: `WorldNavSession._start_walk`만. `emit_travel_hop` / manager / fail-skip 불변.
영향: 월드 내비 walk 시작 틱. 일반 travel·농장 hop 불변.
동의: 사용자. 결과: 구현 (`session.py`).

---

## 2026-10-03 — 던전 콤뱃 툴 정책 → 엔진 + Extra_data 분리

의도: 던전 모드에서만 툴과 동일 동작. 스케줄 `hp_actions`/loot 공통(A).
`safe_zone` OFF, TP −5% 계단, ≤30% 트리→상점, 넛지, 긴급TP OFF.
회복·쇼핑·후퇴 후 월드 내비 재입장. Extra_data 참조 제거.
공유: `dungeon_policy.py`, `apply_hp_actions`, unstick, `_tick_dungeon_farming`,
`world_nav/ready` + `engine/data/world_nav`.
영향: 던전만. 섬 농장·로그인 불변.
동의: 사용자 (A + 툴 로직 불변 조건 + Extra_data 통합). 결과: 구현.

---

## 2026-10-03 — 월드 내비 UI 루틴 통합 (구현)

의도: 스케줄→계정→루틴(`move.routine`) 기준으로 Extra_data
월드 내비를 본 봇 틱에 연결.
공유: `engine/app/_04_decision/world_nav/*`, `Profile.routine`,
`apply_runtime_settings`, `tick_farming`/`finish_retreat`/`bot_controller`.
영향: 기동·상점 후 복귀·후퇴 후 재진입·루틴 duration·재로그인 후
(post_respawn)·실패 시 다음 행·한 바퀴 실패 pause.
의도하지 않은 부작용 후보: 스크롤 사용 증가, GATE 클릭 실패 시 스킵.
동의: 사용자 (UI 기준 추가). 결과: 구현.

---

## 2026-10-03 — 월드 내비 메인 통합 합의 (설계; 배선은 후속)

의도: Extra_data `world_nav_ready`를 본 봇 userdata(스케줄→계정→루틴)에
맞춰 호출한다. 전투/루팅 hop은 범위 밖.
공유: `WorldNavPlanner` / `LiveRunner` / 루틴 `move.routine[]`
(`battle`|`break` + duration). 메인 의사결정 배선은 별도 동의 후.
영향(예정): 기동·상점/회복 후 재진입·루틴 전환·재로그인/리스폰.
의도하지 않은 부작용 후보: 스크롤 남용, 루틴 스킵 루프.
동의: 사용자. 결과: 합의 기록 + Extra_data 상태 로그 선구현.

### 호출 트리거 (합의)

1. 봇 기동 → 첫 루틴 목적지 (당장은 고정 회복지점 출장 유지)
2. 회복/상점 완료 → 사냥 재진입
3. 루틴 `duration` 만료·사냥터/휴식 전환 (battle↔break 순서 소비)
4. 재로그인 / 사망 리스폰 후 → 활성 루틴 목적지 재계획
5. **같은 mapId여도** 월드 내비 필수 (두루마리로 시간 단축 가능)
6. 실패(경로 없음·도착 mapId 불일치 등) → **다음 루틴 목적지**로
   월드 내비. **한 바퀴 전부 실패** 시 pause + 로그 (묵살 정지 방지)

### 상태 로그 (구현)

형식: `[world_nav] STATE=<token> k=v …`
채널: Extra_data Live log + (가능 시) `manmabot.nav`
파일: `planner/nav_state_log.py` → `live_runner` / GUI Plan
토큰: PLAN_OK/FAIL, RUN_*, STEP_*, WALK_*, SCROLL_*, TRANSITION_*,
FAIL_SKIP_NEXT, PAUSE_CYCLE (후자 둘은 메인 통합 시 사용)

---

## 2026-10-03 — 필드 travel hop Chebyshev ≤ 5

의도: 클라이언트 walk 검정 검사는 유지한 채, 필드 한 클릭 hop을
최대 5타일로 제한해 긴 빗나감·벽 스침을 줄인다.
공유: `plan_travel_click` 기본 `max_hop`; `player_mode.TRAVEL_MAX_HOP_TILES`;
`decision.yaml` `travel.max_hop_tiles`.
영향: 필드 TRAVELING / enter-farm / patrol 아닌 일반 맵 travel /
월드내비 live walk. 던전은 기존 `max_hop=2` 유지.
부작용 후보: hop 횟수·클릭 빈도 증가; 전투 path-clickable은 거리 캡 없음
(walk clear만).
동의: 사용자 (walk 조건 유지 + 5타일 캡). 결과: 구현.

---

## 2026-10-03 — 클릭 유효성: A* slack → 클라이언트 walk 검정 검사

의도: 게임은 클릭마다 고정 2구간 경로(축→대각 또는 순수 대각)로만
걷는다. A* slack(`astar_d ≤ chev_d+3`)은 다른 A* 우회를 허용해
실이동에 벽이 있어도 통과시키는 경우가 있음 → slack을 대체.
공유 함수: `game_client_walk_tiles`, `is_game_walk_clear`,
`is_click_valid`, `select_click_waypoint`; combat
`_path_within_slack`도 동일 gate.
영향: TRAVELING / SEARCH 아님(travel hop·enter·patrol·월드내비 live),
전투/루팅 “클릭 가능 path” 판정. 던전 `max_hop=2` 유지.
부작용 후보: 예전보다 hop이 짧아질 수 있음; 몬스터가 비가보 칸이면
engage path가 더 자주 거절될 수 있음(인접≤1은 기존대로 허용).
동의: 사용자 (slack 대체 요청; 효과 불량 시 Chebyshev≤5 hop 상한은
계획만, 코드 미적용).
결과: 구현. 5타일 상한 후보는 `select_click_waypoint(max_hop=)` /
필드 `plan_travel_click` 기본값으로 넣는 방안으로 보류.

---

## 2026-10-03 — 낡은 player MapId 오프셋 완전 제거

의도: `MapId: 308` / `CurrentMapId: 0` 잔재를 offsets에서 삭제해
향후 혼동 방지. MapSubsystem 경로만 정본.
공유: `.cursor/rules/map-id-from-mapsubsystem.mdc` (alwaysApply).
영향: 문서·설정만. 런타임은 이미 MapSubsystem+0x718.
동의: 사용자 (낡은 오프셋 완전 제거). 결과: 구현.

---

## 2026-10-03 — MapId: player+0x134 → MapSubsystem+0x718

의도: 잘못된 플레이어 `MapId`(INT@0x134) 대신
`Extra_data/10_2/2_map_region` 검증 경로 —
mgr→holder→subs→MapSubsystem(vft 0x11C7DF0)→`+0x718`(+0x71C pair).
공유 함수: `findMapSubsystem` / `readCurrentMapId` in
`realtime_monitor_full.c`; offsets `MapSubsystemVftRva`/`MapIdOff`.
영향: monitor JSON `player.mapId` → 월드 내비 `read_pose` 포함 모든
monitor 소비자. print_state xy 불변.
동의: 사용자 (폴더 보고 모순 없으면 바로 통합). 결과: 구현.

---

## 2026-10-03 — 월드 내비: 메모리 MapId 우선

의도: 맵 전환 판정을 AABB 추정 대신 플레이어 구조체 `MapId` 메모리
값으로 한다. 좌표는 기존 `print_state` xy 유지.
공유 함수: `realtime_monitor` JSON `player.mapId`;
`player_map_id_from_snapshot`; `LiveWorld.read_memory_map_id` /
`read_pose`.
영향: Extra_data 월드 내비 live start / live run 맵 전환 대기.
메인 봇·던전 GUI는 아직 미연결(후속).
부작용 후보: 구 DLL(mapId 미출력)이면 기존 infer 폴백; 팩에 없는
mapId는 xy만 있고 pack 없음.
동의: 사용자 (월드 내비 먼저 반영). 결과: 구현.

---

## 2026-10-03 — 커서 min_score 0.8 → 0.98

의도: 라이브 `DrawIconEx` 캡처가 정답 템플릿과 score=1.0으로
일치함을 확인. 교차 유사도(arrow↔arrow_lack 0.927, door↔normal 0.862)
가 통과하지 못하도록 임계값 상향.
공유 함수: `CursorMatcher.min_score`; `action.yaml` `cursor_verify.min_score`.
영향: 커서 verify가 켜진 공격/줍기/이동 클릭 게이트. 로그인·HP·후퇴 불변.
부작용 후보: 템플릿과 미세히 다른 라이브 커서는 미탐(거절) 증가.
동의: 사용자 (0.98로 높이라). 결과: 구현.

---

## 2026-10-03 — Start Dungeon Combat: 전체 던전 목록 + EN/KO/ZH

의도: 하드코딩 3맵 → `engine/maps` 던전 팩 자동 수집. UI 언어
(English / 한국어 / 简体中文)에 따라 표시명 전환. 검색은 EN·KO·ZH·
pack id 어느 쪽이든 매칭. 월드내비 통합은 보류(사용자 결정 대기).
공유 함수: 엔진 본문 미변경. `debug_tools/dungeon_combat_maps.py` 신규,
`dungeon_combat_gui` Map UI만.
제외: `dungeons/`, `_legacy_dungeons/`, `*ship*`, `gerard_test*`,
`unknown_99*`.
영향: Start Dungeon Combat 맵 콤보·검색·언어만. 전투/이동/HP 불변.
동의: 사용자 (목록 먼저, 내비는 이후). 결과: 구현.

---

## 2026-10-03 — 던전: 월드트리 완충 후 물약 상점 arm 복구

의도: 가방 Return-limit→상점 OFF 패치가 `needs_potion`을 farm 틱에서
막아, 트리 완충/`tick_shop_trip` 첫 틱 실패 시 상점이 이어지지 않던
문제 수정. `dungeon_allow_potion_shop` arm으로 트리 후·HP≤30% 상점만
허용. UI Shop NPC + Buy qty는 기존처럼 프로필→`configure`→
`resolve_shopping_behavior_id` / `HP_POTION_BUY_QTY`.
공유 함수: 던전 `_arm_dungeon_potion_shop`, `_maybe_shop`, `_tree_tick`.
영향: Start Dungeon Combat 상점만. 메인 불변.
동의: 사용자 (트리 후 상점+UI NPC). 결과: 구현.

---

## 2026-10-03 — 월드트리 HP→MP: 라이브 핫바 확인 (메인+던전)

의도: `maybe_hp_to_mp_at_tree`가 Setup enabled만 보지 않고, 힐/세계수처럼
라이브 핫바에 `hp_to_mp`(바디 투 마인드)가 있을 때만 emit.
스냅샷 없으면 기존처럼 허용. 실행은 `_live_or_assigned_slot`이 핫바 키 우선.
추가로 MP 예약 게이트가 `hp_to_mp` 키 입력을 막던 문제 수정
(MP 낮을 때 쓰려고 하는 스킬이라 `can_cast_spell` 제외).
공유 함수: `hp_to_mp_on_live_hotbar`; `maybe_hp_to_mp_at_tree`;
`controller._press_assigned_skill`.
영향: 마더트리 recharge HP→MP (메인 Manmabot + 던전 공통).
동의: 사용자 (메인+던전). 결과: 구현.

---

## 2026-10-03 — Start Dungeon Combat: giran_dungeon_F1 추가

의도: 기란 던전 F1도 TI/글루디오처럼 Start Dungeon Combat에서
선택·파밍·루팅.
공유 함수: `dungeon_combat_gui.COMBAT_MAPS`만.
영향: 던전 전투 GUI 맵 목록. 엔진 사냥 로직 불변.
전제: `engine/maps/giran_dungeon_F1` 팩(nav.png) 기존. 패트롤은
에디터에서 저장 필요(현재 waypoints 비어 있음).
동의: 사용자 요청. 결과: 목록 추가.

---

## 2026-10-03 — attacks_me: 맞기 시작 후 죽을 때까지 finish_kill

의도: 나를 친 몹은 AttackAction이 끝나도 sticky를 유지하고 처치 완료까지
전투. 루팅/원거리 동종 rematch/give-up 시계로 끊지 않음.
공유 함수: `finish_kill_until_dead` / `finish_kill_ids`; `begin_engage(finish_kill=)`;
`memory_target_gone`·`sync_attacks_me_force_targets`; `rebind_sticky_target`;
`give_up_target` skip; `advance_engage_or_give_up`.
영향: 자위 전투 sticky. 아데나/일반 사냥은 finish_kill 해제 후.
부작용 후보: 목록외 몹이 사망 신호 없이 오래 남으면 sticky가 길어질 수 있음.
동의: 사용자 (“attack 100% until fully dead once it starts attacking me”).
결과: 구현.

---

## 2026-10-03 — 던전: 긴 IDLE / no-intent 넛지 3초 → 1.5초

의도: `_LONG_IDLE_S`만 단축. 넛지 조건·반경·스킵(상점/후퇴) 동일.
동의: 사용자. 결과: 구현.

---

## 2026-10-03 — 던전: tick_mode 패치가 decide에 안 타던 버그

의도: IDLE/no-intent·blocked 근처 클릭이 안 돌던 원인 —
`DecisionManager`가 `from mode_ticks import tick_mode`로 고정 바인딩.
`mode_ticks.tick_mode`만 패치해도 live decide는 원본 호출.
공유 함수: `_install_dungeon_hp_policy`에서 `manager.tick_mode`도 패치.
영향: Start Dungeon Combat blocked-step / long-idle·no-intent nudge.
동의: 기존 넛지 yes + 실기 “안 움직임” 보고. 결과: 구현.

---

## 2026-10-03 — 줍기 거리: 2타일 → 1타일

의도: Chebyshev ≤1이면 PICKUP/F4, >1이면 walk onto item.
공유 함수: `LOOT_PICKUP_TILES`; `decision.yaml` `farm.loot_pickup_tiles`;
`configure` 로드; `_in_pickup_range` / `_standing_to_pickup`.
영향: 루팅 접근/줍기만. 전투·HP·이동 불변.
부작용 후보: 접근 hop이 한 칸 짧으면 F4가 약간 늦어질 수 있음.
동의: 사용자. 결과: 구현.

---

## 2026-10-03 — attacks_me: 목록/카탈로그 없어도 합성 추적 공격

의도: 나를 치는 몹이 print_state 몬스터 목록·카탈로그에 없어도
`attacks_me` 행만으로 WorldObject를 합성해 engage. 블랙리스트·give-up
무시. AttackAction이 끝날 때까지 sticky.
공유 함수: `sync_attacks_me_force_targets`, `nearest_attacks_me_force`,
`GameState.upsert_object`, `memory_target_gone` force 예외,
`farm_loot_or_combat` sticky 전 sync.
영향: 메인+던전 자위만. 일반 사냥/루팅/HP/이동 불변.
동의: 사용자 yes. 결과: 구현·스모크 OK.

---

## 2026-10-03 — 던전: 긴 IDLE ≥3초 → 근처 walkable 클릭

의도: Start Dungeon Combat에서 `ActionType.IDLE`이 연속 3초 이상이면
반경 2→3 walkable 칸을 돌아가며 걷기 클릭 (blocked-step과 동일 패턴).
공유 함수: 던전 패치 `_try_dungeon_long_idle_step` + `tick_mode`만.
메인 언스틱/TP 불변. blocked 칸은 기존처럼 즉시 스텝.
영향: 던전 평시 IDLE만. 상점 트립·후퇴·세계수 stand는 스킵.
부작용 후보: 몬스터 없을 때 근처를 빙빙 돌 수 있음.
동의: 사용자 yes. 결과: 구현.

---

## 2026-10-03 — 공격 조준 반경: 10px → 0.1타일

의도: 고정 10px 링 대신 `ATTACK_CURSOR_SEARCH_TILES=0.1` 분수 타일 링.
공유 함수: `object_attack_screen_points` (UV + `_fractional_content_ring`);
`decision.yaml` `combat.cursor_search_tiles: 0.1`.
영향: 공격 조준 점만. 틱당 budget/sticky lock 유지. 메모리 타일 점프 없음.
동의: 사용자. 결과: 구현.

---

## 2026-10-03 — 공격 조준: 픽셀 링 + 틱당 제한 probe / sticky lock

의도: UV↔메모리 타일 큰 점프 흔들림 제거. 본체 UV + 10px 4방향 링.
틱마다 전 링을 돌지 않고 `ATTACK_AIM_PROBES_PER_TICK=2`, sticky는 성공 픽셀 고정.
공유 함수: `object_attack_screen_points`; `attack_click_search` /
`mage_cast_click_search` (+ target_id/sticky); `CURSOR_SEARCH_SETTLE_S=0.02`.
영향: knight/elf/royal/mage 공격 조준만. 루팅·HP·이동 불변.
부작용 후보: miss 시 클릭이 다음 틱으로 미뤄질 수 있음.
동의: 사용자 (“픽셀 링 + 틱마다 전 링 돌지 않기”). 결과: 구현.

---

## 2026-10-03 — contested_mobs: 타 유저 공격 중 몹 신규 engage 제외

의도: 스윕에 보이는 다른 Player(또는 내 소유 아닌 Summon)가
AttackAction으로 치고 있는 Monster는 신규 engage하지 않음.
스윕에 유저가 없으면 contested 목록에 없음 → 프리로 공격.
공유 함수: `contested_mobs.dll` + `ContestedMobsReader`;
`list_attackable` 필터; `world.last_contested_mobs`.
예외: sticky 유지, `nearest_attacks_me_force`(자위)는 필터 안 탐.
영향: 메인+던전 신규 타겟만. HP/이동/로그인/루팅 순서 불변.
동의: 사용자 yes. 결과: 구현·DLL 빌드 OK.

---

## 2026-10-03 — 줍기 클리어: 이미 normal이면 마우스 고정

의도: 시체 위에서도 커서가 이미 normal이면 30px 너지/연속 hover 하지 않음.
공유 함수: `clear_loot_attack_hover` — `_cursor_is_attack() is False`면 early return.
영향: 루팅 F4/클릭 직전만. pickup retry 스팸 hover 감소.
동의: 사용자 보고. 결과: 구현.

---

## 2026-10-03 — 아데나 보이면 다른 아이템보다 우선 줍기

의도: 화면/후보에 아데나가 있으면 거리와 무관하게 먼저 줍기.
공유 함수: `nearest_lootable` 정렬(아데나 우선); `continue_or_start_loot`에서
sticky 비아데나가 아데나에 yield.
영향: 루팅 선택만. 전투 sticky / attacks_me / HP0 / pending pickup await 유지.
부작용 후보: 먼 아데나를 위해 가까운 물약 접근을 끊음; 무명 더미도 아데나로 취급.
동의: 사용자 (“sees adena → pick first”). 결과: 구현.

---

## 2026-10-03 — 줍기 커서 클리어: 30px 1회만

의도: ATTACK 잔여 시 55/90 재시도 제거. 30px 한 번만.
공유 함수: `LOOT_CURSOR_CLEAR_RADII_PX = (30,)`; `clear_loot_attack_hover`.
영향: 루팅 실행만. 동의: 사용자. 결과: 구현.

---

## 2026-10-03 — SURROUND_MONSTER_COUNT 기본 4→10

의도: 포위 판정 기본 몹 수를 10으로.
공유: `SURROUND_MONSTER_COUNT`, `decision.yaml surround_count`,
profile/schedule/UI fallback.
영향: `teleport_when_surrounded` ON일 때만 비상 TP 임계값.
동의: 사용자 지정. 결과: 기본값 변경.

---

## 2026-10-03 — 줍기 커서 클리어: ATTACK이면 거리 늘려 재시도

의도: 1회 30px 너지로도 시체 스프라이트에 남아 arrow가 남는 소수 케이스 해소.
공유 함수: `clear_loot_attack_hover` — 30/55/90px, classify가 ATTACK이면 반복.
영향: 루팅 실행만. 전투·HP·이동 불변.
부작용 후보: 최악 ~3스냅 + settle. 동의: 잔여 이슈 보고(옵션1 강화). 결과: 구현.

---

## 2026-10-03 — attacks_me 강제 engage (메인+던전)

의도: AttackAction tgt==me 인 monster/summon은 종 블랙리스트여도
강제 engage. sticky 이후·loot 직전. 메인/던전 공통
(`farm_loot_or_combat`).
공유 함수: `nearest_attacks_me_force`; `farm_loot_or_combat`;
`continue_or_start_combat(reason=...)`.
영향: 전투 타겟 선택만. HP/이동/후퇴/로그인/루팅 경로 구조 유지
(단, 나를 치는 대상이 있으면 loot보다 앞섬).
우회: 종 필터만. give-up·세션 blacklist·LOS/path-cap·수면 골렘 유지.
동의: 사용자 yes (loot 직전, monster+summon). 결과: 구현.

---

## 2026-10-03 — 줍기/F4 전 공격 커서 항상 클리어

의도: pickup·pickup retry 시 시체/잔상에 남은 arrow 커서 때문에 줍기가
막히는 문제를, 줍기 전에 마우스를 ~30px 항상 떼어 해소.
공유 함수: `clear_loot_attack_hover`; `_loot`(F4)·`loot_click`에서 호출.
영향: 루팅 실행만 (던전·농장 공통). 전투·HP·이동·로그인 불변.
의도하지 않은 부작용 후보: 줍기마다 짧은 마우스 스냅(+~30ms settle).
동의: 사용자 옵션 1. 결과: 구현.

---

## 2026-10-02 — 공격 커서 미세 보정 →0타일

의도: 몬스터 조준 미세 보정 반경을 0으로 설정 (iscr/body + memory cell만).
공유 함수: `ATTACK_CURSOR_SEARCH_TILES`; `decision.yaml` `combat.cursor_search_tiles`.
영향: 공격 커서 탐색 링만. 루팅·이동·HP 불변.
동의: 사용자 지정(0). 결과: 구현.

---

## 2026-10-02 — 던전: 세계수 HP/MP 풀 후 항상 물약 상점 (B)

의도: 세계수 `recharge`에서 `vitals_full_at_mother_tree`까지 대기한 뒤,
물약 보충 필요 여부와 무관하게 **항상** `needs_potion` + `tick_shop_trip`.
공유 함수: 던전 패치 `_tree_tick`만. 메인 `_tick_mother_tree_retreat` 불변.
영향: Start Dungeon Combat 세계수→상점. 전투/루팅/로그인 불변.
동의: B. 결과: 구현.

---

## 2026-10-02 — 공격 커서 미세 보정 →0.03타일

의도: 몬스터 조준 미세 보정 반경을 0.03타일로 설정.
공유 함수: `ATTACK_CURSOR_SEARCH_TILES`; `decision.yaml` `combat.cursor_search_tiles`.
영향: 공격 커서 탐색 링만. 루팅·이동·HP 불변.
동의: 사용자 지정(0.03). 결과: 구현.

---

## 2026-10-02 — print_state에서 AttackAction 제거 (롤백)

의도: print_state를 AttackAction 이전 버전으로 되돌림.
AttackAction/attacks_me는 `attacks_me.dll`만 담당.
공유 함수: `print_state.c` 필드 제거; `entity_offsets.txt` ATTACK_*/ENT_GUID
제거; 관찰은 `AttacksMeReader` + `world.last_attacks_me`.
영향: print_state JSON에 attacks_me 없음. 전투 정책 불변.
동의: 사용자 요청(롤백). 결과: 소스 롤백·`.new.dll`/`.exe` 빌드.
`print_state.dll` 교체는 Manmabot 잠금 시 수동 copy 필요.

---

## 2026-10-02 — attacks_me 전용 DLL (관찰만)

의도: combat_attack AttackAction(tgt==meGuid)을 print_state와 분리된
전용 DLL로 읽어 JSON으로 노출. 전투/블랙리스트 우회는 아직 없음.
공유 함수: `analysis/combat_attack/attacks_me.c` + `attacks_me.dll`;
`app._03_world.attacks_me_reader.AttacksMeReader`.
영향: 분석/관찰 경로만. decision/이동/HP 불변.
동의: 1단계 전용 DLL. 결과: 빌드 성공.

---

## 2026-10-02 — dungeon combat: blocked 칸 → 근처 walkable 클릭 (A)

의도: Start Dungeon Combat만. 맵 blocked 칸에 있으면 A* 불가로
IDLE 고착되던 문제. 언스틱/TP/스크롤 재활성 없이, origin이
unwalkable일 때만 반경 2→3 walkable 타일로 걷기 클릭.
공유 함수: 엔진 본문 미변경. `dungeon_combat_gui._try_dungeon_blocked_step`
+ `tick_mode` 패치. `walkable_around` 재사용.
영향: Start Dungeon Combat만. 전체 이동 언스틱·confined·HP 스크롤 불변.
부작용 후보: blocked에서 전투보다 한 틱 먼저 스텝 클릭.
동의: A only. 결과: 구현.

---

## 2026-10-02 — 공격 커서: 메모리 주변 0.05타일 링

의도: 몬스터 커서 검사를 iscr/body·메모리 칸만이 아니라 **0.05타일**
분수 링까지 돌려, 실제 몬스터 조준 오탐 reject를 줄임. 태어나기 전
고스트는 여전히 5연속 FAIL 후 give-up.
공유 함수: `object_attack_screen_points` → `ATTACK_CURSOR_SEARCH_TILES`;
`decision.yaml` `combat.cursor_search_tiles: 0.05`.
영향: 기사/엘프/마법 공격 조준만. 루팅 F4·이동·HP·로그인 불변.
동의: 예. 결과: 구현.

---

## 2026-10-02 — 세계수: 라이브 핫바 확인 후 사용

의도: `mother_tree`를 텔레포트와 같이 라이브 핫바에 있을 때만
사용 가능으로 보고, 던전 UI hotbar 칸에도 role을 표시.
공유 함수: `mother_tree_on_live_hotbar`; `elf_uses_mother_tree(state, blackboard)`.
영향: 엘프 세계수 후퇴(메인·Start Dungeon Combat). 핫바에 없으면 상점 등으로 폴백.
동의: 스냅 있으면 핫바 필수, 미읽힘이면 프로필 슬롯 허용. 결과: 구현.

---

## 2026-10-02 — 줍기: 클릭/커서 검사 임시 OFF (F4만)

의도: 성능 확인 전까지 아이템 클릭·NORMAL 커서 게이트를 끄고 F4만.
공유 함수: `ActionExecutor._loot`의 `LOOT_PICKUP_USE_F4=True` 임시 분기.
클릭 경로는 코드에 남겨 둠(False로 복구 가능). 성능 좋으면 클릭 분기 삭제.
영향: 루팅 실행만. 접근·PICKUP emit·메모리 await 불변.
동의: 예 (임시 disable). 결과: 구현.

---

## 2026-10-02 — dungeon combat: HP탈출 토킹스크롤 OFF

의도: Start Dungeon Combat만. HP escape용 talking scroll 끄기.
상점 출동/복귀 스크롤과 기존 TP 계단·≤30% 트리/상점은 유지.
공유 함수: 엔진 본문 미변경. `dungeon_combat_gui` 패치 —
`_force_safe_scroll_if_due` no-op, `safe_zone` execute 차단,
`arm_hp_escape_fallback` none, `_maybe_retreat_talking_scroll`이
HP-safe/spellbook purpose만 차단.
영향: Start Dungeon Combat만. 메인 exe 불변.
동의: 사용자 요청(HP escape only OFF). 결과: 구현.

---

## 2026-10-02 — 던전 path>30 스킵 사유 UI 표시

의도: A* 경로가 30 초과로 새 대상을 스킵할 때 정확한 사유
(`path>30:N` / `path>30:blocked`)를 던전 전투 GUI·디버그 스냅샷에 표시.
공유 함수: `path_cap_skip_reason` / `path_cap_skips` / `_filter_dungeon_path_cap`.
영향: UI·로그 가시성만. 스킵 정책(던전·새 대상·30타일) 불변.
결과: 구현.

---

## 2026-10-02 — no-intent IDLE: why/trying 진단 reason

의도: `no behavior produced an intent`만으로는 부족. IDLE fallback reason에
당시 하려던 행동(`trying`/mode/goal/purpose/nav)과 emit 실패 원인(`why`),
핸드오프 이력을 넣음. 클릭 선택 자체는 불변(여전히 IDLE).
공유 함수: `Blackboard.note_no_intent`; `DecisionManager._no_intent_reason`;
`emit_travel_hop` miss 태그; `tick_traveling` 도착/포기 breadcrumb.
영향: decision 로그·UI reason 문구만. 이동/전투/HP/로그인 분기 불변.
동의: 사용자 요청(진단). 결과: 구현.

---

## 2026-10-02 — 아이템 포기: 줍기 miss → 이전 커서 4회 복원

의도: 아이템 soft-skip을 다시 **커서 연속 FAIL 4회**(`CURSOR_VERIFY_FAIL_GIVE_UP_ITEM`)로.
줍기 후 메모리 잔류 miss 카운트/`loot_pickup_miss_streak` 제거.
공유 함수: `note_cursor_verify_fail`(아이템 분기); `loot_awaiting_memory_gone` /
`mark_loot_clicked`를 이전 await 동작으로.
영향: 루팅 포기만. 몬스터 커서 5회→160틱·min_score 0.8 유지.
동의: 예 (명시 복원 요청). 결과: 구현.

---

## 2026-10-02 — dungeon combat: TP −5% 계단 + ≤30% 월드트리/물약상점

의도: Start Dungeon Combat만. 텔레포트는 사용자 %에서 1회 후 −5%씩
재사용, HP가 설정값 위로 회복되면 계단 리셋. HP≤30% 고정에서 물약 보충이
필요하면 월드트리(가능 시)→풀 회복 후 물약 상점, 불가 시 바로 상점.
상점 UI(restock/limit/buy qty/NPC)는 메인 Fix/Return과 동일 필드.
공유 함수: 엔진 본문 미변경. `dungeon_combat_gui` 패치 —
`_hp_action_availability` / `_execute_hp_action` / `apply_hp_actions` /
`_tick_mother_tree_retreat`. 상점·post-shop 복귀는 패치하지 않음(경로 허용).
영향: Start Dungeon Combat만. ManmabotV1.exe 불변.
부작용 후보: 던전에서 상점 스크롤·복귀가 다시 켜짐. 트리 후 마법서 상인 대신
물약 상점. TP가 더 자주/깊게 나갈 수 있음.
동의: A 범위 + 30% 고정 + 회복 후 리셋 + 메인형 상점 UI + 트리/상점 허용.
결과: 구현.

---

## 2026-10-02 — 커서 min_score 0.8 + 몬스터/아이템 포기 5회

의도: 커서 매칭을 더 엄격히(0.72→0.8). 같은 몬스터 id 커서 FAIL 연속 5회면
~160틱 give-up. 아이템은 커서 streak 포기 제거 → 근처 줍기 클릭 후 메모리에
남아 있으면 miss 1회, 5회면 짧은 loot 쿨다운 abandon.
공유 함수: `CursorMatcher.min_score`; `note_cursor_verify_fail`(+`give_up_target`);
`loot_awaiting_memory_gone` / `note_loot_pickup_miss` / `mark_loot_clicked`(재클릭이
await 타이머를 연장하지 않음).
영향: 전투 커서 게이트·give-up; 루팅 포기 기준. 이동/로그인/HP/후퇴 불변.
부작용 후보: 정상 공격도 FAIL↑; 몬스터 빨리 포기; 아이템은 클릭 안 되면 miss 미증가.
동의: 예 (명시). 결과: 구현.

---

## 2026-10-02 — 던전: 새 공격/루팅 대상 A* 경로 >30 스킵

의도: 던전에서 **새** 몬스터/아이템을 고를 때만, A* 경로 걸음 수가
`DUNGEON_ENGAGE_MAX_PATH_TILES`(30) 초과면 그 대상으로 가지 않고 현재 행동 유지.
공유 함수: `dungeon_new_engage_path_ok`; `list_attackable` / `list_lootable` 필터.
영향: 던전 새 전투·루팅 후보만. 스티키 전투/루팅, 섬(비던전) 불변.
부작용 후보: 우회가 긴 가까운 몹/아이템도 스킵; A* 호출 증가(새 후보만).
동의: 새 대상만 + 던전만. 결과: 구현.

---

## 2026-10-02 — HP 핫바: cfg id + 이름 필드 개별 매칭

의도: 라이브 핫바에 `상쾌한 빨간 물약`이 있어도 UI/엔진이 `no hotbar`로 나오던 버그 수정.
원인: (1) hotbar_listen은 템플릿 id를 `cfg`에 두고 `uid`는 인스턴스인데,
코드가 `uid`를 catalog id로 읽음. (2) `name`+`label`을 한 문자열로 붙여
exact fold 매칭이 실패.
공유 함수: `find_hp_restore_hotbar` / `discover_live_item_ids` /
`_live_catalog_id` / `_any_name_matches` (`hp_actions.py`);
수량 판정 `_hp_item_count`도 동일 매칭으로 맞춤.
영향: HP 물약 핫바 인식·수량·사용. 전투/이동/후퇴 정책 불변.
결과: 구현. 라이브 슬롯(box2/f9, cfg=20487)에서 재현 후 수정 확인.

---

## 2026-10-02 — HP: 상쾌한 빨간 물약 별칭 제거, DB 직접 매칭

의도: `_HP_EXTRA_ALIASES`(빨간 물약→상쾌한…) 제거. 핫바/가방 이름을
`item.json` 행과 직접 매칭. 한글/중문 리스트에 `상쾌한 빨간 물약` /
`清爽紅色藥水` (id 20487, 회복량 options) 등록.
공유 함수: `list_hp_restore_items` / `hp_restore_item` / `HpRestoreItem.aliases`.
영향: HP 물약 이름·id 매칭. `빨간 물약`은 더 이상 상쾌한을 포함하지 않음.
부작용 후보: 예전에 빨간 물약 행만으로 상쾌한을 쓰던 설정은 가방에서
`상쾌한 빨간 물약`을 따로 추가해야 함.
결과: 구현.

---

## 2026-10-02 — dungeon combat: 기본 빨간 물약 행 제거

의도: 던전 HP UI 기본값에 물약(상쾌한/빨간)을 넣지 않음. 회복 아이템은
가방에서 사용자가 추가. 카탈로그 정식 키는 `빨간 물약`이며 `상쾌한 빨간 물약`은
라이브/이벤트 별칭만.
공유 함수: `dungeon_combat_gui._finalize_dungeon_hp_actions` / `_load_dungeon_hp_actions`
만. 엔진 `default_hp_actions`(메인 스케줄 기본 빨간 물약) 불변.
영향: Start Dungeon Combat HP UI·`dungeon_combat_hp.json`만.
결과: 구현. 기존 저장의 시드 물약 행은 `potion_default_cleared` 마이그레이션으로 1회 제거.

---

## 2026-10-02 — dungeon combat: 힐 복원 + 토킹스크롤 % 제거

의도: Start Dungeon Combat HP를 메인 Fix/HP와 동일하게 — 물약·힐·텔레포트는
사용자 순서·%·ON/OFF. 월드트리는 던전에서 제외. 토킹스크롤은 사용자 % 없음,
힐 스킬+회복 아이템이 수량/MP로 불가일 때만 자동. 실시간 `[던전HP]` 상세 로그.

공유 함수: 엔진 본문 미변경. `dungeon_combat_gui._install_dungeon_hp_policy`가
`_hp_action_availability` / `_execute_hp_action` / `_force_safe_scroll_if_due` /
`apply_hp_actions`만 프로세스 한정 래핑. `begin_retreat`·`apply_inplace_hp_support`
직접 수정 없음. TP→스크롤 escalate·unstick·confined는 기존처럼 끔.

영향: Start Dungeon Combat만. ManmabotV1.exe / 메인 스케줄 불변.
부작용 후보: 힐이 다시 나가 물약보다 앞이면 힐 우선. 스크롤이 빨간 물약만이 아니라
힐+모든 회복 아이템 소진 기준. 로그 빈도(1초 스로틀 + 실행 시 즉시).

결과: 동의 후 구현.

---

## 2026-10-01 — 루팅: 시야여도 30타일 이상이면 제외

의도: 화면에 보여도 Chebyshev ≥30이면 줍지 않음 (경로 탐색 없음).
공유 함수: `loot_within_engage_tiles` / `list_lootable` / `loot_in_view`;
sticky도 동일 캡으로 포기 (`continue_or_start_loot`).
설정: `LOOT_ENGAGE_MAX_TILES` / `farm.loot_engage_max_tiles` (기본 30).
영향: 사냥·던전 루팅. 이동·전투·HP·로그인 불변.
부작용 후보: 먼 드롭은 다가간 뒤에야 후보가 됨.
결과: 동의 후 구현.

---

## 2026-10-01 — dungeon combat: 전체 아이템 / 아데나만 토글

의도: Start Dungeon Combat에서 루팅 모드를 UI로 선택.
공유 함수: 엔진 본문 미변경. `_make_profile`의 `loot_mode`만 연결·저장.
영향: 던전 전투 루팅만. 이동·전투·HP 규칙 불변.
결과: 구현.

---

## 2026-10-01 — HP 아이템: 카탈로그 id ≠ 실기 id 시 동적 매칭

의도: 이벤트팩 등 id가 카탈로그와 다를 때 하드코딩 id 대신
핫바·인벤 스냅샷의 **정확한 이름**으로 매칭하고, 그 이름에서 id를 수집해 재사용.
공유 함수: `item_match_sets` / `discover_live_item_ids` / `find_hp_restore_hotbar` /
`_hp_item_count`; `hp_restore_live_name_aliases` (카탈로그 고정 pack id 제거).
영향: 사냥·던전 HP 물약 사용/카운트. 이동·후퇴·로그인 불변.
부작용 후보: 카탈로그 키(`빨간 물약`)는 기존처럼 별칭으로 이벤트명을 찾을 수 있음.
결과: 구현.

---

## 2026-10-01 — 상쾌한 빨간 물약 이름/id 매칭

의도: 실기 아이템명 `상쾌한 빨간 물약`(id 20487)을 빨간 물약 회복 행과 동일 취급.
공유 함수: `game_catalog` aliases/extra ids; 던전 HP 키 마이그레이션.
영향: 핫바/가방 카운트·사용 매칭. 전투 이동 규칙 불변.
결과: 이후 동적 이름 매칭으로 대체(고정 20487 제거).

---

## 2026-10-01 — dungeon combat: HP 물약·텔레포트·두루마리 정책

의도: 던전에서 힐 스킬 무시, 텔레포트는 %만, 두루마리는 빨간 물약 0개일 때만,
텔레포트 후 두루마리 escalate 금지.
공유 함수: 엔진 본문 미변경. `dungeon_combat_gui` 패치로
`_hp_action_availability` / `_execute_hp_action` / `_force_safe_scroll_if_due` /
`maybe_escalate_teleport_to_safe`만 오버라이드.
영향: Start Dungeon Combat만. ManmabotV1.exe 불변.
결과: 구현.

---

## 2026-10-01 — dungeon combat: 13초/5타일 confined TP 끔

의도: 던전 전투에서만 5타일 내 13초 정체 시 텔레포트 제거.
공유 함수: 엔진 본문 미변경. `dungeon_combat_gui` 패치로
`_maybe_confined_escape`→none, `try_confined_escape`→false.
영향: Start Dungeon Combat만. ManmabotV1.exe / 메인 스케줄 불변.
결과: 구현.

---

## 2026-10-01 — dungeon combat: HP % UI + talking scroll HP 탈출만

의도: 던전 전투에 heal/물약/teleport/talking scroll %·우선순위 UI; 세계수 없음; scroll은 HP 탈출만.
공유 함수: `talking_scroll_available` 패치 제거(실슬롯 유지). `_maybe_scroll_to_hunt_map` /
`_maybe_post_shop_farm_return` / `_maybe_post_respawn_spellbook`만 none. `apply_hp_actions` 경로는
프로필 `hp_actions`로만 문턱 적용(로직 분기 추가 없음). `mother_tree`는 시작 프로필에서 enabled=False.
영향: `dungeon_combat_gui` + `UserData/dungeon_combat_hp.json`. 메인 스케줄 UI 불변.
부작용 후보: 다른 스크롤 호출부가 패치 목록에 없으면 열릴 수 있음 — 현재 사냥/상점/리스폰 진입점 차단.
결과: 구현. 동의: scroll=HP 탈출만.

---

## 2026-10-01 — 무게 게이지 baseline 50% → 80%

의도: Fix/Return 무게 게이지 기본·저장값을 80%로.
공유 함수: `needs_sell` / `SELL_WEIGHT_RATIO` (상점 출발 문턱만).
영향: profile·schedule 기본값, `sell_weight_ratio`. HP·로그인·이동 규칙 불변.
결과: 구현. 기존 50% 저장값도 80%로 맞춤.

---

## 2026-10-01 — dungeon combat: decision action + cursor check fail 표시

의도: Session 패널에 mouse 줄과 같이 현재 decision action·커서 검증 실패(streak)를 보이게.
공유 함수: 없음 (snapshot 필드·GUI 포맷만). 클릭/커서 게이트 불변.
영향: `debug_snapshot` decision/action_result, `dungeon_combat_gui` Session 텍스트.
결과: 구현.

---

## 2026-10-01 — dungeon combat: 실제 마우스 결과 + 왼쪽 스크롤

의도: Session preview에 decision intent가 아닌 execute 후 실제 click/hover 표시; 왼쪽 패널 스크롤.
공유 함수: `ActionExecutor.execute`에 `last_mouse_outcome`만 기록 (클릭 조건 불변). snapshot `action_result`.
영향: dungeon combat GUI·debug snapshot. 전투/이동/HP 규칙 불변.
결과: 구현.

---

## 2026-10-01 — 던전 벽 가림: 포기 목록에 넣지 않음 (동의: 구현 요청)

의도: 벽에 가려 공격 불가인 동안만 스킵하고, LOS가 열리면 다시 선택 가능하게.
공유 함수: `continue_or_start_combat` (던전 분기). `give_up_target` 호출 제거 → sticky clear만.
영향: 던전 사냥/던전 전투 툴. 섬 맵 우회·unstick 불변. HP·로그인 불변.
부작용 후보: 같은 tick에 LOS 없는 몹을 sticky로 다시 잡을 수 있음 — `nearest_attackable`의 `can_engage_target` 필터로 완화.
결과: 구현. reason `dungeon wall/fence` give-up 경로 제거.

---

## 2026-10-01 — dungeon combat: 정지 중에도 맵/엔티티 렌더

의도: 봇 Stopped여도 nav 맵·플레이어·엔티티 표시를 계속 갱신.
공유 함수: 없음 (GUI 전용 `_IdleWorldFeed` + `LiveEntitySweep` poll). 의사결정/이동/전투/HP 불변.
영향: `debug_tools/dungeon_combat_gui.py`만. Start 전에 idle sweep close, Stop 완료 후 재개.
부작용 후보: print_state.dll 이중 open 방지 실패 시 시작 실패 — handoff로 완화.
결과: 구현.

---

## 2026-10-01 — give-up 관측 (동의: dungeon combat panel)

의도: 임시 give-up(잠시 공격 안 함)을 id / reason / 남은 cooldown으로 보이게 함.
공유 함수: `give_up_target` (reason kwarg + scratch history만 추가, 포기 조건 불변).
영향: combat 로그·debug snapshot·dungeon combat GUI. 타겟 선택 타이밍 변화 없음.
구현: call site reason 전달; snapshot `give_ups` / `last_give_up`; GUI 세션·맵 표시.
결과: 대기 중 사용자 확인.

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

### CN59 — 2026-09-30
요청: 던전 전투는 시야(직선 LOS) 있는 적만 공격. 클릭 가능/화면 안이어도 벽 너머면 불가. 섬은 보류—제약 검증 후 적용.
고지한 영향: `can_engage_target` 던전 분기만 (LOS 필수 + click-range 또는 A*). `list_attackable`/스티키 게이트 동일. 섬 A*/인접 벽 우회 유지. HP·로그인·이동 공유 가드 추가 없음.
사용자 동의: 예 (“dungeon first”)
구현: dungeon `if not los: False; return in_range or path_ok`. 테스트 3건 추가.
결과(실기/테스트): `test_combat_focus` dungeon LOS 게이트.
악순환 여부: 던전만 조임. 섬은 기존. 새 플래그 없음.

### CN60 — 2026-09-30
요청: 던전 travel 클릭 ≤2타일; 던전에서 combat wall detour 금지. 섬 유지.
고지한 영향: `DUNGEON_MAX_HOP_TILES` 4→2 (`plan_travel_click` 자동 캡). `try_combat_wall_detour` 던전 early False. sticky가 LOS 불가 시 give-up 후 다른 대상. HP·로그인·섬 detour 미변경.
사용자 동의: 예 (“dungeon only”)
구현: hop=2; unstick+mode_actions 던전 no-detour give-up.
결과(실기/테스트): hop/detour 단위 테스트.
악순환 여부: 던전만. 새 가드 플래그 없음.

### CN61 — 2026-09-30
요청: 9.30 정본에 맞춰 메모리 엔티티/핫바가 다시 읽히게 보정.
고지한 영향: 의사결정/HP/로그인/이동 코드 미변경. `print_state` 투영 상수 + `skill_offsets.txt` `HSD_ADJ`만 정본화.
  - 투영: `PPS=0.53`, `VP_DX=+1.8`, `VP_DY=63.0`, `ANCHOR_DV=0` (self≈401,237)
  - 핫바: `HSD_ADJ=0x18` (`sub[30]+0x18` 컨테이너)
사용자 동의: 예 (“yes, plz … fully be working properly again”)
구현: `settings_print_state.json`, `entity_offsets.txt`, `print_state.c`(기본값+TXT `VP_DX/VP_DY` 파싱), `Hotbar/skill_offsets.txt`. console exe + `print_state.dll` 재빌드.
결과(실기/테스트): 콘솔 `print_state.exe`로 self 화면≈(401,237)·entities on-screen 확인 후 봇 재시작. (대기)
악순환 여부: 공유 가드/플래그 추가 없음. hybrid가 빈 memory 리스트를 쓰던 원인(잘못된 화면좌표)만 제거.

### CN62 — 2026-09-30
요청: `analysis/modify`는 엔티티가 나오는데 production `print_state`는 0건 — modify 방식으로 맞춤. 워크플로/의사결정 로직 유지.
고지한 영향: `print_state` 셀맵 HEAD 해석 + MGR guard만. hybrid/vision/HP/로그인/이동 미변경.
  - modify: `sent=*(actor+HEAD+8)` 이므로 HEAD=`798,7D8` (+8 → 9.30 sentinel `7A0/7E0`)
  - production이 `MAP_HEADS=7A0,7E0`로 두어 +8이 sentinel을 빗나감 → entities=[]
  - MGR guard(+0xD8==1) hard-fail 제거 (modify/enttrack과 동일)
사용자 동의: 예 (“if so, let's update current our code… keeping … workflows”)
구현: `entity_offsets.txt` `MAP_HEADS=798,7D8`; `print_state.c` 기본 HEAD + guard soft; DLL/EXE 재빌드.
결과(실기/테스트): `print_state --once` entity count 확인.
악순환 여부: 공유 가드/플래그 추가 없음. 엔티티 스윕만 복구.

### CN63 — 2026-09-30
요청: `analysis/modify1` 수준의 엔티티 데이터로 production 갱신. 위치는 `iscr`만 사용(`scr` 금지).
고지한 영향: `print_state` 이름/self/range + `memory_entities._entity_screen_xy`만. HP/로그인/이동 공유 가드 미변경.
  - 이름: len≥16 힙 역참조 + 제어문자 절단 (modify1)
  - self: MyPlayer vft 우선 + 타일 백업
  - range=0 무제한 셀맵 (modify1과 동일량)
  - 클릭 좌표: `iscr` only
사용자 동의: 예 (“check modify1… update entities… use iscr, not scr”)
구현: `print_state.c` / `settings_print_state.json` / `memory_entities.py`; DLL/EXE 재빌드.
결과(실기/테스트): `print_state --once` 엔티티 수·이름·iscr 확인.
악순환 여부: 엔티티 위치 소스만 `iscr`로 고정. 새 플래그 없음.

### CN64 — 2026-09-30
요청: 핫바 메모리 미동작 → `analysis/hotbar1` 확인 후 production 갱신.
고지한 영향: `hotbar_listen` / `skill_offsets.txt`만. 의사결정·HP·로그인·이동 미변경.
  - hotbar1 라이브 검증됨 (ITEM 슬롯↔인벤 cfg 조인)
  - production 깨짐: `HSD_ADJ=0`, HSD_VFT/VFT2 뒤집힘, walk=`header+8`, SSO를 length로 판정
사용자 동의: 예 (“if so, let's update current to the working one”)
구현: `skill_offsets.txt`=hotbar1 정본; `hotbar_listen.c` sentinel L/R walk + `V_CAP` SSO; DLL/EXE 재빌드.
결과(실기/테스트): `hotbar_listen.exe` OK — anchor `adj=0x18`/`hsd_vft=0x1183010`; slot0 ITEM `상쾌한 주홍 물약 (59)` cfg=20488.
악순환 여부: 핫바 읽기만. 새 가드 플래그 없음.

### CN65 — 2026-09-30
요청: hotbar1이 정상 데이터이므로 production 핫바 읽기만 정합 (기타 구현/로직 유지).
고지한 영향: `hotbar_listen` map walk + `N_PARENT`만. JSON 24슬롯/box/key/DLL·봇 로직 미변경.
  - hotbar1: `root = header+N_PARENT` 후 전체 트리 walk
  - production 오류: `_Left/_Right`에서 시작해 트리 일부만/왜곡 수집
사용자 동의: 예 (“update current hotbar reading, while keeping current other implementation”)
구현: `N_PARENT` 로드; walk 진입을 hotbar1과 동일; `isHeap(node)` 가드; DLL/EXE 재빌드.
결과(실기/테스트): 라이브 정합 — 양쪽 n=24, slot0 ITEM `상쾌한 주홍 물약 (59)` cfg=20488 uid=4421601 등 전 슬롯 type/cfg/uid 일치. production JSON(box/key/label) 형식 유지.
악순환 여부: 핫바 map walk만. 새 플래그 없음.

### CN66 — 2026-09-30
요청: 메모리 엔티티가 정상이므로 농장 YOLO/이미지 인식 제거(로그인·상점 UI 비전 유지). Phase 1.
고지한 영향:
  - `memory.entity_source: memory` 기본 + `decision_rows` / `needs_entity_vision`
  - memory 모드에서 `vision.process`·`sync_vision_region` 스킵
  - 스윕 실패 시 마지막 엔티티 목록 hold (vision 대체 없음)
  - `entity_level_fallback` memory 모드에서 강제 false
  - 공유: `try_unstick_escape` / `begin_retreat` / HP / 로그인 / 상점 UI 미변경
  - Decision·전투·이동 로직은 handoff 계약 유지 (이름만 vision인 API 유지)
사용자 동의: 예 (“yes, let's update”)
구현: `memory_entities.py`, `bot_controller.py`, `memory.yaml`, `tests/test_memory_entities.py`
결과(실기/테스트): (대기) unit `test_vision_source_is_kept_when_hybrid_sweep_fails` 확장
악순환 여부: entity_source 값 `memory` 추가·기본 전환만. 새 전투/HP 가드 플래그 없음.

### CN67 — 2026-09-30
요청: Phase 1 실기 OK 후 Phase 2 — 농장 YOLO/ResNet 기동 로드 생략.
고지한 영향:
  - `VisionSystem(load_models=False)` / `ensure_models_loaded` / deferred `set_region`
  - `bot_controller`가 `entity_source=memory`이면 가중치 미로드
  - talking_scroll `set_region`은 리전 키만 기록 (가중치 로드 없음)
  - 로그인/상점 UI·커서·capture/preview·Decision/HP/이동 미변경
사용자 동의: 예 (“all checked properly. let's step to the next.”)
구현: `vision_system.py`, `bot_controller.py`, `memory.yaml` 주석
결과(실기/테스트): (대기) 기동 로그 `Farm vision models not loaded`
악순환 여부: 로드 스킵 플래그만. 전투/HP 가드 추가 없음.

### CN68 — 2026-09-30
요청: Phase 3 — 비전 이름 스키마를 perception handoff로 정리 (동작 유지).
고지한 영향:
  - `handoff_to_perception` / `update_from_perception` / `entities_to_handoff` 정본
  - 구이름 `vision_to_perception` / `update_from_vision` / `entities_to_vision` 별칭 유지
  - converter 필수 키 `.get(..., 0)` 완화 (메모리 stub)
  - Decision/전투/HP/로그인/상점 로직 미변경
사용자 동의: 예 (“yes. once phase 3 is done…”)
구현: `converter.py`, `gamestate.py`, `memory_entities.py`, `bot_controller.py`, `__init__.py`, 주석
결과(실기/테스트): (대기) unit 회귀
악순환 여부: rename/alias만. 새 가드 플래그 없음.

### CN69 — 2026-09-30
요청: `_02_vision` 전체·weight_hud·미사용 농장 이미지 인식 제거 (로그인/상점/커서 유지).
고지한 영향:
  - `engine/app/_02_vision/*` 삭제; preview → `app/_03_world/preview.py`
  - bot 루프에서 VisionSystem / sync_vision_region / weight_hud 제거
  - entity 클릭 강제 memory; hybrid/vision 설정은 무시+로그
  - `vision.yaml`은 ObjectType conf 게이트만 유지; `regions.yaml` 삭제
  - 로그인 OCR/템플릿·상점 UV·커서 템플릿·capture 유지
  - Decision/HP/이동 공유 가드 미변경
사용자 동의: 예 (“no need engine/app/_02_vision… remove weight_hud…”)
구현: bot_controller, preview 이동, config, tests; 패키지 삭제
결과(실기/테스트): (대기)
악순환 여부: 농장 비전 경로 제거. 새 전투/HP 플래그 없음.

### CN70 — 2026-09-30
요청: 공격 커서 픽셀/0.2타일 링 hunt 제거. iscr/body에서 커서 없으면 클릭 스킵 → 다음 틱.
고지한 영향: `object_attack_screen_points` + `ATTACK_CURSOR_SEARCH_TILES=0` (knight/elf/royal/mage). 이동 링·상점 dialog·루팅 pile aim 유지.
사용자 동의: 예
구현: cursor_verify.py; player_mode/decision.yaml; tests.
결과(실기/테스트): test_attack_cursor_search / test_loot_stand 갱신.
악순환 여부: aim 실패↑ 가능, 틱 지연↓. 새 플래그 없음.

### CN71 — 2026-09-30
요청: 라이브 dead 정리 (다른 구현·워크플로 유지).
고지한 영향:
  - `inspect_hotbars` 미사용 화면스캔 인자 제거 (메모리 경로 유지)
  - `needs_entity_vision` 삭제; `decision_rows` memory-only; legacy hybrid/vision coerce
  - `align_memory_rows` / `LiveEntitySweep`에서 level_fallback 배선 제거
  - `fill_unleveled_from_vision`·IconMatcher·레거시 상점 템플릿·debug_tools·로그인/커서/UV 유지
  - Decision/HP/이동 미변경
사용자 동의: 예 (“yes. let's do 정리(live dead)”)
구현: inspect.py, memory_entities.py, bot_controller, memory.yaml, tests
결과(실기/테스트): (대기)
악순환 여부: 라이브 dead API만 축소. 새 가드 없음.

### CN72 — 2026-09-30
요청: 가방 메모리 20초 주기 스캔 제거. 필요한 경우에만 수동 읽기.
고지한 영향: 주기 `poll()` 가 스캔을 시작하지 않음. 시작 1회, 상점 여행 시작 1회, 구매/판매 성공 1회만 `force` 스캔. 판매 필터 Reload는 그대로. 사냥 중 물약/화살 개수는 그 읽기 전까지 마지막 가방을 씀. Decision/HP 클릭 경로는 그대로.
사용자 동의: 예 (이번 요청)
구현: inventory_listen_reader.py, bot_controller.py, memory.yaml
결과(실기/테스트): (대기)
악순환 여부: 새 플래그 없음. 상점 needs_* 는 가방 스캔이 끝난 뒤에만 갱신.

### CN73 — 2026-09-30
요청: decide의 섬 전체 A* 반복을 줄인다. 고르는 대상은 유지.
고지한 영향: screen_only는 경로 검색 전에 화면 밖을 뺀다. 같은 틱의 두 번째 몬스터 스캔은 이미 고른 대상을 쓴다. 클릭 사거리+시야 확보, 던전 벽은 검색 없이 기존과 같은 yes/no. 같은 플레이어 칸·몬스터 칸의 경로 yes/no는 재사용. 다이아몬드 범위 제한은 넣지 않음. 이동 홉 계획·HP·루팅 순서는 그대로.
사용자 동의: 예 (“yes”, 1–4)
구현: combat_query.py, mode_actions.py, tests/test_combat_focus.py
결과(실기/테스트): test_combat_focus, test_hunt_attack_settings 통과. 실기 대기.
악순환 여부: 새 가드 없음. 경로 답 캐시만 추가.

### CN74 — 2026-09-30
요청: 디버그 탭에 틱마다 A* 횟수, 각 검색 시간, 원인을 표시.
고지한 영향: `find_path`가 검색 루프를 돌면 한 줄을 기록한다. 반환 경로는 그대로. 막힌 칸·같은 칸은 기록하지 않는다. 이동·전투·HP 선택은 바꾸지 않음.
사용자 동의: 예 (디버그 탭 요청)
구현: astar_trace.py, pathfinding.py, bot_controller.py, debug_snapshot.py, schedule_i18n.py
결과(실기/테스트): (대기)
악순환 여부: 새 가드 없음. 표시만 추가.

### CN75 — 2026-10-01
요청: 결정 루프의 구성별 시간을 디버그 탭에 표시하고, 약 1000ms의 원인을 실기에서 확인.
고지한 영향: decide 동안 함수 소요만 기록한다. 고르는 행동·경로 결과는 바꾸지 않음. 5ms 미만의 중첩 단계는 표에서 숨긴다.
사용자 동의: 예 (디버그 탭에 구성 시간 요청)
구현: decide_spans.py, manager.py, mode_ticks.py, mode_actions.py, combat_query.py, travel.py, pathfinding.py, hierarchical_path.py, search_hop.py, bot_controller.py, debug_snapshot.py
결과(실기/테스트): test_debug_snapshot 통과. 실기 186틱에서 결정 시간은 7–192ms. 가장 큰 한 번은 복도 A* 161ms. 수색 틱은 몬스터 스캔 3회(각 약 50–70ms). 섬 전체 A*는 이번 실행에 없음.
악순환 여부: 새 가드 없음. 표시만 추가.

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
