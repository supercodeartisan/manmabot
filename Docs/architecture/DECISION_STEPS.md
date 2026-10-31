# Decision step catalog

목표: **모드 = 행동 칸의 열**. 열 순서의 코드 정본은
[`steps/columns.py`](../../Engine/app/_04_decision/steps/columns.py) +
[`run_column`](../../Engine/app/_04_decision/steps/runner.py).
핸들러 본문은 `mode_ticks` 어댑터가 맡는다. 이 Markdown은 접수·고지용 주소록이다.

규칙:

- `id` = `domain.action` (안정 문자열)
- `ActionType` = 정리된 19종 ([`enums.py`](../../Engine/app/_02_state/enums.py); `GATE` 포함)
- outcome: `pass` | `emit` | `handoff(<mode>)`
- prep = 열 밖 부수효과 (칸 번호 없음)
- 공유 칸은 여러 열에 같은 `id`로 재등장
- **id ≠ 틱 출력 1:1**. 틱 주 출력은 `ActionIntent` 하나; id는 그 틱을 이긴 칸. 물약(HP/MP/해독)과 줍기거리 `PICKUP`은 사다리를 이기지 않고 `blackboard.side_intents`로 같은 틱에 병행(F4는 주 Intent 전)
- `idle_kind` (IDLE을 낼 수 있는 칸): `wait` | `fail` | `gap` | `—` (비IDLE 주력)
  - `wait` = 조건 대기(정상일 수 있음)
  - `fail` = 경로/설정 실패로 IDLE
  - `gap` = nudge/blocked 간격 IDLE
  - 합성 IDLE(A2)은 칸이 아니라 `decide` — [ISSUE_idle_livelock.md](ISSUE_idle_livelock.md)

계층: [DECISION_HIERARCHY.md](DECISION_HIERARCHY.md)

---

## ActionType (의도 19종) — 칸이 낼 수 있는 것

| ActionType | 전형적인 칸 |
| --- | --- |
| `IDLE` | wait / fail / gap (아래 idle_kind) |
| `RESPAWN` | `survival.death` |
| `DISMISS_LEVEL_UP` | `ui.dismiss_level_up` |
| `HEAL` / `USE_HP_POTION` / `USE_MP_POTION` / `USE_DEPOISON` | `survival.hp`, `survival.inplace_hp`, `spell.support` |
| `TELEPORT` | `survival.emergency_tp`, `survival.hp`, `retreat.teleport` |
| `RETURN_TO_MOTHER_TREE` / `HP_TO_MP` | `retreat.mother_tree` |
| `USE_TALKING_SCROLL` | `nav.*`, `retreat.scroll`, `shop.*`, `world_nav.drive` |
| `GATE` | `world_nav.drive` (map_transition) |
| `BUFF` | `spell.buffs` |
| `SHOP_STOP` / `SHOP_RUN` | `shop.*` |
| `ATTACK` / `PICKUP` | `farm.engage`, `retreat.loot_if_clear`, world_nav walk overlay |
| `TRAVELING` | `travel.hop`, `retreat.walk_safe`, `world_nav.drive`, `shop.drive` (same-map walk) |
| `SEARCHING` | `farm.search`, unstick hops |

---

## Column `global` (`tick_mode` 접두)

| # | id | impl | typical ActionType | outcome | idle_kind |
| --- | --- | --- | --- | --- | --- |
| G1 | `survival.death` | `_maybe_death` | `RESPAWN`, `IDLE` | emit | wait |
| G2 | `ui.dismiss_level_up` | `_maybe_dismiss_level_up` | `DISMISS_LEVEL_UP` | emit | — |

이후 `PlayerMode`로 dispatch.

---

## Column `world_nav` (`tick_world_navigating`)

Sticky `PlayerMode.WORLD_NAV`. 진입: `begin_world_nav` / farming `nav.world`·`nav.hunt_map` handoff.

