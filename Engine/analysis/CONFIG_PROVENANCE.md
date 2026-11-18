# CONFIG PROVENANCE — 11-18analysis (v38)

v38(26.11.17.2002) 근거가 있는 키만 갱신했다. 근거 없는 값은 **추정하지 않고 유지**한다.

## 1. 단일 원본

모든 신규 값은 `registry/LC930_REGISTRY.txt`(v38)의 동일 의미 키에서 왔다.
오버레이 파일은 소비자 DLL이 registry 전체를 읽지 않도록 만든 **투영 사본**이다.

| 파일 | 투영 키 (예) |
|---|---|
| char_offsets.txt | MGR, CD_VFT, CD_OFF, VFT_STATUS |
| entity_offsets.txt | MGR, ACTOR_VFT←VFT_ACTORSUBS, PLAYER_*←ST_BLOCK+ST_*, VFT_*, CAM_GLOB |
| inventory_offsets.txt | MGR, INV_VFT←VFT_INVENTORY, ITEM_VFT, MSG_ANCHOR_RVA |
| skill_offsets.txt | MGR, HSD_VFT2←VFT_HUDSLOT |
| offsets.json | PosXAbs/Y←PLAYER_*, ExperiencePct64, MapSubsystemVftRva←VFT_MAPSUBS |
| settings_*.json | ent_mgr/grid/player/vft_* ← 위와 동일 |

## 2. 의도적 예외

| 항목 | 값 | 사유 |
|---|---|---|
| PARTY_JOIN_ACTOR | 1 | analysis 동작 보존 (11_18 원본 0) |
| data/dungeon | analysis 유지 | 구조 보존 |
| list/image | 유지 | 소비자 리소스 |
| listen 플러그인 8종 | 설정 갱신으로 v38 대응 | 바이너리 유지 |
| contested_mobs / shop | 설정+소스 기본값 갱신 | shop은 재빌드 권장 |

## 3. v38 근거 없음 — 값 유지

char_offsets 의 status/stat 필드 오프셋, entity NODE_*/ENT_*/NAME_*/off_*,
inventory INV_VEC_*/ITEM_* field/MSG chain(앵커 제외), skill HSD_VFT(legacy),
offsets.json 레거시 캐시 필드, inventory_offsets.json(orphan).

## 4. 재검증

```
python _build\check_configs.py
```
