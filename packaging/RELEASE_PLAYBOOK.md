# Manmabot V1 — Release playbook

This is the document for the **first** customer folder. Follow it from top to bottom on the **updated product folder**. Do not paste that folder over an older tree, and do not invent extra packaging steps.

When `release\portable\ManmabotV1` already exists, do not run this full copy again. Stage 1 refuses to wipe it. Update that folder with [`INCREMENTAL_RELEASE.md`](INCREMENTAL_RELEASE.md). `--force-full` is only for a broken folder or a python/manifest change that the incremental updater cannot apply.

The customer receives one folder: `release\portable\ManmabotV1`.  
`Engine\data` in that folder is a normal directory (maps, catalog, cursors). It is **not** left as `data.pack`.  
`Engine\analysis_text.pack` stays packed. Offset text is written only while the program is running and deleted on a normal exit.

---

## 0. What you are producing

```
<updated-product-root>\
  packaging\                          build scripts (not shipped)
  release\
    portable\ManmabotV1\              THIS is the customer folder
    checksums\SHA256SUMS              optional, next to the zip
    version-info\BUILD.json           build record, not required by the customer
```

Customer launch file: `ZF.bat` (or `ZF.exe` if that file is in the folder).

Locked choices:

| Item | Choice |
|------|--------|
| Compile | Nuitka `--module`, one `.py` → one sibling `.pyd` |
| Python in the customer folder | Bundled embeddable CPython 3.14, pruned |
| Python that compiles | A full CPython 3.14 that has `include\Python.h` |
| `Tools`, `Research`, `Docs`, `Others`, `.cursor`, `packaging` | Not shipped |
| `Engine\data` | Real folder. `data.pack` is deleted before checksums |
| `Engine\analysis_text.pack` | Shipped. Plain offset text is not left in the zip |
| Signing | Off, unless you set the sign variables yourself |
| Game logic | Do not change login, movement, combat, or HP while releasing |

---

## 1. Machine requirements

Windows 10 or 11, 64-bit. Free disk: at least 8 GB. Stage 2 takes about 30–40 minutes.

### 1.1 Product folder shape

The updated tree must look like this. Names can differ inside `Engine` only if you also edit `packaging\manifests\`.

```
<product-root>\
  run.py
  launcher_manmabot.py
  ZF.bat
  ZF.exe
  Driver_Install_Interception.bat
  Driver_Start_SignedDriver.bat
  Engine\
  UI\
  Drivers\
  python\                 embeddable CPython 3.14
  UserData\               not copied as-is
  Tools\                  excluded
  Research\               excluded
```

Check the bundled runtime:

```bat
cd /d <product-root>
python\python.exe -c "import sys; print(sys.version)"
```

The version line must start with `3.14`.

### 1.2 Build Python (not the bundled one)

The bundled `python\` has no `Python.h`. Nuitka fails on it with `unsupported embeddable CPython`.

Install a full CPython 3.14 (python.org or the Windows Store `pythoncore-3.14-64` layout). Then:

```bat
"<full-python>\python.exe" -c "import sys; from pathlib import Path; print(sys.version); print((Path(sys.executable).parent / 'include' / 'Python.h').is_file())"
```

If that prints `False`, try `Path(sys.base_prefix) / 'include' / 'Python.h'`. You need `True`.

On the machine that built version1 the path was:

```bat
set MANMABOT_BUILD_PYTHON=C:\Users\Condra\AppData\Local\Python\pythoncore-3.14-64\python.exe
```

Use your own path. Set it in the same command window that runs Stage 2.

Install the compiler packages into **that** interpreter:

```bat
"%MANMABOT_BUILD_PYTHON%" -m pip install -U -r packaging\requirements-build.txt
```

`packaging\requirements-build.txt` is `nuitka`, `ordered-set`, `zstandard`. The version1 build used Nuitka 4.2.2.

### 1.3 C compiler

Nuitka needs MSVC `cl.exe` (Visual Studio or Build Tools, C++ workload) or MinGW `gcc`. The known-good build used MSVC `cl 14.5`.

### 1.4 What you do not need

- A code-signing certificate. Stage 4 is run with `--skip-sign`.
- A license server.
- The game client, for the build itself. A live hunt is a separate check after the zip exists.

---

## 2. Copy packaging into the updated tree

Do this in the **updated** folder. Leave older product folders alone.

1. Copy the whole `packaging\` directory from the tree that contains this file onto `<updated-product-root>\packaging\`.
2. Copy these three files onto the same relative path. They are new modules. Overwrite only if the updated tree does not already have a newer copy of them:

```
Engine\session\asset_pack.py
Engine\session\asset_pack_format.py
Engine\session\asset_store.py
```

3. Merge the four files below. Do **not** replace the whole file. The updated tree may have extra flags and helpers.

Do not copy `release\` from an old build. Stage 1 deletes and recreates it.

`robocopy` exit code 0 or 1 means the copy worked. Codes 8 and above are failures.

### 2.1 `run.py` — call the asset hook

After `_setup_path(...)` and before `prepare_runtime()`, insert:

```python
        from session.paths import ensure_userdata
        from session.asset_pack import ensure_packed_assets

        ensure_userdata()
        ensure_packed_assets()
