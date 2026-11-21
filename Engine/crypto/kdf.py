"""HKDF helpers for MMB2 (READY Phase 1 Spec §5.2)."""

from __future__ import annotations

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .constants import CEK_LEN, INFO_AES, INFO_MANIFEST, PACK_ID_LEN


def _require_cek(cek: bytes) -> bytes:
    if not isinstance(cek, (bytes, bytearray)) or len(cek) != CEK_LEN:
        raise ValueError(f"CEK must be {CEK_LEN} bytes")
    return bytes(cek)


def _require_pack_id(pack_id: bytes) -> bytes:
    if not isinstance(pack_id, (bytes, bytearray)) or len(pack_id) != PACK_ID_LEN:
        raise ValueError(f"pack_id must be {PACK_ID_LEN} bytes")
    return bytes(pack_id)


def derive_pack_aes_key(cek: bytes, pack_id: bytes, cek_id_canonical: str) -> bytes:
    cek = _require_cek(cek)
    pack_id = _require_pack_id(pack_id)
    info = (INFO_AES + cek_id_canonical).encode("utf-8")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=pack_id,
        info=info,
    ).derive(cek)


def derive_manifest_key(cek: bytes, pack_id: bytes, cek_id_canonical: str) -> bytes:
    cek = _require_cek(cek)
    pack_id = _require_pack_id(pack_id)
    info = (INFO_MANIFEST + cek_id_canonical).encode("utf-8")
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=pack_id,
        info=info,
    ).derive(cek)


def derived_nonce(entry_index: int) -> bytes:
    if entry_index < 0:
        raise ValueError("entry_index must be >= 0")
    return b"\x00\x00\x00\x00" + int(entry_index).to_bytes(8, "big")
