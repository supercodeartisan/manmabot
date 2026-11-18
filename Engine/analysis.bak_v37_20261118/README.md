# 11-11analysis — analysis_1 구조 보존 + 11_11(v37) 결합 트리

작성 2026-11-11 · 기준 클라이언트 **LC.exe 26.11.10.2003** · registry **v37**

이 트리는 `analysis_1`(2026-11-09 스냅샷)의 **구조와 소비자 계약을 그대로 유지**한 채,
`11_11`(v37 / 26.11.10.2003)의 최신 상수·소스·빌드 결과를 결합한 것이다.

| 원본 | 역할 |
|---|---|
| `analysis_1` | 디렉터리 구조, DLL 이름/export, 설정 파일 이름·형식, 리소스(list/), 오프셋 오버레이 |
| `11_11` | registry v37, core, 모듈 소스, 재빌드된 EXE, 재매핑된 VFT/전역 슬롯 |

## 1. 보존된 계약 (소비자 프로젝트 영향 없음)

- 디렉터리: `bin/ core/ data/ dll/ list/ out/ registry/ src/` — **삭제/이름변경 없음**
- EXE 31개 이름 동일, DLL 12개 이름 동일
- DLL export 동일
  - LCAPI 2종(`party`, `partyhud`): `lcapi_abi_version/configure/set_params/run/module_*` (ABI 1)
  - 플러그인 10종: `<name>_snapshot`, `<name>_shutdown`
- sink 텍스트 형식, 출력 파일명(`*_out.txt`, `party_cache.txt`, `uidialogmon_cache.txt`), 설정 파일 이름·키 이름·형식 동일
- `list/image/*.png` 1,023장, `data/` 이름표 2종 그대로

## 2. 이번에 갱신한 것

| 대상 | 내용 |
|---|---|
| `core/` | `11_11/core` 로 교체. `lcore.h` fallback 상수 **42개를 v37 registry 값으로 동기화** |
| `registry/LC930_REGISTRY.txt` | **v37** (26.11.10.2003). 단, `PARTY_JOIN_ACTOR=1` 유지(analysis_1 동작 보존) |
| `registry/region_table.tsv` | 11_11 동일본 |
| `bin/*.exe` | 모듈 29개 **v37 재빌드본**으로 교체 (해시 29/29 = 11_11) |
| `dll/party.dll`, `dll/partyhud.dll` | analysis_1 소스(버그픽스 포함) + v37 fallback으로 **재빌드** |
| `char_offsets.txt`(루트/registry) | MGR·CD_VFT·CD_OFF·VFT_STATUS → v37 |
| `registry/entity_offsets.txt` | MGR, ACTOR_VFT, VFT_PRES_*, ACT/ATTACK/DEATH/DEADBODY, PLAYER_X/Y/HP/…/LEVEL, CAM_GLOB, VFT_* 9종, ENT_VFT_SET, MON_VFTS, CLASSES → v37 |
| `registry/inventory_offsets.txt` | MGR, INV_VFT, ITEM_VFT, MSG_ANCHOR_RVA → v37 |
| `registry/skill_offsets.txt` | MGR, HSD_VFT2 → v37 (HSD_IDX=30 유지, 라이브 확인) |
| `registry/offsets.json` | moduleBase/Size, PosXAbs/PosYAbs, ExperiencePct64, MapSubsystemVftRva → v37 |
| `registry/settings_*.json` (3종) | MGR, grid_vft, player_* offsets, vft_pres_*, act_vft, attack_act_vft, vft_self/player/monster/summon, classes → v37 |
| `src/party/lparty.h` | fallback 4개(v37): MGR `0x1708750`, PARTY_VFT_* `0x1240D60/0x1240CD8/0x1240C70` |

> registry 해시는 11_11 원본(`5DCC152BF5A85D22`)과 다르다 — 의도적 1키 차이
> (`PARTY_JOIN_ACTOR=1`) 때문이며, 이 트리 해시는 **`BA4B0D944347F9D1`** 이다.

## 3. 라이브 검증 (LC.exe PID 23400, v37)

| 대상 | 결과 |
|---|---|
| `dll/party.dll` (LCAPI host) | abi=1, configure=0, sub vft `0x1240CD8`(=PARTY_VFT_RC v37), leader/member 2명, hp%/mp%/pos 정상 |
| `dll/partyhud.dll` (LCAPI host) | ioctl=82, `WIN 192x387`, `SLOT 0 guid=0x3BCFF hp=100 mp=80` |
| `bin/charread_930.exe` | `decode=15/15`, `vft=011FC540`, Lv/HP/MP/POS 정상 |
| `bin/*.exe` 해시 | 29/29 = `11_11/bin` |

## 4. 남은 제약 (중요)

1. **플러그인 DLL 10종은 v36 바이너리**다(소스 미포함). 이 중 8종은 설정 파일을 읽으므로
   위 v37 설정 갱신으로 동작한다: `buff_listen`, `storewin_build`, `uidialog_listen`(registry),
   `print_state`(char/entity offsets + settings), `realtime_monitor`(offsets/registry),
   `attacks_me`(settings), `inventory_listen`(offsets), `hotbar_listen`(offsets).
2. **`contested_mobs.dll`, `shop_listen.dll`** — 설정 경로 문자열이 없어 **상수 하드코딩(v36)**.
   v37에서 쓰려면 소스 확보 후 재빌드해야 한다.
3. `src/listen/realtime_monitor_full.c` 는 9.30~26.10 초기 상수를 담은 **구버전 소스**다.
   현재 `realtime_monitor.dll`(11-07 빌드)과 일치하지 않으므로 재빌드하지 않았다.
4. `registry/.applied.sha` 는 의미가 확인되지 않아 **그대로 두었다**(어떤 파일과도 해시 불일치).
5. `bin/inventory_listen.exe`, `bin/realtime_monitor_full.exe` 는 9월 빌드 그대로 유지(구조 보존).
6. v37 근거가 없는 오프셋은 **추정하지 않고 유지**했다 — `CONFIG_PROVENANCE.md` 참조.

## 5. 재빌드 / 재검증

```
build_bot_modules.bat                      :: dll\party.dll, dll\partyhud.dll
_build\build_host.bat                      :: LCAPI host smoke test
_build\lcapi_host_test.exe dll\party.dll registry\LC930_REGISTRY.txt 3
_build\lcapi_host_test.exe dll\partyhud.dll registry\LC930_REGISTRY.txt 2
```

EXE 29개는 `11_11` 에서 `build_all.bat` 으로 빌드한 뒤 `bin\` 에 복사했다
(`11_11` = v37 단일 상수출처).

## 6. 구조 변경 요약

| 항목 | 변경 |
|---|---|
| 디렉터리/파일 이름 | 없음 (analysis_1과 동일) |
| 추가 | `UPDATE_STATUS.md`, `README.md`, `CONFIG_PROVENANCE.md`, `MANIFEST.txt`, `_build/`(재빌드·검증 스크립트) |
| 삭제 | 없음 |
