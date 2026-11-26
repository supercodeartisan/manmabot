"""Customer-side out-of-band license activation (no HTTP server).

Create a request blob for the seller, then apply the seller response into
``UserData/license/{ticket,envelope}.json``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from session.licensed_runtime import (
    DEVICE_KEY_DIR,
    ENVELOPE_PATH,
    LICENSE_DIR,
    TICKET_PATH,
    clear_trusted_keys,
    load_trusted_kids_file,
    open_licensed_session,
    write_license_artifacts,
)
from session.paths import USERDATA


DEFAULT_PRODUCT_ID = "00000000-0000-4000-8000-000000000001"
REQUEST_PATH = LICENSE_DIR / "activation_request.json"
RESPONSE_APPLIED_PATH = LICENSE_DIR / "activation_response.applied.json"


def create_activation_request(
    *,
    license_key: str,
    product_id: str | None = None,
    ttl_hours: int = 48,
    force_soft_device: bool = False,
    out_path: Path | None = None,
) -> dict:
    from crypto.device_key import open_or_create_device_key
    from crypto.oob_activation import (
        REQ_PREFIX,
        build_activation_request,
        encode_wire,
        write_json,
    )

    DEVICE_KEY_DIR.mkdir(parents=True, exist_ok=True)
    force = force_soft_device or os.environ.get("MANMABOT_FORCE_SOFT_DEVICE", "").strip() in {
        "1",
        "true",
        "yes",
    }
    device = open_or_create_device_key(DEVICE_KEY_DIR, force_soft=force)
    req = build_activation_request(
        license_key=license_key,
        product_id=product_id or DEFAULT_PRODUCT_ID,
        spki_der=device.get_public_key_spki_der(),
        device_id=device.device_id,
        ttl_hours=ttl_hours,
    )
    path = out_path or REQUEST_PATH
    write_json(path, req)
    return {
        "path": str(path),
        "wire": encode_wire(REQ_PREFIX, req),
        "request": req,
        "device_id": device.device_id,
        "note": "Send this file (or wire) to the seller. Do not send SellerData.",
    }


def apply_activation_response(
    path_or_wire: str | Path,
    *,
    force_soft_device: bool = False,
    keep_request: bool = False,
) -> dict:
    from crypto.authorized_session import open_authorized_session
    from crypto.device_key import open_or_create_device_key
    from crypto.oob_activation import (
        load_response_file_or_wire,
        validate_activation_response,
        write_json,
    )

    resp = validate_activation_response(load_response_file_or_wire(path_or_wire))
    clear_trusted_keys()
    if load_trusted_kids_file() < 1:
        raise RuntimeError(
            "no trusted_kids.json pinned in this build; cannot verify activation"
        )

    DEVICE_KEY_DIR.mkdir(parents=True, exist_ok=True)
    force = force_soft_device or os.environ.get("MANMABOT_FORCE_SOFT_DEVICE", "").strip() in {
        "1",
        "true",
        "yes",
    }
    device = open_or_create_device_key(DEVICE_KEY_DIR, force_soft=force)

    # Verify unwrap works for this device before committing artifacts.
    from session.licensed_runtime import _TRUSTED_KIDS

    session = open_authorized_session(
        ticket=resp["ticket"],
        envelope=resp["envelope"],
        device=device,
        trusted_keys=_TRUSTED_KIDS,
        expected_product_id=resp.get("product_id"),
    )
    if len(session.decrypted_cek_32) != 32:
        raise RuntimeError("CEK unwrap failed")

    write_license_artifacts(ticket=resp["ticket"], envelope=resp["envelope"])
    write_json(RESPONSE_APPLIED_PATH, {
        "license_id": resp.get("license_id"),
        "product_id": resp.get("product_id"),
        "cek_id": resp.get("cek_id"),
        "request_id": resp.get("request_id"),
        "fulfilled_at": resp.get("fulfilled_at"),
        "kid": resp.get("kid"),
    })
    if not keep_request and REQUEST_PATH.is_file():
        REQUEST_PATH.unlink()

    # Reset process session cache so next open reads from disk.
    import session.licensed_runtime as lr

    lr._SESSION = None
    open_licensed_session(force_soft_device=force)
    return {
        "status": "ok",
        "ticket": str(TICKET_PATH),
        "envelope": str(ENVELOPE_PATH),
        "license_id": resp.get("license_id"),
        "userdata": str(USERDATA),
    }


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description="Customer OOB license activation (request / apply)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("request", help="Create activation_request for the seller")
    c.add_argument("--license-key", required=True)
    c.add_argument("--product-id", default=None)
    c.add_argument("--ttl-hours", type=int, default=48)
    c.add_argument("--out", type=Path, default=None)
    c.add_argument("--force-soft", action="store_true")

    a = sub.add_parser("apply", help="Apply seller activation_response")
    a.add_argument("response", help="Response JSON path or MMB-RSP1. wire")
    a.add_argument("--force-soft", action="store_true")
    a.add_argument("--keep-request", action="store_true")

    args = p.parse_args(argv)
    try:
        if args.cmd == "request":
            info = create_activation_request(
                license_key=args.license_key,
                product_id=args.product_id,
                ttl_hours=args.ttl_hours,
                force_soft_device=args.force_soft,
                out_path=args.out,
            )
            # Do not dump full license_key echo beyond what is already in request file.
            print(json.dumps(
                {
                    "path": info["path"],
                    "wire": info["wire"],
                    "device_id": info["device_id"],
                    "note": info["note"],
                },
                indent=2,
                sort_keys=True,
            ))
            return 0
        if args.cmd == "apply":
            info = apply_activation_response(
                args.response,
                force_soft_device=args.force_soft,
                keep_request=args.keep_request,
            )
            print(json.dumps(info, indent=2, sort_keys=True))
            return 0
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
