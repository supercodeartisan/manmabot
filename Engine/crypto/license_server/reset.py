"""Binding reset + audit (seller admin)."""

from __future__ import annotations

from datetime import datetime, timezone

from .activation import ActivationError, ActivationStatus
from .db import LicenseDatabase


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class ResetService:
    def __init__(self, db: LicenseDatabase) -> None:
        self._db = db

    def reset_binding(
        self,
        *,
        license_id: str,
        reason: str,
        admin_id: str,
    ) -> dict:
        """
        Clear binding, increment generation, audit old_device_id.
        Old device reactivation is denied via binding_resets rows.
        """
        self._db.begin_immediate()
        try:
            lic = self._db.conn.execute(
                "SELECT * FROM licenses WHERE license_id = ?",
                (license_id,),
            ).fetchone()
            if lic is None:
                raise ActivationError(ActivationStatus.NOT_FOUND, "license not found")

            binding = self._db.conn.execute(
                "SELECT * FROM bindings WHERE license_id = ?",
                (license_id,),
            ).fetchone()
            if binding is None:
                raise ActivationError(ActivationStatus.BAD_REQUEST, "license not bound")

            old_device = binding["device_id"]
            old_gen = int(binding["binding_generation"])
            new_gen = old_gen + 1

            self._db.conn.execute(
                "DELETE FROM bindings WHERE license_id = ?",
                (license_id,),
            )
            self._db.conn.execute(
                """
                INSERT INTO binding_resets(
                    license_id, old_device_id, old_generation, new_generation,
                    reset_at, reason, admin_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (license_id, old_device, old_gen, new_gen, _utc_now(), reason, admin_id),
            )
            # Keep license issued so a *new* device can activate after reset.
            self._db.conn.execute(
                "UPDATE licenses SET updated_at = ? WHERE license_id = ?",
                (_utc_now(), license_id),
            )
            self._db.commit()
            return {
                "license_id": license_id,
                "old_device_id": old_device,
                "old_generation": old_gen,
                "new_generation": new_gen,
            }
        except ActivationError:
            self._db.rollback()
            raise
        except Exception:
            self._db.rollback()
            raise
