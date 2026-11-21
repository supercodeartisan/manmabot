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