| # | id | typical ActionType | outcome | idle_kind |
| --- | --- | --- | --- | --- |
| 1 | `survival.death` | `RESPAWN`, `IDLE` | emit | wait |
| 2 | `survival.emergency_tp` | `TELEPORT` | emit | — |
| 3 | `survival.hp` | heal/… | emit / handoff retreating | — |
| 4 | `survival.mp_safe` | — | handoff retreating | — |
| 5 | `survival.return_vitals` | — | handoff retreating | — |
| 6 | `shop.trip` | `SHOP_*` / scroll / walk | **handoff SHOPPING** (request after_shop) | wait |
| 7 | `spell.support` | heal | emit | — |
| 8 | `spell.buffs` | `BUFF` | emit | — |
| 9 | `unstick.confined` | `TELEPORT`, `USE_TALKING_SCROLL`, `IDLE` | emit on a `walk` / `gate_approach` standstill; after the pose leaves, `request_world_nav` with the same reason | wait |
| 10 | `world_nav.drive` | `TRAVELING`, `USE_TALKING_SCROLL`, `GATE`, `IDLE`, walk→`ATTACK`/`PICKUP` | emit / handoff farming on arrive | wait |

게이트는 Intent `GATE` → `ActionExecutor._gate` → `apply_gate_result`. worker side-channel 없음.

---

## Column `shopping` (`tick_shopping`)

Sticky `PlayerMode.SHOPPING`. 진입: `begin_shopping` / farming·world_nav·traveling의 `shop.*` handoff / `PURPOSE_SHOP` 도착. 같은 맵 걷기는 `TRAVELING`으로 넘기지 않는다 (`start_travel` + `PURPOSE_SHOP` + hop).

| # | id | typical ActionType | outcome | idle_kind |
| --- | --- | --- | --- | --- |
| 1 | `survival.death` | `RESPAWN`, `IDLE` | emit | wait |
| 2 | `survival.emergency_tp` | `TELEPORT` | emit | — |
| 3 | `survival.hp` | heal/… | emit / handoff retreating | — |
| 4 | `survival.mp_safe` | — | handoff retreating | — |
| 5 | `survival.return_vitals` | — | handoff retreating | — |
| 6 | `shop.drive` | `SHOP_STOP`, `SHOP_RUN`(+kind/qty/equip), scroll, walk, `IDLE` | emit / leave→farming or `need_world_nav` | wait |

---

## Column `farming.island` (`tick_farming`)

| # | id | impl | typical ActionType | outcome | idle_kind |
| --- | --- | --- | --- | --- | --- |
| — | *(prep)* `farm.route_ensure` | `ensure_farm_tour` | — | pass | — |
| 1 | `survival.death` | `_maybe_death` | `RESPAWN`, `IDLE` | emit | wait |
| 2 | `survival.emergency_tp` | `_maybe_emergency_teleport` | `TELEPORT`, scroll | emit | — |
| 3 | `survival.hp` | `apply_hp_actions` | heal/potion/`TELEPORT`/… | emit / **handoff retreating** | — |
| 4 | `survival.mp_safe` | `_maybe_low_mp_to_safe` | — | **handoff retreating** | — |
| 5 | `survival.return_vitals` | `_maybe_return_on_vitals` | — | **handoff retreating** | — |
| 6 | `survival.return_idle` | `_maybe_return_on_idle` | — | **handoff retreating** | — |
| 7 | `shop.before_world_nav` | `_shop_before_world_nav` | `SHOP_*`, scroll, walk | **handoff SHOPPING** | wait |
| 8 | `nav.world` | `_maybe_world_nav` | scroll/gate/`IDLE`; walk→engage | emit | wait |
| 9 | `spell.support` | `_maybe_support_spells(buffs=False)` | `HEAL` 등 | emit | — |
| 10 | `spell.buffs` | `_maybe_support_spells(buffs=True)` | `BUFF` | emit | — |
| 11 | `unstick.confined` | `_maybe_confined_escape` | `TELEPORT`, scroll | emit | — |
| 12 | `farm.newbie` | `_tick_newbie_training` | scroll / travel | emit / handoff | — |
| 13 | `farm.post_respawn_spellbook` | `_maybe_post_respawn_spellbook` | scroll, `IDLE` | emit | wait |
| 14 | `farm.upkeep` | `_try_farm_upkeep` | — | handoff **traveling** | — |
| 15 | `farm.post_shop_return` | `_maybe_post_shop_farm_return` | nav request | emit / pass | — |
| 16 | `nav.hunt_map` | `_maybe_scroll_to_hunt_map` | scroll / world_nav | emit | — |
| 17 | `farm.engage` | `farm_loot_or_combat` | `ATTACK`, `PICKUP`, approach | emit | fail |
| 18 | `farm.enter` | `_enter_farm_if_needed` | `TRAVELING`, `IDLE` | emit / handoff traveling | fail |
| 19 | `farm.search` | `_search_inside_farm` | `SEARCHING`, `IDLE` | emit | fail |

