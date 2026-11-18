# 11-18analysis — analysis_1 구조 보존 + 11_18(v38) 결합 트리

작성 2026-11-17 · 기준 클라이언트 **LC.exe 26.11.17.2002** · registry **v38**

이 트리는 `analysis_1` 계열의 **디렉터리/DLL 이름/설정 파일 계약을 유지**한 채,
`11_18`(v38 / 26.11.17.2002)의 최신 상수·core·모듈 EXE를 결합한 것이다.

| 원본 | 역할 |
|---|---|
| analysis_1 계약 | 디렉터리, DLL 이름/export, 설정 파일 이름·형식, `list/`, 오프셋 오버레이 |
| `11_18` | registry v38, core, 모듈 EXE, VFT/전역 슬롯 |

## 1. 보존된 계약

- 디렉터리: `bin/ core/ data/ dll/ list/ out/ registry/ src/` — 삭제/이름변경 없음
- DLL export 동일 (LCAPI ABI 1 + 플러그인 `*_snapshot`/`*_shutdown`)
- 오버레이 파일 이름·키 이름 유지. **값은 registry 투영만 갱신**

## 2. 오버레이 = registry 투영

`char/entity/inventory/skill_offsets*`, `offsets.json`, `settings_*.json` 은
독립 원본이 아니라 `registry/LC930_REGISTRY.txt` 에서 갈라낸 소비자용 사본이다.
근거 있는 키만 갱신한다. 구조 오프셋(객체 내부)은 유지.
검증: `python _build\check_configs.py`

## 3. 이번에 갱신한 것

| 대상 | 내용 |
|---|---|
| `core/` | `11_18/core` 교체 + `lcore.h` fallback 동기화 |
| `registry/LC930_REGISTRY.txt` | **v38** + `PARTY_JOIN_ACTOR=1` |
| overlay 설정 | MGR/PLAYER_*/VFT_*/MSG_ANCHOR/HSD_VFT2/MapSubsystem 등 |
| `bin/*_930.exe`/`*_1009.exe` | `11_18` 재빌드본 |
| `dll/party.dll`, `dll/partyhud.dll` | analysis 소스 + v38 fallback **재빌드** |
| `src/party/lparty.h` | fallback 4키만 v38 (blind-read 본문 유지) |
| `src/listen/NPC_conv/shop_listen.c` | 하드코딩 기본값 v38 |

registry hash: **`FC74E3F779D75270`**

## 4. 재빌드 / 재검증

```
build_bot_modules.bat
python _build\check_configs.py
_build\verify.bat
```

재생성:
```
python 11_18\tools\analysis_1118\build_analysis_1118.py --force
```
