"""SPKI DER normalize + RSA-2048 / e=65537 checks."""

from __future__ import annotations

import base64
import hashlib

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from ..errors import CryptoError


class SpkiError(CryptoError):
    pass


def normalize_spki_der(raw: bytes | str) -> bytes:
    """Accept DER bytes or base64/base64url; return canonical SPKI DER."""
    if isinstance(raw, str):
        s = raw.strip().replace("-", "+").replace("_", "/")
        pad = (-len(s)) % 4
        if pad:
            s += "=" * pad
        try:
            raw_bytes = base64.b64decode(s, validate=False)
        except Exception as e:
            raise SpkiError("invalid SPKI base64") from e
    else:
        raw_bytes = bytes(raw)
    try:
        pub = serialization.load_der_public_key(raw_bytes)
    except Exception as e:
        raise SpkiError("SPKI DER parse failed") from e
    if not isinstance(pub, RSAPublicKey):
        raise SpkiError("SPKI must be RSA")
    if pub.key_size != 2048:
        raise SpkiError("RSA key must be 2048-bit")
    numbers = pub.public_numbers()
    if numbers.e != 65537:
        raise SpkiError("RSA public exponent must be 65537")
    # Re-encode for DER normalization
    return pub.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def device_id_hex(spki_der: bytes) -> str:
    return hashlib.sha256(spki_der).hexdigest()


def load_rsa_public(spki_der: bytes) -> RSAPublicKey:
    pub = serialization.load_der_public_key(spki_der)
    if not isinstance(pub, RSAPublicKey):
        raise SpkiError("not RSA")
    return pub
