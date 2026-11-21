"""Seller-side store root (never ship to customers)."""

from __future__ import annotations

import json
import os
from pathlib import Path

from ..license_server.db import LicenseDatabase
from ..license_server.vault import CekVault

DEFAULT_PRODUCT_ID = "00000000-0000-4000-8000-000000000001"


def default_seller_root() -> Path:
    env = os.environ.get("MANMABOT_SELLER_DATA", "").strip()
    if env:
        return Path(env)
    # Product root / SellerData  (sibling of Engine, UserData)
    # Engine/crypto/seller_cli/store.py → parents[3] = product root
    return Path(__file__).resolve().parents[3] / "SellerData"


class SellerStore:
    """Layout under SellerData/ — private keys + vault key + license.db."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else default_seller_root()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "signing" / "private").mkdir(parents=True, exist_ok=True)
        (self.root / "signing" / "public").mkdir(parents=True, exist_ok=True)
        (self.root / "artifacts").mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "license.db"
        self.vault_key_path = self.root / "vault_key.bin"
        self.config_path = self.root / "config.json"
        self._db: LicenseDatabase | None = None
        self._vault: CekVault | None = None

    def vault_key(self) -> bytes:
        if self.vault_key_path.is_file():
            key = self.vault_key_path.read_bytes()
            if len(key) != 32:
                raise RuntimeError("vault_key.bin must be 32 bytes")
            return key
        key = os.urandom(32)
        self.vault_key_path.write_bytes(key)
        try:
            os.chmod(self.vault_key_path, 0o600)
        except OSError:
            pass
        return key

    def db(self) -> LicenseDatabase:
        if self._db is None:
            self._db = LicenseDatabase(self.db_path)
        return self._db

    def vault(self) -> CekVault:
        if self._vault is None:
            self._vault = CekVault(self.db(), self.vault_key())
        return self._vault

    def config(self) -> dict:
        if not self.config_path.is_file():
            cfg = {
                "product_id": DEFAULT_PRODUCT_ID,
                "current_kid": None,
                "previous_kid": None,
            }
            self.save_config(cfg)
            return cfg
        return json.loads(self.config_path.read_text(encoding="utf-8"))

    def save_config(self, cfg: dict) -> None:
        self.config_path.write_text(
            json.dumps(cfg, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    def private_key_path(self, kid: str) -> Path:
        return self.root / "signing" / "private" / f"{kid}.pem"

    def public_key_path(self, kid: str) -> Path:
        return self.root / "signing" / "public" / f"{kid}.pem"

    def close(self) -> None:
        if self._db is not None:
            self._db.close()
            self._db = None
            self._vault = None
