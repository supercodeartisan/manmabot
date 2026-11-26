"""Engine.crypto — Phase-1 license / MMB2 packaging (no bot decision logic)."""

from .authorized_session import AuthorizedSession, SessionError, open_authorized_session
from .device_key import DeviceKeyError, DeviceKeyProvider, open_or_create_device_key
from .errors import CryptoError, PackFormatError, PathPolicyError, SessionBindingError
from .hwid import HwidParts, collect_hwid, device_id_from_spki
from .kdf import derive_manifest_key, derive_pack_aes_key, derived_nonce
from .pack_format import Mmb2Reader, SimplePackSession, PackInfo, read_pack, write_pack
from .paths import canonicalize_pack_path
from .ticket import TicketError, VerifiedTicket, envelope_hash_hex, sign_ticket, verify_ticket

__all__ = [
    "CryptoError",
    "PackFormatError",
    "PathPolicyError",
    "SessionBindingError",
    "DeviceKeyError",
    "DeviceKeyProvider",
    "open_or_create_device_key",
    "AuthorizedSession",
    "SessionError",
    "open_authorized_session",
    "SimplePackSession",
    "PackInfo",
    "Mmb2Reader",
    "write_pack",
    "read_pack",
    "derive_pack_aes_key",
    "derive_manifest_key",
    "derived_nonce",
    "canonicalize_pack_path",
    "HwidParts",
    "collect_hwid",
    "device_id_from_spki",
    "TicketError",
    "VerifiedTicket",
    "envelope_hash_hex",
    "sign_ticket",
    "verify_ticket",
]
