"""RFC 8785 JCS via Trail of Bits ``rfc8785`` + strict duplicate-key parse.

Used for:
  - Ticket signing body (UTF-8 JCS without signature)
  - envelope_hash = SHA-256(UTF-8 JCS(envelope))
  - activation payload_hash = SHA-256(UTF-8 JCS(body))
"""

from __future__ import annotations

import json
from typing import Any

import rfc8785
from rfc8785 import CanonicalizationError

from .errors import CryptoError


class JcsError(CryptoError):
    pass


def canonicalize(obj: Any) -> str:
    """Return RFC 8785 canonical JSON as a Unicode string."""
    try:
        return dumps(obj).decode("utf-8")
    except CanonicalizationError as e:
        raise JcsError(str(e)) from e


def dumps(obj: Any) -> bytes:
    """RFC 8785 canonical UTF-8 bytes."""
    try:
        return rfc8785.dumps(obj)
    except CanonicalizationError as e:
        raise JcsError(str(e)) from e


def loads_strict(text: str | bytes) -> Any:
    """Parse JSON rejecting duplicate object keys."""
    if isinstance(text, bytes):
        text = text.decode("utf-8")

    def _no_dup(pairs: list[tuple[str, Any]]) -> dict:
        out: dict[str, Any] = {}
        for k, v in pairs:
            if k in out:
                raise JcsError(f"duplicate key {k!r}")
            out[k] = v
        return out

    try:
        return json.loads(text, object_pairs_hook=_no_dup)
    except json.JSONDecodeError as e:
        raise JcsError(f"invalid JSON: {e}") from e
