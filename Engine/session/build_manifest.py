"""Customer Engine/BUILD.json consistency + Ed25519 authenticity check."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Mapping

BUILD_NAME = "BUILD.json"


class BuildManifestError(RuntimeError):
    pass


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _pack_magic(path: Path) -> str:
    if not path.is_file():
        return "absent"
    with path.open("rb") as fh:
        magic = fh.read(4)
    if magic == b"MMB2":
        return "mmb2"
    if magic == b"MMBA":
        return "mmba"
    return "unknown"


def verify_build_signature(obj: dict, trusted_keys: Mapping) -> None:
    """Verify Ed25519 over RFC 8785 JCS(core without signature)."""
    from cryptography.exceptions import InvalidSignature
    from crypto.jcs import dumps as jcs_dumps

    kid = obj.get("kid")
    sig_hex = obj.get("signature")
    if not isinstance(kid, str) or kid not in trusted_keys:
        raise BuildManifestError("BUILD.json unknown or missing kid")
    if not isinstance(sig_hex, str):
        raise BuildManifestError("BUILD.json missing signature")
    try:
        sig = bytes.fromhex(sig_hex)
    except ValueError as e:
        raise BuildManifestError("BUILD.json invalid signature hex") from e
    core = {k: v for k, v in obj.items() if k != "signature"}
    body = jcs_dumps(core)
    try:
        trusted_keys[kid].verify(sig, body)
    except InvalidSignature as e:
        raise BuildManifestError("BUILD.json Ed25519 signature invalid") from e


def verify_engine_build_manifest(
    engine_dir: Path,
    *,
    trusted_keys: Mapping | None = None,
    require_signature: bool = True,
) -> dict | None:
    """
    If any MMB2 pack is present, BUILD.json is required and must match.
    When ``require_signature`` (default), Ed25519 kid must verify via trusted_keys
    (or session.licensed_runtime pinned kids).
    """
    engine_dir = Path(engine_dir)
    data = engine_dir / "data.pack"
    analysis = engine_dir / "analysis_text.pack"
    kinds = {_pack_magic(data), _pack_magic(analysis)}
    has_mmb2 = "mmb2" in kinds
    if not has_mmb2:
        return None

    manifest_path = engine_dir / BUILD_NAME
    if not manifest_path.is_file():
        raise BuildManifestError(
            f"MMB2 packs present but {BUILD_NAME} missing — refuse mixed/incomplete build"
        )

    try:
        obj = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise BuildManifestError(f"invalid {BUILD_NAME}: {e}") from e

    if not isinstance(obj, dict) or obj.get("format_version") != 1:
        raise BuildManifestError(f"unsupported {BUILD_NAME} format")
    build_id = obj.get("build_id")
    cek_id = obj.get("cek_id")
    packs = obj.get("packs")
    if not isinstance(build_id, str) or not build_id:
        raise BuildManifestError("BUILD.json missing build_id")
    if not isinstance(cek_id, str) or not cek_id:
        raise BuildManifestError("BUILD.json missing cek_id")
    if not isinstance(packs, dict) or not packs:
        raise BuildManifestError("BUILD.json missing packs")

    if require_signature:
        keys = trusted_keys
        if keys is None:
            from session.licensed_runtime import _TRUSTED_KIDS, load_trusted_kids_file

            if not _TRUSTED_KIDS:
                load_trusted_kids_file()
            keys = _TRUSTED_KIDS
        if not keys:
            raise BuildManifestError(
                "BUILD.json signature required but no trusted kids pinned"
            )
        verify_build_signature(obj, keys)

    pack_ids: list[str] = []
    for name, info in packs.items():
        if not isinstance(info, dict):
            raise BuildManifestError(f"bad pack entry {name}")
        path = engine_dir / name
        if not path.is_file():
            raise BuildManifestError(f"BUILD lists {name} but file missing")
        expect = info.get("sha256")
        if not isinstance(expect, str) or len(expect) != 64:
            raise BuildManifestError(f"BUILD {name} missing sha256")
        actual = _sha256_file(path)
        if actual != expect.lower() and actual != expect:
            raise BuildManifestError(
                f"BUILD mismatch for {name}: file sha256 != manifest (mixed build?)"
            )
        pid = info.get("pack_id_hex")
        if isinstance(pid, str):
            pack_ids.append(pid.lower())

    if len(pack_ids) != len(set(pack_ids)):
        raise BuildManifestError("BUILD.json has duplicate pack_id_hex")

    return obj
