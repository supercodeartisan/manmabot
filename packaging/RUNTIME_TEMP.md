# Runtime TEMP / pack wiring (Phase 1)

## Flow

```text
run_entry.main
  → wipe_stale_analysis_temps()
  → ensure_packed_assets()
       → data.pack     → load_pack_files (MMB2|MMBA) → asset_store.mount_bytes
       → analysis_text → load_pack_files → %TEMP%/manmabot_an_<128bit>/ + overlay
  → body_pose.refresh_offsets()   # bind MGR / MyPlayer / stand-walk VFTs from overlay
  → RealtimeMonitorReader(default_offsets_path) → absolute TEMP …/registry/offsets.json
```

## Rules

- No public `decrypt(path, cek)` API — CEK only via `AuthorizedSession` / `Mmb2Reader`.
- Dev plain `Engine/data` → data pack skipped.
- No analysis pack → overlay cleared; readers use `Engine/analysis`.
- MMB2 requires `UserData/license/{ticket,envelope}.json` + trusted kid (seller keygen) unless tests pass `session=` into `load_pack_files`.
- Login / move / combat / HP / party **decision** logic unchanged.
- Offset **text** readers must use `analysis_registry_file` / `source_registry` (overlay first). Do not hardcode `Engine/analysis/registry/…` next to `__file__` — that breaks pack-only and surfaces as `body pose: action slot unread` / `moving=unread` (see `RELEASE_BUGFIX_LOG.md` RBF-008).

## Multi-instance

Each process creates its own `manmabot_an_*` with `owner.pid` + lock. Stale dirs (dead pid) are wiped; live dirs are protected.
