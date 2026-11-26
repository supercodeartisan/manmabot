# Stage 5 → MMB2

## Build (seller machine)

```bat
REM SellerData must already have signing key + CEK epoch
set PYTHONPATH=Engine
python -m crypto.seller_cli cek create
REM note cek_id from output (fingerprint only — no raw CEK)

python packaging\pack_assets.py --cek-id <cek_id>
python packaging\verify_stage5.py
```

Env alternatives: `MANMABOT_CEK_ID`, `MANMABOT_SELLER_DATA`.

Transition: `--legacy-mmba` still builds MMBA v1.

## Pipeline

1. Snapshot source bytes (mid-build edits ignored)
2. `reserve_pack_id` under vault `cek_id` (**distinct** pack_id for `data.pack` vs `analysis_text.pack`)
3. Vault load CEK → `write_pack` (MMB2) for each pack
4. Independent `Mmb2Reader` round-trip verify **before any publish**
5. Atomic publish both packs (`*.partial` → `os.replace`)
6. Publish `Engine/BUILD.json` **last** (`build_id`, `cek_id`, per-pack `sha256` + `pack_id_hex`, Ed25519 `kid`+`signature` over JCS core — **no CEK / no new key hierarchy**)

Runtime (`ensure_packed_assets`) refuses MMB2 packs when BUILD.json is missing, signature fails (trusted kid), or sha256/pack_id mismatched (mixed-build + tamper protection).

After a successful ensure, `run_entry` calls `body_pose.refresh_offsets()` so stand/walk VFTs and MyPlayer find anchors load from the analysis TEMP overlay (`entity_offsets.txt` / `LC930_REGISTRY.txt` inside `analysis_text.pack`). Without that refresh, pack-only builds log `body pose: action slot unread` (RBF-008).

`analysis_text.pack` also carries `dll/*.dll` and `.csv` (RBF-009; skips `*.new.dll`). Data-only republish **carry-forwards** the on-disk analysis pack into `BUILD.json` so both packs stay sha256-pinned. Readers resolve DLLs via `analysis_dll_path` (TEMP overlay first).

After pack strip (and again in Stage 4), empty product directories are removed except `UserData/` and bundled `python/` (RBF-010).

Startup splash logo (`Engine/data/logo.png`) lives inside the pack; GDI+ cannot read the RAM mount directly. Runtime materializes a temp file in `startup_splash._load_logo` — **no extra Stage 5 unpack step for logo.**

## E2E (unit / integration)

`Engine/crypto/tests/test_e2e_customer_activation.py` — Seller → packs → activation → offline reload → TEMP.  
Not a substitute for Pack-only in-game / hunting baseline.

## License / DeviceKey (customer activation)

First install: TPM with retries, then Soft+DPAPI if TPM fails — see
`Engine/crypto/LICENSE_HANDBOOK.md`. Recompile portable `crypto` / `session`
modules after DeviceKey policy changes (incremental release).

## Not done (release gates)

Pack-only in-game, hunting baseline, multi-instance in-game, TPM ACL / NCrypt
hardening (Soft fallback already covers activation compatibility).
