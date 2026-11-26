"""AuthorizedSession — Ticket → envelope_hash → CEK decrypt (R-02 / F-03)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .constants import CEK_LEN
from .device_key import DeviceKeyProvider
from .errors import CryptoError
from .ticket import TicketError, VerifiedTicket, verify_ticket


class SessionError(CryptoError):
    pass


@dataclass
class AuthorizedSession:
    """In-memory only. CEK never written to disk by this type."""

    verified_ticket: VerifiedTicket
    authorized_product_id: str
    authorized_cek_id: str
    decrypted_cek_32: bytes

    def __post_init__(self) -> None:
        if len(self.decrypted_cek_32) != CEK_LEN:
            raise SessionError("CEK must be 32 bytes")
        # Hide CEK from naive repr
        object.__setattr__(self, "_cek_locked", True)

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"AuthorizedSession(product_id={self.authorized_product_id!r}, "
            f"cek_id={self.authorized_cek_id!r}, device_id={self.verified_ticket.device_id!r})"
        )


def open_authorized_session(
    *,
    ticket: dict | str | bytes,
    envelope: Mapping,
    device: DeviceKeyProvider,
    trusted_keys: Mapping[str, Ed25519PublicKey],
    expected_product_id: str | None = None,
) -> AuthorizedSession:
    """
    Order (spec §3.4):
      1–5  verify ticket + envelope_hash + device/product binding
      6    decrypt_cek
      7    CEK length == 32
      8    AuthorizedSession
    """
    try:
        vt = verify_ticket(
            ticket,
            trusted_keys=trusted_keys,
            expected_device_id=device.device_id,
            expected_product_id=expected_product_id,
            envelope=envelope,
        )
    except TicketError as e:
        raise SessionError(f"ticket verify failed: {e}") from e

    wrapped = envelope.get("wrapped_cek")
    if not isinstance(wrapped, str):
        raise SessionError("envelope.wrapped_cek missing")
    try:
        ciphertext = bytes.fromhex(wrapped)
    except ValueError as e:
        raise SessionError("wrapped_cek not hex") from e

    # Only after signature + envelope_hash verification:
    try:
        cek = device.decrypt_cek(ciphertext)
    except Exception as e:
        raise SessionError("CEK unwrap failed") from e
    if len(cek) != CEK_LEN:
        raise SessionError("CEK length != 32")

    if vt.product_id != (expected_product_id or vt.product_id):
        raise SessionError("product_id mismatch")
    if expected_product_id is not None and vt.product_id != expected_product_id:
        raise SessionError("product_id mismatch")

    return AuthorizedSession(
        verified_ticket=vt,
        authorized_product_id=vt.product_id,
        authorized_cek_id=vt.cek_id,
        decrypted_cek_32=cek,
    )
