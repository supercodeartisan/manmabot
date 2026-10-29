"""Monsters claimed by another player, derived from the enttrack sample."""
from __future__ import annotations

from typing import Any, Optional

from app._01_perception.lc_session import ModuleReader


class ContestedMobsReader(ModuleReader):
    module = "enttrack"

    def _read(self) -> Optional[dict[str, Any]]:
        from app._01_perception.lc_view import contested_mobs

        data = contested_mobs()
        return data if isinstance(data, dict) else None


__all__ = ["ContestedMobsReader"]
