"""Licensed pack bootstrap: Ticket → AuthorizedSession → MMB2 bytes.

Does not expose a public ``decrypt(path, cek)`` API. CEK stays inside
``AuthorizedSession`` / reader calls only.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from session.paths import USERDATA, manmabot_root

LICENSE_DIR = USERDATA / "license"
TICKET_PATH = LICENSE_DIR / "ticket.json"
ENVELOPE_PATH = LICENSE_DIR / "envelope.json"
DEVICE_KEY_DIR = LICENSE_DIR / "device_key"

# Build-pinned Ed25519 public keys (kid → raw 32-byte or PEM path later).
# Empty until seller keygen ships; MMB2 customer packs require at least one kid.
_TRUSTED_KIDS: dict[str, Any] = {}

_SESSION = None  # AuthorizedSession | None


class LicensedRuntimeError(RuntimeError):
    pass


def register_trusted_key(kid: str, public_key) -> None:
    """Seller/build hook: pin an Ed25519 public key by kid."""
    _TRUSTED_KIDS[kid] = public_key


def clear_trusted_keys() -> None:
    _TRUSTED_KIDS.clear()


def current_session():
    return _SESSION


def _load_json(path: Path) -> dict:
    raw = path.read_bytes()
    from crypto.jcs import loads_strict

    obj = loads_strict(raw)
    if not isinstance(obj, dict):
        raise LicensedRuntimeError(f"expected object in {path}")
    return obj


def load_trusted_kids_file(path: Path | None = None) -> int:
    """Load public Ed25519 PEMs from trusted_kids.json (seller export). Returns count."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    pin = path or (Path(__file__).resolve().parent / "trusted_kids.json")
    if not pin.is_file():
        return 0
    data = json.loads(pin.read_text(encoding="utf-8"))
    kids = data.get("kids") or {}
    n = 0
    for kid, pem in kids.items():
        if not isinstance(kid, str) or not isinstance(pem, str):
            continue
        pk = serialization.load_pem_public_key(pem.encode("ascii"))
        if not isinstance(pk, Ed25519PublicKey):
            raise LicensedRuntimeError(f"trusted kid {kid} is not Ed25519")
        register_trusted_key(kid, pk)
        n += 1
    return n


def open_licensed_session(*, force_soft_device: bool = False):
    """
    Load ticket+envelope from UserData, unwrap CEK via DeviceKeyProvider.
    Returns AuthorizedSession. Idempotent within process if already open.
    """
    global _SESSION
    if _SESSION is not None:
        return _SESSION

    if not TICKET_PATH.is_file() or not ENVELOPE_PATH.is_file():
        raise LicensedRuntimeError(
            f"missing license artifacts under {LICENSE_DIR} "
            "(ticket.json / envelope.json)"
        )
    if not _TRUSTED_KIDS:
        load_trusted_kids_file()
    if not _TRUSTED_KIDS:
        raise LicensedRuntimeError(
            "no trusted Ed25519 kids registered (build pin / keygen required)"
        )

    from crypto.authorized_session import open_authorized_session
    from crypto.device_key import open_or_create_device_key

    DEVICE_KEY_DIR.mkdir(parents=True, exist_ok=True)
    force = force_soft_device or os.environ.get("MANMABOT_FORCE_SOFT_DEVICE", "").strip() in {
        "1",
        "true",
        "yes",
    }
    device = open_or_create_device_key(DEVICE_KEY_DIR, force_soft=force)
    ticket = _load_json(TICKET_PATH)
    envelope = _load_json(ENVELOPE_PATH)
    _SESSION = open_authorized_session(
        ticket=ticket,
        envelope=envelope,
        device=device,
        trusted_keys=_TRUSTED_KIDS,
    )
    return _SESSION


def pack_magic(path: Path) -> str:
    if not path.is_file():
        return "absent"
    with path.open("rb") as fh:
        magic = fh.read(4)
    if magic == b"MMB2":
        return "mmb2"
    if magic == b"MMBA":
        return "mmba"
    return "unknown"


def load_pack_files(path: Path, *, session=None) -> dict[str, bytes]:
    """
    Load pack into memory.
    MMB2 requires AuthorizedSession (or explicit session=).
    MMBA v1 uses legacy obfuscation (transition only).
    """
    kind = pack_magic(path)
    if kind == "mmba":
        from session.asset_pack_format import load_pack_bytes

        return load_pack_bytes(path)
    if kind != "mmb2":
        raise LicensedRuntimeError(f"unsupported pack magic at {path}: {kind}")

    sess = session if session is not None else (_SESSION or open_licensed_session())
    from crypto.pack_format import Mmb2Reader

    blob = path.read_bytes()
    return Mmb2Reader(blob, sess).read_all()


def write_license_artifacts(*, ticket: dict, envelope: dict) -> None:
    """Seller/test helper: persist activation response for runtime."""
    LICENSE_DIR.mkdir(parents=True, exist_ok=True)
    TICKET_PATH.write_text(json.dumps(ticket, indent=2), encoding="utf-8")
    ENVELOPE_PATH.write_text(json.dumps(envelope, indent=2), encoding="utf-8")
