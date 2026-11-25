# CONFIG PROVENANCE — 11-25analysis

v39(26.11.10.2003) 근거가 있는 키만 갱신했다. 근거 없는 값은 **추정하지 않고 유지**한다.

## 1. 갱신 근거

모든 신규 값은 `registry/LC930_REGISTRY.txt`(v39)의 동일 의미 키에서 왔다.

| 파일 | 키 | 이전 (v38) | 신규 (v39) | 근거 키 |
|---|---|---|---|---|
| char_offsets.txt | `MGR` | 0x16EB6F0 | 0x1708750 | MGR |
| char_offsets.txt | `CD_VFT` | 0x11E5088 | 0x11FC560 | CD_VFT |
| char_offsets.txt | `VFT_STATUS` | 0x11E50F8 | 0x11FC540 | VFT_STATUS |
| entity_offsets.txt | `ACTOR_VFT` | 0x11DE3E8 | 0x11F5958 | VFT_ACTORSUBS (라이브 sub[22]) |
| entity_offsets.txt | `VFT_PRES_A/B` | 0x11DD728 / 0x11E1098 | 0x11F4BD8 / 0x11F8538 | VFT_PRES_A/B |
| entity_offsets.txt | `ACT_VFT` | 11E07C8 | 11F7C70 | VFT_AC |
| entity_offsets.txt | `ATTACK_ACT_VFT` | 11E0508 | 11F79B0 | VFT_ATTACKACT |
| entity_offsets.txt | `DEATH_VFT` / `DEADBODY_VFT` | 11E0310 / 11E03E8 | 11F7800 / 11F7890 | VFT_DEATH / VFT_DEADBODY |
| entity_offsets.txt | `PLAYER_X/Y` | 16EB5A0 / 16EB5A4 | 1708600 / 1708604 | PLAYER_X/Y (ST_BLOCK) |
| entity_offsets.txt | `PLAYER_HP…LEVEL` | 16EA0FC…16EA10C | 170860C…170861C | ST_BLOCK + ST_HP/MAXHP/MP/MAXMP/LEVEL |
| entity_offsets.txt | `CAM_GLOB` | 1886820 | 18B5E30 | CAM_GLOB (라이브 단일 히트) |
| entity_offsets.txt | `VFT_SELF/PLAYER/MONSTER/ITEM/SHIP/SUMMONED/ACTOR` | 11E13xx… | 11F8828/11F87F0/11F86E0/11F8638/11F8B00/11F8C90/11F4C48 | 동명 registry 키 |
| entity_offsets.txt | `VFT_INTERACT/INTERACTIVE` | 11E1160 | 11F8600 | VFT_NPC |
| entity_offsets.txt | `ENT_VFT_SET`, `MON_VFTS`, `CLASSES` | 위 v38 값 | 위 v39 값 | 위 키 조합 |
| inventory_offsets.txt | `INV_VFT` | 0x1227468 | 0x123EE28 | VFT_INVENTORY (라이브 sub[26]) |
| inventory_offsets.txt | `ITEM_VFT` | 0x1226E20 | 0x123E848 | ITEM_VFT |
| inventory_offsets.txt | `MSG_ANCHOR_RVA` | 0x16EB718 | 0x1708778 | MSG_ANCHOR_RVA |
| skill_offsets.txt | `HSD_VFT2` | 11E2C58 | 11F9FE0 | VFT_HUDSLOT (라이브 sub[30]) |
| offsets.json | `PosXAbs/PosYAbs` | 0x16EB5A0/04 | 0x1708600/04 | PLAYER_X/Y |
| offsets.json | `ExperiencePct64` | 0x1641B00 | 0x16604C8 | ExperiencePct64 (포인터 슬롯) |
| offsets.json | `MapSubsystemVftRva` | 0x1228960 | 0x1240480 | VFT_MAPSUBS (라이브 sub[23]) |
| settings_*.json | `ent_mgr_offset` / `grid_vft` | 0x16EB6F0 / 0x11DE3E8 | 0x1708750 / 0x11F5958 | MGR / VFT_ACTORSUBS |
| settings_*.json | `player_*`, `vft_pres_*`, `classes` | v38 | v39 | 위 표와 동일 |
| settings_attacks/contested | `act_vft`, `attack_act_vft`, `vft_*` | v38 | v39 | VFT_AC/ATTACKACT/SELF/PLAYER/MONSTER/SUMMON |

구조 인덱스는 라이브로 재확인했다: `INV_SUB_IDX=26`, `HSD_IDX=30` (v39 subs와 일치).

## 2. 의도적 예외

| 항목 | 값 | 사유 |
|---|---|---|
| `PARTY_JOIN_ACTOR` | `1` (11_25 원본은 0) | analysis_1 동작 보존. 파티원 레벨/사망/공격대상 수집. 드라이버 콜은 샘플당 11회 |
| `data/dungeon/floors_entrances.txt` | 26,829B (analysis_1) | 11_25 쪽은 26,542B 로 더 오래된 사본 |
| `bin/inventory_listen.exe`, `bin/realtime_monitor_full.exe` | 9월 빌드 유지 | 소스/재빌드 근거 없음, 구조 보존 |
| `dll/*` 플러그인 10종 | v38 바이너리 | 소스 미포함. 8종은 설정 갱신으로 v39 대응, 2종은 하드코딩 |

## 3. v39 근거 없음 / 의도적 격리 (UNVERIFIED — 갱신 2026-11-25)

| 파일 | 키 | 상태 |
|---|---|---|
| entity_offsets.txt | `MAP_HEADS`, `NODE_*`, `ENT_*`, `OFF_LIVE_*`, `OFF_A_*`, 투영/이름 상수 | 유지 (구조 오프셋) |
| skill_offsets.txt | `HSD_VFT` secondary `11E2400` | registry에 대응 키 없음 — 유지 |
| offsets.json | `Ent*VftRva` | 사전 v39 값 유지 (추정 금지) |
| offsets.json | `InventoryBase/Cache*/Mgr`, `SkillListBase`, `BuffListBase`, `PartyBase`, `ServerTick`, `PosZAbs` | **0 격리** (잘못된 절대주소 로드 방지) |
| settings_print_state.json | `off_live_*`, `off_a_*`, `off_ent_*`, `off_name_*`, `item_qty_is_o38` | 구조 상수 유지 |
| settings_attacks/contested | `off_atk_owner/tgt`, `off_ent_*` | 구조 상수 유지; `player_x/y`는 v39 |
| `registry/.applied.sha` | — | 의미 미확인, 변경 안 함 |

이미 registry에 맞춰 갱신된 키(`ST_*`/`STAT_*`/`INV_VEC_*`/`HSD_ADJ`/`PlayerBase`/`ItemEntityVtableRva` 등)는 위 표에서 제외.

## 4. 재검증 방법

```
python _build\check_configs.py     :: registry ↔ 오버레이 키 대조 (문자열/hex 형식 인지)
```
