# License Server (seller-side, Phase 1)

Not shipped to customers. Python API over SQLite (`BEGIN IMMEDIATE`).

## Modules

| Module | Role |
|--------|------|
| `db.py` | Schema: licenses, bindings, activation_requests, binding_resets, cek_vault |
| `activation.py` | Validate → idempotency → bind → OAEP envelope → Ed25519 ticket |
| `vault.py` | AES-256-GCM CEK at rest; `mask_cek` for logs |
| `reset.py` | Clear binding, audit, block old `device_id` reactivation |
| `spki.py` | SPKI DER normalize, RSA-2048 / e=65537, `device_id` |

## JCS

All hashes/signatures use **RFC 8785** via Trail of Bits `rfc8785` (`Engine.crypto.jcs`).

## Activate (happy path)

```python
from Engine.crypto.license_server import (
    LicenseDatabase, CekVault, ActivationService, ResetService,
)
```

1. `issue_license(...)` — store CEK in vault, status=`issued`
2. Client sends activation body (`request_id` UUID v4, `license_key`, SPKI, `device_id`, `client_nonce` 32B)
3. `ActivationService.activate(body)` → `{ticket, envelope}`

## Completion checklist

- [x] Activation API + SQLite transactions
- [x] Idempotency + 8-thread concurrent same `request_id`
- [x] Envelope / Ticket issue + client verify
- [x] Vault / Reset / Audit tests

HTTP front-end is optional later; this package is the authority.
