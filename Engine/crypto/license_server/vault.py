"""CEK vault — AES-256-GCM at rest; never log plaintext CEK."""

from __future__ import annotations

import os
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..constants import CEK_LEN
from ..errors import CryptoError
from .db import LicenseDatabase


class VaultError(CryptoError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def mask_cek(cek: bytes) -> str:
    """Log-safe CEK fingerprint (not reversible)."""
    if len(cek) != CEK_LEN:
        return "<invalid-cek-len>"
    return f"cek_fp={cek[:4].hex()}…{cek[-2:].hex()}"


class CekVault:
    def __init__(self, db: LicenseDatabase, vault_key: bytes) -> None:
        if len(vault_key) != 32:
            raise VaultError("vault_key must be 32 bytes")
        self._db = db
        self._aes = AESGCM(vault_key)

    def exists(self, cek_id: str) -> bool:
        row = self._db.conn.execute(
            "SELECT 1 FROM cek_vault WHERE cek_id = ?",
            (cek_id,),
        ).fetchone()
        return row is not None

    def store(self, *, cek_id: str, product_id: str, cek: bytes) -> None:
        """Store CEK. Same cek_id + same CEK is idempotent; different CEK → error."""
        if len(cek) != CEK_LEN:
            raise VaultError("CEK must be 32 bytes")
        if self.exists(cek_id):
            existing = self.load(cek_id)
            if existing != cek:
                raise VaultError(
                    "cek_id already bound to a different CEK (rotate with a new cek_id)"
                )
            return
        nonce = os.urandom(12)
        # AAD binds cek_id so ciphertext cannot be swapped across rows.
        aad = f"cek-vault-v1|{cek_id}|{product_id}".encode("utf-8")
        ct = self._aes.encrypt(nonce, cek, aad)
        # AESGCM returns ciphertext||tag
        self._db.conn.execute(
            """
            INSERT INTO cek_vault(cek_id, product_id, ciphertext, nonce, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (cek_id, product_id, ct, nonce, _utc_now()),
        )

    def load(self, cek_id: str) -> bytes:
        row = self._db.conn.execute(
            "SELECT product_id, ciphertext, nonce FROM cek_vault WHERE cek_id = ?",
            (cek_id,),
        ).fetchone()
        if row is None:
            raise VaultError(f"cek_id not in vault: {cek_id}")
        aad = f"cek-vault-v1|{cek_id}|{row['product_id']}".encode("utf-8")
        try:
            pt = self._aes.decrypt(bytes(row["nonce"]), bytes(row["ciphertext"]), aad)
        except Exception as e:
            raise VaultError("vault decrypt failed") from e
        if len(pt) != CEK_LEN:
            raise VaultError("vault CEK length != 32")
        return pt
