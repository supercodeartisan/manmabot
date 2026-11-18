# UPDATE STATUS — 11-11analysis (2026-11-11)

> **갱신 완료.** `analysis_1` 구조 유지 + `11_11`(v37 / LC.exe **26.11.10.2003**) 결합.

| 항목 | 값 |
|---|---|
| 트리 | `11-11analysis` |
| 기준 클라이언트 | LC.exe **26.11.10.2003** (base `0x7FF7113B0000`, `MODULE_SIZE=0x3FA2000`) |
| registry | **v37** · hash `BA4B0D944347F9D1` |
| 규모 | 1,187 files (MANIFEST 제외) / 18.68 MB |
| 구조 | `analysis_1` 경로 **누락 0**, 문서·`_build/`(검증 도구)만 추가 |

---

## 1. 갱신 요약

| 대상 | 이전 (analysis_1 / v36) | 현재 (11-11analysis / v37) |
|---|---|---|
| `MGR` | `0x16EB6F0` | **`0x1708750`** |
| `PLAYER_X/Y` | `0x16EB5A0/04` | **`0x1708600/04`** |
| `ST_BLOCK` | `0x16EA0F0` | **`0x1708600`** |
| `ExperiencePct64` | `0x1641B00` | **`0x16604C8`** |
| `CAM_GLOB` | `0x1886820` | **`0x18B5E30`** |
| `MSG_ANCHOR_RVA` | `0x16EB718` | **`0x1708778`** |
| ActorSubsystem | `0x11DE3E8` | **`0x11F5958`** |
| CharData / Status | `0x11E5088` / `0x11E50F8` | **`0x11FC560` / `0x11FC540`** |
| Inventory / Item | `0x1227468` / `0x1226E20` | **`0x123EE28` / `0x123E848`** |
| HudSlot | `0x11E2C58` | **`0x11F9FE0`** |
| Party VFT 3종 | `0x12293B8/350/328` | **`0x1240D60/0x1240CD8/0x1240C70`** |
| MapSubsystem | `0x1228960` | **`0x1240480`** |
| VFT_SELF/PLAYER/MONSTER | `0x11E1388/350/240` | **`0x11F8828/7F0/6E0`** |

의도적 예외: **`PARTY_JOIN_ACTOR=1`** (11_11 원본 0) — analysis_1 동작 보존.

## 2. 파일별 갱신 내역

| 경로 | 조치 |
|---|---|
| `core/*` | `11_11/core` 로 교체 (11 files) |
| `core/lcore.h` | fallback 상수 **42개** v37 동기화 |
| `registry/LC930_REGISTRY.txt` | v37 복사 + `PARTY_JOIN_ACTOR=1` |
| `registry/region_table.tsv` | 11_11 동일본 |
| `bin/*.exe` (29) | 11_11 v37 빌드로 교체 — 해시 **29/29 일치** |
| `bin/inventory_listen.exe`, `bin/realtime_monitor_full.exe` | 유지 (9월 빌드, 구조 보존) |
| `dll/party.dll`, `dll/partyhud.dll` | analysis_1 소스 + v37 fallback **재빌드** |
| `dll/*` 플러그인 10종 | 유지 (v36 바이너리, 아래 제약) |
| `char_offsets.txt` (루트·registry) | MGR/CD_VFT/CD_OFF/VFT_STATUS |
| `registry/entity_offsets.txt` | 28키 + ST_BLOCK 파생 5키 |
| `registry/inventory_offsets.txt` | MGR/INV_VFT/ITEM_VFT/MSG_ANCHOR |
| `registry/skill_offsets.txt` | MGR/HSD_VFT2 |
| `registry/offsets.json` | moduleBase/Size, PosXAbs/Y, ExperiencePct64, MapSubsystemVftRva |
| `registry/settings_*.json` (3) | MGR/grid/player offsets/vft_pres/act/attack/vft_* |
| `src/party/lparty.h` | fallback 4키 v37 |
| `data/` | analysis_1 유지 (이름표 동일, dungeon 최신본 유지) |
| `list/image/*.png` | 1,023장 유지 |

## 3. 검증 결과 (라이브, LC.exe PID 23400)

| 항목 | 결과 |
|---|---|
| `dll/party.dll` (LCAPI host) | `abi=1`, `configure=0`, sub vft `0x1240CD8`, 파티 2명 정상 |
| `dll/partyhud.dll` | `ioctl=82`, `WIN 192x387`, `SLOT 0 guid=0x3BCFF` |
| `bin/charread_930.exe` | `decode=15/15`, `vft=011FC540` |
| `_build/check_configs.py` | **PASS** (registry ↔ 오버레이 전 키) |
| EXE 해시 | 29/29 = `11_11/bin` |
| 구조 대조 | 누락 0 |

## 4. 남은 제약

| 항목 | 상태 |
|---|---|
| `contested_mobs.dll`, `shop_listen.dll` | 설정 경로 없음 → **v36 상수 하드코딩**, 소스 필요 |
| 플러그인 8종 | v36 바이너리지만 설정 파일(v37 갱신)을 읽음 |
| `src/listen/realtime_monitor_full.c` | 구버전 소스 → 재빌드 안 함 |
| `registry/.applied.sha` | 의미 미확인, 변경 안 함 |
| v37 근거 없는 오프셋 | 유지 — `CONFIG_PROVENANCE.md` §3 |
| `bin/out/uidialogmon_out.txt` | v36 시절 산출물, 구조 보존 위해 유지 |

## 5. 해시

| 파일 | SHA256 first16 |
|---|---|
| `registry/LC930_REGISTRY.txt` | `BA4B0D944347F9D1` |
| `dll/party.dll` | `FCED8EFC100BBA87` |
| `dll/partyhud.dll` | `1CDB6AE8CBF2268D` |
| `MANIFEST.txt` | 전 파일 1,187건 수록 |

## 6. 재생성

```
11_11\tools\make_analysis_1111.bat                 :: 기본 출력 ..\..\11-11analysis
11_11\tools\make_analysis_1111.bat D:\out\x --force :: 다른 위치/덮어쓰기
```

빌드 스크립트는 `analysis_1`(구조) + `11_11`(v37 분석결과)에서 이 트리를 재현한다.
