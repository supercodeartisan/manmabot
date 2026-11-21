"""Seller-side OOB fulfill — SellerData only; never ship this package to customers."""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..license_server.activation import (
    ActivationError,
    ActivationService,
    ActivationStatus,
)
from ..oob_activation import (
    OobActivationError,
    build_activation_response,
    encode_wire,
    load_request_file_or_wire,
    validate_activation_request,
    write_json,
    RSP_PREFIX,
)
from .signing import load_private
from .store import SellerStore


def fulfill(
    store: SellerStore,
    request_path_or_wire: str | Path,
    *,
    out_path: Path | None = None,
) -> dict:
    request = load_request_file_or_wire(request_path_or_wire)
    activate_body = validate_activation_request(request)
    kid, sk = load_private(store)
    svc = ActivationService(store.db(), store.vault(), signing_key=sk, signing_kid=kid)
    try:
        result = svc.activate(activate_body)
    except ActivationError as e:
        raise OobActivationError(f"fulfill failed ({int(e.status)}): {e.message}") from e
    if result.status != ActivationStatus.OK:
        raise OobActivationError(f"fulfill status {result.status}")

    key_hash = hashlib.sha256(activate_body["license_key"].encode("utf-8")).hexdigest()
    row = store.db().conn.execute(
        "SELECT license_id, product_id, cek_id FROM licenses WHERE license_key_hash = ?",
        (key_hash,),
    ).fetchone()
    if row is None:
        raise OobActivationError("license vanished after activate")

    resp = build_activation_response(
        activate_body=result.body,
        license_id=row["license_id"],
        product_id=row["product_id"],
        cek_id=row["cek_id"],
        kid=kid,
        request_id=activate_body["request_id"],
    )
    path = out_path or (
        store.root / "artifacts" / f"response-{activate_body['request_id']}.json"
    )
    write_json(path, resp)
    return {
        "path": str(path),
        "wire": encode_wire(RSP_PREFIX, resp),
        "response": resp,
        "license_id": row["license_id"],
        "device_id": activate_body["device_id"],
        "status": "ok",
        "note": "Send response JSON (or wire) to customer. Never send SellerData.",
    }
