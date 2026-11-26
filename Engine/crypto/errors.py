"""MMBA v2 / crypto error types."""

from __future__ import annotations


class CryptoError(Exception):
    """Base for Engine.crypto failures."""


class PackFormatError(CryptoError):
    """MMB2 container format / integrity failure."""


class PathPolicyError(CryptoError):
    """Rejected asset path under MMB2 path rules."""


class SessionBindingError(CryptoError):
    """AuthorizedSession product_id / cek_id mismatch."""