---

## Column `farming.dungeon` (`_tick_dungeon_farming`)

| # | id | notes | idle_kind |
| --- | --- | --- | --- |
| 1 | `survival.death` | shared | wait |
| — | ~~`survival.emergency_tp`~~ | **off** | — |
| 2 | `survival.hp` | shared (+ dungeon_policy) | — |
| 3 | `survival.mp_safe` | shared | — |
| 4 | `survival.return_vitals` | shared | — |
| 5 | `survival.return_idle` | shared | — |
| 6 | `shop.before_world_nav` | shared | wait |
| 7 | `nav.world` | shared | wait |
| 8 | `spell.support` | shared | — |
| 9 | `spell.buffs` | shared | — |
| — | ~~`unstick.confined`~~ | **off** | — |
| — | ~~`farm.newbie`~~ | **off** | — |
| 10 | `farm.post_respawn_spellbook` | shared | wait |
| — | ~~`farm.upkeep`~~ | **off** | — |
| 11 | `farm.post_shop_return` | shared | — |
| 12 | `nav.hunt_map` | shared | — |
| 13 | `dungeon.off_floor` | `IDLE` if wrong floor | fail |
| 14 | `dungeon.blocked` | `try_blocked_step` → walk / `IDLE` | gap |
| 15 | `farm.engage` | shared | fail |
| 16 | `dungeon.patrol` | handoff traveling | — |
| 17 | `dungeon.idle_nudge` | `try_idle_nudge` | gap |

---

## Column `traveling` (`tick_traveling`)

| # | id | impl | typical ActionType | outcome | idle_kind |
| --- | --- | --- | --- | --- | --- |
| 1 | `survival.death` | shared | `RESPAWN`, `IDLE` | emit | wait |
| 2 | `survival.emergency_tp` | shared | `TELEPORT` | emit | — |
| 3 | `survival.hp` | shared | … | emit / handoff retreating | — |
| 4 | `survival.mp_safe` | shared | — | handoff retreating | — |
| 5 | `survival.return_vitals` | shared | — | handoff retreating | — |
| 6 | `routine.duration` | `_maybe_routine_duration` | — | **handoff WORLD_NAV** (row minutes up) | — |
| 7 | `spell.support` | shared | | emit | — |
| 8 | `spell.buffs` | shared | `BUFF` | emit | — |
| 9 | `unstick.confined` | shared | | emit | — |
| 10 | `shop.trip` | `_maybe_shop_trip` | `SHOP_*`, scroll, walk | **handoff SHOPPING** | wait |
| 11 | `travel.training_done` | purpose check | — | handoff farming | — |
| 12 | `nav.hunt_map` | enter/patrol only | | emit | — |
| 13 | `farm.engage` | enter/patrol only | `ATTACK`, `PICKUP` | emit | fail |
| 14 | `travel.push_deeper_farm` | retarget interior | `TRAVELING`, `IDLE` | emit | fail |
| 15 | `travel.arrive` | `complete_travel_arrival` | — | **handoff** (FAILURE) | — |
| 16 | `travel.hop` | `emit_travel_hop` | `TRAVELING` | emit | — |
| 17 | `travel.hop_fail` | clear → farming | — | handoff farming | — |

---

## Column `retreating` (`tick_retreating`)

