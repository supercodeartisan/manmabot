"""Thin package shim — body in `_public` (`.pyd` in release)."""
from ._public import *  # noqa: F403
from ._public import __all__  # noqa: F401
