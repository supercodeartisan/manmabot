"""Soft RSA-2048 device key sealed with DPAPI CurrentUser."""

from __future__ import annotations

import json
from pathlib import Path

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey, RSAPublicKey

from . import dpapi
from .constants import CEK_LEN
from .errors import CryptoError
from .hwid import device_id_from_spki

SOFT_KEY_FILENAME = "device_rsa_soft.dpapi"
SOFT_PUB_FILENAME = "device_rsa_soft.spki"
META_FILENAME = "device_key_meta.dpapi"
CONTAINER_NAME = "ManmabotV1.DeviceRSA"  # documented name (Soft file-backed)


class SoftKeyError(CryptoError):
    pass


def soft_key_exists(store_dir: Path) -> bool:
    return (store_dir / SOFT_KEY_FILENAME).is_file()


def load_soft_private(store_dir: Path) -> RSAPrivateKey:
    path = store_dir / SOFT_KEY_FILENAME
    if not path.is_file():
        raise SoftKeyError("soft key absent")
    try:
        pem = dpapi.unprotect(path.read_bytes())
    except dpapi.DpapiError as e:
        raise SoftKeyError(f"soft key unprotect failed: {e}") from e
    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, RSAPrivateKey):
        raise SoftKeyError("soft key is not RSA")
    if key.key_size != 2048:
        raise SoftKeyError("soft key must be RSA-2048")
    return key


def load_soft_spki(store_dir: Path) -> bytes:
    pub_path = store_dir / SOFT_PUB_FILENAME
    if pub_path.is_file():
        return pub_path.read_bytes()
    # Recover SPKI from private if pub file missing.
    priv = load_soft_private(store_dir)
    return priv.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def create_soft_key(store_dir: Path) -> tuple[RSAPrivateKey, bytes]:
    store_dir.mkdir(parents=True, exist_ok=True)
    if soft_key_exists(store_dir):
        raise SoftKeyError("soft key already exists")
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    sealed = dpapi.protect(pem, description="ManmabotV1.SoftDeviceRSA")
    (store_dir / SOFT_KEY_FILENAME).write_bytes(sealed)
    spki = key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    (store_dir / SOFT_PUB_FILENAME).write_bytes(spki)
    return key, spki


def oaep_decrypt_cek(private_key: RSAPrivateKey, ciphertext: bytes) -> bytes:
    try:
        pt = private_key.decrypt(
            ciphertext,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
    except Exception as e:
        raise SoftKeyError("OAEP decrypt failed") from e
    if len(pt) != CEK_LEN:
        raise SoftKeyError("CEK plaintext must be 32 bytes")
    return pt


def oaep_encrypt_cek(public_key: RSAPublicKey, cek: bytes) -> bytes:
    if len(cek) != CEK_LEN:
        raise SoftKeyError("CEK must be 32 bytes")
    return public_key.encrypt(
        cek,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )


# --- Meta (DPAPI JSON) ---


def meta_path(store_dir: Path) -> Path:
    return store_dir / META_FILENAME


def meta_exists(store_dir: Path) -> bool:
    return meta_path(store_dir).is_file()


def write_meta(
    store_dir: Path,
    *,
    provider_type: str,
    device_id: str,
    created_at: str,
) -> None:
    if provider_type not in ("tpm", "soft"):
        raise SoftKeyError("invalid provider_type")
    payload = json.dumps(
        {
            "provider_type": provider_type,
            "device_id": device_id,
            "created_at": created_at,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    store_dir.mkdir(parents=True, exist_ok=True)
    sealed = dpapi.protect(payload, description="ManmabotV1.DeviceKeyMeta")
    meta_path(store_dir).write_bytes(sealed)


def read_meta(store_dir: Path) -> dict:
    path = meta_path(store_dir)
    if not path.is_file():
        raise SoftKeyError("meta absent")
    try:
        raw = dpapi.unprotect(path.read_bytes())
    except dpapi.DpapiError as e:
        # Caller maps inaccessible vs invalid.
        raise SoftKeyError(f"meta inaccessible: {e}") from e
    try:
        obj = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise SoftKeyError("meta invalid json") from e
    if not isinstance(obj, dict):
        raise SoftKeyError("meta invalid type")
    for k in ("provider_type", "device_id", "created_at"):
        if k not in obj or not isinstance(obj[k], str):
            raise SoftKeyError(f"meta missing {k}")
    if obj["provider_type"] not in ("tpm", "soft"):
        raise SoftKeyError("meta invalid provider_type")
    return obj


def spki_matches_device_id(spki: bytes, device_id: str) -> bool:
    return device_id_from_spki(spki) == device_id