| # | id | impl | typical ActionType | outcome | idle_kind |
| --- | --- | --- | --- | --- | --- |
| 1 | `survival.death` | inline / shared | `RESPAWN`, `IDLE` | emit | wait |
| 2 | `retreat.mother_tree` | `_tick_mother_tree_retreat` | tree, `HP_TO_MP`, scroll | emit | — |
| 3 | `retreat.exit` | `finish_retreat` | — | **handoff** (FAILURE) | — |
| 4 | `retreat.scroll` | talking scroll | `USE_TALKING_SCROLL` | emit | — |
| 5 | `retreat.teleport` | pending TP | `TELEPORT` | emit | — |
| 6 | `retreat.escalate_safe` | escalate | scroll | emit | — |
| 7 | `retreat.post_land_tree` | post-land tree | tree / … | emit | — |
| 8 | `spell.support` | no buffs | heal | emit | — |
| 9 | `survival.inplace_hp` | `apply_inplace_hp_support` | heal/potion | emit | — |
| 10 | `retreat.loot_if_clear` | loot if safe | `PICKUP` | emit | — |
| 11 | `retreat.walk_safe` | `emit_travel_hop` | `TRAVELING` | emit | — |
| 12 | `retreat.idle_emergency` | re-`begin_retreat` | `TELEPORT`, scroll, walk | emit | — |
| 13 | `retreat.wait` | recover idle | `IDLE` | emit | wait |

---

## Shared step index

| id | columns | idle_kind |
| --- | --- | --- |
| `survival.death` | global, all modes | wait |
| `survival.emergency_tp` | island, traveling | — |
| `survival.hp` | island, dungeon, traveling | — |
| `survival.mp_safe` | island, dungeon, traveling | — |
| `survival.return_vitals` | island, dungeon, traveling | — |
| `survival.return_idle` | island, dungeon | — |
| `survival.inplace_hp` | retreating | — |
| `shop.before_world_nav` | island, dungeon | wait |
| `shop.trip` | traveling, world_nav | wait |
| `shop.drive` | shopping | wait |
| `nav.world` | island, dungeon | wait |
| `world_nav.drive` | world_nav | wait |
| `nav.hunt_map` | island, dungeon, traveling(enter/patrol) | — |
| `spell.support` | island, dungeon, traveling, retreating | — |
| `spell.buffs` | island, dungeon, traveling | — |
| `unstick.confined` | island, traveling, world_nav | — |
| `farm.engage` | island, dungeon, traveling(enter/patrol) | fail |
| `farm.search` | island | fail |
| `farm.enter` | island | fail |
| `farm.upkeep` | island | — |
| `farm.newbie` | island | — |
| `farm.post_respawn_spellbook` | island, dungeon | wait |
| `farm.post_shop_return` | island, dungeon | — |
| `dungeon.off_floor` | dungeon | fail |
| `dungeon.blocked` | dungeon | gap |
| `dungeon.patrol` | dungeon | — |
| `dungeon.idle_nudge` | dungeon | gap |
| `travel.*` | traveling | fail on push_deeper; else — |
| `retreat.wait` | retreating | wait |
| `retreat.exit` | retreating | — (handoff; A2 risk) |
| `ui.dismiss_level_up` | global | — |

합성 IDLE / handoff livelock: [ISSUE_idle_livelock.md](ISSUE_idle_livelock.md) (B1–B7).

---

## 코드 위치

| 열 | tuple | tick 진입 |
| --- | --- | --- |
| `global` | `GLOBAL` | `tick_mode` 접두 (`require_terminal=False`) |
| `world_nav` | `WORLD_NAV` | `tick_world_navigating` |
| `shopping` | `SHOPPING` | `tick_shopping` |
| `farming.island` | `FARMING_ISLAND` | `tick_farming` |
| `farming.dungeon` | `FARMING_DUNGEON` | `_tick_dungeon_farming` |
| `traveling` | `TRAVELING` | `tick_traveling` → `_tick_traveling_column` |
| `retreating` | `RETREATING` | `tick_retreating` |

이긴 칸 id는 `blackboard.scratch["winning_step"]`에 기록된다.

## 아직 정하지 않은 것

1. `farm.route_ensure`를 prep으로 둘지 칸으로 승격할지  
2. `spell.support`+`spell.buffs` 합칠지  
3. ISSUE 해결 시 wait vs fail 화이트리스트·실패 토큰

열 순서가 코드와 다르면 `steps/columns.py`가 이긴다. 표만 고치면 런타임은 안 바뀐다.
