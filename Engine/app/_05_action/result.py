"""Structured outcome of one ``ActionExecutor.execute`` call."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class ActionResult:
    """Feedback from Action → Decision / worker (not a second decide path).

    Gate and shop previously used scattered ``last_gate_*`` / ``last_shop_*``
    fields on the executor. Readers should use ``executor.result`` only.
    """

    shop_ok: bool = False
    shop_behavior_id: str = ""
    gate_ok: bool = False
    gate_error: str = ""
    gate_pose: Optional[tuple[int, int, int]] = None
