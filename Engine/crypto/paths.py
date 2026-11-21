"""MMB2 path policy (READY Phase 1 Spec §5.7)."""

from __future__ import annotations

import re
import unicodedata

from .constants import MAX_PATH_BYTES
from .errors import PathPolicyError

_RESERVED = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        *(f"COM{i}" for i in range(1, 10)),
        *(f"LPT{i}" for i in range(1, 10)),
    }
)

_BAD_CHARS = set('<>:"|?*\\')


def _is_reserved_component(name: str) -> bool:
    # CON, CON.txt, Con.anything → reserved (extension still counts).
    base = name.split(".", 1)[0].upper()
    return base in _RESERVED


def canonicalize_pack_path(path: str) -> str:
    """Validate and return the canonical `/`-separated path for storage."""
    if not isinstance(path, str):
        raise PathPolicyError("path must be str")
    if "\\" in path:
        raise PathPolicyError("backslash not allowed")
    if "\x00" in path:
        raise PathPolicyError("NUL in path")
    if any(ord(c) < 32 for c in path):
        raise PathPolicyError("control character in path")
    if any(c in _BAD_CHARS for c in path):
        raise PathPolicyError("forbidden character in path")
    if path.startswith("/") or path.startswith("//"):
        raise PathPolicyError("absolute / UNC path rejected")
    if re.match(r"^[A-Za-z]:", path):
        raise PathPolicyError("drive letter rejected")

    nfc = unicodedata.normalize("NFC", path)
    if not nfc:
        raise PathPolicyError("empty path")

    parts = nfc.split("/")
    if any(p == "" for p in parts):
        raise PathPolicyError("empty path component")
    for p in parts:
        if p in (".", ".."):
            raise PathPolicyError(f"rejected component {p!r}")
        if p.endswith(" ") or p.endswith("."):
            raise PathPolicyError("trailing space/dot in component")
        if _is_reserved_component(p):
            raise PathPolicyError(f"reserved name {p!r}")

    canonical = "/".join(parts)
    encoded = canonical.encode("utf-8")
    if len(encoded) > MAX_PATH_BYTES:
        raise PathPolicyError("path exceeds max length")
    if len(encoded) == 0:
        raise PathPolicyError("empty path bytes")
    return canonical


def assert_no_case_collisions(paths: list[str]) -> None:
    seen: dict[str, str] = {}
    for p in paths:
        key = p.casefold()
        if key in seen and seen[key] != p:
            raise PathPolicyError(f"case-insensitive collision: {seen[key]!r} vs {p!r}")
        seen[key] = p