```

Keep every flag the updated `run.py` already has (`--follow-player`, `--action-view`, and anything newer).

`paths.py` must already define `ensure_userdata`. If `data_root` is missing, add only this function at the end of `Engine\session\paths.py`:

```python
def data_root() -> Path:
    """Engine data directory (Engine/data)."""
    return manmabot_root() / "data"
```

### 2.2 `Engine\session\player_monitor.py`

`reader_module()` must import the package first and only then fall back to a `.py` path. After Stage 2 the `.py` file is gone, so a path-only load reports “Memory monitor disconnected”.

Inside `reader_module()`, after the `sys.modules` cache check and before `spec_from_file_location`:

```python
    try:
        from app._01_perception import realtime_monitor_reader as module

        sys.modules[_MODULE_NAME] = module
        return module
    except Exception:
        pass
```

Leave `shared_monitor()` and `shutdown_shared_monitor()` as they are.

### 2.3 `Engine\session\pipe_client.py`

Same pattern for `memory_client`. Keep `format_memory_error` and any other helpers the updated file already has.

At the start of `_load_memory_client_module()`, after the cache check:

```python
    try:
        from app._01_perception import memory_client as mod

        _PIPE_CLIENT_MOD = mod
        return mod
    except Exception:
        pass
```

The `.py` path fallback stays under that block.

### 2.4 `UI\ui_qt\widgets\flow_layout.py`

Change only the empty flag constructor:

```python
        return Qt.Orientations(0)
```

`return Qt.Orientations()` crashes the map editor on Python 3.14 (`EnumType.__call__() missing 'value'`). If the updated file already passes a value, leave it.

### 2.5 Do not do these during a release

- Do not change hunt, retreat, login, or HP code to “make the build work”.
- Do not remove UI buttons that exist in the updated source. The schedule **Add** button stays if that source still has it.
- Do not read the live map id from the player struct, `+0x134`, or `CurrentMapId: 0`. The live id comes only from MapSubsystem: `mgr → holder → subs → MapSubsystem(vft) → +MapIdOff`.
- Do not put certificates, `accounts.json`, or this PC’s `UserData` into the customer folder.

### 2.6 Keep-scripts and `__init__.py` shims (every re-release)

Nuitka cannot `--module` compile `__init__.py` as a standalone file, and autologin
**must** spawn `Engine\autologin\bot\bot2.py` by path. Those files therefore stay
as `.py`, but they must be **thin shims**. Real logic lives in siblings that Stage 2
turns into `.pyd`:

| Keep-script (stays `.py`) | Body (compiled) |
|---------------------------|-----------------|
| `run.py` | `Engine\session\run_entry.py` |
| `Engine\autologin\bot\bot2.py` | `Engine\autologin\bot\bot2_core.py` |
| `launcher_manmabot.py` | (self-contained exe bootstrap — keep tiny) |

Fat package `__init__.py` files re-export from `_public.py` (or `UI\ui\fonts\bundled_fonts.py`).
Stage 2 compiles those siblings; the shim `__init__.py` remains a few lines.

Do not name a compiled sibling `loader.py`. On Python 3.14, Nuitka aborts in
`importlib._spec_from_module` (`nuitka_module_loader` has no `__name__`) and
`pythonw` then exits with no window.

**Before Stage 2 (dev tree and/or portable):**

```bat
python\python.exe packaging\verify_shims.py
python\python.exe packaging\verify_shims.py --portable
```

If `verify_shims` fails, move logic out of the keep-script / `__init__.py` — do not
raise the line limits to “make the build pass”.

Future installer / `data.pack` / Interception UX work is tracked in
`packaging\CUSTOMER_HARDENING_ROADMAP.md` (not part of this build loop yet).

---

## 3. Build commands

Open **cmd** (not a one-line PowerShell `-c` string; quoting breaks). From the updated product root:

```bat
cd /d <product-root>
set MANMABOT_BUILD_PYTHON=C:\Users\<you>\AppData\Local\Python\pythoncore-3.14-64\python.exe

