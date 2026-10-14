# UserData vs Engine data policy

작성: 2026-10-05  
상태: **문서만** (구현 보류). 작업은 추후 진행.

## 원칙

| 영역 | 보관 내용 |
|------|-----------|
| `UserData/` | 사용자가 **메인 UI**(또는 명시된 편집 UI)로 customize한 운영 설정만 |
| `Engine/data/` | 사용자가 경로를 몰라도 되는 제품 데이터·캘리브레이션·맵/카탈로그 |
| 로그·임시 | 설정이 아님. `UserData/logs` 등 runtime 위치에 두거나 별도 폴더로 묶을 수 있음 |

`session/paths.py`의 “Engine은 Version 1에서 읽기 전용” 문구는 위 원칙과 충돌한다.  
추후 정책을 **「카탈로그·캘리브는 Engine에 두고 쓸 수 있음 / 사용자 오버레이만 UserData」**로 맞출 것.

이미 이동됨: NPC 카탈로그 → `Engine/data/npc_behaviors.yaml` (buy/sell/warehouse/teleporter). `data/maps` 교체와 분리.

---

## 현재 UserData 분류 (2026-10-05 스냅샷)

### 유지 (UserData에 적합)

| 항목 | 이유 |
|------|------|
| `profile.json`, `profiles/` | 사냥/회복 등 UI 설정 |
| `schedules.json` | 스케줄 UI |
| `accounts.json` | 계정 UI |
| `maps/*/farms.yaml` | 맵 에디터 농장 사각형 |
| `maps/*/patrol.yaml` | 던전 패트롤 사용자 오버레이 (엔진 팩에 기본본 있음) |
| `window_icon.ico` | UI 자산 (선택) |

### Engine으로 옮길 후보

| 항목 | 이유 | 제안 위치 |
|------|------|-----------|
| `hotbar_slot_layout.json` | Hotbar Inspector 캘리브 → 라이브 매칭. 메인 UI 설정 아님 | `Engine/data/hotbar/` |
| `shop_sell_slot_layout.json` | Sell 슬롯 캘리브 | `Engine/data/shop/` |

로드 시 레거시 UserData 파일이 있으면 1회 이관하는 패턴을 `npc_behaviors`와 같이 쓰면 됨.

### 쪼개야 하는 것

| 항목 | 이슈 | 제안 |
|------|------|------|
| `npc_behaviors`의 `garbage_list` / `keep_list` | NPC 카탈로그는 Engine인데 Sell 탭에서 사용자가 keep/garbage를 고침 | **분리**: 카탈로그=Engine, `sell_filters.yaml`(가칭)만 UserData |
| `shop_sell_ui_prefs.json` | 툴 UI 마지막 선택 | `Tools/output` 또는 `UserData/prefs/` |
| `dungeon_combat_hp.json` / `dungeon_combat_ui.json` | 던전 전투 GUI 전용; 프로필 HP와 중복 가능 | 당분간 UserData 유지 가능. 장기적으로 profile/schedule과 통합 검토 |
| `defaults/profile.defaults.json` | 코드 기본값 미러 | Engine 또는 생성물; UserData 필수 아님 |

### 정리·삭제 후보 (설정 아님)

| 항목 | 제안 |
|------|------|
| `logs/`, `autologin_runs/` | 유지 가능. 원하면 `UserData/runtime/`로 묶기 |
| `accounts.locked-*.json` | 잠금/크래시 잔여 → 정리 정책 |
| `_hp_check.txt` | 디버그 잔여 → 삭제 |

---

## 추후 작업 순서 (미착수)

1. `paths.py` / `LAYOUT.md` 정책 문구 정리 (Engine 쓰기 허용 범위)
2. `sell_filters`를 UserData로 분리 (behaviors YAML에서 분리)
3. hotbar / shop sell slot layout → `Engine/data/...` + 레거시 이관
4. 툴 prefs (`dungeon_combat_*`, `shop_sell_ui_prefs`) 소속 명확화 또는 profile 흡수
5. locked accounts / `_hp_check.txt` 청소, UserData README에 허용 목록 명시

이 문서를 구현 착수 시 체크리스트로 쓴다.
