"""Stage 5 MMB2 pack builder — vault CEK, pack_id reserve, atomic verify.

Seller-side only. Never logs raw CEK. Customer packs contain no CEK / private keys.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Callable, Mapping

PACKAGING_DIR = Path(__file__).resolve().parent
REPO_ROOT = PACKAGING_DIR.parent

CUSTOMER_BUILD_NAME = "BUILD.json"


def _engine_on_path() -> None:
    eng = str(REPO_ROOT / "Engine")
    if eng not in sys.path:
        sys.path.insert(0, eng)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def snapshot_tree(
    src: Path,
    *,
    select: Callable[[Path], bool] | None = None,
) -> dict[str, bytes]:
    """
    Read a consistent in-memory snapshot (posix relative paths → bytes).
    Mid-build source edits after this call do not affect the pack.
    """
    if not src.is_dir():
        raise FileNotFoundError(f"source missing: {src}")
    entries: dict[str, bytes] = {}
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        if select is not None and not select(path):
            continue
        rel = path.relative_to(src).as_posix()
        entries[rel] = path.read_bytes()
    if not entries:
        raise RuntimeError(f"no files to pack under {src}")
    return entries


def build_mmb2_blob(
    entries: Mapping[str, bytes],
    *,
    seller_root: Path,
    cek_id: str,
    product_id: str | None = None,
    note: str = "stage5",
) -> tuple[bytes, dict]:
    """
    Reserve pack_id → load CEK from vault → write MMB2 → independent verify.
    Returns (blob, meta). Raw CEK never placed in meta.
    """
    _engine_on_path()
    from crypto.pack_format import Mmb2Reader, SimplePackSession, write_pack
    from crypto.seller_cli.cek_ops import reserve_pack_id
    from crypto.seller_cli.store import SellerStore
    from crypto.license_server.vault import mask_cek

    store = SellerStore(seller_root)
    try:
        cfg = store.config()
        product_id = product_id or cfg.get("product_id")
        if not product_id:
            raise RuntimeError("product_id required")
        if not store.vault().exists(cek_id):
            raise RuntimeError(f"cek_id not in vault: {cek_id}")

        reserved = reserve_pack_id(store, cek_id=cek_id, note=note)
        pack_id: bytes = reserved["pack_id"]
        cek = store.vault().load(cek_id)
        # Build
        blob = write_pack(
            dict(entries),
            cek=cek,
            product_id=product_id,
            cek_id=cek_id,
            pack_id=pack_id,
        )
        # Independent reader verification (separate session object).
        session = SimplePackSession(
            authorized_product_id=product_id,
            authorized_cek_id=cek_id,
            decrypted_cek_32=cek,
        )
        got = Mmb2Reader(blob, session).read_all()
        if set(got) != set(entries):
            raise RuntimeError("reader path set mismatch after write")
        for rel, raw in entries.items():
            if got[rel] != raw:
                raise RuntimeError(f"reader bytes mismatch: {rel}")

        meta = {
            "format": "MMB2",
            "product_id": product_id,
            "cek_id": cek_id,
            "cek_fingerprint": mask_cek(cek),
            "pack_id_hex": pack_id.hex(),
            "files": len(entries),
            "raw_bytes": sum(len(v) for v in entries.values()),
            "pack_bytes": len(blob),
        }
        return blob, meta
    finally:
        store.close()


def atomic_publish(blob: bytes, final_path: Path) -> dict:
    """Write to .partial beside final, then os.replace. No incomplete final."""
    final_path = Path(final_path)
    final_path.parent.mkdir(parents=True, exist_ok=True)
    partial = final_path.with_suffix(final_path.suffix + ".partial")
    try:
        partial.write_bytes(blob)
        os.replace(partial, final_path)
    except Exception:
        if partial.is_file():
            partial.unlink(missing_ok=True)
        raise
    return {
        "pack_path": str(final_path),
        "pack_bytes": len(blob),
        "sha256": sha256_file(final_path),
    }


def write_customer_build_manifest(
    engine_dir: Path,
    *,
    build_id: str,
    product_id: str,
    cek_id: str,
    packs: Mapping[str, dict],
    signing_kid: str,
    signing_key,
) -> Path:
    """
    Publish Engine/BUILD.json **last** after both packs are on disk.
    Signed with the same Ed25519 kid as license tickets (no new key hierarchy).
    Runtime: verify signature + sha256 match.
    """
    _engine_on_path()
    from crypto.jcs import dumps as jcs_dumps

    # Distinct pack_ids required when multiple packs share a cek_id.
    ids = [p.get("pack_id_hex") for p in packs.values() if p.get("pack_id_hex")]
    if len(ids) != len(set(ids)):
        raise RuntimeError("duplicate pack_id across customer packs (forbidden)")

    # Canonical pack map (sorted keys) for stable JCS.
    packs_obj = {
        name: {
            "files": info.get("files"),
            "pack_bytes": info.get("pack_bytes"),
            "pack_id_hex": info["pack_id_hex"],
            "sha256": info["sha256"],
        }
        for name, info in sorted(packs.items())
    }
    core = {
        "build_id": build_id,
        "cek_id": cek_id,
        "format_version": 1,
        "kid": signing_kid,
        "packs": packs_obj,
        "product_id": product_id,
    }
    body = jcs_dumps(core)
    sig_hex = signing_key.sign(body).hex()
    manifest = dict(core)
    manifest["signature"] = sig_hex

    # Pretty JSON for humans; signature covers JCS(core) only.
    text = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if "BEGIN PRIVATE" in text.upper():
        raise RuntimeError("BUILD.json must not contain private keys")
    path = Path(engine_dir) / CUSTOMER_BUILD_NAME
    partial = path.with_suffix(path.suffix + ".partial")
    try:
        partial.write_text(text, encoding="utf-8")
        os.replace(partial, path)
    except Exception:
        if partial.is_file():
            partial.unlink(missing_ok=True)
        raise
    return path


def carry_forward_existing_pack(
    engine_dir: Path,
    pack_name: str,
    *,
    cek_id: str,
    product_id: str,
) -> dict:
    """Pin an on-disk MMB2 pack into BUILD when that side was not rebuilt.

    Reads public header fields (no CEK) and refuses cek_id / product_id mismatch.
    """
    _engine_on_path()
    from crypto.pack_format import peek_mmb2_public_header

    path = Path(engine_dir) / pack_name
    if not path.is_file():
        raise RuntimeError(
            f"cannot carry-forward missing {pack_name} — rebuild that pack or restore it"
        )
    blob = path.read_bytes()
    if not blob.startswith(b"MMB2"):
        raise RuntimeError(f"{pack_name} is not MMB2; refuse carry-forward")
    header = peek_mmb2_public_header(blob)
    if header["cek_id"] != cek_id:
        raise RuntimeError(
            f"{pack_name} cek_id {header['cek_id']} != publish cek_id {cek_id}"
        )
    if header["product_id"] != product_id:
        raise RuntimeError(
            f"{pack_name} product_id mismatch (header {header['product_id']})"
        )
    # Prefer prior BUILD file count when present; else header entry_count.
    files = int(header["entry_count"])
    prior = Path(engine_dir) / CUSTOMER_BUILD_NAME
    if prior.is_file():
        try:
            old = json.loads(prior.read_text(encoding="utf-8"))
            old_info = (old.get("packs") or {}).get(pack_name) or {}
            if isinstance(old_info.get("files"), int):
                files = int(old_info["files"])
            old_pid = old_info.get("pack_id_hex")
            if isinstance(old_pid, str) and old_pid.lower() != header["pack_id_hex"]:
                # Disk pack replaced outside BUILD — still pin header pack_id.
                pass
        except (json.JSONDecodeError, OSError, TypeError, ValueError):
            pass
    return {
        "pack_path": str(path.resolve()),
        "pack_bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "pack_id_hex": header["pack_id_hex"],
        "files": files,
        "carried_forward": True,
    }


def publish_verified_pack_pair(
    *,
    engine_dir: Path,
    data_blob: bytes | None,
    data_meta: dict | None,
    analysis_blob: bytes | None,
    analysis_meta: dict | None,
    seller_root: Path | None = None,
) -> dict:
    """
    Publish data.pack + analysis_text.pack only after both blobs are verified,
    then write signed BUILD.json last. Prevents mixed-build consumption on crash.

    When only one side is rebuilt (typical after incremental data restore), the
    other on-disk MMB2 pack is carry-forwarded into BUILD so both stay sha256-pinned.
    """
    _engine_on_path()
    from crypto.seller_cli.signing import load_private
    from crypto.seller_cli.store import SellerStore

    engine_dir = Path(engine_dir)
    if data_blob is None and analysis_blob is None:
        raise RuntimeError("nothing to publish")

    product_id = (data_meta or analysis_meta or {}).get("product_id")
    cek_id = (data_meta or analysis_meta or {}).get("cek_id")
    if not product_id or not cek_id:
        raise RuntimeError("product_id/cek_id required in pack meta")

    if data_meta and analysis_meta:
        if data_meta["pack_id_hex"] == analysis_meta["pack_id_hex"]:
            raise RuntimeError("data and analysis packs must use distinct pack_ids")
        if data_meta["cek_id"] != analysis_meta["cek_id"]:
            raise RuntimeError("data and analysis packs must share cek_id")

    if seller_root is None:
        raise RuntimeError("seller_root required to sign BUILD.json")
    store = SellerStore(seller_root)
    try:
        kid, sk = load_private(store)
    finally:
        store.close()

    build_id = str(uuid.uuid4())
    published: dict[str, dict] = {}

    if data_blob is not None and data_meta is not None:
        pub = atomic_publish(data_blob, engine_dir / "data.pack")
        published["data.pack"] = {
            **pub,
            "pack_id_hex": data_meta["pack_id_hex"],
            "files": data_meta["files"],
        }
    else:
        published["data.pack"] = carry_forward_existing_pack(
            engine_dir, "data.pack", cek_id=cek_id, product_id=product_id
        )

    if analysis_blob is not None and analysis_meta is not None:
        pub = atomic_publish(analysis_blob, engine_dir / "analysis_text.pack")
        published["analysis_text.pack"] = {
            **pub,
            "pack_id_hex": analysis_meta["pack_id_hex"],
            "files": analysis_meta["files"],
        }
    else:
        published["analysis_text.pack"] = carry_forward_existing_pack(
            engine_dir,
            "analysis_text.pack",
            cek_id=cek_id,
            product_id=product_id,
        )

    if published["data.pack"]["pack_id_hex"] == published["analysis_text.pack"]["pack_id_hex"]:
        raise RuntimeError("duplicate pack_id across customer packs (forbidden)")

    manifest_path = write_customer_build_manifest(
        engine_dir,
        build_id=build_id,
        product_id=product_id,
        cek_id=cek_id,
        packs=published,
        signing_kid=kid,
        signing_key=sk,
    )
    return {
        "build_id": build_id,
        "build_json": str(manifest_path),
        "packs": published,
        "product_id": product_id,
        "cek_id": cek_id,
        "kid": kid,
    }


def pack_directory_mmb2(
    src: Path,
    out: Path,
    *,
    seller_root: Path,
    cek_id: str,
    product_id: str | None = None,
    select: Callable[[Path], bool] | None = None,
    note: str = "stage5",
    dry_run: bool = False,
) -> dict:
    """Snapshot → build → verify → atomic publish (single pack; tests/helpers)."""
    entries = snapshot_tree(src, select=select)
    if dry_run:
        return {
            "dry_run": True,
            "files": len(entries),
            "pack": str(out),
            "sample": list(entries)[:8],
        }
    blob, meta = build_mmb2_blob(
        entries,
        seller_root=seller_root,
        cek_id=cek_id,
        product_id=product_id,
        note=note,
    )
    pub = atomic_publish(blob, out)
    pub.update(meta)
    return pub


def assert_no_secrets_in_pack_sidecar(path: Path) -> None:
    """BUILD.json / artifacts must not contain private keys or raw CEK hex."""
    text = path.read_text(encoding="utf-8")
    upper = text.upper()
    if "BEGIN PRIVATE" in upper:
        raise RuntimeError(f"secret material in {path}")
    if '"cek"' in text.lower() and "cek_fingerprint" not in text.lower() and "cek_id" not in text.lower():
        raise RuntimeError(f"suspicious cek field in {path}")