python\python.exe packaging\build_release.py --stage 0

python\python.exe packaging\verify_shims.py

python\python.exe packaging\build_release.py --stage 1 --skip-python --no-checksums
python\python.exe packaging\verify_portable.py
python\python.exe packaging\verify_shims.py --portable

python\python.exe packaging\build_release.py --stage 2 --no-checksums
python\python.exe packaging\verify_stage2.py

python\python.exe packaging\build_release.py --stage 3 --no-checksums

python\python.exe packaging\build_release.py --stage 5 --no-checksums
python\python.exe packaging\verify_stage5.py

python\python.exe packaging\unpack_customer_data.py
release\portable\ManmabotV1\python\python.exe packaging\smoke_portable.py

python\python.exe packaging\build_release.py --stage 4 --skip-sign
python\python.exe packaging\verify_checksums.py
```

Order is mandatory: **1 → 2 → 3 → 5 → unpack → smoke → 4**.

- `--no-checksums` on stages 1–5 avoids hashing a tree you are about to change.
- `--skip-python` on Stage 1 is correct. Stage 3 copies the pruned runtime.
- `verify_stage5.py` must run **before** unpack. After unpack it fails on purpose, because `Engine\data` is a real folder and `data.pack` is gone.
- Stage 4 is last, so `SHA256SUMS` matches the folder you zip.
- Do not run Stage 4 again after someone has launched the bot. A launch writes logs and bytecode, and those get hashed.

Expected sizes from the version1 build (counts move when the source grows):

| Step | Result |
|------|--------|
| Stage 1 | about 3,800 files copied, Tools/Research denied |
| Stage 2 | about 280 modules, 30–40 minutes |
| Stage 3 | about 9,400 Python files, about 1.0 GB, `runtime import verify OK` |
| Stage 5 | `data.pack` and `analysis_text.pack` created, plain `Engine\data` removed from the **portable only** |
| Unpack | about 1,600 files restored under `Engine\data`, `data.pack` deleted |
| Stage 4 | checksum file written, signing skipped |

Stage 2 prints `development tree was not modified`. If a stage exits non-zero, stop. Do not continue with a half-built portable.

### 3.1 What each stage does

**Stage 0.** Checks `packaging\manifests\` and writes `release\version-info\BUILD.json`.

**Stage 1.** Deletes `release\portable\ManmabotV1` and copies `Engine`, `UI`, `Drivers`, and the root launchers. Applies `deny_globs.txt`. Seeds an empty `UserData`. Does not compile.

**Stage 2.** Compiles each non-init `.py` in the packages listed in `compile_packages.txt` to a `.pyd`, then deletes that `.py`. These scripts stay as `.py` (`keep_scripts.txt`):

- `run.py`
- `launcher_manmabot.py`
- `Engine\autologin\bot\bot2.py`

`__init__.py` and `__main__.py` also stay. Autologin starts `bot2.py` as a file. If it is compiled away, login dies before it can write a result.

**Stage 3.** Copies `python\` with the packages in `prune_site_packages.txt` removed (torch, ultralytics, pytest, Nuitka, PyInstaller, matplotlib, and similar). Keeps PySide6, numpy, OpenCV, PyYAML, scipy, onnxruntime, mss, keyboard, interception, pywin32.

**Stage 5.** Packs portable `Engine\data` into `data.pack` and deletes that plain folder. Packs analysis text (`.json`, `.txt`, `.yaml`, `.yml`, `.md`, `.bak`) into `analysis_text.pack` and deletes those text files. DLLs and EXEs in `Engine\analysis` stay, because Windows cannot `LoadLibrary` a file that exists only in memory. The development `Engine\data` is not touched.

**Unpack.** `unpack_customer_data.py` decrypts `data.pack` into `Engine\data` and deletes `data.pack`. `analysis_text.pack` stays.

**Smoke.** Uses the portable `python.exe`. Confirms OpenCV imports, `skills_names.json` and map `meta.yaml` are real files, `data.pack` is gone, `analysis_text.pack` exists, `bot2.py` and the `run.py` hook exist, and `FlowLayout.expandingDirections()` is `Qt.Orientations(0)`. It does not click Start and does not log into the game.

**Stage 4.** Writes `release\checksums\SHA256SUMS` and `release\portable\ManmabotV1\SHA256SUMS.txt`. `--skip-sign` does not call `signtool`.

---

## 4. Confirm the customer folder before you zip it

`release\portable\ManmabotV1` must contain:

- `run.py`, `launcher_manmabot.py`, `ZF.bat`
- `python\python.exe`
- `Engine\data\catalog\skills_names.json`
- `Engine\data\maps\<some map>\meta.yaml`
- `Engine\analysis_text.pack`
- `Engine\autologin\bot\bot2.py`
- `Drivers\SignedDriver\signeddrv.sys`
- `UI\` and `Engine\` `.pyd` files

It must **not** contain:

- `Engine\data.pack`
- `Tools\`, `Research\`, `Docs\`, `Others\`, `.cursor\`, `packaging\`
- `UserData\accounts.json` or another PC’s logs, schedules, or trial data
- a junction or symlink at `Engine\data`

`run.py` still calls `ensure_packed_assets()`. With no `data.pack` and a real `Engine\data`, the data mount does nothing. Analysis text still comes from `analysis_text.pack`.

---

## 5. What to give the customer

1. Zip **only** `release\portable\ManmabotV1`.
2. Optionally send `release\checksums\SHA256SUMS` beside the zip.
3. Tell them to keep the folder together, run `Driver_Install_Interception.bat` as administrator once, start the game client, then run `ZF.bat`.

Do not zip the product root. That zip would include source, Tools, and Research.

Accounts are encrypted with Windows DPAPI for the user who saved them. Copying `accounts.json` to another PC does not decrypt. The customer creates accounts on their own PC.

`UserData` “trial” is a local workspace name, not a license.

---

## 6. Later releases — changed files only

After the first portable exists, update it. Do not run Stage 1 again. Stage 1 stops if that folder is already there.

```bat
cd /d <product-root>
python\python.exe packaging\incremental_release.py --dry-run
python\python.exe packaging\incremental_release.py
```

The updater hashes the source files that would ship, including gitignored `*.png`, `*.dll`, `*.exe`, and `*.bat`. `git diff` is not used. A changed file is copied, or compiled when it is a Nuitka module. Unchanged `.pyd` files stay. Details: `packaging\INCREMENTAL_RELEASE.md`.

`--force-full` on Stage 1 deletes the customer folder and starts the first-release copy again. Use it only when the portable folder is missing or unusable, or when the bundled `python\` layout or the compile/deny manifests change in a way the updater reports it cannot apply. Throwing the folder away is:

```bat
rmdir /s /q release\portable
```

Then start at Stage 0 again. Do not reuse another folder’s `.pyd` files.

---

## 7. Checks that are in this document because they failed before

| ID | What broke | What the source must contain |
|----|------------|------------------------------|
| RBF-001 | Memory monitor disconnected after compile | `player_monitor.py` and `pipe_client.py` import the package, then fall back to `.py` |
| RBF-002 | Map editor blank, `expandingDirections` missing `value` | `flow_layout.py` returns `Qt.Orientations(0)` |
| RBF-003 | `RecursionError` at startup | `asset_store.py` must not call `os.path.abspath` after it hooks `isdir` |
| RBF-004 | `meta.yaml` missing on an `8.3` path such as `MANMAB~3` | `asset_store.py` expands short paths |
| RBF-005 | Same recursion **only inside the `.pyd`**, and `\\server\share` missed `skills_names.json` | `_BUSY` is a one-item list. `isfile` / `isdir` / `exists` keep the original function as a default argument. Paths are canonicalized with `GetFinalPathNameByHandleW` |

Details are in `packaging\RELEASE_BUGFIX_LOG.md`. Fix the source and rebuild. Dropping a loose `.py` next to a `.pyd` does nothing: Python loads the `.pyd`.

`verify_stage2.py` loads the player-monitor reader. If it fails, do not ship.

---

## 8. Failures this packaging does not remove

These showed up on a customer PC and are not fixed by a new zip:

- **`login_failed` with an empty detail.** Autologin starts `python\python.exe` on `Engine\autologin\bot\bot2.py`. That string is only the fallback when the child exits before writing `result.json`. If `UserData\logs` has no new `bot2_run.log` lines, the process died during import, before `main()`.
- **`ImportError: recursion is detected during loading of "cv2" binary extensions`.** OpenCV’s loader imported the `cv2` package again instead of `cv2.pyd`. On a good portable, `python\python.exe -c "import cv2; print(cv2.__version__)"` prints a version (5.0.0 on the version1 build). If that command fails on the customer PC, the copy is incomplete or another program is blocking the DLL. Re-copy the zip. Do not point them at a system Python.
- **SmartScreen** can block the elevated `python.exe` even when `pythonw.exe` (the UI) is already open.
- **ToDesk, WireGuard, an IME helper, or other injectors** can interfere with input or UAC. They are not a reason to change bot code during release.
- **Interception missing** falls back to SendInput. It does not by itself produce `login_failed`.
- **`signeddrv.sys` / the vulnerable-driver blocklist** runs only after login succeeds. It does not cause an empty `login_failed`.
- Killing the process can leave offset text under `Engine\analysis`. The next normal exit deletes it.

A local smoke does not prove hunt, loot, or login on another PC. Run that on a machine with the game if you need that sign-off.

---

## 9. Manifest edits (only if the tree shape changed)

| Change | File |
|--------|------|
| Root launcher renamed | `manifests\root_files.txt` |
| New top-level folder that must ship | `manifests\allow_roots.txt` |
| New path that must not ship | `manifests\deny_globs.txt` |
| New package to compile | `manifests\compile_packages.txt` |
| A `.py` that must stay a script | `manifests\keep_scripts.txt` |
| Another bundled library to drop | `manifests\prune_site_packages.txt` |

If the layout matches section 1, do not edit these.

---

## 10. Errors and what to do

**`unsupported embeddable CPython`.** Stage 2 used `python\python.exe`. Set `MANMABOT_BUILD_PYTHON` to the full 3.14.

**`to compile a package, specify its directory but, not the '__init__.py'`.** You copied an old `compile_inplace.py`. Copy the current `packaging\` folder again.

**Stage 3 `WinError 3` / path not found.** The product path is too long for a normal copy. Current `prune_python.py` uses `\\?\` extended paths. Copy the current `packaging\` and do not use a very deep folder name.

**`bot2.py` missing.** `keep_scripts.txt` must list `Engine/autologin/bot/bot2.py`. Rerun Stage 2 after fixing it.

**`verify_portable` says an analysis DLL is missing.** The updated `Engine\analysis` has sources but not the built DLL. The customer build cannot load memory without that DLL. Build the DLL in the source tree first. Do not ship `.c` files; `deny_globs.txt` already drops them.

**torch imports inside the portable.** Stage 3 did not run. Run it.

**Customer sees `FileNotFoundError` for `Engine\data\catalog\skills_names.json`.** `data.pack` was left in place and the plain folder was not restored, or the copy dropped `Engine\data`. Run `unpack_customer_data.py` and confirm the json file is on disk. Do not tell them the folder appears only after launch.

**Checksum verify fails right after a manual test launch.** You hashed a folder the bot had already written into, or you changed files after Stage 4. Delete runtime junk (`UserData\logs`, `UserData\autologin_runs`, new `__pycache__`) only if you created it, then run Stage 4 once more. Do not hash a tree the customer has used.

**`verify_stage5` fails after unpack.** Expected. Run it only while `data.pack` still exists.

---

## 11. Signing (later, not part of this release)

Leave this unset. Do not commit a certificate or password.

```bat
set MANMABOT_SIGN=1
set MANMABOT_SIGN_PFX=C:\secure\codesign.pfx
set MANMABOT_SIGN_PASSWORD=...
python\python.exe packaging\build_release.py --stage 4
```

Or `MANMABOT_SIGN_THUMBPRINT` instead of a PFX. Optional: `MANMABOT_SIGNTOOL`, `MANMABOT_SIGN_TIMESTAMP`.

---

## 12. When a customer build bug is fixed

1. Change the development source (`Engine`, `UI`, or `packaging`). Do not patch only `release\`.
2. Add an `RBF-00N` entry to `packaging\RELEASE_BUGFIX_LOG.md` (symptom, cause, files, how to verify).
3. Extend `verify_portable.py`, `verify_stage2.py`, `verify_stage5.py`, or `smoke_portable.py` if the failure can be detected without the game.
4. Rebuild with section 6. The next person should not need a manual file swap.

---

## 13. Printable checklist

- [ ] Updated folder was not pasted over an older product folder
- [ ] `packaging\` copied, including this file, `unpack_customer_data.py`, and `smoke_portable.py`
- [ ] `asset_pack.py`, `asset_pack_format.py`, `asset_store.py` copied
- [ ] `run.py`, `player_monitor.py`, `pipe_client.py`, `paths.py`, `flow_layout.py` merged, not blindly replaced
- [ ] `python\python.exe` is 3.14
- [ ] `MANMABOT_BUILD_PYTHON` is full 3.14 with `Python.h`, Nuitka installed, MSVC or MinGW available
- [ ] Stage 0 OK
- [ ] `verify_shims` OK (dev tree)
- [ ] Stage 1 and `verify_portable` OK
- [ ] `verify_shims --portable` OK
- [ ] Stage 2 and `verify_stage2` OK
- [ ] Stage 3 OK (`runtime import verify OK`)
- [ ] Stage 5 and `verify_stage5` OK **before** unpack
- [ ] `unpack_customer_data.py` OK (`data.pack` gone, `Engine\data` present)
- [ ] `smoke_portable.py` prints `SMOKE OK`
- [ ] Stage 4 `--skip-sign` and `verify_checksums` OK
- [ ] Zip is only `release\portable\ManmabotV1`
- [ ] No accounts, logs, Tools, or Research in that zip

---

## 14. Files this playbook uses

| File | Role |
|------|------|
| `packaging\build_release.py` | Stages 0–5. Stage 1 refuses when a customer folder already exists |
| `packaging\incremental_release.py` | Later releases: copy or compile only changed files |
| `packaging\release_snapshot.py` | Hash record of shippable inputs, including gitignored files |
| `packaging\INCREMENTAL_RELEASE.md` | How to run an update after the first release |
| `packaging\compile_inplace.py` | Stage 2 |
| `packaging\prune_python.py` | Stage 3 |
| `packaging\pack_assets.py` | Stage 5 |
| `packaging\unpack_customer_data.py` | Restore `Engine\data`, delete `data.pack` |
| `packaging\smoke_portable.py` | Local portable check, no game login |
| `packaging\verify_portable.py` | After Stage 1 |
| `packaging\verify_shims.py` | Keep-scripts / `__init__.py` stay thin (§2.6) |
| `packaging\verify_stage2.py` | After Stage 2, including the memory reader |
| `packaging\verify_stage5.py` | After Stage 5, before unpack |
| `packaging\verify_checksums.py` | After Stage 4 |
| `packaging\sign_release.py` | Used only if signing is turned on |
| `packaging\RELEASE_BUGFIX_LOG.md` | Why the merges in section 2 exist |
| `packaging\SENSITIVE_ASSETS.md` | What Stage 5 packs, and why analysis DLLs stay plain |
| `packaging\CUSTOMER_HARDENING_ROADMAP.md` | Future installer / pack / Interception UX (not in build loop yet) |
| `packaging\manifests\` | Copy, deny, compile, and prune lists |
