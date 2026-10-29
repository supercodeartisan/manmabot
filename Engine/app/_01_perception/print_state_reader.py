"""Entity frame from the enttrack module, in the print_state snapshot shape."""
from __future__ import annotations

from typing import Any, Optional

from app._01_perception.lc_session import ModuleReader


class PrintStateReader(ModuleReader):
    module = "enttrack"

    def _read(self) -> Optional[dict[str, Any]]:
        from app._01_perception.lc_view import print_state

        data = print_state()
        return data if isinstance(data, dict) else None


__all__ = ["PrintStateReader"]
