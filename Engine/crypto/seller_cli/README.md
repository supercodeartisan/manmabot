# Seller Keygen CLI

**Seller machine only.** Prefer UI: `Seller\Seller_License_Tool.bat`  
Vault lives in `Seller\SellerData\` (legacy: root `SellerData\`).  
Never ship `Seller/` or Ed25519 private keys / vault key / raw CEK.

```bat
cd <product>
set PYTHONPATH=Engine
python -m crypto.seller_cli signing-key create
python -m crypto.seller_cli signing-key export-public
python -m crypto.seller_cli cek create
python -m crypto.seller_cli license create --cek-id <uuid>
python -m crypto.seller_cli artifact generate --license-id <id> --license-key <key>
python -m crypto.seller_cli fulfill --request path\to\activation_request.json
```

OOB activation (no HTTP server): see `Engine/crypto/OOB_ACTIVATION.md`.  
Full seller/customer handbook: `Engine/crypto/LICENSE_HANDBOOK.md`.

Optional: `MANMABOT_SELLER_DATA` or `--seller-data`.

## Security rules

1. Pin exported `trusted_kids.json` public keys in the client; unknown kid → reject.
2. Private signing key stays under `Seller/SellerData/signing/private/`.
3. Same `cek_id` ⇒ same CEK; rotate ⇒ new `cek_id`; pack rebuild ⇒ `cek reserve-pack-id`.
4. Licenses go through existing License Server (`issue_license` / `ResetService`).
5. No new crypto hierarchy — vault + Ed25519 + MMB2 only.

## Not Phase-1 complete

This CLI is a provisioning tool. Pack-only in-game + hunting baseline + Stage5 MMB2 remain release gates.
