"""Out-of-band (no HTTP server) activation: request ↔ response blobs.

Reuses ``ActivationService.activate`` crypto/binding. Transport is file/chat only.
Never embed raw CEK or signing private keys in either blob.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


def _device_id_hex(spki_der: bytes) -> str:
    return hashlib.sha256(spki_der).hexdigest()

REQ_PREFIX = "MMB-REQ1."
RSP_PREFIX = "MMB-RSP1."
DEFAULT_TTL_HOURS = 48
FORMAT_VERSION = 1

_FORBIDDEN = re.compile(
    r"(BEGIN (PRIVATE|RSA PRIVATE|ENCRYPTED PRIVATE) KEY"
    r"|\"cek\"\s*:\s*\"[0-9a-fA-F]{64}\""
    r"|vault_key"
    r"|wrapped_cek_raw)",
    re.IGNORECASE,
)


class OobActivationError(RuntimeError):
    pass


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)


def _utc_iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def _parse_iso(text: str) -> datetime:
    raw = text.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    dt = datetime.fromisoformat(raw)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def _dumps(obj: dict) -> str:
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def assert_no_secrets(obj: dict, *, label: str) -> None:
    blob = json.dumps(obj)
    if _FORBIDDEN.search(blob):
        raise OobActivationError(f"{label} contains forbidden secret material")
    upper = blob.upper()
    if "BEGIN PRIVATE KEY" in upper or "BEGIN RSA PRIVATE" in upper:
        raise OobActivationError(f"{label} must not contain private key material")


def encode_wire(prefix: str, obj: dict) -> str:
    raw = json.dumps(obj, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return prefix + _b64url(raw)


def decode_wire(text: str) -> dict:
    s = text.strip().replace("\n", "").replace("\r", "").replace(" ", "")
    if s.startswith(REQ_PREFIX):
        payload = s[len(REQ_PREFIX) :]
    elif s.startswith(RSP_PREFIX):
        payload = s[len(RSP_PREFIX) :]
    else:
        raise OobActivationError("wire must start with MMB-REQ1. or MMB-RSP1.")
    obj = json.loads(_b64url_decode(payload).decode("utf-8"))
    if not isinstance(obj, dict):
        raise OobActivationError("wire payload must be a JSON object")
    return obj


def load_request_file_or_wire(path_or_text: str | Path) -> dict:
    text = str(path_or_text)
    p = Path(text)
    if p.is_file():
        obj = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            raise OobActivationError("request file must be a JSON object")
        return obj
    if text.strip().startswith(REQ_PREFIX):
        return decode_wire(text)
    raise OobActivationError("provide a request JSON path or MMB-REQ1. wire string")


def load_response_file_or_wire(path_or_text: str | Path) -> dict:
    text = str(path_or_text)
    p = Path(text)
    if p.is_file():
        obj = json.loads(p.read_text(encoding="utf-8"))
        if not isinstance(obj, dict):
            raise OobActivationError("response file must be a JSON object")
        return obj
    if text.strip().startswith(RSP_PREFIX):
        return decode_wire(text)
    raise OobActivationError("provide a response JSON path or MMB-RSP1. wire string")


def build_activation_request(
    *,
    license_key: str,
    product_id: str,
    spki_der: bytes,
    device_id: str | None = None,
    ttl_hours: int = DEFAULT_TTL_HOURS,
    request_id: str | None = None,
    client_nonce: str | None = None,
) -> dict:
    if not isinstance(license_key, str) or not license_key.startswith("MMB-"):
        raise OobActivationError("license_key must be an MMB-… string")
    if not isinstance(product_id, str) or not product_id:
        raise OobActivationError("product_id required")
    if not isinstance(spki_der, (bytes, bytearray)) or not spki_der:
        raise OobActivationError("spki_der required")
    did = (device_id or _device_id_hex(bytes(spki_der))).lower()
    if len(did) != 64:
        raise OobActivationError("device_id must be 64 hex chars")
    now = _utc_now()
    if ttl_hours < 1 or ttl_hours > 24 * 14:
        raise OobActivationError("ttl_hours out of range (1..336)")
    nonce = client_nonce or os.urandom(32).hex()
    if len(bytes.fromhex(nonce)) != 32:
        raise OobActivationError("client_nonce must be 32 bytes hex")
    req = {
        "format_version": FORMAT_VERSION,
        "mode": "oob_file",
        "product_id": product_id,
        "license_key": license_key,
        "request_id": (request_id or str(uuid.uuid4())).lower(),
        "client_nonce": nonce.lower(),
        "spki_der_b64": _b64url(bytes(spki_der)),
        "device_id": did,
        "created_at": _utc_iso(now),
        "expires_at": _utc_iso(now + timedelta(hours=ttl_hours)),
    }
    assert_no_secrets(req, label="activation_request")
    return req


def validate_activation_request(req: dict, *, now: datetime | None = None) -> dict:
    if not isinstance(req, dict):
        raise OobActivationError("request must be object")
    if req.get("format_version") != FORMAT_VERSION:
        raise OobActivationError("unsupported request format_version")
    for key in (
        "license_key",
        "product_id",
        "request_id",
        "client_nonce",
        "spki_der_b64",
        "device_id",
        "created_at",
        "expires_at",
    ):
        if key not in req:
            raise OobActivationError(f"request missing {key}")
    expires = _parse_iso(str(req["expires_at"]))
    stamp = now or _utc_now()
    if stamp > expires:
        raise OobActivationError("activation request expired; customer must create a new one")
    assert_no_secrets(req, label="activation_request")
    # Body shape expected by ActivationService.activate
    return {
        "format_version": 1,
        "request_id": str(req["request_id"]).lower(),
        "license_key": str(req["license_key"]),
        "spki_der_b64": str(req["spki_der_b64"]),
        "device_id": str(req["device_id"]).lower(),
        "client_nonce": str(req["client_nonce"]).lower(),
        "product_id": str(req["product_id"]),
    }


def build_activation_response(
    *,
    activate_body: dict,
    license_id: str,
    product_id: str,
    cek_id: str,
    kid: str,
    request_id: str,
) -> dict:
    ticket = activate_body.get("ticket")
    envelope = activate_body.get("envelope")
    if not isinstance(ticket, dict) or not isinstance(envelope, dict):
        raise OobActivationError("activate response missing ticket/envelope")
    resp = {
        "format_version": FORMAT_VERSION,
        "mode": "oob_file",
        "license_id": license_id,
        "product_id": product_id,
        "cek_id": cek_id,
        "kid": kid,
        "request_id": request_id,
        "fulfilled_at": _utc_iso(_utc_now()),
        "ticket": ticket,
        "envelope": envelope,
    }
    assert_no_secrets(resp, label="activation_response")
    # envelope contains wrapped_cek (hex) — allowed; forbid raw CEK patterns only.
    if "wrapped_cek" not in envelope:
        raise OobActivationError("envelope missing wrapped_cek")
    return resp


def validate_activation_response(resp: dict) -> dict:
    if not isinstance(resp, dict):
        raise OobActivationError("response must be object")
    if resp.get("format_version") != FORMAT_VERSION:
        raise OobActivationError("unsupported response format_version")
    for key in ("ticket", "envelope", "product_id", "cek_id", "license_id"):
        if key not in resp:
            raise OobActivationError(f"response missing {key}")
    assert_no_secrets(resp, label="activation_response")
    ticket = resp["ticket"]
    envelope = resp["envelope"]
    if not isinstance(ticket, dict) or not isinstance(envelope, dict):
        raise OobActivationError("ticket/envelope must be objects")
    return resp


def write_json(path: Path, obj: dict) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_dumps(obj), encoding="utf-8")
    return path

