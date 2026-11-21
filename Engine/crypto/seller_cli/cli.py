"""seller-cli argparse entry (seller machine only)."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import artifact as artifact_ops
from . import cek_ops
from . import fulfill_ops
from . import license_ops
from . import signing
from .store import SellerStore


def _print(obj: dict) -> int:
    print(json.dumps(obj, indent=2, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="seller-cli",
        description="Manmabot seller keygen / license provisioning (never ship SellerData)",
    )
    p.add_argument(
        "--seller-data",
        type=Path,
        default=None,
        help="SellerData root (default: <product>/SellerData or MANMABOT_SELLER_DATA)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    # signing-key
    sk = sub.add_parser("signing-key", help="Ed25519 signing keys")
    sk_sub = sk.add_subparsers(dest="action", required=True)
    sk_sub.add_parser("create", help="Generate keypair + kid")
    sk_sub.add_parser("inspect", help="Show current/previous kids")
    ex = sk_sub.add_parser("export-public", help="Export client trust bundle (public only)")
    ex.add_argument("--out", type=Path, default=None)

    # cek
    ck = sub.add_parser("cek", help="CEK epoch / vault")
    ck_sub = ck.add_subparsers(dest="action", required=True)
    c_create = ck_sub.add_parser("create", help="New CEK + cek_id in vault")
    c_create.add_argument("--product-id", default=None)
    c_create.add_argument("--cek-id", default=None)
    c_ins = ck_sub.add_parser("inspect", help="Inspect vault entry (fingerprint only)")
    c_ins.add_argument("cek_id")
    c_rot = ck_sub.add_parser("rotate", help="New epoch (new cek_id)")
    c_rot.add_argument("--product-id", default=None)
    c_pack = ck_sub.add_parser("reserve-pack-id", help="Reserve pack_id under cek_id")
    c_pack.add_argument("cek_id")
    c_pack.add_argument("--note", default="")

    # license
    lic = sub.add_parser("license", help="License provisioning via License Server")
    lic_sub = lic.add_subparsers(dest="action", required=True)
    l_create = lic_sub.add_parser("create", help="Issue license bound to cek_id")
    l_create.add_argument("--cek-id", required=True)
    l_create.add_argument("--product-id", default=None)
    l_create.add_argument("--license-id", default=None)
    l_create.add_argument(
        "--label",
        default="",
        help="Customer account / username label (seller ledger only)",
    )
    l_create.add_argument("--note", default="", help="Private seller note")
    l_ins = lic_sub.add_parser("inspect", help="Inspect license (no secrets)")
    l_ins.add_argument("license_id")
    l_label = lic_sub.add_parser("set-label", help="Set customer account label")
    l_label.add_argument("license_id")
    l_label.add_argument("--label", required=True)
    l_label.add_argument("--note", default=None)
    l_reset = lic_sub.add_parser("reset", help="Binding reset + audit")
    l_reset.add_argument("license_id")
    l_reset.add_argument("--reason", default="seller-cli")
    l_reset.add_argument("--admin-id", default="seller")

    # artifact
    art = sub.add_parser("artifact", help="Customer metadata (no CEK / no signing private)")
    art_sub = art.add_subparsers(dest="action", required=True)
    a_gen = art_sub.add_parser("generate", help="Write customer artifact JSON")
    a_gen.add_argument("--license-id", required=True)
    a_gen.add_argument("--license-key", required=True)
    a_gen.add_argument("--out", type=Path, default=None)
    a_ver = art_sub.add_parser("verify", help="Verify artifact has no secrets")
    a_ver.add_argument("path", type=Path)

    # fulfill (OOB activation — no HTTP server)
    ful = sub.add_parser(
        "fulfill",
        help="Fulfill customer activation_request → activation_response (OOB)",
    )
    ful.add_argument(
        "--request",
        required=True,
        help="Path to activation_request.json or MMB-REQ1. wire string",
    )
    ful.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Response JSON path (default: SellerData/artifacts/response-<id>.json)",
    )

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    store = SellerStore(args.seller_data)
    try:
        if args.cmd == "signing-key":
            if args.action == "create":
                return _print(signing.create_signing_key(store))
            if args.action == "inspect":
                return _print(signing.inspect_signing(store))
            if args.action == "export-public":
                return _print(signing.export_public_trust_bundle(store, args.out))
        if args.cmd == "cek":
            if args.action == "create":
                return _print(
                    cek_ops.create_cek(
                        store, product_id=args.product_id, cek_id=args.cek_id
                    )
                )
            if args.action == "inspect":
                return _print(cek_ops.inspect_cek(store, args.cek_id))
            if args.action == "rotate":
                return _print(cek_ops.rotate_cek(store, product_id=args.product_id))
            if args.action == "reserve-pack-id":
                return _print(
                    cek_ops.reserve_pack_id(store, cek_id=args.cek_id, note=args.note)
                )
        if args.cmd == "license":
            if args.action == "create":
                return _print(
                    license_ops.create_license(
                        store,
                        cek_id=args.cek_id,
                        product_id=args.product_id,
                        license_id=args.license_id,
                        customer_label=args.label,
                        seller_note=args.note,
                    )
                )
            if args.action == "inspect":
                return _print(license_ops.inspect_license(store, args.license_id))
            if args.action == "set-label":
                return _print(
                    license_ops.set_customer_label(
                        store,
                        args.license_id,
                        customer_label=args.label,
                        seller_note=args.note,
                    )
                )
            if args.action == "reset":
                return _print(
                    license_ops.reset_license(
                        store,
                        args.license_id,
                        reason=args.reason,
                        admin_id=args.admin_id,
                    )
                )
        if args.cmd == "artifact":
            if args.action == "generate":
                return _print(
                    artifact_ops.generate_artifact(
                        store,
                        license_id=args.license_id,
                        license_key=args.license_key,
                        out_path=args.out,
                    )
                )
            if args.action == "verify":
                return _print(artifact_ops.verify_artifact_file(args.path))
        if args.cmd == "fulfill":
            return _print(
                fulfill_ops.fulfill(store, args.request, out_path=args.out)
            )
        print("unknown command", file=sys.stderr)
        return 2
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    finally:
        store.close()
