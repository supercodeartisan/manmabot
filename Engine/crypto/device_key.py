"""DeviceKeyProvider — TPM + Soft state machine (READY Spec §2)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.rsa import RSAPrivateKey

from .errors import CryptoError
from .hwid import device_id_from_spki
from .soft_key import (
    create_soft_key,
    load_soft_private,
    load_soft_spki,
    meta_exists,
    oaep_decrypt_cek,
    read_meta,
    soft_key_exists,
    spki_matches_device_id,
    write_meta,
)
from .tpm_key import (
    KeyProbeStatus,
    TpmError,
    TpmFailureClass,
    classify_tpm_failure,
    create_tpm_key,
    decrypt_cek_tpm,
    export_tpm_spki,
    probe_tpm_key,
)


class DeviceKeyError(CryptoError):
    """Operator-facing device key failure (may need seller reset)."""


class ProviderType(str, Enum):
    tpm = "tpm"
    soft = "soft"


@dataclass
class DeviceKeyProvider:
    """Bound device RSA key (TPM or Soft)."""

    store_dir: Path
    provider_type: ProviderType
    device_id: str
    _soft_private: RSAPrivateKey | None = None
    _spki: bytes | None = None

    def get_public_key_spki_der(self) -> bytes:
        if self._spki is None:
            if self.provider_type is ProviderType.soft:
                self._spki = load_soft_spki(self.store_dir)
            else:
                self._spki = export_tpm_spki()
        return self._spki

    def key_probe(self) -> str:
        return "present"

    def decrypt_cek(self, ciphertext: bytes) -> bytes:
        if self.provider_type is ProviderType.soft:
            if self._soft_private is None:
                self._soft_private = load_soft_private(self.store_dir)
            return oaep_decrypt_cek(self._soft_private, ciphertext)
        return decrypt_cek_tpm(ciphertext)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _tpm_present() -> bool:
    return probe_tpm_key().status is KeyProbeStatus.present


def _soft_present(store_dir: Path) -> bool:
    return soft_key_exists(store_dir)


def _recover_tpm_meta(store_dir: Path) -> DeviceKeyProvider:
    spki = export_tpm_spki()
    did = device_id_from_spki(spki)
    write_meta(
        store_dir,
        provider_type="tpm",
        device_id=did,
        created_at=_utc_now_iso(),
    )
    return DeviceKeyProvider(
        store_dir=store_dir,
        provider_type=ProviderType.tpm,
        device_id=did,
        _spki=spki,
    )


def _recover_soft_meta(store_dir: Path) -> DeviceKeyProvider:
    spki = load_soft_spki(store_dir)
    did = device_id_from_spki(spki)
    write_meta(
        store_dir,
        provider_type="soft",
        device_id=did,
        created_at=_utc_now_iso(),
    )
    return DeviceKeyProvider(
        store_dir=store_dir,
        provider_type=ProviderType.soft,
        device_id=did,
        _spki=spki,
        _soft_private=load_soft_private(store_dir),
    )


def _first_install(store_dir: Path, *, allow_soft_fallback: bool) -> DeviceKeyProvider:
    """No meta, no existing keys — try TPM then Soft only if permanent failure."""
    probe = probe_tpm_key()
    if probe.status is KeyProbeStatus.present:
        # Should have been recovered earlier; treat as recover.
        return _recover_tpm_meta(store_dir)

    if probe.status is KeyProbeStatus.error_transient:
        raise DeviceKeyError("TPM transient error; retry (Soft fallback forbidden)")
    if probe.status is KeyProbeStatus.error_denied:
        raise DeviceKeyError("TPM access denied (Soft fallback forbidden)")
    if probe.status is KeyProbeStatus.error_unknown:
        raise DeviceKeyError("TPM status unknown (Soft fallback forbidden)")

    # absent / unsupported / provider_permanent → try create TPM
    if probe.status in (KeyProbeStatus.absent, KeyProbeStatus.unsupported) or (
        probe.status is KeyProbeStatus.absent
    ):
        try:
            spki = create_tpm_key()
            did = device_id_from_spki(spki)
            write_meta(
                store_dir,
                provider_type="tpm",
                device_id=did,
                created_at=_utc_now_iso(),
            )
            return DeviceKeyProvider(
                store_dir=store_dir,
                provider_type=ProviderType.tpm,
                device_id=did,
                _spki=spki,
            )
        except TpmError as e:
            klass = classify_tpm_failure(e.hr or 0) if e.hr is not None else TpmFailureClass.unknown
            if klass is TpmFailureClass.transient:
                raise DeviceKeyError("TPM create transient failure; retry") from e
            if klass is TpmFailureClass.denied:
                raise DeviceKeyError("TPM create denied") from e
            if klass is not TpmFailureClass.permanent and probe.status is not KeyProbeStatus.unsupported:
                # Unknown create failure — Soft forbidden
                if not allow_soft_fallback:
                    raise DeviceKeyError(f"TPM create failed: {e}") from e
                # For tests we may force soft; production: unknown → no Soft
                raise DeviceKeyError(f"TPM create failed (no Soft): {e}") from e
            # permanent or unsupported → Soft if allowed
            if not allow_soft_fallback:
                raise DeviceKeyError(f"TPM permanently unavailable: {e}") from e

    # Soft fallback (permanent TPM unavailability / non-Windows tests)
    if not allow_soft_fallback:
        raise DeviceKeyError("Soft fallback not permitted")
    _priv, spki = create_soft_key(store_dir)
    did = device_id_from_spki(spki)
    write_meta(
        store_dir,
        provider_type="soft",
        device_id=did,
        created_at=_utc_now_iso(),
    )
    return DeviceKeyProvider(
        store_dir=store_dir,
        provider_type=ProviderType.soft,
        device_id=did,
        _spki=spki,
        _soft_private=_priv,
    )


def open_or_create_device_key(
    store_dir: Path,
    *,
    force_soft: bool = False,
) -> DeviceKeyProvider:
    """Apply §2.2 state machine. ``force_soft`` skips TPM (unit tests only)."""
    store_dir = Path(store_dir)
    store_dir.mkdir(parents=True, exist_ok=True)

    tpm = False if force_soft else _tpm_present()
    soft = _soft_present(store_dir)

    if meta_exists(store_dir):
        try:
            meta = read_meta(store_dir)
        except Exception as e:
            msg = str(e)
            if "inaccessible" in msg:
                raise DeviceKeyError("device key meta inaccessible; retry") from e
            raise DeviceKeyError("device key meta invalid; seller reset required") from e

        ptype = meta["provider_type"]
        did = meta["device_id"]

        if ptype == "tpm":
            if soft:
                raise DeviceKeyError("meta=tpm but Soft key also present (conflict)")
            if force_soft:
                raise DeviceKeyError("meta=tpm but force_soft requested")
            if not tpm:
                # Distinguish transient probe vs truly missing
                probe = probe_tpm_key()
                if probe.status is KeyProbeStatus.error_transient:
                    raise DeviceKeyError("TPM transient; retry")
                if probe.status is KeyProbeStatus.error_denied:
                    raise DeviceKeyError("TPM denied")
                raise DeviceKeyError("meta=tpm but TPM key missing; seller reset required")
            spki = export_tpm_spki()
            if not spki_matches_device_id(spki, did):
                raise DeviceKeyError("meta device_id ≠ TPM SPKI; seller reset required")
            return DeviceKeyProvider(
                store_dir=store_dir,
                provider_type=ProviderType.tpm,
                device_id=did,
                _spki=spki,
            )

        if ptype == "soft":
            if tpm and not force_soft:
                raise DeviceKeyError("meta=soft but TPM key also present (conflict)")
            if not soft:
                raise DeviceKeyError("meta=soft but Soft key missing; seller reset required")
            spki = load_soft_spki(store_dir)
            if not spki_matches_device_id(spki, did):
                raise DeviceKeyError("meta device_id ≠ Soft SPKI; seller reset required")
            return DeviceKeyProvider(
                store_dir=store_dir,
                provider_type=ProviderType.soft,
                device_id=did,
                _spki=spki,
                _soft_private=load_soft_private(store_dir),
            )

        raise DeviceKeyError("unknown provider_type in meta")

    # Meta absent
    if tpm and soft:
        raise DeviceKeyError("meta absent but both TPM and Soft keys exist (conflict)")
    if tpm:
        return _recover_tpm_meta(store_dir)
    if soft:
        return _recover_soft_meta(store_dir)

    # First install
    if force_soft:
        _priv, spki = create_soft_key(store_dir)
        did = device_id_from_spki(spki)
        write_meta(
            store_dir,
            provider_type="soft",
            device_id=did,
            created_at=_utc_now_iso(),
        )
        return DeviceKeyProvider(
            store_dir=store_dir,
            provider_type=ProviderType.soft,
            device_id=did,
            _spki=spki,
            _soft_private=_priv,
        )

    return _first_install(store_dir, allow_soft_fallback=True)
