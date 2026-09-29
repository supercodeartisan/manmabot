"""Read source + CODEX docs, write only CODEX evidence artifacts. No game access."""
import ast
from datetime import datetime, timezone
from html.parser import HTMLParser
import hashlib
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / 'docs'
FUNCTIONS = {
 'manmabot_v1/bot_controller.py': ['_run_bot_loop', '_commit_hotbar_scan'],
 'manmabot_v1/task_runtime.py': ['apply_runtime_settings'],
 'manmabot_v1/hp_actions.py': ['to_engine_actions', 'normalize_hp_actions'],
 'engine/app/_04_decision/manager.py': ['decide', 'apply_cursor_verify_feedback'],
 'engine/app/_04_decision/configure.py': ['configure_decision'],
 'engine/app/_04_decision/behaviors/mode_ticks.py': ['tick_mode','tick_farming','tick_traveling','tick_retreating','_tick_dungeon_farming','_maybe_return_on_vitals','_maybe_return_on_idle','_maybe_emergency_teleport','_maybe_confined_escape','_tick_newbie_training','_maybe_post_shop_farm_return','_maybe_low_mp_to_safe'],
 'engine/app/_04_decision/behaviors/mode_actions.py': ['apply_hp_actions','apply_inplace_hp_support','_hp_action_availability','_execute_hp_action','_can_teleport_now','can_active_hp_recover','farm_loot_or_combat','maybe_escalate_teleport_to_safe','_effective_loot_mode','_force_safe_scroll_if_due'],
 'engine/app/_04_decision/mode_control.py': ['begin_retreat','retreat_exit_ready','finish_retreat','update_death_timer','death_confirmed'],
 'engine/app/_04_decision/hp_actions.py': ['default_hp_actions','pick_hp_action'],
 'engine/app/_04_decision/shops.py': ['resolve_shopping_behavior_id','resolve_sell_behavior_ids','buy_qty_for_behavior','affordable_hp_potion_qty'],
 'engine/app/_04_decision/shop_trip.py': ['shopping_blocks_teleport','bag_weight_ratio','choose_shopping_behavior','tick_shop_trip','_at_shop'],
 'engine/app/_03_world/memory_inventory.py': ['inventory_state_from_snapshot','refresh_shop_needs_from_inventory'],
 'engine/app/_03_world/memory_sync.py': ['game_to_nav','player_from_snapshot'],
 'engine/app/_04_decision/combat_query.py': ['in_attack_click_range','object_on_screen','list_attackable','nearest_attackable','memory_target_gone','_is_adena'],
 'engine/app/_04_decision/behaviors/combat.py': ['rebind_sticky_target','continue_sticky_combat','advance_engage_or_give_up'],
 'engine/app/_04_decision/attack_feedback.py': ['note_cursor_verify_fail'],
 'engine/app/_04_decision/behaviors/unstick.py': ['try_unstick_escape','try_combat_blocked_unstick','try_enter_farm_detour','try_confined_escape','note_confined_progress'],
 'engine/app/_04_decision/behaviors/travel.py': ['travel_arrived','start_travel','emit_travel_hop'],
 'engine/app/_04_decision/behaviors/loot_hop.py': ['mark_loot_clicked','loot_awaiting_memory_gone','tick_loot_item'],
 'engine/app/_04_decision/talking_scroll.py': ['emit_talking_scroll','apply_talking_scroll_arrival','farm_return_scroll_spot','player_on_selected_map'],
 'engine/app/_04_decision/spells.py': ['can_cast_spell','maybe_heal_after_teleport','due_buff','try_unstick_teleport'],
 'engine/app/_04_decision/hunt_area.py': ['rotate_reason'],
 'engine/app/_04_decision/species_rules.py': ['is_avoided_species','is_newbie_player'],
 'engine/app/_05_action/controller.py': ['execute','_shop_buy_arrows','_shop_run_behavior','_teleport'],
 'manmabot_v1/shopping/runtime.py': ['execute_calibrated_buy','execute_calibrated_sell'],
}

class Structure(HTMLParser):
    def __init__(self):
        super().__init__()
        self.ids = []
        self.links = []
        self.external = []
        self.presets = 0
        self.tabs = 0
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if 'id' in a: self.ids.append(a['id'])
        if tag == 'a': self.links.append(a.get('href',''))
        if tag in ('script','link','img'):
            url = a.get('src', a.get('href',''))
            if url.startswith(('http:', 'https:', '//')): self.external.append(url)
        if 'data-saved' in a and 'data-default' in a: self.presets += 1
        if a.get('role') == 'tab': self.tabs += 1

