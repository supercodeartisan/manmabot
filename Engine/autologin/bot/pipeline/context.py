"""Shared runtime context passed through all stages."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Set


@dataclass
class PipelineContext:
    bot: Any
    cfg: Dict[str, Any] = field(default_factory=dict)
    # language policy: L0 = clicks language-invariant; verify with OR lists
    lang_policy: str = "L0"
    locked_ui_lang: Optional[str] = None
    # noise / session flags
    purple_logged_in: bool = False
    auth_relaunch_used: bool = False  # True when relaunch budget exhausted
    auth_relaunch_count: int = 0
    shake_armed: bool = False
    seen_screens: Set[str] = field(default_factory=set)
    extras: Dict[str, Any] = field(default_factory=dict)
    # retry counters per stage / exception id
    retries: Dict[str, int] = field(default_factory=dict)

    def bump_retry(self, key: str) -> int:
        self.retries[key] = self.retries.get(key, 0) + 1
        return self.retries[key]

    def retry_count(self, key: str) -> int:
        return self.retries.get(key, 0)
