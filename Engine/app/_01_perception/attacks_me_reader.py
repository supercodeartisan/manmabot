"""Attackers whose target is MyPlayer, derived from the enttrack sample."""
from __future__ import annotations

from typing import Any, Optional

from app._01_perception.lc_session import ModuleReader


class AttacksMeReader(ModuleReader):
    module = "enttrack"

    def _read(self) -> Optional[dict[str, Any]]:
        from app._01_perception.lc_view import attacks_me

        data = attacks_me()
        return data if isinstance(data, dict) else None


__all__ = ["AttacksMeReader"]
