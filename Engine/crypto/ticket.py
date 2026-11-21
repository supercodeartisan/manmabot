"""Ed25519 license ticket verify / sign (READY Spec §1, §3.4).

Client trusts only build-pinned public keys by kid. CEK decrypt happens
only after signature + envelope_hash checks (R-02).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .errors import CryptoError
from .jcs import JcsError, dumps as jcs_dumps, loads_strict


class TicketError(CryptoError):
    pass


REQUIRED_TICKET_FIELDS = frozenset(
    {
        "format_version",
        "kid",
        "license_id",
        "product_id",
        "cek_id",
        "device_id",
        "binding_generation",
        "envelope_hash",
        "signature",
    }
)


@dataclass(frozen=True)
class VerifiedTicket:
    fields: dict
    kid: str
    license_id: str
    product_id: str
    cek_id: str
    device_id: str
    binding_generation: int
    envelope_hash: str  # hex sha256 of JCS(envelope)


def envelope_hash_hex(envelope: Mapping) -> str:
    body = jcs_dumps(dict(envelope))
    return hashlib.sha256(body).hexdigest()


def _ticket_body_without_signature(ticket: dict) -> bytes:
    core = {k: v for k, v in ticket.items() if k != "signature"}
    return jcs_dumps(core)


def sign_ticket(ticket_core: dict, private_key: Ed25519PrivateKey) -> dict:
    """Seller/test helper: add Ed25519 signature over RFC 8785 JCS(core)."""
    if "signature" in ticket_core:
        raise TicketError("ticket_core must not include signature")
    missing = REQUIRED_TICKET_FIELDS - {"signature"} - set(ticket_core.keys())
    if missing:
        raise TicketError(f"missing fields: {sorted(missing)}")
    # Sign the exact JCS bytes of the core (extras like activation_id allowed).
    body = jcs_dumps(ticket_core)
    sig = private_key.sign(body)
    out = dict(ticket_core)
    out["signature"] = sig.hex()
    return out


def verify_ticket(
    ticket_obj: dict | str | bytes,
    *,
    trusted_keys: Mapping[str, Ed25519PublicKey],
    expected_device_id: str | None = None,
    expected_product_id: str | None = None,
    envelope: Mapping | None = None,
) -> VerifiedTicket:
    """
    Verify ticket. If ``envelope`` is provided, also check envelope_hash.
    Does **not** decrypt CEK.
    """
    if isinstance(ticket_obj, (str, bytes)):
        try:
            ticket = loads_strict(ticket_obj)
        except JcsError as e:
            raise TicketError(str(e)) from e
    else:
        ticket = dict(ticket_obj)

    if not isinstance(ticket, dict):
        raise TicketError("ticket must be object")
    for f in REQUIRED_TICKET_FIELDS:
        if f not in ticket:
            raise TicketError(f"missing field {f}")

    if ticket.get("format_version") != 1:
        raise TicketError("unsupported ticket format_version")

    kid = ticket["kid"]
    if not isinstance(kid, str) or kid not in trusted_keys:
        raise TicketError("unknown or missing kid")

    sig_hex = ticket["signature"]
    if not isinstance(sig_hex, str):
        raise TicketError("signature must be hex string")
    try:
        sig = bytes.fromhex(sig_hex)
    except ValueError as e:
        raise TicketError("invalid signature hex") from e

    body = _ticket_body_without_signature(ticket)
    try:
        trusted_keys[kid].verify(sig, body)
    except InvalidSignature as e:
        raise TicketError("Ed25519 signature invalid") from e

    env_hash = ticket["envelope_hash"]
    if not isinstance(env_hash, str) or len(env_hash) != 64:
        raise TicketError("envelope_hash must be 64 hex chars")

    if envelope is not None:
        expect = envelope_hash_hex(envelope)
        if expect != env_hash:
            raise TicketError("envelope_hash mismatch")

    device_id = ticket["device_id"]
    product_id = ticket["product_id"]
    cek_id = ticket["cek_id"]
    license_id = ticket["license_id"]
    gen = ticket["binding_generation"]
    if not all(isinstance(x, str) for x in (device_id, product_id, cek_id, license_id)):
        raise TicketError("id fields must be strings")
    if not isinstance(gen, int) or isinstance(gen, bool) or gen < 0:
        raise TicketError("binding_generation must be non-negative int")

    if expected_device_id is not None and device_id != expected_device_id:
        raise TicketError("device_id mismatch")
    if expected_product_id is not None and product_id != expected_product_id:
        raise TicketError("product_id mismatch")

    return VerifiedTicket(
        fields=ticket,
        kid=kid,
        license_id=license_id,
        product_id=product_id,
        cek_id=cek_id,
        device_id=device_id,
        binding_generation=gen,
        envelope_hash=env_hash,
    )
