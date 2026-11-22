# License handbook (seller + customer)

Use this for every customer release that ships MMB2 packs.  
Companion: `OOB_ACTIVATION.md` (file exchange details), `seller_cli/README.md`.

## What the customer receives

- Zip of `release\portable\ManmabotV1` only (never `Seller\` / `SellerData`)
- One license key string (`MMB-…`)
- No HWID collection before purchase
- Pack-only assets: `Engine\data.pack` + `Engine\analysis_text.pack` (MMB2, same CEK epoch) and `Engine\BUILD.json` pinning both sha256 values. Analysis pack holds offset text, `item_name_kr.csv`, and `dll/*.dll`; those materialize under `%TEMP%` at runtime (not left plain in the zip). Empty research folders under `Engine\analysis` are collapsed at Stage 4.

## What stays on the seller PC

- Entire `Seller\` folder (`SellerData` vault, `license.db`, signing keys, artifacts)
- Backup this folder; losing it breaks CEK/signing continuity for that epoch

## UI look

Customer License window and `Seller\Seller_License_Tool` use the same classic Qt
theme as the main ZF console (`ui_qt.theme`: chrome panels, accent buttons,
status strip, brand icon). Activation steps are unchanged.

## Activation flow (OOB, no HTTP server)

1. Customer runs `ZF.bat` → License window (ko/zh)
2. Enters key → **Create request file** → sends `activation_request.json` to seller
3. Seller **Fulfill** → sends response JSON only (no raw CEK)
4. Customer **Select response file** / paste wire → Apply
5. Later launches are offline on that PC

Request TTL default **48h**. One license → one device until seller **Reset binding**.

## DeviceKey (TPM then Soft) — customer PC binding

On first activation the client creates a per-PC RSA DeviceKey:

1. Try Windows TPM (NCrypt), with a short retry loop
2. If TPM probe/create still fails (transient / denied / unknown / absent) → **Soft + DPAPI**
3. Request file embeds that device public key; seller wraps CEK to it

**After Soft is chosen for a PC, that install stays Soft** (meta in `UserData\license\device_key\`).  
Do not delete Soft keys and expect TPM to take over without a seller reset + new request.

Already activated with **meta=tpm**: TPM temporary failure does **not** auto-switch to Soft (would break the ticket). Customer retries / seller reset if the TPM key is gone.

Optional test-only override: `MANMABOT_FORCE_SOFT_DEVICE=1` (or `session.oob_activation --force-soft`). Not for normal customers.

### Customer-facing guidance (if activation request fails)

1. Press **Create request file** again (retries are automatic inside the app as well)
2. Reboot once, then retry
3. If it still fails, contact seller (rare after Soft fallback)

Seller does **not** need `tpm.msc` steps for Soft-fallback builds; those were for the older “Soft forbidden on transient” policy.

## Files on the customer PC after success

| Path | Required? |
|------|-----------|
| `UserData\license\ticket.json` | **Yes** |
| `UserData\license\envelope.json` | **Yes** |
| `UserData\license\device_key\` | **Yes** (TPM and/or Soft material) |
| `activation_response.applied.json` | No (audit meta) |
| `activation_request.json` | No (removed after successful apply) |

## Seller daily checklist

1. `Seller\Seller_License_Tool.bat`
2. Create key → send key + zip
3. Fulfill customer request → send response only
4. PC change → Reset binding → customer new request
5. Never ship `Seller\` inside the customer zip

## Release note for packagers

After changing `Engine/crypto/device_key.py` (or license UI), run an **incremental release** so portable `.pyd` picks up the Soft-fallback policy before the next customer zip.

Pack-only customer builds also need `MANMABOT_CEK_ID` + `MANMABOT_SELLER_DATA` so Stage 5 / incremental keep **both** packs in `BUILD.json` (carry-forward when only one side rebuilds). Confirm with `packaging\verify_stage5.py`. Details: `packaging\RELEASE_PLAYBOOK.md`, `SENSITIVE_ASSETS.md`, `RUNTIME_TEMP.md`, RBF-008…010 in `RELEASE_BUGFIX_LOG.md`.
