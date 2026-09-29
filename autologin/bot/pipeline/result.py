"""Stage outcomes — every stage returns one of these (no silent continue)."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, Optional


class StageStatus(Enum):
    OK = auto()           # advance to next stage
    RETRY = auto()        # same stage, bounded retries
    HANDLED = auto()      # exception handler consumed the tick; stay/re-enter
    BLOCKED = auto()      # waiting on external ready (noise / loading)
    FAILED = auto()       # abort pipeline (auto failure, no human prompt)
    SKIP = auto()         # stage not needed this run (e.g. already logged in)


@dataclass
class StageResult:
    status: StageStatus
    stage_id: str
    message: str = ""
    evidence: Dict[str, Any] = field(default_factory=dict)
    next_stage_id: Optional[str] = None  # override linear order when set
    retry_after_sec: float = 0.0

    @classmethod
    def ok(cls, stage_id: str, message: str = "", **evidence) -> "StageResult":
        return cls(StageStatus.OK, stage_id, message, evidence)

    @classmethod
    def retry(cls, stage_id: str, message: str = "",
              after: float = 0.3, **evidence) -> "StageResult":
        return cls(StageStatus.RETRY, stage_id, message, evidence,
                   retry_after_sec=after)

    @classmethod
    def blocked(cls, stage_id: str, message: str = "",
                after: float = 0.4, **evidence) -> "StageResult":
        return cls(StageStatus.BLOCKED, stage_id, message, evidence,
                   retry_after_sec=after)

    @classmethod
    def failed(cls, stage_id: str, message: str = "", **evidence) -> "StageResult":
        return cls(StageStatus.FAILED, stage_id, message, evidence)

    @classmethod
    def skip(cls, stage_id: str, message: str = "", **evidence) -> "StageResult":
        return cls(StageStatus.SKIP, stage_id, message, evidence)

    @classmethod
    def handled(cls, stage_id: str, message: str = "",
                next_stage_id: Optional[str] = None,
                **evidence) -> "StageResult":
        return cls(StageStatus.HANDLED, stage_id, message, evidence,
                   next_stage_id=next_stage_id)
