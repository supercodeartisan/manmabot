# Sensitive assets & backup policy

고객 배포본에서 맵 PNG·오프셋 텍스트 등을 **폴더 브라우징으로 바로 열어보지 못하게** 하는 계층입니다.  
완벽한 비밀 유지가 아닙니다. 실행 중인 클라이언트에서 메모리/캐시를 덤프하면 복구 가능합니다.

---

## 1. 무엇을 보호하는가

| 자산 | 고객 빌드에서의 형태 | 런타임 |
|------|----------------------|--------|
| `Engine/data/**` (맵 PNG, cursors, catalog, world JSON 등) | **평문 `Engine/data/`.** Stage 5가 `data.pack`을 만든 뒤 `unpack_customer_data.py`가 풀고 팩을 지운다 | 디스크의 `Engine/data`를 직접 읽는다. `data.pack`이 없으면 RAM 마운트는 하지 않는다 |
| `Engine/analysis/**` 민감 텍스트 (offsets.json, `*_offsets.txt`, zone_table, list JSON/MD 등) | `Engine/analysis_text.pack` | C DLL이 경로로 열어야 하므로 실행 중에만 `Engine/analysis/`에 쓰고, 프로세스 종료 시 삭제 |
| 분석 DLL / `.pyd` / 드라이버 | 평문 유지 | 그대로 로드 |

의도적으로 **보호하지 않는 것**:

- 고객이 편집하는 `UserData/` (스케줄, 계정, 맵 오버레이)
- 번들 `python/`
- Authenticode 서명 키 / PFX (빌드 PC에만, 저장소에 커밋 금지)

---

## 2. 솔직한 한계 (기대치)

- 팩 키는 클라이언트에 포함됩니다 (`session/asset_pack_format.py` → Stage 2 후 `.pyd`).
- 숙련된 리버스 엔지니어는 실행 중 메모리를 덤프하거나 키스트림을 복원할 수 있습니다.
- 목표: zip을 열거나, 실행 후 탐색기에서 맵 폴더를 복사하는 **캐주얼 유출**을 막는 것. DRM 대체가 아님.

---

## 3. 개발 트리 vs 릴리스

| | 개발 저장소 | `release/portable/ManmabotV1` |
|--|-------------|-------------------------------|
| `Engine/data/` | **항상 평문 유지** (편집·디버그) | Stage 5로 팩을 만든 다음 unpack으로 평문 복구. 고객 zip에는 `data.pack` 없음 |
| `Engine/analysis/*.json` 등 | 평문 유지 | Stage 5 이후 팩으로만 (DLL 남음) |
| 백업 | git / 로컬 백업의 정본 | 배포 zip은 팩 포함본 |

**금지:** 개발 트리의 `Engine/data`를 Stage 5로 지우거나 팩만 남기지 말 것.  
`packaging/pack_assets.py` 는 `release/portable/...` 만 수정합니다.

---

## 4. 백업 정책

1. **정본(source of truth)**  
   - 맵/커서/카탈로그: 개발 트리 `Engine/data/`  
   - 오프셋: 개발 트리 `Engine/analysis/` (+ Research 근거 문서)

2. **릴리스 아티팩트**  
   - `release/portable/ManmabotV1/` 전체를 버전 태그와 함께 보관 (또는 zip).  
   - `release/checksums/SHA256SUMS` 동봉.

3. **고객 PC**  
   - 맵·카탈로그는 `Engine/data` 평문이다. `data.pack`은 배포하지 않는다.  
   - 오프셋 텍스트는 실행 중에만 생겼다가 종료 시 지워진다. 강제 종료로 남으면 다음 실행이 덮어쓰고, 정상 종료 때 다시 지운다.

4. **유실 시 복구**  
   - 개발 트리에서 Stage 1→5 재빌드.  
   - 고객에게 새 portable을 배포.

---

## 5. 빌드 순서 (중요)

```
Stage 1 → 2 → 3 → 5 → verify_stage5 → unpack_customer_data.py → smoke → 4
```

`verify_stage5.py`는 unpack **전**에만 실행한다. unpack 이후에는 `data.pack`이 없고 `Engine/data`가 평문이므로 그 검증은 실패하는 것이 맞다.  
체크섬(Stage 4)은 unpack 다음이다. 절차 전문은 `RELEASE_PLAYBOOK.md`.  
`run.py` 가 `ensure_packed_assets()` 를 호출하므로 Stage 2에 `session/asset_pack*.py` 가 포함되어야 합니다 (일반 session 컴파일에 포함).

검증:

```bat
python\python.exe packaging\verify_stage5.py
```

---

## 6. 런타임 훅

- `run.py` → `session.asset_pack.ensure_packed_assets()`
- `session.asset_store` 가 `Engine/data` 읽기를 RAM으로 연결 (`Path`, `os.walk`, `PIL`, `cv2`)
- 오프셋 텍스트는 실행 중에만 `Engine/analysis/`에 있고 종료 시 삭제
- 개발 트리에 평문 `Engine/data`가 있으면 마운트하지 않음

---

## 7. 관련 파일

| 파일 | 역할 |
|------|------|
| `Engine/session/asset_pack_format.py` | 팩 포맷 / 빌드·해제 |
| `Engine/session/asset_pack.py` | 기동 시 RAM 마운트 + 오프셋 임시 기록 |
| `Engine/session/asset_store.py` | 디스크에 풀지 않는 읽기 훅 |
| `packaging/pack_assets.py` | Stage 5 빌더 |
| `packaging/verify_stage5.py` | 팩 존재·라운드트립 검증 |
| `packaging/build_release.py --stage 5` | 엔트리 |
