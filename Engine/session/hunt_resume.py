"""Persist hunt map/time across disconnect relogin (not policy stops)."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Optional

from session.paths import USERDATA, assert_userdata_write, ensure_userdata

RESUME_PATH = USERDATA / "hunt_resume.json"
RESUME_TTL_S = 45 * 60


def _path() -> Path:
    ensure_userdata()
    return assert_userdata_write(RESUME_PATH)


def clear_hunt_resume() -> None:
    path = _path()
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def save_hunt_resume_from_controller(controller: Any) -> Optional[dict]:
    """Snapshot routine index/elapsed + farm tour from a live BotController."""
    clock = None
    farm = None
    try:
        clock = controller.routine_clock()
    except Exception:
        clock = None
    try:
        farm = controller.farm_clock()
    except Exception:
        farm = None
    record: dict[str, Any] = {
        "saved_at": time.time(),
        "saved_mono": time.monotonic(),
        "reason": "session_disconnected",
    }
    if isinstance(clock, dict):
        record["routine_index"] = int(clock.get("index") or 0)
        try:
            record["elapsed_s"] = float(clock.get("elapsed_s") or 0.0)
        except (TypeError, ValueError):
            record["elapsed_s"] = 0.0
        ids = list(clock.get("ids") or [])
        idx = int(record["routine_index"])
        if ids and 0 <= idx < len(ids):
            record["entry_id"] = str(ids[idx])
    if isinstance(farm, dict):
        try:
            record["farm_area_index"] = int(farm.get("index") or 0)
        except (TypeError, ValueError):
            record["farm_area_index"] = 0
    if "routine_index" not in record and "farm_area_index" not in record:
        return None
    path = _path()
    try:
        path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        return None
    return record


def load_hunt_resume(*, ttl_s: float = RESUME_TTL_S) -> Optional[dict]:
    path = _path()
    if not path.is_file():
        return None
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        clear_hunt_resume()
        return None
    if not isinstance(record, dict):
        clear_hunt_resume()
        return None
    saved = float(record.get("saved_at") or 0.0)
    if saved and (time.time() - saved) > float(ttl_s):
        clear_hunt_resume()
        return None
    return record


def apply_hunt_resume(blackboard: Any, record: Optional[dict]) -> bool:
    """Restore routine cursor index/elapsed and farm tour onto a new blackboard."""
    if not isinstance(record, dict) or blackboard is None:
        return False
    scratch = getattr(blackboard, "scratch", None)
    if not isinstance(scratch, dict):
        return False
    from app._04_decision.world_nav.hooks import SCRATCH_ROUTINE

    cursor = scratch.get(SCRATCH_ROUTINE)
    applied = False
    if cursor is not None:
        try:
            idx = int(record.get("routine_index") or 0)
            n = len(getattr(cursor, "entries", []) or [])
            if n > 0:
                cursor.index = max(0, min(idx, n - 1))
                cursor.elapsed_s = max(0.0, float(record.get("elapsed_s") or 0.0))
                cursor.running_since = 0.0
                applied = True
        except Exception:
            pass
    try:
        if "farm_area_index" in record:
            blackboard.farm_area_index = int(record.get("farm_area_index") or 0)
            applied = True
        if "farm_tour_pos" in record:
            blackboard.farm_tour_pos = int(record.get("farm_tour_pos") or 0)
            applied = True
    except Exception:
        pass
    if applied:
        scratch["hunt_resume_applied"] = dict(record)
    return applied
