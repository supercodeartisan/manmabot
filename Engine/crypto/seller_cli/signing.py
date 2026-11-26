"""Ed25519 signing key management (seller-side private keys only)."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .store import SellerStore


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def canonical_kid(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return "e1-" + hashlib.sha256(raw).hexdigest()[:24]


def create_signing_key(store: SellerStore, *, promote_current: bool = True) -> dict:
    sk = Ed25519PrivateKey.generate()
    pk = sk.public_key()
    kid = canonical_kid(pk)
    priv_pem = sk.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = pk.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    priv_path = store.private_key_path(kid)
    if priv_path.is_file():
        raise RuntimeError(f"signing key already exists: {kid}")
    priv_path.write_bytes(priv_pem)
    try:
        import os

        os.chmod(priv_path, 0o600)
    except OSError:
        pass
    store.public_key_path(kid).write_bytes(pub_pem)

    cfg = store.config()
    role = "current"
    if promote_current:
        prev = cfg.get("current_kid")
        if prev and prev != kid:
            cfg["previous_kid"] = prev
            store.db().conn.execute(
                """
                UPDATE signing_keys_meta SET role = 'previous'
                WHERE kid = ? AND role = 'current'
                """,
                (prev,),
            )
        cfg["current_kid"] = kid
    store.save_config(cfg)

    store.db().conn.execute(
        """
        INSERT INTO signing_keys_meta(kid, role, created_at, public_pem)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(kid) DO UPDATE SET
            role=excluded.role,
            public_pem=excluded.public_pem
        """,
        (kid, role, _utc_now(), pub_pem.decode("ascii")),
    )
    return {
        "kid": kid,
        "role": role,
        "public_pem_path": str(store.public_key_path(kid)),
        "private_pem_path": str(priv_path),
        "note": "PRIVATE KEY IS SELLER-ONLY — never ship to customers",
    }


def load_private(store: SellerStore, kid: str | None = None) -> tuple[str, Ed25519PrivateKey]:
    cfg = store.config()
    kid = kid or cfg.get("current_kid")
    if not kid:
        raise RuntimeError("no current signing kid; run signing-key create")
    path = store.private_key_path(kid)
    if not path.is_file():
        raise RuntimeError(f"private key missing for kid={kid}")
    sk = serialization.load_pem_private_key(path.read_bytes(), password=None)
    if not isinstance(sk, Ed25519PrivateKey):
        raise RuntimeError("not Ed25519 private key")
    return kid, sk


def load_public(store: SellerStore, kid: str) -> Ed25519PublicKey:
    path = store.public_key_path(kid)
    if not path.is_file():
        raise RuntimeError(f"public key missing for kid={kid}")
    pk = serialization.load_pem_public_key(path.read_bytes())
    if not isinstance(pk, Ed25519PublicKey):
        raise RuntimeError("not Ed25519 public key")
    return pk


def inspect_signing(store: SellerStore) -> dict:
    cfg = store.config()
    rows = store.db().conn.execute(
        "SELECT kid, role, created_at FROM signing_keys_meta ORDER BY created_at"
    ).fetchall()
    return {
        "current_kid": cfg.get("current_kid"),
        "previous_kid": cfg.get("previous_kid"),
        "keys": [dict(r) for r in rows],
        "private_dir": str(store.root / "signing" / "private"),
    }


def export_public_trust_bundle(store: SellerStore, out_path: Path | None = None) -> dict:
    """
    Client-pinnable public keys only (current + previous).
    Never includes private keys.
    """
    from pathlib import Path

    cfg = store.config()
    kids: dict[str, str] = {}
    for role_kid in (cfg.get("current_kid"), cfg.get("previous_kid")):
        if not role_kid:
            continue
        pem = store.public_key_path(role_kid).read_text(encoding="ascii")
        kids[role_kid] = pem
    bundle = {
        "format_version": 1,
        "product_id": cfg.get("product_id"),
        "kids": kids,
        "note": "Pin these public keys in the client build. Unknown kid → reject.",
    }
    path = out_path or (store.root / "signing" / "trusted_kids.json")
    path.write_text(json_dumps(bundle), encoding="utf-8")
    # Also write a copy under Engine/session for runtime pin (public only).
    engine_pin = Path(__file__).resolve().parents[2] / "session" / "trusted_kids.json"
    engine_pin.write_text(json_dumps(bundle), encoding="utf-8")
    return {"path": str(path), "engine_pin": str(engine_pin), "kids": list(kids.keys())}


def json_dumps(obj: dict) -> str:
    import json

    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def trusted_public_map(store: SellerStore) -> dict[str, Ed25519PublicKey]:
    cfg = store.config()
    out: dict[str, Ed25519PublicKey] = {}
    for kid in (cfg.get("current_kid"), cfg.get("previous_kid")):
        if kid:
            out[kid] = load_public(store, kid)
    return out
