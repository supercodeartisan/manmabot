"""Activation API — validation, idempotency, binding, envelope+ticket."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..jcs import dumps as jcs_dumps, loads_strict
from ..soft_key import oaep_encrypt_cek
from ..ticket import envelope_hash_hex, sign_ticket
from .db import LicenseDatabase
from .spki import SpkiError, device_id_hex, load_rsa_public, normalize_spki_der
from .vault import CekVault, mask_cek

_UUID_V4 = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


class ActivationStatus(int, Enum):
    OK = 200
    CONFLICT = 409
    BAD_REQUEST = 400
    FORBIDDEN = 403
    NOT_FOUND = 404


class ActivationError(Exception):
    def __init__(self, status: ActivationStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class ActivationResult:
    status: ActivationStatus
    body: dict[str, Any]


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def license_key_hash(license_key: str) -> str:
    return hashlib.sha256(license_key.encode("utf-8")).hexdigest()


def payload_hash_hex(body: dict[str, Any]) -> str:
    """SHA-256 of RFC 8785 JCS(activation body)."""
    return hashlib.sha256(jcs_dumps(body)).hexdigest()


def validate_request_id(request_id: str) -> str:
    if not isinstance(request_id, str):
        raise ActivationError(ActivationStatus.BAD_REQUEST, "request_id must be string")
    rid = request_id.strip().lower()
    if not _UUID_V4.match(rid):
        raise ActivationError(ActivationStatus.BAD_REQUEST, "request_id must be UUID v4 lowercase")
    return rid


def validate_client_nonce(nonce_hex: str) -> str:
    if not isinstance(nonce_hex, str):
        raise ActivationError(ActivationStatus.BAD_REQUEST, "client_nonce must be hex string")
    try:
        raw = bytes.fromhex(nonce_hex)
    except ValueError as e:
        raise ActivationError(ActivationStatus.BAD_REQUEST, "client_nonce invalid hex") from e
    if len(raw) != 32:
        raise ActivationError(ActivationStatus.BAD_REQUEST, "client_nonce must be 32 bytes")
    return nonce_hex.lower()


class ActivationService:
    def __init__(
        self,
        db: LicenseDatabase,
        vault: CekVault,
        *,
        signing_key: Ed25519PrivateKey,
        signing_kid: str,
    ) -> None:
        self._db = db
        self._vault = vault
        self._sk = signing_key
        self._kid = signing_kid

    # --- seller admin helpers ---

    def issue_license(
        self,
        *,
        license_id: str,
        product_id: str,
        cek_id: str,
        license_key: str,
        cek: bytes,
    ) -> None:
        """Create issued license + store CEK in vault. Seller-only."""
        now = _utc_now()
        self._vault.store(cek_id=cek_id, product_id=product_id, cek=cek)
        # Intentionally do not log mask_cek in production paths that print keys.
        _ = mask_cek(cek)
        self._db.conn.execute(
            """
            INSERT INTO licenses(
                license_id, product_id, cek_id, license_key_hash, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, 'issued', ?, ?)
            """,
            (license_id, product_id, cek_id, license_key_hash(license_key), now, now),
        )

    def set_status(self, license_id: str, status: str) -> None:
        if status not in ("issued", "revoked", "suspended"):
            raise ActivationError(ActivationStatus.BAD_REQUEST, "invalid status")
        cur = self._db.conn.execute(
            "UPDATE licenses SET status = ?, updated_at = ? WHERE license_id = ?",
            (status, _utc_now(), license_id),
        )
        if cur.rowcount == 0:
            raise ActivationError(ActivationStatus.NOT_FOUND, "license not found")

    # --- activation ---

    def activate(self, request: dict[str, Any] | str | bytes) -> ActivationResult:
        """
        Process one activation request under BEGIN IMMEDIATE.

        Idempotent path runs before license_status checks (R-04 / §3.2 A).
        """
        if isinstance(request, (str, bytes)):
            body = loads_strict(request)
        else:
            # Re-canonicalize via JCS roundtrip so hash is stable.
            body = loads_strict(jcs_dumps(request).decode("utf-8"))

        if not isinstance(body, dict):
            raise ActivationError(ActivationStatus.BAD_REQUEST, "body must be object")
        if body.get("format_version") != 1:
            raise ActivationError(ActivationStatus.BAD_REQUEST, "unsupported format_version")

        request_id = validate_request_id(str(body.get("request_id", "")))
        license_key = body.get("license_key")
        if not isinstance(license_key, str) or not license_key:
            raise ActivationError(ActivationStatus.BAD_REQUEST, "license_key required")
        client_nonce = validate_client_nonce(str(body.get("client_nonce", "")))
        claimed_device_id = body.get("device_id")
        if not isinstance(claimed_device_id, str) or len(claimed_device_id) != 64:
            raise ActivationError(ActivationStatus.BAD_REQUEST, "device_id must be 64 hex chars")
        claimed_device_id = claimed_device_id.lower()
        hwid_hash = body.get("hwid_hash")
        if hwid_hash is not None and not isinstance(hwid_hash, str):
            raise ActivationError(ActivationStatus.BAD_REQUEST, "hwid_hash must be string")

        try:
            spki_der = normalize_spki_der(body.get("spki_der_b64") or body.get("spki_der") or b"")
        except SpkiError as e:
            raise ActivationError(ActivationStatus.BAD_REQUEST, f"SPKI: {e}") from e
        server_device_id = device_id_hex(spki_der)
        if server_device_id != claimed_device_id:
            raise ActivationError(ActivationStatus.BAD_REQUEST, "device_id mismatch vs SPKI")

        # Canonical body for payload_hash (include normalized fields).
        canon_body = {
            "format_version": 1,
            "request_id": request_id,
            "license_key": license_key,
            "spki_der_b64": _b64url(spki_der),
            "device_id": server_device_id,
            "client_nonce": client_nonce,
        }
        if hwid_hash is not None:
            canon_body["hwid_hash"] = hwid_hash
        if "product_id" in body and isinstance(body["product_id"], str):
            canon_body["product_id"] = body["product_id"]

        p_hash = payload_hash_hex(canon_body)
        key_hash = license_key_hash(license_key)

        self._db.begin_immediate()
        try:
            lic = self._db.conn.execute(
                "SELECT * FROM licenses WHERE license_key_hash = ?",
                (key_hash,),
            ).fetchone()
            if lic is None:
                raise ActivationError(ActivationStatus.NOT_FOUND, "unknown license_key")
            license_id = lic["license_id"]

            # --- A. Idempotent retry (before status gate) ---
            existing = self._db.conn.execute(
                "SELECT * FROM activation_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if existing is not None:
                if existing["license_id"] != license_id or existing["payload_hash"] != p_hash:
                    raise ActivationError(ActivationStatus.CONFLICT, "request_id conflict")
                resp = json.loads(existing["response_json"])
                self._db.commit()
                return ActivationResult(ActivationStatus.OK, resp)

            # --- B. New activation ---
            if lic["status"] != "issued":
                raise ActivationError(
                    ActivationStatus.FORBIDDEN,
                    f"license status {lic['status']} rejects new activation",
                )

            # Reset audit: old device cannot reactivate
            blocked = self._db.conn.execute(
                """
                SELECT 1 FROM binding_resets
                WHERE license_id = ? AND old_device_id = ?
                LIMIT 1
                """,
                (license_id, server_device_id),
            ).fetchone()
            if blocked is not None:
                raise ActivationError(
                    ActivationStatus.FORBIDDEN,
                    "device was reset off this license; reactivation denied",
                )

            binding = self._db.conn.execute(
                "SELECT * FROM bindings WHERE license_id = ?",
                (license_id,),
            ).fetchone()

            if binding is None:
                # After reset(s), next generation = max(new_generation); else 1.
                row_gen = self._db.conn.execute(
                    """
                    SELECT MAX(new_generation) AS g FROM binding_resets
                    WHERE license_id = ?
                    """,
                    (license_id,),
                ).fetchone()
                generation = int(row_gen["g"]) if row_gen and row_gen["g"] is not None else 1
                activation_id = str(uuid.uuid4())
                self._db.conn.execute(
                    """
                    INSERT INTO bindings(
                        license_id, device_id, hwid_hash, spki_der,
                        activation_id, binding_generation, bound_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        license_id,
                        server_device_id,
                        hwid_hash,
                        spki_der,
                        activation_id,
                        generation,
                        _utc_now(),
                    ),
                )
            elif binding["device_id"] == server_device_id:
                # Same device — reissue ticket with same generation (idempotent policy)
                generation = int(binding["binding_generation"])
                activation_id = binding["activation_id"]
                # Refresh SPKI/hwid if needed
                self._db.conn.execute(
                    """
                    UPDATE bindings SET hwid_hash = ?, spki_der = ?, bound_at = ?
                    WHERE license_id = ?
                    """,
                    (hwid_hash, spki_der, _utc_now(), license_id),
                )
            else:
                raise ActivationError(
                    ActivationStatus.CONFLICT,
                    "license already bound to a different device",
                )

            cek = self._vault.load(lic["cek_id"])
            pub = load_rsa_public(spki_der)
            wrapped = oaep_encrypt_cek(pub, cek)
            envelope = {
                "format_version": 1,
                "cek_id": lic["cek_id"],
                "wrap_alg": "RSA-OAEP-SHA256",
                "wrapped_cek": wrapped.hex(),
            }
            env_hash = envelope_hash_hex(envelope)
            ticket_core = {
                "format_version": 1,
                "kid": self._kid,
                "license_id": license_id,
                "product_id": lic["product_id"],
                "cek_id": lic["cek_id"],
                "device_id": server_device_id,
                "binding_generation": generation,
                "envelope_hash": env_hash,
                "activation_id": activation_id,
                "challenge_id": request_id,
            }
            ticket = sign_ticket(ticket_core, self._sk)
            # sign_ticket requires REQUIRED fields — activation_id/challenge_id are extra
            # but ticket.py REQUIRED_TICKET_FIELDS doesn't include them. sign_ticket
            # checks missing from REQUIRED - extras are fine. Good.

            response = {
                "format_version": 1,
                "ticket": ticket,
                "envelope": envelope,
            }
            self._db.conn.execute(
                """
                INSERT INTO activation_requests(
                    request_id, license_id, payload_hash, response_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (request_id, license_id, p_hash, json.dumps(response, separators=(",", ":")), _utc_now()),
            )
            self._db.commit()
            return ActivationResult(ActivationStatus.OK, response)
        except ActivationError:
            self._db.rollback()
            raise
        except Exception:
            self._db.rollback()
            raise


def _b64url(data: bytes) -> str:
    import base64

    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")
