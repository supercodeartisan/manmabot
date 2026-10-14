# Manmabot V1 — packaging

개발 저장소(이 폴더 전체)는 **그대로 유지**합니다.  
고객용 산출물은 `release/` 아래에만 생성됩니다.

**다른 노트북 / 업데이트 코드베이스에서 전체 절차가 필요하면:**  
→ [`RELEASE_PLAYBOOK.md`](RELEASE_PLAYBOOK.md) 를 사용하세요.

**패키징 버그 수정 이력 (수동 패치 없이 재빌드만):**  
→ [`RELEASE_BUGFIX_LOG.md`](RELEASE_BUGFIX_LOG.md)

**민감 자산(맵 PNG·오프셋) 팩 / 백업 정책:**  
→ [`SENSITIVE_ASSETS.md`](SENSITIVE_ASSETS.md)

**고객 설치 EXE / Interception 자동 / data.pack 유지 등 (미구현 로드맵):**  
→ [`CUSTOMER_HARDENING_ROADMAP.md`](CUSTOMER_HARDENING_ROADMAP.md)

**keep-script / `__init__.py` 슬림 정책 검사:**  
→ `python\python.exe packaging\verify_shims.py`

## Decisions (locked)

| Item | Choice |
|------|--------|
| Compile strategy | In-place `.pyd` / Nuitka `--module` (Stage 2+) |
| Tools | Customer pack excludes `Tool_*.bat` and entire `Tools/` |
| Dev tree | Never deleted or replaced by release |
| Sensitive assets | Stage 5 builds both packs. Customer `Engine/data` is then extracted and `data.pack` is deleted. `analysis_text.pack` stays. See RELEASE_PLAYBOOK.md |

## Stages

