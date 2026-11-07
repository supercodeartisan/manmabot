"""Party HUD list rows. Screen boxes for the member bar, not body clicks."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

_ANALYSIS = Path(__file__).resolve().parents[2] / "analysis"


def default_dll_path() -> Path:
    return _ANALYSIS / "dll" / "partyhud.dll"


class PartyHudReader:
    """Latest HUD rows from the partyhud module."""

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        del _args, _kwargs
        self._closed = False
        self._loaded = False
        try:
            from app._01_perception.lc_session import session

            session.ensure("partyhud")
            self._loaded = True
        except Exception:
            self._loaded = False

    @property
    def dll_loaded(self) -> bool:
        return self._loaded and not self._closed

    def snapshot(self) -> Optional[dict[str, Any]]:
        if not self.dll_loaded:
            return None
        from app._01_perception.lc_view import party_hud

        data = party_hud()
        return data if isinstance(data, dict) else None

    def close(self) -> None:
        self._closed = True


__all__ = ["PartyHudReader", "default_dll_path"]
