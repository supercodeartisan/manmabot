"""Party recovery lines. Solo ticks never install this, so they keep solo settings."""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Iterator


@dataclass(frozen=True)
class PartyRecovery:
    """Heal, potion, retreat, and the three retreat methods for one party tick."""

    heal_pct: int = 70
    potion_pct: int = 50
    mage_heal_pct: int = 80
    retreat_pct: int = 30
    mother_tree: bool = True
    talking_scroll: bool = True
    safe_zone: bool = True
    tree_hp_to_mp: bool = True
    tree_hp_to_mp_hp: int = 85
    tree_hp_to_mp_mp: int = 80
    tree_heal: bool = True
    tree_heal_hp: int = 40
    tree_heal_mp: int = 80


_current: ContextVar[PartyRecovery | None] = ContextVar(
    "party_recovery",
    default=None,
)


def active() -> PartyRecovery | None:
    return _current.get()


def party_on() -> bool:
    return _current.get() is not None


def line_for(action_id: str) -> float | None:
    """Party HP ratio for heal, retreat, and the safe-zone gate.

    HP potion stays on the solo recovery row. ``potion_pct`` is not a drink line.
    """
    party = _current.get()
    if party is None:
        return None
    key = str(action_id or "")
    if key == "heal":
        return float(party.heal_pct) / 100.0
    if key in ("retreat", "safe_zone"):
        return float(party.retreat_pct) / 100.0
    return None


def recovery_from_config(cfg: object) -> PartyRecovery:
    return PartyRecovery(
        heal_pct=_pct(getattr(cfg, "member_heal_pct", 70), 70),
        potion_pct=_pct(getattr(cfg, "member_potion_pct", 50), 50),
        mage_heal_pct=_pct(getattr(cfg, "mage_heal_pct", 80), 80),
        retreat_pct=_pct(getattr(cfg, "retreat_pct", 30), 30),
        mother_tree=_flag(getattr(cfg, "mother_tree", True), True),
        talking_scroll=_flag(getattr(cfg, "talking_scroll", True), True),
        safe_zone=_flag(getattr(cfg, "safe_zone", True), True),
        tree_hp_to_mp=_flag(getattr(cfg, "tree_hp_to_mp", True), True),
        tree_hp_to_mp_hp=_pct(getattr(cfg, "tree_hp_to_mp_hp", 85), 85),
        tree_hp_to_mp_mp=_pct(getattr(cfg, "tree_hp_to_mp_mp", 80), 80),
        tree_heal=_flag(getattr(cfg, "tree_heal", True), True),
        tree_heal_hp=_pct(getattr(cfg, "tree_heal_hp", 40), 40),
        tree_heal_mp=_pct(getattr(cfg, "tree_heal_mp", 80), 80),
    )


def recovery_from_profile(profile: object) -> PartyRecovery:
    return PartyRecovery(
        heal_pct=_pct(getattr(profile, "party_member_heal_pct", 70), 70),
        potion_pct=_pct(getattr(profile, "party_member_potion_pct", 50), 50),
        mage_heal_pct=_pct(getattr(profile, "party_mage_heal_pct", 80), 80),
        retreat_pct=_pct(getattr(profile, "party_retreat_pct", 30), 30),
        mother_tree=_flag(getattr(profile, "party_mother_tree", True), True),
        talking_scroll=_flag(getattr(profile, "party_talking_scroll", True), True),
        safe_zone=_flag(getattr(profile, "party_safe_zone", True), True),
        tree_hp_to_mp=_flag(getattr(profile, "party_tree_hp_to_mp", True), True),
        tree_hp_to_mp_hp=_pct(getattr(profile, "party_tree_hp_to_mp_hp", 85), 85),
        tree_hp_to_mp_mp=_pct(getattr(profile, "party_tree_hp_to_mp_mp", 80), 80),
        tree_heal=_flag(getattr(profile, "party_tree_heal", True), True),
        tree_heal_hp=_pct(getattr(profile, "party_tree_heal_hp", 40), 40),
        tree_heal_mp=_pct(getattr(profile, "party_tree_heal_mp", 80), 80),
    )


@contextmanager
def bind(recovery: PartyRecovery) -> Iterator[PartyRecovery]:
    token = _current.set(recovery)
    try:
        yield recovery
    finally:
        _current.reset(token)


def _pct(value: object, default: int) -> int:
    if value is None or str(value).strip() == "":
        return default
    try:
        return max(1, min(100, int(value)))
    except (TypeError, ValueError):
        return default


def _flag(value: object, default: bool) -> bool:
    if value is None or (isinstance(value, str) and not value.strip()):
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)