def main():
    html = (DOCS/'CODEX_전투로직구성도.html').read_text(encoding='utf-8')
    p = Structure(); p.feed(html)
    assert len(set(p.ids)) == len(p.ids), 'Duplicate HTML ids'
    assert p.tabs == 7 and p.presets > 80
    assert not p.external, 'Unexpected external asset'
    assert '\ufffd' not in html
    svgs = re.findall(r'<svg\b.*?</svg>', html, re.S)
    assert len(svgs) == 7
    for svg in svgs: ET.fromstring(svg)
    assert all((DOCS/link).is_file() for link in p.links), 'Missing document link'

    manifest = {}
    sections = []
    for path, names in FUNCTIONS.items():
        data = (ROOT/path).read_bytes()
        manifest[path] = hashlib.sha256(data).hexdigest()
        tree = ast.parse(data.decode('utf-8-sig'))
        lines = {n.name:n.lineno for n in ast.walk(tree) if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
        found = [f'  - `{name}`: {lines[name]}행' for name in names if name in lines]
        missing = [name for name in names if name not in lines]
        assert not missing, f'{path}: missing {missing}'
        sections.append(f'- [{path}](../{path})\n'+'\n'.join(found))
    extra = ['run.py','engine/config/decision.yaml','engine/config/memory.yaml','engine/app/_04_decision/player_mode.py', 'engine/app/_04_decision/farm_time.py','engine/app/_04_decision/behaviors/search_hop.py','engine/app/_03_world/world_coords.py','engine/app/_05_action/humanize.py','engine/app/_05_action/combat_strategies/elf.py','engine/app/_05_action/combat_strategies/knight.py','engine/app/_05_action/combat_strategies/mage.py','engine/app/_05_action/combat_strategies/royal.py','userdata/profile.json','userdata/shopping_behaviors.yaml', 'tests/test_hp_actions.py','tests/test_shop_trip.py','tests/test_combat_focus.py','tests/test_ground_loot.py','tests/test_loot_stand.py','tests/test_unstick.py','tests/test_dungeon_farming.py','tests/test_hunt_attack_settings.py','tests/test_buff_cadence.py','tests/test_weight_source.py']
    for path in extra:
        manifest[path] = hashlib.sha256((ROOT/path).read_bytes()).hexdigest()
    profile = json.loads((ROOT/'userdata/profile.json').read_text(encoding='utf-8'))
    keys = ['character','active_map','game_language','shop_locale','hp_actions','return_arrow_count','arrow_buy_qty','return_potion_count','hp_potion_buy_qty','hp_potion_npc','return_weight_above','loot_adena_weight_ratio','return_idle_seconds','abandon_seconds','farm_stays_s','teleport_surround_count']
    payload = {'author':'Codex','recorded_at_utc':datetime.now(timezone.utc).isoformat(),
               'scope':'Source hashes at evidence-generation time; not EXE/runtime certification',
               'source_sha256':manifest,'profile_subset':{k:profile.get(k) for k in keys}}
    (DOCS/'CODEX_분석스냅샷.json').write_text(json.dumps(payload,ensure_ascii=False,indent=2),encoding='utf-8')
    evidence = '''# [CODEX 작성] 코드 근거와 검증 기록

분석일: 2026-09-28 · [설명서](CODEX_전투로직설명서.md) · [구성도](CODEX_전투로직구성도.html)

## 범위와 한계

Python 실시간 루프, 상태 전이, HP/MP/상점/공격/루팅/막힘 복구와 관련 설정을 추적했다. 기존 설명서와 코드 주석을 보조 자료로 읽되 실제 조건식을 우선했다. 계정 비밀번호나 인증 정보를 문서에 복사하지 않았다. 실게임, EXE 빌드 일치, DLL 내부 정확성 및 NPC 착지는 검증하지 않았다.

다른 편집기와 같은 폴더를 사용하므로 소스 전체를 불변 스냅샷으로 잠그지는 않았다. 이 기록 생성 시점의 해시와 비민감 설정 일부는 [CODEX_분석스냅샷.json](CODEX_분석스냅샷.json)에 있다. 이후 Cursor에서 변경하면 해당 파일 해시가 달라질 수 있다. 줄 번호는 이 기록 생성 시점 기준이다.

## 기존 테스트 실행 결과

관련 10개 파일: **168 passed, 2 failed (총 170개, 9.76초)**.

```powershell
$env:PYTHONPATH = "$PWD\\engine;$PWD"
$env:PYTHONDONTWRITEBYTECODE = '1'
& .\\python\\python.exe -m pytest -p no:cacheprovider tests/test_hp_actions.py tests/test_shop_trip.py tests/test_combat_focus.py tests/test_ground_loot.py tests/test_loot_stand.py tests/test_unstick.py tests/test_dungeon_farming.py tests/test_hunt_attack_settings.py tests/test_buff_cadence.py tests/test_weight_source.py -q
```

실패:

- `test_combat_blocked_unstick_sweeps_around_click`: `try_combat_blocked_unstick(...) is True` 기대에 False 반환.
- `test_combat_blocked_unstick_resets_when_monster_moves`: `combat_block_tile` 키가 지워져 KeyError.

`test_unstick.py`만 단독으로 재실행: **25 passed, 2 failed (총 27개, 0.54초)**. 위와 동일한 두 사례다.

원인 추적: 테스트의 몬스터는 메모리 상대 거리가 10/12칸이지만 기본 화면 위치가 화면 안으로 분류된다. `in_attack_click_range()`의 화면 안 우선 True 분기 때문에 `try_combat_blocked_unstick()`가 시계를 지우고 조기 반환한다. 기대한 5초 우회 경로까지 가지 않는다. 따라서 다른 테스트 파일이 먼저 실행되어야 발생하는 현상은 아니다. 화면 안 대상 우선 정책 자체가 의도된 변경인지, 테스트를 고쳐야 하는지는 후속 합의가 필요하다. 이번에는 테스트나 런타임 소스를 수정하지 않았다.

## 입력 없는 조건 재현

실제 게임 객체 대신 메모리 수치만 가진 대체 객체를 만들어 함수 반환값을 확인했다. 게임 실행이나 마우스·키보드 입력은 없다.

- HP 99/100, MP 10/100, `retreat_for=return`: `retreat_exit_ready=True`.
- 같은 수치, `retreat_for=mp`: `retreat_exit_ready=False`.
- 몬스터 상대 위치 (12,0), 기본 화면 UV: `in_attack_click_range=True`.
- 같은 몬스터 화면 UV를 (2,2)로 화면 밖에 둠: `in_attack_click_range=False`.

이는 MP 후퇴 원인 구분과 화면 안 우선 분기가 실제 함수 반환에 영향을 준다는 증거다. 실게임 문제 원인의 확정이나 전체 시뮬레이션은 아니다.

## 구성도 검사

- 7개 탭, 7개 SVG의 XML 문법, HTML ID 중복, 기준값 전환용 데이터, 연결 문서 파일 존재, UTF-8 대체문자 부재, 외부 자원 의존성 부재를 정적으로 검사했다.
- 전체/사냥/HP/보급/전투·루팅/후퇴/이동·막힘의 7개 상세도를 제공한다.
- Node.js의 `new Function`으로 HTML 내 전환 스크립트의 JavaScript 문법 검사를 통과했다. DOM/렌더링 검증은 아니다.
- 저장 프로필/엔진 기본값 선택, 확대, 전체 인쇄 버튼이 포함된다. 엔진 기본값 보기는 현재 실행값을 의미하지 않는다.
- **브라우저 자동 보안 검토가 file:// 프로토콜 열기를 거부하여 실제 브라우저 렌더링·클릭 검증은 수행하지 못했다.** 정적 검사 통과를 화면 검증 완료로 해석하지 않는다.
- 재생성: `python/python.exe docs/CODEX_구성도생성.py`. 정적 검사 및 근거 갱신: `python/python.exe docs/CODEX_정적검증.py`. 이 도구들은 CODEX 문서 파일만 기록하며 게임을 시작하거나 입력하지 않는다. 과거 테스트 실행 결과는 자동 재실행하지 않는다. 구성도의 문구·분기·저장값은 분석 시점 내용을 수동으로 정의한 것이므로 소스나 프로필 변경 시 생성 도구의 데이터와 설명서도 함께 갱신해야 한다.

## 기존 설명서/주석과 다른 주요 지점

1. HP 행동 순서는 UI가 변경할 수 있다. 저장 순서는 힐→빨간 물약→텔레포트→안전지대→나무다.
2. 공격 커서 실패로 몬스터를 횟수 기반 포기하지 않는다. 4회 포기는 아이템에 적용된다.
3. 화면 안 몬스터는 8칸을 넘어도 클릭 가능 분기가 먼저다.
4. 무게는 메모리가 우선이다. HUD 전용으로 설명하면 잘못이다.
5. 이동 모드도 사냥터 진입/교대/순찰 목적이면 교전·루팅을 한다.
6. 현재 V1 시작은 별도 MP 후퇴를 강제로 끈다. Fix/Return MP 귀환과 구분해야 한다.
7. 막힘 탈출은 텔레포트 우선, 불가하면 두루마리다. 상점/전투에는 예외가 있다.
8. 사냥터별 3600초 설정, 무게 판매 30%, 화살 100/100, 물약 1/3은 YAML 기본값과 다르다.
9. 상점 성공 피드백은 구매 수량 증가가 아니라 UI 절차 완료 기준이다.
10. 전투 중 갇힘 검사 생략은 벽시계 자체 정지와 같지 않다.

## 함수별 코드 위치

'''+ '\n\n'.join(sections)+'\n'
    (DOCS/'CODEX_분석근거.md').write_text(evidence,encoding='utf-8')
    print(f'Static checks passed: {len(svgs)} SVGs, {p.tabs} tabs, {p.presets} preset text nodes, {len(manifest)} source hashes')

if __name__ == '__main__':
    main()
