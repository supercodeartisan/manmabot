"""Practice catalog — mirrors userdata shopping behaviors."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


@dataclass(frozen=True)
class PracticeEntry:
    id: str
    title: str
    description: str
    category: str
    status: str = "stub"  # ready | needs_uv | stub


@dataclass(frozen=True)
class PracticeResult:
    ok: bool
    message: str


PracticeFn = Callable[[PracticeEntry], PracticeResult]

# Optional per-id overrides; default runner uses calibrated YAML behavior.
_PRACTICE_RUNNERS: dict[str, PracticeFn] = {}


def register_practice(behavior_id: str, fn: PracticeFn) -> None:
    _PRACTICE_RUNNERS[behavior_id] = fn


def shopping_catalog() -> list[PracticeEntry]:
    """Build the Practice list from ``userdata/shopping_behaviors.yaml``."""
    from manmabot_v1.shopping.behaviors import load_behaviors, load_sell_filters
    from manmabot_v1.shopping.sell_slot_layout import load_sell_slot_layout

    try:
        behaviors = load_behaviors()
        filters = load_sell_filters()
        sell_slots_ok = load_sell_slot_layout() is not None
    except Exception as exc:
        return [
            PracticeEntry(
                id="_error",
                title="(failed to load behaviors)",
                description=str(exc),
                category="Error",
                status="stub",
            )
        ]

    entries: list[PracticeEntry] = []
    for b in behaviors:
        ready = b.ui.calibrated(action=b.action)
        if b.action == "sell" and not sell_slots_ok:
            ready = False
        status = "ready" if ready else "needs_uv"
        if b.action == "sell":
            filter_bits = (
                f"mode={b.sell_mode} · "
                f"garbage={len(filters.garbage_list)} · keep={len(filters.keep_list)}"
            )
        else:
            filter_bits = f"item_index={b.item_index} · qty={b.default_qty}"
        desc = (
            f"{b.action} · map={b.map_id} · scroll={b.scroll_spot} · "
            f"{filter_bits} · "
            f"npc=[{b.npc_world_x},{b.npc_world_y}] · "
            "Run Practice: talking-scroll to shop if needed, then dialog buys/sells"
        )
        if not ready:
            if b.action == "sell":
                desc += (
                    " — calibrate sell/confirm UVs + Sell → Slot positions "
                    "before Run Practice"
                )
            else:
                desc += " — calibrate dialog UVs on the Behaviors tab before Run Practice"
        entries.append(
            PracticeEntry(
                id=b.id,
                title=b.name or b.id,
                description=desc,
                category=b.action.capitalize(),
                status=status,
            )
        )
    return entries


def behavior_by_id(behavior_id: str) -> Optional[PracticeEntry]:
    for item in shopping_catalog():
        if item.id == behavior_id:
            return item
    return None


def run_practice(behavior_id: str) -> PracticeResult:
    """Run practice for a userdata behavior id."""
    entry = behavior_by_id(behavior_id)
    if entry is None:
        return PracticeResult(ok=False, message=f"unknown behavior id: {behavior_id!r}")
    if entry.id == "_error":
        return PracticeResult(ok=False, message=entry.description)

    fn = _PRACTICE_RUNNERS.get(behavior_id)
    if fn is not None:
        try:
            return fn(entry)
        except Exception as exc:
            return PracticeResult(ok=False, message=f"practice {behavior_id} failed: {exc}")

    # Default: calibrated UV shopping loop from userdata YAML.
    try:
        from debug_tools.shopping_methods import practice_calibrated_behavior

        return practice_calibrated_behavior(behavior_id)
    except Exception as exc:
        return PracticeResult(ok=False, message=f"practice {behavior_id} failed: {exc}")


# Back-compat alias used by older imports.
ShoppingBehavior = PracticeEntry
