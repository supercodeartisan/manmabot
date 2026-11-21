"""Customer distribution metadata — no private keys, no raw CEK."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .store import SellerStore

_FORBIDDEN = re.compile(
    r"(BEGIN (PRIVATE|RSA PRIVATE|ENCRYPTED PRIVATE) KEY"
    r"|wrapped_cek"
    r"|\"cek\"\s*:\s*\"[0-9a-fA-F]{64}\""
    r"|vault_key)",
    re.IGNORECASE,
)


def generate_artifact(
    store: SellerStore,
    *,
    license_id: str,
    license_key: str,
    out_path: Path | None = None,
) -> dict:
    row = store.db().conn.execute(
        "SELECT * FROM licenses WHERE license_id = ?",
        (license_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"unknown license_id: {license_id}")
    cfg = store.config()
    artifact = {
        "format_version": 1,
        "product_id": row["product_id"],
        "license_id": license_id,
        "license_key": license_key,
        "cek_id": row["cek_id"],
        "signing": {
            "current_kid": cfg.get("current_kid"),
            "previous_kid": cfg.get("previous_kid"),
            "note": "Public keys are pinned in the client build, not this file.",
        },
        "activation": {
            "mode": "hybrid_first_online",
            "note": "Customer sends license_key + device SPKI; server returns ticket+envelope.",
        },
    }
    verify_artifact_dict(artifact)
    path = out_path or (store.root / "artifacts" / f"{license_id}.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(artifact, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return {"path": str(path), "artifact": artifact}


def verify_artifact_dict(artifact: dict) -> None:
    if "license_id" not in artifact or "product_id" not in artifact:
        raise RuntimeError("artifact missing license_id/product_id")
    if "cek_id" not in artifact:
        raise RuntimeError("artifact missing cek_id reference")
    # Must not embed secrets beyond the customer license_key.
    blob = json.dumps(artifact)
    if _FORBIDDEN.search(blob):
        raise RuntimeError("artifact contains forbidden secret material")
    # Reject accidental PEM private blocks even if regex missed.
    if "BEGIN PRIVATE KEY" in blob.upper() or "BEGIN RSA PRIVATE" in blob.upper():
        raise RuntimeError("artifact must not contain private key material")


def verify_artifact_file(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(obj, dict):
        raise RuntimeError("artifact must be a JSON object")
    verify_artifact_dict(obj)
    return {"path": str(path), "ok": True, "license_id": obj.get("license_id")}
