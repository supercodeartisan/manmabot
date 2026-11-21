"""License provisioning through existing ActivationService / ResetService."""

from __future__ import annotations

import secrets
import uuid
from datetime import datetime, timezone

from ..license_server.activation import ActivationService
from ..license_server.reset import ResetService
from .signing import load_private
from .store import SellerStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _license_key() -> str:
    # Customer-facing key material (not CEK, not signing key).
    return "MMB-" + secrets.token_urlsafe(24)


def create_license(
    store: SellerStore,
    *,
    cek_id: str,
    product_id: str | None = None,
    license_id: str | None = None,
    customer_label: str = "",
    seller_note: str = "",
) -> dict:
    cfg = store.config()
    product_id = product_id or cfg.get("product_id")
    if not product_id:
        raise RuntimeError("product_id required")
    if not store.vault().exists(cek_id):
        raise RuntimeError(f"cek_id not in vault: {cek_id}")
    cek = store.vault().load(cek_id)
    license_id = license_id or str(uuid.uuid4())
    license_key = _license_key()
    label = (customer_label or "").strip()
    note = (seller_note or "").strip()

    kid, sk = load_private(store)
    svc = ActivationService(store.db(), store.vault(), signing_key=sk, signing_kid=kid)
    # Provision via existing License Server API (no bypass).
    svc.issue_license(
        license_id=license_id,
        product_id=product_id,
        cek_id=cek_id,
        license_key=license_key,
        cek=cek,
    )
    store.db().conn.execute(
        """
        UPDATE licenses
        SET customer_label = ?, seller_note = ?, updated_at = ?
        WHERE license_id = ?
        """,
        (label, note, _utc_now(), license_id),
    )
    return {
        "license_id": license_id,
        "license_key": license_key,
        "product_id": product_id,
        "cek_id": cek_id,
        "customer_label": label,
        "seller_note": note,
        "status": "issued",
        "signing_kid": kid,
    }


def set_customer_label(
    store: SellerStore,
    license_id: str,
    *,
    customer_label: str = "",
    seller_note: str | None = None,
) -> dict:
    """Attach / update seller-side account name for an existing license."""
    row = store.db().conn.execute(
        "SELECT license_id FROM licenses WHERE license_id = ?",
        (license_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"unknown license_id: {license_id}")
    label = (customer_label or "").strip()
    if seller_note is None:
        store.db().conn.execute(
            "UPDATE licenses SET customer_label = ? WHERE license_id = ?",
            (label, license_id),
        )
    else:
        store.db().conn.execute(
            "UPDATE licenses SET customer_label = ?, seller_note = ? WHERE license_id = ?",
            (label, (seller_note or "").strip(), license_id),
        )
    return inspect_license(store, license_id)


def inspect_license(store: SellerStore, license_id: str) -> dict:
    row = store.db().conn.execute(
        "SELECT * FROM licenses WHERE license_id = ?",
        (license_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"unknown license_id: {license_id}")
    binding = store.db().conn.execute(
        "SELECT device_id, binding_generation, activation_id, bound_at FROM bindings WHERE license_id = ?",
        (license_id,),
    ).fetchone()
    keys = set(row.keys())
    return {
        "license_id": row["license_id"],
        "product_id": row["product_id"],
        "cek_id": row["cek_id"],
        "status": row["status"],
        "created_at": row["created_at"],
        "customer_label": row["customer_label"] if "customer_label" in keys else "",
        "seller_note": row["seller_note"] if "seller_note" in keys else "",
        "binding": dict(binding) if binding else None,
        # Never expose license_key (only hash stored) or CEK.
        # Plain key (if saved) lives under SellerData/artifacts/<license_id>.json
    }


def reset_license(store: SellerStore, license_id: str, *, reason: str, admin_id: str) -> dict:
    """Binding reset via existing ResetService (audit + generation)."""
    return ResetService(store.db()).reset_binding(
        license_id=license_id,
        reason=reason,
        admin_id=admin_id,
    )


def set_license_status(store: SellerStore, license_id: str, status: str) -> None:
    kid, sk = load_private(store)
    svc = ActivationService(store.db(), store.vault(), signing_key=sk, signing_kid=kid)
    svc.set_status(license_id, status)
