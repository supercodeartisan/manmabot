"""CEK epoch management — vault reuse, no alternate crypto."""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

from ..constants import CEK_LEN, PACK_ID_LEN
from ..license_server.vault import VaultError, mask_cek
from .store import SellerStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def new_cek_id() -> str:
    return str(uuid.uuid4())


def create_cek(store: SellerStore, *, product_id: str | None = None, cek_id: str | None = None) -> dict:
    cfg = store.config()
    product_id = product_id or cfg.get("product_id")
    if not product_id:
        raise RuntimeError("product_id required")
    cek_id = cek_id or new_cek_id()
    cek = os.urandom(CEK_LEN)
    try:
        store.vault().store(cek_id=cek_id, product_id=product_id, cek=cek)
    except VaultError as e:
        raise RuntimeError(str(e)) from e
    return {
        "cek_id": cek_id,
        "product_id": product_id,
        "cek_len": CEK_LEN,
        "fingerprint": mask_cek(cek),
        "note": "raw CEK is vault-only; never embed in customer artifacts",
    }


def inspect_cek(store: SellerStore, cek_id: str) -> dict:
    row = store.db().conn.execute(
        "SELECT cek_id, product_id, created_at FROM cek_vault WHERE cek_id = ?",
        (cek_id,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"unknown cek_id: {cek_id}")
    cek = store.vault().load(cek_id)
    return {
        "cek_id": row["cek_id"],
        "product_id": row["product_id"],
        "created_at": row["created_at"],
        "cek_len": len(cek),
        "fingerprint": mask_cek(cek),
    }


def rotate_cek(store: SellerStore, *, product_id: str | None = None) -> dict:
    """New epoch = new cek_id + new CEK (never reuse cek_id for a new CEK)."""
    return create_cek(store, product_id=product_id, cek_id=new_cek_id())


def reserve_pack_id(store: SellerStore, *, cek_id: str, note: str = "") -> dict:
    """Atomically reserve a new pack_id under cek_id (never reuse)."""
    if not store.vault().exists(cek_id):
        raise RuntimeError(f"cek_id not in vault: {cek_id}")
    pack_id = os.urandom(PACK_ID_LEN)
    store.db().conn.execute(
        """
        INSERT INTO pack_id_reservations(cek_id, pack_id, note, reserved_at)
        VALUES (?, ?, ?, ?)
        """,
        (cek_id, pack_id, note or "seller-cli", _utc_now()),
    )
    return {
        "cek_id": cek_id,
        "pack_id": pack_id,
        "pack_id_hex": pack_id.hex(),
        "note": "rebuild always gets a new pack_id; reserved ids are never reused",
    }


def assert_same_cek_id_same_bytes(store: SellerStore, cek_id: str, cek: bytes) -> None:
    """Policy helper for tests / packaging."""
    existing = store.vault().load(cek_id)
    if existing != cek:
        raise RuntimeError("same cek_id must map to the same CEK bytes")