| Stage | Command | What it does |
|-------|---------|--------------|
| 0 | `python packaging/build_release.py --stage 0` | Validate manifests; write `release/version-info/` |
| 1 | `python packaging/build_release.py --stage 1` | Clean portable copy (no compile yet) |
| 2 | `python packaging/build_release.py --stage 2` | In-place Nuitka `--module` compile inside portable |
| 3 | `python packaging/build_release.py --stage 3` | Copy pruned `python\` (drop torch/ultralytics/build tools) |
| 5 | `python packaging/build_release.py --stage 5` | Obfuscated `Engine/data.pack` + `analysis_text.pack`; strip plain assets |
| 4 | `python packaging/build_release.py --stage 4` | SHA256 checksums + optional Authenticode signing |

Recommended full flow:

```bat
python\python.exe packaging\build_release.py --stage 1 --skip-python --no-checksums
python\python.exe packaging\build_release.py --stage 2 --no-checksums
python\python.exe packaging\build_release.py --stage 3 --no-checksums
python\python.exe packaging\build_release.py --stage 5 --no-checksums
python\python.exe packaging\verify_stage5.py
python\python.exe packaging\unpack_customer_data.py
release\portable\ManmabotV1\python\python.exe packaging\smoke_portable.py
python\python.exe packaging\build_release.py --stage 4 --skip-sign
```

Stage 2 smoke test (one module):

```bat
python\python.exe packaging\build_release.py --stage 2 --packages session --limit 1 --no-checksums
```

### Stage 2 requirements

- Full CPython **3.14** with `include\Python.h` (set `MANMABOT_BUILD_PYTHON` if auto-detect fails)
- Build deps: `python -m pip install -r packaging\requirements-build.txt` on that full interpreter
- MSVC (`cl`) or MinGW — Nuitka uses these for the C backend
- Portable tree from Stage 1 already present under `release\portable\ManmabotV1`

Stage 2 compiles each `.py` to a sibling `.pyd` (keeps `Path(__file__)` layouts), then deletes the `.py` except scripts listed in `manifests/keep_scripts.txt` (`run.py`, `launcher_manmabot.py`, `Engine/autologin/bot/bot2.py`).

Fast check without copying the ~1.8 GB `python\` tree:

```bat
python\python.exe packaging\build_release.py --stage 1 --skip-python
```

Dry-run (list actions only):

```bat
python\python.exe packaging\build_release.py --stage 1 --dry-run
```

Verify a Stage 1 portable folder:

```bat
python\python.exe packaging\verify_portable.py
```

Verify Stage 2 compiled imports:

```bat
python\python.exe packaging\verify_stage2.py
```

### Stage 3 notes

- Copies `python\` into the portable folder **without** torch / ultralytics / pytest / Nuitka / PyInstaller / matplotlib, etc.
- Keeps runtime needs: PySide6, numpy, OpenCV, PyYAML, mss/dxcam/keyboard/interception, onnxruntime/RapidOCR, scipy, pywin32, …
- Manifest: `manifests/prune_site_packages.txt`
- Typical size drop observed: ~1890 MB → ~1050 MB

### Stage 4 notes

Checksums (always):

```bat
python\python.exe packaging\build_release.py --stage 4
python\python.exe packaging\verify_checksums.py
```

**Run Stage 5, then `unpack_customer_data.py`, then Stage 4.** Checksums must match the unpacked `Engine/data` and must not include `data.pack`. `verify_stage5.py` runs before the unpack.

### Stage 5 notes

```bat
python\python.exe packaging\build_release.py --stage 5
python\python.exe packaging\verify_stage5.py
```

- Builds `Engine/data.pack` from portable `Engine/data`, then deletes the plain folder.
- `unpack_customer_data.py` extracts that pack back to `Engine/data` and deletes `data.pack`. The customer folder ships the real directory.
- Builds `Engine/analysis_text.pack` from analysis text/json, then deletes those plain files (DLLs stay).
- Runtime: `run.py` → `ensure_packed_assets()`. With no `data.pack`, data is read from disk. Analysis text is written only while the process runs.
- Policy / backup: [`SENSITIVE_ASSETS.md`](SENSITIVE_ASSETS.md)
- Dev tree `Engine/data` is never touched.

Outputs:
- `release/checksums/SHA256SUMS`
- `release/portable/ManmabotV1/SHA256SUMS.txt`
- `release/version-info/BUILD.json`

Optional Authenticode signing (build machine only — **do not commit certs/passwords**):

```bat
set MANMABOT_SIGN=1
set MANMABOT_SIGN_PFX=C:\secure\codesign.pfx
set MANMABOT_SIGN_PASSWORD=***
python\python.exe packaging\build_release.py --stage 4
```

Or use a store certificate:

```bat
set MANMABOT_SIGN=1
set MANMABOT_SIGN_THUMBPRINT=YourCertSha1Thumbprint
```

Without those env vars, Stage 4 still writes checksums and skips signing safely.  
`signtool.exe` was detected on this machine under Windows Kits when present.

- Compiles **per `.py` file** to a sibling `.pyd` (preserves `Path(__file__)` data paths)
- Leaves `__init__.py` / `__main__.py` as thin shims (Nuitka cannot `--module` those as single files)
- Keeps `run.py`, `launcher_manmabot.py`, `Engine/autologin/bot/bot2.py` as scripts
- Build interpreter must be full CPython 3.14 with headers (`MANMABOT_BUILD_PYTHON`); portable `python\` is embeddable and cannot compile
- Customer runtime still uses portable `python\` to load the `.pyd` files

## Output layout

```
release/
  portable/ManmabotV1/     customer folder
  checksums/               SHA256SUMS (Stage 1+)
  version-info/            BUILD.json
```

## Manifests

- `manifests/root_files.txt` — root files to copy
- `manifests/allow_roots.txt` — top-level directories to copy
- `manifests/deny_globs.txt` — paths/patterns never shipped

## New dependencies

Stage 0–1: **none** (stdlib only).  
Stage 2 build machine: see `requirements-build.txt` (`nuitka`, `ordered-set`, `zstandard`) installed into the **full** CPython 3.14 used for compiling (not required inside the customer `python\` tree at runtime).

## Rollback

Delete `release\`. The development tree is untouched.
