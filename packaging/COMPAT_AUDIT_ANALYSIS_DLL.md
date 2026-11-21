# Compat audit — Analysis DLL file paths (Phase 1)

**Status:** Source audit complete (V102-06 / F-13). No bot decision/login/combat logic changed.  
**Date:** 2026-11-20

## Verdict

| Track | Result |
|-------|--------|
| `realtime_monitor` offsets path injection | **OK — absolute path argument** |
| Sibling files next to `offsets.json` | **OK — `g_dataDir` from that path** |
| Analysis text materialize target | **Must use isolated TEMP** (current overlay writes `Engine/analysis/`) |
| CWD-relative fallbacks | **Present** — must not rely on them in customer pack mode |
| Multi-instance via CWD | **Risk in LCAPI modules** (`SetCurrentDirectoryA`) — prefer absolute TEMP paths |
| VFS / API hook | Phase 1 **out of scope** |

**Phase 1 Blocker:** none for realtime_monitor path injection.  
**Follow-ups:** TEMP root + absolute path wiring; LCAPI CWD modules need per-call absolute paths or documented single-instance constraint.

---

## 1. How DLLs open analysis text

### 1.1 `realtime_monitor` (P0 for live pose / mapId)

Source: `Engine/analysis/src/listen/realtime_monitor_full.c`

| Question | Evidence |
|----------|----------|
| Path as argument? | **Yes.** Export `realtime_monitor_snapshot(const char* offsetsPath, ...)` → `monitorEnsure` → `loadOffsets(path)`. |
| Config file? | Primary path is the argument; optional `offsets_discovered.json` resolved beside it. |
| CWD relative? | **Fallback only:** `loadOffsets(NULL)` / exe `main` uses `"offsets.json"`. DLL path from Python should always be absolute. |
| Hardcoded only? | **No** for the DLL export path. |
| TEMP inject possible? | **Yes** — pass absolute `...\manmabot_an_<id>\registry\offsets.json`. `rememberDataDir` sets `g_dataDir` to that directory; `pathInDataDir` opens siblings under the same root. |

### 1.2 Python caller

`Engine/app/_01_perception/native_realtime_monitor_reader.py` defaults to  
`Engine/analysis/registry/offsets.json`.  
Customer pack mode must pass the **materialized absolute** path (today: overlay under `Engine/analysis` via `ensure_analysis_text_pack`).

### 1.3 Other fopen / CreateFile users

| Area | API | Path style | Pack relevance |
|------|-----|------------|----------------|
| `signeddrv_client.c` | `CreateFileW` | Device `\\.\...` | Not analysis_text |
| `lcreg.h` / LCAPI | `fopen`, `SetCurrentDirectoryA` | Often EXE/base relative | Registry/text modules — need absolute roots |
| `lcore.h` T3_maps | `fopen` | `root/...` or `T3_maps/...` | Map obstacle bins — typically not in `analysis_text.pack` |
| inventory / hotbar / shop listen | `fopen` | module-relative or CWD | Offset txt/json — same materialize list as Stage 5 |
| `lcapi_engine.c` | `LoadLibraryA`, `FindFirstFileA` | DLL dir | Loads `.dll` only (plain ship) |

---

## 2. Materialize list (analysis_text → disk for DLL)

Aligned with `packaging/pack_assets.py` Stage 5 analysis pack contents (offsets / tables). At runtime, extract under:

```text
%TEMP%\manmabot_an_<128-bit-hex>\
```

Requirements (spec F-12 / §0.2):

- Per-process unique dir; restrictive ACL; no reparse follow on open
- Pass **absolute** paths into DLL APIs that accept them
- Wipe on clean exit; next start recreates
- Do **not** leave plain texts in shipped `Engine/analysis/` after Stage 5

Current gap: `session/asset_pack.ensure_analysis_text_pack` writes into `Engine/analysis/` and atexit-unlinks. Phase 1 hardening should relocate to TEMP and point readers at that root (no decision-logic change).

---

## 3. CWD / multi-instance (F-13)

| Finding | Impact |
|---------|--------|
| `realtime_monitor` uses absolute `offsetsPath` when provided | Multi-instance OK if each process has its own TEMP tree + path |
| LCAPI comments + `SetCurrentDirectoryA` in `lcreg.h` / `lcapi_engine.c` | Concurrent instances can race CWD; **do not** rely on CWD for pack files |
| Mitigation | Always absolute TEMP paths; avoid changing process CWD for asset IO |

If a future module **only** opens hardcoded relative names with no inject API → record **Blocker** (VFS = Phase 2). None found for the primary realtime_monitor path.

---

## 4. Short-path / UNC

Not proven in this pass. Customer smoke should cover:

- 8.3 short names on / off  
- Long path under TEMP  
- No UNC dependency for analysis_text (local TEMP only)

---

## 5. Next implementation hooks (no code in this audit)

1. `Engine.crypto` / runtime: AuthorizedSession → MMB2 read of `analysis_text` + `data.pack`.  
2. Replace MMBA v1 in Stage 5 with MMB2 (after vault/CEK).  
3. Change materialize root to `%TEMP%\manmabot_an_*` and thread absolute offsets path into `realtime_monitor_snapshot`.  
4. Keep bot decision / login / combat / HP / MapSubsystem paths untouched.
